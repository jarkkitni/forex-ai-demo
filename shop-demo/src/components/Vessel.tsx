import type { Vessel as Shape } from "@/lib/catalog";

const PATHS: Record<Shape, string> = {
  bowl: "M22 46 Q22 84 60 84 Q98 84 98 46 Z",
  cup: "M34 34 L38 82 Q60 90 82 82 L86 34 Z",
  vase: "M50 18 L50 34 Q26 48 30 82 Q60 94 90 82 Q94 48 70 34 L70 18 Z",
  plate: "M14 54 Q60 40 106 54 Q60 74 14 54 Z",
};

/** ภาพสินค้าเป็น SVG ล้วน — ไม่มีไฟล์รูป จึงไม่มี layout shift และไม่กิน bandwidth */
export function Vessel({ shape, glaze }: { shape: Shape; glaze: string }) {
  const id = `g-${shape}-${glaze.replace("#", "")}`;
  return (
    <svg viewBox="0 0 120 100" role="img" aria-label="ภาพสินค้า">
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={glaze} stopOpacity="0.75" />
          <stop offset="100%" stopColor={glaze} />
        </linearGradient>
      </defs>
      <ellipse cx="60" cy="88" rx="34" ry="4" fill="#000" opacity="0.07" />
      <path d={PATHS[shape]} fill={`url(#${id})`} />
      <path d={PATHS[shape]} fill="none" stroke="#1e2422" strokeOpacity="0.28" strokeWidth="1" />
      <g stroke="#1e2422" strokeOpacity="0.15" strokeWidth="0.6" fill="none">
        <path d="M40 50 L52 70 L46 82" />
        <path d="M74 46 L68 64 L78 78" />
        <path d="M58 52 L60 76" />
      </g>
    </svg>
  );
}
