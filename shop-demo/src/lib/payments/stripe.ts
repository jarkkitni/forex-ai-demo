import Stripe from "stripe";
import type { PaymentDriver, ChargeResult } from "./types";
import type { Order } from "../store";

let client: Stripe | null = null;
function stripe(): Stripe {
  if (!client) {
    const key = process.env.STRIPE_SECRET_KEY;
    if (!key) throw new Error("STRIPE_SECRET_KEY ไม่ได้ตั้งค่า");
    client = new Stripe(key, { apiVersion: "2024-12-18.acacia" });
  }
  return client;
}

export const stripeDriver: PaymentDriver = {
  name: "stripe",

  async charge(order: Order, idempotencyKey: string): Promise<ChargeResult> {
    const intent = await stripe().paymentIntents.create(
      {
        amount: order.totalSatang, // Stripe รับเป็นหน่วยย่อยอยู่แล้ว = สตางค์
        currency: "thb",
        payment_method_types: [order.method],
        metadata: { orderId: order.id },
      },
      // กันสร้าง PaymentIntent ซ้ำเมื่อ client retry / เน็ตหลุดกลางทาง
      { idempotencyKey },
    );

    if (order.method === "promptpay") {
      const confirmed = await stripe().paymentIntents.confirm(intent.id, {
        payment_method_data: { type: "promptpay" },
      });
      const qr = confirmed.next_action?.promptpay_display_qr_code;
      return {
        paymentRef: confirmed.id,
        qrPayload: qr?.data ?? null,
        clientSecret: null,
      };
    }

    return {
      paymentRef: intent.id,
      qrPayload: null,
      clientSecret: intent.client_secret,
    };
  },

  async probe(paymentRef: string) {
    const pi = await stripe().paymentIntents.retrieve(paymentRef);
    if (pi.status === "succeeded") return "paid";
    if (pi.status === "canceled") return "dead";
    return "pending";
  },
};
