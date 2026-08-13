import { NextResponse } from "next/server";
import { findProduct } from "@/lib/catalog";
import { createOrder, type OrderLine } from "@/lib/store";
import { driver } from "@/lib/payments";

export const runtime = "nodejs";

const MAX_QTY = 20;
const MAX_LINES = 20;

export async function POST(req: Request) {
  let body: { items?: unknown; method?: unknown; idempotencyKey?: unknown };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "รูปแบบข้อมูลไม่ถูกต้อง" }, { status: 400 });
  }

  const method = body.method === "card" ? "card" : "promptpay";
  const raw = Array.isArray(body.items) ? body.items : [];
  if (raw.length === 0 || raw.length > MAX_LINES) {
    return NextResponse.json({ error: "ตะกร้าว่างหรือมีรายการมากเกินไป" }, { status: 400 });
  }

  // ─── จุดสำคัญด้านความปลอดภัย ───
  // client ส่งมาได้แค่ slug กับ qty ราคาทุกบาทดึงจาก catalog ฝั่งเซิร์ฟเวอร์
  // ถ้ารับราคาที่ client ส่งมา = ลูกค้าแก้ราคาเป็น 1 บาทได้ด้วย devtools
  const lines: OrderLine[] = [];
  for (const item of raw) {
    if (typeof item !== "object" || item === null) continue;
    const { slug, qty } = item as { slug?: unknown; qty?: unknown };
    if (typeof slug !== "string") continue;

    const product = findProduct(slug);
    if (!product) {
      return NextResponse.json({ error: `ไม่พบสินค้า ${slug}` }, { status: 404 });
    }
    const n = Math.floor(Number(qty));
    if (!Number.isFinite(n) || n < 1 || n > MAX_QTY) {
      return NextResponse.json({ error: "จำนวนไม่ถูกต้อง" }, { status: 400 });
    }
    if (n > product.stock) {
      return NextResponse.json(
        { error: `${product.name} เหลือ ${product.stock} ชิ้น` },
        { status: 409 },
      );
    }
    lines.push({ slug, name: product.name, qty: n, unitSatang: product.satang });
  }

  if (lines.length === 0) {
    return NextResponse.json({ error: "ไม่มีรายการที่ถูกต้อง" }, { status: 400 });
  }

  const total = lines.reduce((sum, l) => sum + l.unitSatang * l.qty, 0);
  const order = createOrder(lines, total, method);

  const key =
    typeof body.idempotencyKey === "string" && body.idempotencyKey.length <= 128
      ? body.idempotencyKey
      : order.id;

  try {
    const result = await driver().charge(order, key);
    order.paymentRef = result.paymentRef;
    order.qrPayload = result.qrPayload;
    return NextResponse.json({ orderId: order.id, expiresAt: order.expiresAt });
  } catch (err) {
    console.error("[checkout] charge ล้มเหลว", err);
    order.status = "failed";
    return NextResponse.json({ error: "สร้างรายการชำระเงินไม่สำเร็จ" }, { status: 502 });
  }
}
