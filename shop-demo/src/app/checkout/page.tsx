"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { useCart } from "@/components/CartProvider";
import { findProduct } from "@/lib/catalog";
import { baht } from "@/lib/money";

export default function CheckoutPage() {
  const { items, clear, ready } = useCart();
  const router = useRouter();
  const [method, setMethod] = useState<"promptpay" | "card">("promptpay");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // คีย์เดิมตลอดการกดซ้ำ — กดรัวหรือเน็ตหลุดแล้วลองใหม่ ก็ได้รายการชำระเงินเดียว
  const idem = useRef<string>(
    typeof crypto !== "undefined" ? crypto.randomUUID() : String(Date.now()),
  );

  if (!ready) return <div className="shell empty" />;

  const rows = items
    .map((i) => ({ qty: i.qty, product: findProduct(i.slug) }))
    .filter((r): r is { qty: number; product: NonNullable<typeof r.product> } =>
      Boolean(r.product),
    );

  if (rows.length === 0) {
    return (
      <div className="shell empty">
        <h2>ไม่มีรายการให้ชำระ</h2>
        <Link href="/#catalog" className="btn" data-tone="ghost">
          ดูสินค้า
        </Link>
      </div>
    );
  }

  const total = rows.reduce((n, r) => n + r.product.satang * r.qty, 0);

  async function pay() {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          items: items.map((i) => ({ slug: i.slug, qty: i.qty })),
          method,
          idempotencyKey: idem.current,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.error ?? "เกิดข้อผิดพลาด ลองอีกครั้ง");
        setBusy(false);
        return;
      }
      clear();
      router.push(`/order/${data.orderId}`);
    } catch {
      setError("เชื่อมต่อเซิร์ฟเวอร์ไม่ได้ ตรวจสอบอินเทอร์เน็ตแล้วลองใหม่");
      setBusy(false);
    }
  }

  return (
    <div className="shell" style={{ paddingBlock: "clamp(2rem,5vw,3.5rem)", maxWidth: "44rem" }}>
      <h1 style={{ fontSize: "clamp(1.8rem,4vw,2.6rem)", marginBottom: "1.5rem" }}>
        ชำระเงิน
      </h1>

      <div className="panel">
        {rows.map((r) => (
          <div className="line" key={r.product.slug}>
            <div>
              <div className="line-name">{r.product.name}</div>
              <div className="line-meta">จำนวน {r.qty}</div>
            </div>
            <span />
            <div style={{ fontFamily: "var(--mono)" }}>
              {baht(r.product.satang * r.qty)}
            </div>
          </div>
        ))}
        <div className="total">
          <span>ยอดที่ต้องชำระ</span>
          <strong>{baht(total)}</strong>
        </div>
      </div>

      <div className="method">
        <label>
          <input
            type="radio"
            name="method"
            checked={method === "promptpay"}
            onChange={() => setMethod("promptpay")}
          />
          <span>
            พร้อมเพย์
            <small>
              สแกนจากแอปธนาคาร ระบบอัปเดตสถานะให้เองเมื่อธนาคารยืนยัน ไม่ต้องส่งสลิป
            </small>
          </span>
        </label>
        <label>
          <input
            type="radio"
            name="method"
            checked={method === "card"}
            onChange={() => setMethod("card")}
          />
          <span>
            บัตรเครดิต / เดบิต
            <small>Visa, Mastercard, JCB — รู้ผลทันที</small>
          </span>
        </label>
      </div>

      {error && (
        <p role="alert" style={{ color: "var(--ember)", fontSize: "0.9rem" }}>
          {error}
        </p>
      )}

      <button className="btn" data-tone="ember" onClick={pay} disabled={busy}>
        {busy ? "กำลังสร้างรายการ…" : `ชำระ ${baht(total)}`}
      </button>
    </div>
  );
}
