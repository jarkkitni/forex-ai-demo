import Link from "next/link";
import { CATALOG } from "@/lib/catalog";
import { baht } from "@/lib/money";
import { Vessel } from "@/components/Vessel";
import { Reveal } from "@/components/Reveal";

export default function Home() {
  return (
    <>
      <section className="shell hero">
        <div>
          <p className="eyebrow">เชียงใหม่ · เผารีดักชัน 1,260°C</p>
          {/* ฮีโร่ไม่มี opacity:0 รอ JS — LCP จึงวัดได้ตั้งแต่เฟรมแรก */}
          <h1>
            เคลือบเขียว
            <br />
            ที่<em>แตกลายเอง</em>
            <br />
            ในเตา
          </h1>
          <p>
            เราเผาทีละเตา เตาละ 40–60 ใบ น้ำเคลือบไหลไม่เท่ากันทุกครั้ง
            ใบที่คุณได้จึงไม่ซ้ำกับใบไหนเลย
          </p>
          <Link href="#catalog" className="btn" data-tone="ember">
            ดูของจากเตาล่าสุด
          </Link>
        </div>
        <div style={{ maxWidth: "26rem", marginInline: "auto", width: "100%" }}>
          <Vessel shape="vase" glaze="#6E9C87" />
        </div>
      </section>

      <div className="shell section-head" id="catalog">
        <h2>ของจากเตาที่ 39 · 41 · 44</h2>
        <p>{CATALOG.length} รายการ · ส่งภายใน 2 วันทำการ</p>
      </div>

      <Reveal>
        <div className="shell" style={{ paddingInline: 0 }}>
          <div className="grid">
            {CATALOG.map((p) => (
              <Link key={p.slug} href={`/p/${p.slug}`} className="card reveal">
                <span className="card-kiln">{p.kiln}</span>
                <div style={{ maxWidth: "11rem" }}>
                  <Vessel shape={p.vessel} glaze={p.glaze} />
                </div>
                <h3>{p.name}</h3>
                <span className="card-stock">เหลือ {p.stock} ชิ้น</span>
                <span className="card-price">{baht(p.satang)}</span>
              </Link>
            ))}
          </div>
        </div>
      </Reveal>

      <Reveal>
        <section className="shell" style={{ paddingBlock: "clamp(3rem,7vw,5rem)" }}>
          <div className="panel reveal">
            <h2 style={{ fontSize: "1.6rem", marginBottom: "1rem" }}>
              จ่ายยังไงก็ได้ที่ถนัด
            </h2>
            <p style={{ margin: 0, maxWidth: "52ch", color: "var(--kiln-soft)" }}>
              สแกนพร้อมเพย์จากแอปธนาคารไหนก็ได้ หรือจ่ายด้วยบัตรเครดิต
              ระบบจะอัปเดตสถานะให้เองเมื่อธนาคารยืนยัน ไม่ต้องส่งสลิปมาให้ตรวจ
            </p>
          </div>
        </section>
      </Reveal>
    </>
  );
}
