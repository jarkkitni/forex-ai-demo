"use client";

import Link from "next/link";
import { useCart } from "./CartProvider";

export function TopBar() {
  const { count, ready } = useCart();
  return (
    <header className="top">
      <div className="shell top-in">
        <Link href="/" className="wordmark">
          ศิลาดล<span>.</span>
        </Link>
        <Link href="/cart" className="cart-link" data-full={ready && count > 0}>
          ตะกร้า {ready && count > 0 ? `(${count})` : ""}
        </Link>
      </div>
    </header>
  );
}
