export type Vessel = "bowl" | "cup" | "vase" | "plate";

export interface Product {
  slug: string;
  name: string;
  kiln: string;
  /** ราคาเป็น "สตางค์" — เก็บเป็น integer เสมอ ห้ามใช้ float กับเงิน */
  satang: number;
  vessel: Vessel;
  glaze: string;
  blurb: string;
  spec: { label: string; value: string }[];
  stock: number;
}

export const CATALOG: readonly Product[] = [
  {
    slug: "chaam-mork",
    name: "ชามหมอก",
    kiln: "เตาที่ 41",
    satang: 89000,
    vessel: "bowl",
    glaze: "#8FB4A2",
    blurb: "ชามข้าวปากผาย เคลือบศิลาดลบางจนเห็นรอยนิ้วช่างที่ขอบใน",
    spec: [
      { label: "ขนาด", value: "ปาก 14 ซม. สูง 7 ซม." },
      { label: "เผา", value: "รีดักชัน 1,260°C" },
      { label: "ใช้กับ", value: "ไมโครเวฟ / เครื่องล้างจานได้" },
    ],
    stock: 12,
  },
  {
    slug: "thuay-nam-kang",
    name: "ถ้วยน้ำค้าง",
    kiln: "เตาที่ 39",
    satang: 45000,
    vessel: "cup",
    glaze: "#A8C9BA",
    blurb: "ถ้วยชาไร้หู เคลือบหนาจนน้ำเคลือบไหลรวมที่ก้น เกิดวงสีเข้ม",
    spec: [
      { label: "ความจุ", value: "180 มล." },
      { label: "เผา", value: "รีดักชัน 1,260°C" },
      { label: "ใช้กับ", value: "เครื่องล้างจานได้ เลี่ยงไมโครเวฟ" },
    ],
    stock: 24,
  },
  {
    slug: "jae-kan-ruay",
    name: "แจกันร้าว",
    kiln: "เตาที่ 44",
    satang: 390000,
    vessel: "vase",
    glaze: "#6E9C87",
    blurb: "แจกันคอแคบ ผิวเคลือบแตกลายงาทั้งใบ ไม่มีสองใบที่ลายเหมือนกัน",
    spec: [
      { label: "ขนาด", value: "สูง 32 ซม. ฐาน 11 ซม." },
      { label: "เผา", value: "รีดักชัน 1,280°C" },
      { label: "หมายเหตุ", value: "รอยแตกลายงาเป็นลักษณะเฉพาะ ไม่ใช่ตำหนิ" },
    ],
    stock: 3,
  },
  {
    slug: "jan-din-plao",
    name: "จานดินเปล่า",
    kiln: "เตาที่ 41",
    satang: 62000,
    vessel: "plate",
    glaze: "#B9C7BC",
    blurb: "จานแบน เคลือบเฉพาะด้านใน เว้นขอบนอกเป็นเนื้อดินดิบให้จับได้ถนัด",
    spec: [
      { label: "ขนาด", value: "เส้นผ่าศูนย์กลาง 22 ซม." },
      { label: "เผา", value: "รีดักชัน 1,260°C" },
      { label: "ใช้กับ", value: "ไมโครเวฟ / เครื่องล้างจานได้" },
    ],
    stock: 18,
  },
  {
    slug: "chaam-khiao-kem",
    name: "ชามเขียวเข้ม",
    kiln: "เตาที่ 44",
    satang: 118000,
    vessel: "bowl",
    glaze: "#4F7A66",
    blurb: "ชามก๋วยเตี๋ยวทรงลึก เคลือบสูตรเหล็กสูง สีเข้มขึ้นตามรอบเผา",
    spec: [
      { label: "ขนาด", value: "ปาก 18 ซม. สูง 9 ซม." },
      { label: "เผา", value: "รีดักชัน 1,280°C" },
      { label: "ใช้กับ", value: "ไมโครเวฟ / เครื่องล้างจานได้" },
    ],
    stock: 7,
  },
  {
    slug: "thuay-tin-sung",
    name: "ถ้วยตีนสูง",
    kiln: "เตาที่ 39",
    satang: 54000,
    vessel: "cup",
    glaze: "#93B8A6",
    blurb: "ถ้วยกาแฟฐานสูง ยกแล้วมือไม่ร้อน ก้นเว้นดินดิบไว้ให้เห็นเนื้อ",
    spec: [
      { label: "ความจุ", value: "220 มล." },
      { label: "เผา", value: "รีดักชัน 1,260°C" },
      { label: "ใช้กับ", value: "เครื่องล้างจานได้" },
    ],
    stock: 15,
  },
] as const;

const BY_SLUG = new Map(CATALOG.map((p) => [p.slug, p]));

export function findProduct(slug: string): Product | undefined {
  return BY_SLUG.get(slug);
}
