# วิธี Deploy ForexAI Demo → Render.com (ฟรี)

## ขั้นตอน 1: อัปโหลดขึ้น GitHub

เปิด PowerShell ใน folder นี้ แล้วพิมพ์ทีละบรรทัด:

```
cd "C:\Users\ACER\Ai Agen\forex-ai-demo"
git init
git add .
git commit -m "ForexAI Pro Demo"
```

จากนั้นไปสร้าง repo ใหม่ที่ https://github.com/new
- ชื่อ: forex-ai-demo
- Private ก็ได้
- กด Create repository

แล้วกลับมา PowerShell:
```
git remote add origin https://github.com/YOUR_USERNAME/forex-ai-demo.git
git push -u origin main
```

---

## ขั้นตอน 2: Deploy บน Render

1. ไปที่ https://render.com → Sign Up (ฟรี)
2. กด **New +** → **Web Service**
3. เลือก **Connect GitHub** → เลือก repo `forex-ai-demo`
4. ตั้งค่า:
   - Name: `forexai-demo`
   - Runtime: **Python 3**
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python api_server.py`
5. กด **Advanced** → **Add Environment Variable**:
   ```
   ANTHROPIC_API_KEY = sk-ant-xxxxx
   LINE_TOKEN        = Bearer 6Mkae7...
   LINE_USER_ID      = U28e75f9...
   ```
6. กด **Create Web Service**
7. รอ ~3 นาที → ได้ URL เช่น `https://forexai-demo.onrender.com`

---

## ส่งลูกค้า

```
นี่คือ Demo ระบบ ForexAI ครับ 🚀

🔗 https://forexai-demo.onrender.com

ลองกดปุ่ม "วิเคราะห์ด้วย Claude AI" ได้เลยครับ
ระบบจะวิเคราะห์สัญญาณ EUR/USD, BTC และคู่อื่นๆ แบบ Real-time
พร้อม Entry / Stop Loss / Take Profit และส่ง LINE ได้ครับ
```
