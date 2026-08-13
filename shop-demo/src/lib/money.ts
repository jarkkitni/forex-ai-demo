const THB = new Intl.NumberFormat("th-TH", {
  style: "currency",
  currency: "THB",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

/** รับ integer สตางค์ คืน string บาท */
export function baht(satang: number): string {
  return THB.format(satang / 100);
}
