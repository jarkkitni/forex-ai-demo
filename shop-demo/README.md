# ศิลาดล — เดโมร้านค้า + Payment Gateway

ร้านค้าออนไลน์ทำงานได้จริงตั้งแต่หน้าแรกจนถึงหน้ายืนยันการชำระเงิน
รันได้ทันทีโดยไม่ต้องมีคีย์ Stripe แล้วสลับไปใช้ Stripe จริงด้วยการเปลี่ยน env ตัวเดียว

```bash
npm install
cp .env.example .env.local
npm run dev
```

เปิด http://localhost:3000 → เลือกสินค้า → ตะกร้า → ชำระเงิน → หน้ารอสแกน
ในโหมดสาธิตจะมีปุ่ม "จำลองจ่ายสำเร็จ" แทนสัญญาณจากธนาคาร

---

## สถาปัตยกรรม

```
Browser ──POST /api/checkout──▶ คำนวณราคาฝั่งเซิร์ฟเวอร์ ──▶ Gateway
                                       │                        │
                                  สร้าง order                สร้าง PaymentIntent
                                  (awaiting_payment)          คืน QR payload
                                       │
Browser ──poll /api/order/[id]─────────┘
                                       ▲
ธนาคาร ──▶ Gateway ──webhook──▶ /api/webhook/stripe
                                       │
                          cron /api/cron/reconcile (ตาข่ายรองรับ)
```

### ทำไมต้อง poll ไม่ใช่รอ response
พร้อมเพย์ไม่ใช่การตัดบัตร ตอนกดชำระเรายังไม่รู้ผล — ลูกค้าต้องไปสแกนในแอปธนาคารก่อน
แล้วธนาคารถึงส่งสัญญาณกลับมาทาง webhook ทีหลัง อาจกินเวลาไม่กี่วินาทีถึงหลายนาที

ถ้าเขียนโค้ดเหมือนบัตรเครดิต (รอ response แล้วถือว่าจบ) ผลคือ **ออเดอร์ค้างสถานะ "รอชำระ"
ทั้งที่ลูกค้าโอนเงินมาแล้ว** ซึ่งเป็นบั๊กที่เจอบ่อยที่สุดในระบบพร้อมเพย์ที่ทำไม่ครบ

## จุดที่ตั้งใจทำให้ถูกตั้งแต่แรก

| เรื่อง | ที่อยู่ | ทำอะไร |
|---|---|---|
| ราคาคำนวณฝั่งเซิร์ฟเวอร์ | `api/checkout/route.ts` | client ส่งได้แค่ `slug` + `qty` แก้ราคาผ่าน devtools ไม่ได้ |
| Idempotency | `api/checkout` + `payments/stripe.ts` | กดรัว/เน็ตหลุดแล้ว retry ก็ได้รายการชำระเดียว |
| Webhook raw body | `api/webhook/stripe/route.ts` | verify signature ก่อนแตะข้อมูล |
| กัน webhook ซ้ำ | `lib/store.ts` → `seenEvents` | event เดิมยิงกี่ครั้งผลลัพธ์เท่าเดิม |
| ห้ามถอยสถานะ | `markFailed()` | จ่ายแล้วจะไม่ถูก event ที่มาช้ากว่าเปลี่ยนเป็น failed |
| QR หมดอายุ | `ORDER_TTL_MS` | 10 นาที ตรวจแบบ lazy ไม่ต้องมี timer ค้างต่อออเดอร์ |
| Reconcile | `api/cron/reconcile` | webhook หายเมื่อไรก็ตามยอดกลับมาได้ |
| เงินเก็บเป็น integer | `lib/money.ts` | หน่วยสตางค์ ไม่มี float กับเงิน |
| Motion ไม่ถ่วง LCP | `components/Reveal.tsx` | GSAP โหลดหลัง first paint, hero ใช้ CSS ล้วน |
| Reduced motion | `globals.css` | ปิดแอนิเมชันตาม OS setting |

## สลับไปใช้ Stripe จริง

```env
PAYMENT_DRIVER=stripe
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

```bash
stripe listen --forward-to localhost:3000/api/webhook/stripe
```

**ข้อจำกัดที่ต้องรู้ก่อน:** พร้อมเพย์บน Stripe ใช้ได้เฉพาะบัญชี Stripe ที่จดทะเบียนในประเทศไทย
และรับเฉพาะสกุล THB ถ้ายังไม่มีบัญชี ให้เดโมรันโหมด `mock` ไปก่อน — flow เหมือนกันทุกขั้น

**คำแนะนำเรื่องการเลือก gateway:** ถ้าลูกค้าขายในไทยเป็นหลัก รับเงินบาท
**Omise/Opn หรือ GBPrimePay ค่าธรรมเนียมถูกกว่าและเงินเข้าบัญชีไทยไวกว่า Stripe**
Stripe เหมาะเมื่อต้องรับเงินหลายสกุลหรือขายต่างประเทศ
โครงสร้าง `lib/payments/` แยก driver ไว้แล้ว เพิ่มไฟล์ใหม่ตาม interface `PaymentDriver` ก็สลับได้เลย

## ก่อนขึ้นโปรดักชันต้องแก้

1. **`lib/store.ts` เก็บใน memory** — ข้อมูลหายเมื่อรีสตาร์ต และใช้กับหลาย instance ไม่ได้
   เปลี่ยนเป็น Postgres: unique index บน `payment_ref`, ตาราง `webhook_events` แยกสำหรับ idempotency
2. **ตัดสต็อกจริง** — ตอนนี้เช็คสต็อกแต่ไม่หัก ต้อง reserve ตอนสร้างออเดอร์ + คืนเมื่อหมดอายุ ใช้ transaction
3. **QR ในโหมด mock เป็นลวดลายจำลอง** สแกนไม่ได้จริง โหมด Stripe ใช้ `image_url_png` ที่ Stripe ส่งมา
   หรือเข้ารหัส payload ด้วย lib `qrcode`
4. **Rate limit** `/api/checkout` — ต่อ IP และต่อ session
5. **เก็บอีเมล/ที่อยู่จัดส่ง** — เดโมข้ามไปเพื่อให้กดลองได้เร็ว
6. **Cron reconcile** — Vercel Cron หรือ cron-job.org ยิงทุก 5 นาที พร้อม header
   `Authorization: Bearer $CRON_SECRET`

## Deploy

Vercel: import repo → ตั้ง env → เสร็จ
`lib/store.ts` ต้องเปลี่ยนเป็น DB จริงก่อน ไม่งั้น serverless แต่ละ instance จะเห็นออเดอร์คนละชุด
