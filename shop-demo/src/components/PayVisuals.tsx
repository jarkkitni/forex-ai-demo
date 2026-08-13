"use client";

const MODULES = 25;

/** ตารางจุดที่คงที่ต่อ payload หนึ่งค่า — ใช้แสดงผลในโหมดจำลองเท่านั้น */
function pattern(payload: string): boolean[] {
  let h = 2166136261;
  const cells: boolean[] = [];
  for (let i = 0; i < MODULES * MODULES; i++) {
    h ^= payload.charCodeAt(i % payload.length);
    h = Math.imul(h, 16777619) >>> 0;
    cells.push((h & 0x80) !== 0);
  }
  return cells;
}

function isFinder(r: number, c: number): boolean {
  const inBox = (r0: number, c0: number) =>
    r >= r0 && r < r0 + 7 && c >= c0 && c < c0 + 7;
  return inBox(0, 0) || inBox(0, MODULES - 7) || inBox(MODULES - 7, 0);
}

/**
 * โหมดจำลอง: วาดลวดลายจาก payload
 * โหมดจริง: Stripe ส่ง image_url_png มาให้ หรือเข้ารหัส payload ด้วย lib `qrcode`
 * ไม่ได้ใส่ตัวเข้ารหัส QR จริงในเดโม เพื่อไม่ให้มี dependency ที่ไม่จำเป็น
 */
export function QrPanel({ payload }: { payload: string }) {
  const cells = pattern(payload);
  return (
    <svg viewBox={`0 0 ${MODULES} ${MODULES}`} shapeRendering="crispEdges" role="img" aria-label="รหัสคิวอาร์สำหรับชำระเงิน">
      <rect width={MODULES} height={MODULES} fill="#f6f5f0" />
      {cells.map((on, i) => {
        const r = Math.floor(i / MODULES);
        const c = i % MODULES;
        if (isFinder(r, c)) return null;
        return on ? <rect key={i} x={c} y={r} width={1} height={1} fill="#1e2422" /> : null;
      })}
      {[
        [0, 0],
        [0, MODULES - 7],
        [MODULES - 7, 0],
      ].map(([r, c]) => (
        <g key={`${r}-${c}`}>
          <rect x={c} y={r} width={7} height={7} fill="#1e2422" />
          <rect x={c + 1} y={r + 1} width={5} height={5} fill="#f6f5f0" />
          <rect x={c + 2} y={r + 2} width={3} height={3} fill="#1e2422" />
        </g>
      ))}
    </svg>
  );
}

const STATE_GLAZE: Record<string, { fill: number; label: string; tone: string }> = {
  awaiting_payment: { fill: 0.34, label: "รอรับเงินจากธนาคาร", tone: "#7fa894" },
  paid: { fill: 1, label: "ได้รับเงินแล้ว", tone: "#3d6053" },
  failed: { fill: 0.12, label: "ชำระเงินไม่สำเร็จ", tone: "#c2521f" },
  expired: { fill: 0.12, label: "รหัสหมดอายุ", tone: "#c2521f" },
  canceled: { fill: 0.12, label: "ยกเลิกรายการแล้ว", tone: "#4a534f" },
};

/**
 * ตัวบอกสถานะ: ภาชนะที่เติมน้ำเคลือบตามสถานะจริงของออเดอร์
 * เลือกใช้แทนวงกลมหมุน เพราะสถานะ "รอ" ของ PromptPay กินเวลาเป็นนาที
 * วงกลมหมุนนานๆ อ่านว่า "ค้าง" ส่วนระดับน้ำที่นิ่งอ่านว่า "กำลังรอ"
 */
export function GlazeGauge({ status }: { status: string }) {
  const s = STATE_GLAZE[status] ?? STATE_GLAZE.awaiting_payment;
  const top = 84 - 66 * s.fill;
  return (
    <figure style={{ margin: 0, display: "grid", gap: "0.85rem", justifyItems: "center" }}>
      <svg viewBox="0 0 120 100" width="132" height="110" role="img" aria-label={s.label}>
        <defs>
          <clipPath id="vesselClip">
            <path d="M30 18 Q26 84 60 88 Q94 84 90 18 Z" />
          </clipPath>
        </defs>
        <g clipPath="url(#vesselClip)">
          <rect x="0" y="0" width="120" height="100" fill="#e4e2d8" />
          <rect
            x="0"
            y={top}
            width="120"
            height="100"
            fill={s.tone}
            style={{ transition: "y 900ms cubic-bezier(.22,.61,.36,1), fill 500ms ease" }}
          />
        </g>
        <path
          d="M30 18 Q26 84 60 88 Q94 84 90 18 Z"
          fill="none"
          stroke="#1e2422"
          strokeOpacity="0.35"
          strokeWidth="1.4"
        />
        {status === "paid" && (
          <g stroke="#f6f5f0" strokeOpacity="0.5" strokeWidth="0.7" fill="none">
            <path d="M44 30 L52 52 L46 74" />
            <path d="M74 26 L68 48 L78 70" />
          </g>
        )}
      </svg>
      <figcaption className="state-note">{s.label}</figcaption>
    </figure>
  );
}
