"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { useCart } from "./CartProvider";

export function AddToCart({ slug, stock }: { slug: string; stock: number }) {
  const { add } = useCart();
  const router = useRouter();
  const [qty, setQty] = useState(1);

  if (stock === 0) {
    return <p className="state-note">สินค้าหมด — รอบเผาถัดไปประมาณ 3 สัปดาห์</p>;
  }

  return (
    <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "center" }}>
      <div className="qty">
        <button onClick={() => setQty((n) => Math.max(1, n - 1))} aria-label="ลดจำนวน">
          −
        </button>
        <output>{qty}</output>
        <button
          onClick={() => setQty((n) => Math.min(stock, n + 1))}
          aria-label="เพิ่มจำนวน"
        >
          +
        </button>
      </div>
      <button
        className="btn"
        data-tone="ember"
        onClick={() => {
          add(slug, qty);
          router.push("/cart");
        }}
      >
        ใส่ตะกร้า
      </button>
    </div>
  );
}
