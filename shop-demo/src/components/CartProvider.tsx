"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

/** ตะกร้าเก็บแค่ slug กับ qty — ราคาไม่เคยอยู่ฝั่ง client ให้แก้ได้ */
export interface CartItem {
  slug: string;
  qty: number;
}

interface CartApi {
  items: CartItem[];
  count: number;
  add: (slug: string, qty?: number) => void;
  setQty: (slug: string, qty: number) => void;
  remove: (slug: string) => void;
  clear: () => void;
  ready: boolean;
}

const KEY = "siladon.cart.v1";
const Ctx = createContext<CartApi | null>(null);

export function CartProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<CartItem[]>([]);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(KEY);
      if (raw) {
        const parsed: unknown = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          setItems(
            parsed.filter(
              (i): i is CartItem =>
                typeof i?.slug === "string" && Number.isInteger(i?.qty) && i.qty > 0,
            ),
          );
        }
      }
    } catch {
      /* ข้อมูลเสีย — เริ่มตะกร้าใหม่ ดีกว่าหน้าจอพัง */
    }
    setReady(true);
  }, []);

  useEffect(() => {
    if (ready) localStorage.setItem(KEY, JSON.stringify(items));
  }, [items, ready]);

  const add = useCallback((slug: string, qty = 1) => {
    setItems((prev) => {
      const hit = prev.find((i) => i.slug === slug);
      if (hit) {
        return prev.map((i) =>
          i.slug === slug ? { ...i, qty: Math.min(i.qty + qty, 20) } : i,
        );
      }
      return [...prev, { slug, qty }];
    });
  }, []);

  const setQty = useCallback((slug: string, qty: number) => {
    setItems((prev) =>
      qty <= 0
        ? prev.filter((i) => i.slug !== slug)
        : prev.map((i) => (i.slug === slug ? { ...i, qty: Math.min(qty, 20) } : i)),
    );
  }, []);

  const remove = useCallback(
    (slug: string) => setItems((prev) => prev.filter((i) => i.slug !== slug)),
    [],
  );

  const clear = useCallback(() => setItems([]), []);

  const value = useMemo<CartApi>(
    () => ({
      items,
      count: items.reduce((n, i) => n + i.qty, 0),
      add,
      setQty,
      remove,
      clear,
      ready,
    }),
    [items, add, setQty, remove, clear, ready],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useCart(): CartApi {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useCart ต้องอยู่ภายใน CartProvider");
  return ctx;
}
