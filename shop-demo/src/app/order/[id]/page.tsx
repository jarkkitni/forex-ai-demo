import { notFound } from "next/navigation";
import { getOrder } from "@/lib/store";
import { OrderTracker } from "./OrderTracker";

export const dynamic = "force-dynamic";
export const metadata = { title: "สถานะคำสั่งซื้อ", robots: { index: false } };

export default async function OrderPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const order = getOrder(id);
  if (!order) notFound();

  return (
    <OrderTracker
      mockEnabled={process.env.PAYMENT_DRIVER !== "stripe"}
      initial={{
        id: order.id,
        status: order.status,
        method: order.method,
        totalSatang: order.totalSatang,
        lines: order.lines,
        qrPayload: order.status === "awaiting_payment" ? order.qrPayload : null,
        expiresAt: order.expiresAt,
        paidAt: order.paidAt,
      }}
    />
  );
}
