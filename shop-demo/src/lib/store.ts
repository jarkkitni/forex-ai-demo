import { randomUUID } from "node:crypto";

export type OrderStatus =
  | "awaiting_payment"
  | "paid"
  | "failed"
  | "expired"
  | "canceled";

export interface OrderLine {
  slug: string;
  name: string;
  qty: number;
  unitSatang: number;
}

export interface Order {
  id: string;
  status: OrderStatus;
  lines: OrderLine[];
  totalSatang: number;
  method: "card" | "promptpay";
  paymentRef: string | null;
  qrPayload: string | null;
  createdAt: number;
  expiresAt: number;
  paidAt: number | null;
  /** กัน webhook ยิงซ้ำ — เก็บ event id ที่ประมวลผลไปแล้ว */
  seenEvents: Set<string>;
}

/**
 * เดโมเก็บใน memory เพื่อให้รันได้ทันทีโดยไม่ต้องตั้ง DB
 * globalThis กัน state หายตอน hot-reload ของ dev server
 * โปรดักชันเปลี่ยนเป็น Postgres: unique index บน payment_ref + ตาราง webhook_events
 */
const g = globalThis as unknown as { __orders?: Map<string, Order> };
const orders: Map<string, Order> = (g.__orders ??= new Map());

export const ORDER_TTL_MS = 10 * 60 * 1000; // QR PromptPay อายุ 10 นาที

export function createOrder(
  lines: OrderLine[],
  totalSatang: number,
  method: Order["method"],
): Order {
  const now = Date.now();
  const order: Order = {
    id: randomUUID(),
    status: "awaiting_payment",
    lines,
    totalSatang,
    method,
    paymentRef: null,
    qrPayload: null,
    createdAt: now,
    expiresAt: now + ORDER_TTL_MS,
    paidAt: null,
    seenEvents: new Set(),
  };
  orders.set(order.id, order);
  return order;
}

export function getOrder(id: string): Order | undefined {
  const o = orders.get(id);
  if (!o) return undefined;
  // lazy expiry — ไม่ต้องมี timer ค้างไว้ต่อออเดอร์
  if (o.status === "awaiting_payment" && Date.now() > o.expiresAt) {
    o.status = "expired";
  }
  return o;
}

export function findByPaymentRef(ref: string): Order | undefined {
  for (const o of orders.values()) if (o.paymentRef === ref) return o;
  return undefined;
}

/** idempotent — ยิงซ้ำกี่ครั้งผลลัพธ์เท่าเดิม */
export function markPaid(order: Order, eventId: string): boolean {
  if (order.seenEvents.has(eventId)) return false;
  order.seenEvents.add(eventId);
  if (order.status === "paid") return false;
  order.status = "paid";
  order.paidAt = Date.now();
  return true;
}

export function markFailed(order: Order, eventId: string, status: OrderStatus) {
  if (order.seenEvents.has(eventId)) return;
  order.seenEvents.add(eventId);
  if (order.status === "paid") return; // จ่ายแล้วห้ามถอยสถานะ
  order.status = status;
}

export function stalePendingOrders(olderThanMs: number): Order[] {
  const cutoff = Date.now() - olderThanMs;
  return [...orders.values()].filter(
    (o) => o.status === "awaiting_payment" && o.createdAt < cutoff,
  );
}
