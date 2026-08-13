import type { Metadata } from "next";
import "./globals.css";
import { CartProvider } from "@/components/CartProvider";
import { TopBar } from "@/components/TopBar";

const site = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

export const metadata: Metadata = {
  metadataBase: new URL(site),
  title: {
    default: "ศิลาดล — เครื่องปั้นเคลือบเขียวจากเชียงใหม่",
    template: "%s — ศิลาดล",
  },
  description:
    "ชาม ถ้วย แจกัน เคลือบศิลาดล เผารีดักชันทีละเตา ชำระด้วยพร้อมเพย์หรือบัตรเครดิต",
  openGraph: {
    type: "website",
    locale: "th_TH",
    siteName: "ศิลาดล",
    title: "ศิลาดล — เครื่องปั้นเคลือบเขียวจากเชียงใหม่",
    description: "เผารีดักชันทีละเตา ไม่มีสองใบที่ลายเหมือนกัน",
  },
  robots: { index: true, follow: true },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="th">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Anuphan:wght@500;600;700&family=IBM+Plex+Sans+Thai:wght@400;600&family=IBM+Plex+Mono:wght@400;500&display=swap"
        />
      </head>
      <body>
        <CartProvider>
          <TopBar />
          <main>{children}</main>
          <footer className="foot shell">
            <span>ศิลาดล — เดโมระบบร้านค้า</span>
            <span>พร้อมเพย์ · บัตรเครดิต · Stripe</span>
          </footer>
        </CartProvider>
      </body>
    </html>
  );
}
