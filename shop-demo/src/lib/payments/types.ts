import type { Order } from "../store";

export interface ChargeResult {
  paymentRef: string;
  /** payload สำหรับ render QR — null เมื่อจ่ายด้วยบัตร */
  qrPayload: string | null;
  /** URL สำหรับ redirect ไป confirm บัตร — null เมื่อเป็น PromptPay */
  clientSecret: string | null;
}

export interface PaymentDriver {
  readonly name: string;
  charge(order: Order, idempotencyKey: string): Promise<ChargeResult>;
  /** ใช้โดย reconcile job ตอน webhook หาย */
  probe(paymentRef: string): Promise<"paid" | "pending" | "dead">;
}
