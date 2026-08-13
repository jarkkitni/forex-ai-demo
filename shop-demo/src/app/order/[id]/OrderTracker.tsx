"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { baht } from "@/lib/money";
import { QrPanel, GlazeGauge } from "@/components/PayVisuals";

interface OrderView {
  id: string;
  status: string;
  method: "card" | "promptpay";
  totalSatang: number;
  lines: { slug: string; name: string; qty: number; unitSatang: number }[];
  qrPayload: string | null;
  expiresAt: number;
  paidAt: number | null;
}

const TERMINAL = new Set(["paid", "failed", "expired", "canceled"]);

function clock(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

export function OrderTracker({
  initial,
  mockEnabled,
}: {
  initial: OrderView;
  mockEnabled: boolean;
}) {
  const [order, setOrder] = useState(initial);
  const [left, setLeft] = useState(() => initial.expiresAt - Date.now());
  const attempt = useRef(0);

  const poll = useCallback(async () => {
    try {
      const res = await fetch(`/api/order/${initial.id}`, { cache: "no-store" });
      if (!res.ok) return;
      setOrder(await res.json());
      attempt.current = 0;
    } catch {
      attempt.current++; // เน็ตสะดุด — ถอยจังหวะแทนที่จะรัวยิงซ้ำ
    }
  }, [initial.id]);

  useEffect(() => {
    if (TERMINAL.has(order.status)) return;
    // 2 วิเป็นหลัก แต่ถอยเป็นเท่าตัวเมื่อยิงพลาด เพดาน 15 วิ
    const wait = Math.min(2000 * 2 ** attempt.current, 15000);
    const t = setTimeout(poll, wait);
    return () => clearTimeout(t);
  }, [order, poll]);

  useEffect(() => {
    if (TERMINAL.has(order.status)) return;
    const t = setInterval(() => setLeft(order.expiresAt - Date.now()), 1000);
    return () => clearInterval(t);
  }, [order.status, order.expiresAt]);

  const waiting = order.status === "awaiting_payment";

  return (
    <div className="shell wait">
      <div>
        {waiting && order.qrPayload ? (
          <div className="qr-frame">
            <QrPanel payload={order.qrPayload} />
            <p className="countdown" data-urgent={left < 120_000}>
              รหัสหมดอายุใน {clock(left)}
            </p>
          </div>
        ) : (
          <div className="qr-frame" style={{ paddingBlock: "2.5rem" }}>
            <GlazeGauge status={order.status} />
          </div>
        )}
      </div>

      <div>
        <p className="eyebrow">คำสั่งซื้อ {order.id.slice(0, 8).toUpperCase()}</p>

        {waiting && (
          <>
            <h1 style={{ fontSize: "clamp(1.8rem,4vw,2.6rem)" }}>
              สแกนเพื่อชำระ {baht(order.totalSatang)}
            </h1>
            <p style={{ color: "var(--kiln-soft)", maxWidth: "44ch" }}>
              เปิดแอปธนาคารแล้วสแกนรหัสนี้ หน้านี้จะเปลี่ยนเองเมื่อธนาคารยืนยัน
              ไม่ต้องกดรีเฟรช และไม่ต้องส่งสลิปมาให้ตรวจ
            </p>
            <div style={{ marginTop: "1.5rem" }}>
              <GlazeGauge status={order.status} />
            </div>
          </>
        )}

        {order.status === "paid" && (
          <>
            <h1 style={{ fontSize: "clamp(1.8rem,4vw,2.6rem)" }}>ได้รับเงินแล้ว</h1>
            <p style={{ color: "var(--kiln-soft)", maxWidth: "44ch" }}>
              เราจะแพ็กของภายในวันทำการถัดไป และส่งเลขพัสดุให้ทางอีเมล
            </p>
          </>
        )}

        {order.status === "expired" && (
          <>
            <h1 style={{ fontSize: "clamp(1.8rem,4vw,2.6rem)" }}>รหัสหมดอายุแล้ว</h1>
            <p style={{ color: "var(--kiln-soft)", maxWidth: "44ch" }}>
              รหัสพร้อมเพย์มีอายุ 10 นาที สั่งใหม่อีกครั้งเพื่อรับรหัสใหม่
              ยังไม่มีการตัดเงินจากบัญชีคุณ
            </p>
          </>
        )}

        {(order.status === "failed" || order.status === "canceled") && (
          <>
            <h1 style={{ fontSize: "clamp(1.8rem,4vw,2.6rem)" }}>ชำระเงินไม่สำเร็จ</h1>
            <p style={{ color: "var(--kiln-soft)", maxWidth: "44ch" }}>
              ธนาคารไม่ได้อนุมัติรายการนี้ ยอดเงินยังอยู่ในบัญชีคุณครบ
              ลองใหม่หรือเปลี่ยนวิธีชำระได้เลย
            </p>
          </>
        )}

        <div className="panel" style={{ marginTop: "2rem" }}>
          {order.lines.map((l) => (
            <div className="line" key={l.slug}>
              <div>
                <div className="line-name">{l.name}</div>
                <div className="line-meta">จำนวน {l.qty}</div>
              </div>
              <span />
              <div style={{ fontFamily: "var(--mono)" }}>
                {baht(l.unitSatang * l.qty)}
              </div>
            </div>
          ))}
          <div className="total">
            <span>ยอดรวม</span>
            <strong>{baht(order.totalSatang)}</strong>
          </div>
        </div>

        {mockEnabled && waiting && (
          <div className="mock-bar">
            <p>
              โหมดสาธิต — ปุ่มสองปุ่มนี้แทนสัญญาณที่ธนาคารส่งกลับมา
              ของจริงระบบจะได้รับเองโดยลูกค้าไม่ต้องทำอะไร
            </p>
            <button
              className="btn"
              onClick={async () => {
                await fetch("/api/mock/pay", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ orderId: order.id }),
                });
                poll();
              }}
            >
              จำลองจ่ายสำเร็จ
            </button>
            <button
              className="btn"
              data-tone="ghost"
              onClick={async () => {
                await fetch("/api/mock/pay", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ orderId: order.id, outcome: "fail" }),
                });
                poll();
              }}
            >
              จำลองจ่ายไม่ผ่าน
            </button>
          </div>
        )}

        {!waiting && (
          <div style={{ marginTop: "1.5rem" }}>
            <Link href="/#catalog" className="btn" data-tone="ghost">
              กลับไปดูสินค้า
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}
