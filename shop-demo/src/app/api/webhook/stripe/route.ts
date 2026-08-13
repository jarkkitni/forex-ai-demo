import { NextResponse } from "next/server";
import Stripe from "stripe";
import { findByPaymentRef, markPaid, markFailed } from "@/lib/store";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * ต้องอ่าน raw body ก่อน verify signature
 * ถ้า parse JSON แล้ว stringify กลับ ลายเซ็นจะไม่ตรง (byte ต่างกัน)
 * App Router ไม่แตะ body ให้ จึงใช้ req.text() ได้ตรง ๆ
 */
export async function POST(req: Request) {
  const secret = process.env.STRIPE_WEBHOOK_SECRET;
  const sig = req.headers.get("stripe-signature");
  if (!secret || !sig) {
    return NextResponse.json({ error: "unsigned" }, { status: 400 });
  }

  const raw = await req.text();
  let event: Stripe.Event;
  try {
    event = Stripe.webhooks.constructEvent(raw, sig, secret);
  } catch (err) {
    console.error("[webhook] signature ไม่ผ่าน", err);
    return NextResponse.json({ error: "bad signature" }, { status: 400 });
  }

  const pi = event.data.object as Stripe.PaymentIntent;
  const order = findByPaymentRef(pi.id);

  // ตอบ 200 แม้หาออเดอร์ไม่เจอ ไม่งั้น Stripe retry ไม่เลิก
  if (!order) {
    console.warn("[webhook] ไม่พบออเดอร์ของ", pi.id);
    return NextResponse.json({ received: true });
  }

  switch (event.type) {
    case "payment_intent.succeeded":
      markPaid(order, event.id);
      break;
    case "payment_intent.payment_failed":
      markFailed(order, event.id, "failed");
      break;
    case "payment_intent.canceled":
      markFailed(order, event.id, "canceled");
      break;
  }

  return NextResponse.json({ received: true });
}
