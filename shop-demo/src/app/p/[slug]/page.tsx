import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { CATALOG, findProduct } from "@/lib/catalog";
import { baht } from "@/lib/money";
import { Vessel } from "@/components/Vessel";
import { AddToCart } from "@/components/AddToCart";

export function generateStaticParams() {
  return CATALOG.map((p) => ({ slug: p.slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const p = findProduct(slug);
  if (!p) return { title: "ไม่พบสินค้า" };
  return {
    title: p.name,
    description: p.blurb,
    openGraph: { title: `${p.name} — ศิลาดล`, description: p.blurb },
  };
}

export default async function ProductPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const p = findProduct(slug);
  if (!p) notFound();

  // structured data ให้ Google แสดงราคาและสถานะสต็อกในผลค้นหา
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "Product",
    name: p.name,
    description: p.blurb,
    offers: {
      "@type": "Offer",
      priceCurrency: "THB",
      price: (p.satang / 100).toFixed(2),
      availability:
        p.stock > 0
          ? "https://schema.org/InStock"
          : "https://schema.org/OutOfStock",
    },
  };

  return (
    <div className="shell detail">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <div style={{ background: "var(--crackle)", padding: "2.5rem" }}>
        <Vessel shape={p.vessel} glaze={p.glaze} />
      </div>
      <div>
        <p className="eyebrow">{p.kiln}</p>
        <h1>{p.name}</h1>
        <p className="price-big">{baht(p.satang)}</p>
        <p style={{ color: "var(--kiln-soft)", maxWidth: "44ch" }}>{p.blurb}</p>
        <AddToCart slug={p.slug} stock={p.stock} />
        <dl className="spec">
          {p.spec.map((s) => (
            <div key={s.label}>
              <dt>{s.label}</dt>
              <dd>{s.value}</dd>
            </div>
          ))}
          <div>
            <dt>คงเหลือ</dt>
            <dd>{p.stock} ชิ้น</dd>
          </div>
        </dl>
      </div>
    </div>
  );
}
