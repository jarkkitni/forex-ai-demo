"use client";

import Link from "next/link";
import { useCart } from "@/components/CartProvider";
import { findProduct } from "@/lib/catalog";
import { baht } from "@/lib/money";

export default function CartPage() {
  const { items, setQty, remove, ready } = useCart();

  if (!ready) return <div className="shell empty" />;

  const rows = items
    .map((i) => ({ item: i, product: findProduct(i.slug) }))
    .filter((r): r is { item: typeof r.item; product: NonNullable<typeof r.product> } =>
      Boolean(r.product),
    );

  if (rows.length === 0) {
    return (
      <div className="shell empty">
        <h2>ตะกร้ายังว่าง</h2>
        <p style={{ color: "var(--kiln-soft)" }}>เลือกของจากเตาล่าสุดได้เลย</p>
        <Link href="/#catalog" className="btn" data-tone="ghost">
          ดูสินค้า
        </Link>
      </div>
    );
  }

  // ยอดฝั่งนี้ใช้แสดงผลอย่างเดียว ยอดจริงเซิร์ฟเวอร์คำนวณใหม่ตอน checkout
  const total = rows.reduce((n, r) => n + r.product.satang * r.item.qty, 0);

  return (
    <div className="shell" style={{ paddingBlock: "clamp(2rem,5vw,3.5rem)", maxWidth: "48rem" }}>
      <h1 style={{ fontSize: "clamp(1.8rem,4vw,2.6rem)", marginBottom: "1.5rem" }}>
        ตะกร้าของคุณ
      </h1>
      <div className="panel">
        {rows.map(({ item, product }) => (
          <div className="line" key={item.slug}>
            <div>
              <div className="line-name">{product.name}</div>
              <div className="line-meta">
                {product.kiln} · {baht(product.satang)} / ชิ้น
              </div>
              <button
                onClick={() => remove(item.slug)}
                style={{
                  background: "none",
                  border: "none",
                  padding: 0,
                  marginTop: "0.35rem",
                  font: "inherit",
                  fontSize: "0.75rem",
                  color: "var(--kiln-soft)",
                  textDecoration: "underline",
                  cursor: "pointer",
                }}
              >
                เอาออก
              </button>
            </div>
            <div className="qty">
              <button onClick={() => setQty(item.slug, item.qty - 1)} aria-label="ลดจำนวน">
                −
              </button>
              <output>{item.qty}</output>
              <button
                onClick={() => setQty(item.slug, Math.min(product.stock, item.qty + 1))}
                aria-label="เพิ่มจำนวน"
              >
                +
              </button>
            </div>
            <div style={{ fontFamily: "var(--mono)" }}>
              {baht(product.satang * item.qty)}
            </div>
          </div>
        ))}
        <div className="total">
          <span>ยอดรวม</span>
          <strong>{baht(total)}</strong>
        </div>
      </div>
      <div style={{ marginTop: "1.5rem", display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
        <Link href="/checkout" className="btn" data-tone="ember">
          ไปชำระเงิน
        </Link>
        <Link href="/#catalog" className="btn" data-tone="ghost">
          เลือกเพิ่ม
        </Link>
      </div>
    </div>
  );
}
