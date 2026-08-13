import type { MetadataRoute } from "next";
import { CATALOG } from "@/lib/catalog";

const site = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    { url: site, priority: 1 },
    ...CATALOG.map((p) => ({ url: `${site}/p/${p.slug}`, priority: 0.8 })),
  ];
}
