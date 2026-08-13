import { NextResponse } from "next/server";
import { getOrder, markPaid, markFailed } from "@/lib/store";

export const runtime = "nodejs";

/** แทนสัญญาณจากธนาคารในโหมด mock — ปิดตายเมื่อรันด้วย driver จริง */
export async function POST(req: Request) {
  if (process.env.PAYMENT_DRIVER === "stripe") {
    return NextResponse.json({ error: "ปิดใช้งาน" }, { status: 403 });
  }

  const { orderId, outcome } = (await req.json()) as {
    orderId?: string;
    outcome?: string;
  };
  if (!orderId) {
    return NextResponse.json({ error: "ต้องระบุ orderId" }, { status: 400 });
  }

  const order = getOrder(orderId);
  if (!order) return NextResponse.json({ error: "ไม่พบคำสั่งซื้อ" }, { status: 404 });
  if (order.status !== "awaiting_payment") {
    return NextResponse.json({ status: order.status });
  }

  const eventId = `mock_evt_${Date.now()}`;
  if (outcome === "fail") markFailed(order, eventId, "failed");
  else markPaid(order, eventId);

  return NextResponse.json({ status: order.status });
}
