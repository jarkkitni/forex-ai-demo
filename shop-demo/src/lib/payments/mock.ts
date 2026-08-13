import type { PaymentDriver, ChargeResult } from "./types";
import type { Order } from "../store";

/**
 * จำลอง gateway ให้เดโมรันได้โดยไม่ต้องมีคีย์
 * flow เหมือนของจริงทุกอย่าง: สร้าง ref -> คืน QR -> รอสัญญาณจากภายนอก
 * ต่างแค่ "ภายนอก" คือปุ่มจำลอง แทนที่จะเป็นธนาคาร
 */
export const mockDriver: PaymentDriver = {
  name: "mock",

  async charge(order: Order): Promise<ChargeResult> {
    const ref = `mock_${order.id.slice(0, 8)}`;
    if (order.method === "card") {
      return { paymentRef: ref, qrPayload: null, clientSecret: `${ref}_secret` };
    }
    // payload รูปแบบเดียวกับ EMVCo ที่ PromptPay ใช้จริง (ตัวเลขจำลอง)
    const amount = (order.totalSatang / 100).toFixed(2);
    const payload = `00020101021229370016A00000067701011101130066000000005802TH5303764540${amount.length}${amount}6304MOCK`;
    return { paymentRef: ref, qrPayload: payload, clientSecret: null };
  },

  async probe() {
    return "pending" as const;
  },
};
