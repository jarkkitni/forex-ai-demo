import { NextResponse } from "next/server";
import { getOrder } from "@/lib/store";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const order = getOrder(id);
  if (!order) {
    return NextResponse.json({ error: "ไม่พบคำสั่งซื้อ" }, { status: 404 });
  }

  // ไม่ส่ง paymentRef / seenEvents ออกฝั่ง client
  return NextResponse.json(
    {
      id: order.id,
      status: order.status,
      method: order.method,
      totalSatang: order.totalSatang,
      lines: order.lines,
      qrPayload: order.status === "awaiting_payment" ? order.qrPayload : null,
      expiresAt: order.expiresAt,
      paidAt: order.paidAt,
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}
