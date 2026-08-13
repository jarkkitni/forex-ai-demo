import Link from "next/link";

export default function NotFound() {
  return (
    <div className="shell empty">
      <h2>ไม่พบหน้านี้</h2>
      <p style={{ color: "var(--kiln-soft)" }}>
        ลิงก์อาจหมดอายุ หรือของชิ้นนั้นขายไปแล้ว
      </p>
      <Link href="/" className="btn" data-tone="ghost">
        กลับหน้าแรก
      </Link>
    </div>
  );
}
