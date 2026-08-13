import { NextResponse } from "next/server";
import { stalePendingOrders, markPaid, markFailed } from "@/lib/store";
import { driver } from "@/lib/payments";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const STALE_MS = 15 * 60 * 1000;

/**
 * ตาข่ายรองรับเมื่อ webhook หาย — เกิดขึ้นจริงเสมอในระบบที่รันนานพอ
 * ตั้ง cron ยิงทุก 5 นาที
 */
export async function GET(req: Request) {
  const secret = process.env.CRON_SECRET;
  if (!secret || req.headers.get("authorization") !== `Bearer ${secret}`) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const stale = stalePendingOrders(STALE_MS);
  const d = driver();
  let fixed = 0;

  for (const order of stale) {
    if (!order.paymentRef) continue;
    try {
      const state = await d.probe(order.paymentRef);
      const evt = `reconcile_${order.id}_${Date.now()}`;
      if (state === "paid") {
        markPaid(order, evt);
        fixed++;
      } else if (state === "dead") {
        markFailed(order, evt, "expired");
        fixed++;
      }
    } catch (err) {
      console.error("[reconcile] probe ล้มเหลว", order.id, err);
    }
  }

  return NextResponse.json({ scanned: stale.length, fixed });
}
