# รูปประกอบ demo ต่อร้าน (นกน้อยเปิดรัง — 22 ก.ค. 2026)

วางรูปที่นี่: `static/demo/<slug>/ชื่อรูป.jpg` → อ้างใน `demo_configs.json` ว่า `/static/demo/<slug>/ชื่อรูป.jpg`

## คีย์ใหม่ใน demo_configs.json (ทุกตัว "ไม่บังคับ" — ไม่ใส่ = หน้าตาเดิมเป๊ะ)

```jsonc
{
  "coffee-nim": {
    "logo_url": "/static/demo/coffee-nim/logo.jpg",        // โลโก้แทนอีโมจิใน header แชท
    "photos": [                                             // ปุ่ม "📷 ดูรูปร้าน" โผล่อัตโนมัติเมื่อมีรูป
      {"src": "/static/demo/coffee-nim/shop.jpg", "label": "หน้าร้าน"},
      {"src": "/static/demo/coffee-nim/cake.jpg", "label": "เค้กมะพร้าว"}
    ],
    "services": [
      {"name": "ลาเต้", "emoji": "☕", "price": "65.-", "bg": "#fff4e0",
       "img": "/static/demo/coffee-nim/latte.jpg"}          // รูปแทนอีโมจิบนการ์ดบริการ
    ]
  }
}
```

## กติกา (จาก WORK-นกน้อยเปิดรัง.md)

- Starter pack ฟรี: **รูปไม่เกิน 3 ใบ + โลโก้ 1** — เกินนั้นคือของ BotKit จ่ายแล้ว
- ใช้เฉพาะรูปที่ลูกค้าเป็นเจ้าของเอง + บอกลูกค้าว่าลิงก์ demo เป็นสาธารณะ
- ย่อรูปก่อนวาง (กว้าง ≤ 800px, ≤ 150KB/ใบ) — repo นี้ deploy ขึ้น Render ทุก push อย่าลากไฟล์กล้องดิบ 5MB เข้ามา
