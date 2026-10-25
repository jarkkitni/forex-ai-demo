"""สร้างรูปตัวอย่างลิงก์ (OG image 1200x630) ให้ทุกบทความใน blog/posts.json

ใช้:  python tools/make_blog_og.py            (สร้างเฉพาะที่ยังไม่มี)
      python tools/make_blog_og.py --all      (สร้างใหม่ทั้งหมด)
      python tools/make_blog_og.py <slug> ... (เฉพาะบทความที่ระบุ)
ผลลัพธ์: static/og/blog/<slug>.png  — blog.py จะใช้รูปนี้อัตโนมัติถ้ามีไฟล์
ต้องมี: pip install playwright  และเบราว์เซอร์ Edge หรือ Chrome ในเครื่อง
"""
import html
import json
import os
import re
import sys

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "static", "og", "blog")

CATS = {  # ชื่อหมวด, สีหลัก
    "chatbot": ("แชทบอท LINE / Facebook", "#00e47a"),
    "automation": ("n8n และระบบอัตโนมัติ", "#ff9f43"),
    "ai": ("ใช้ AI ทำงาน", "#b388ff"),
    "dev": ("เขียนโค้ด & ดูแลระบบ", "#22d3ee"),
    "payment": ("รับเงินออนไลน์", "#ffd166"),
    "ads": ("โฆษณา Google Ads", "#4da3ff"),
    "seo": ("SEO และหาลูกค้า", "#ff6b9a"),
}

TPL = """<!DOCTYPE html><html lang="th"><head><meta charset="utf-8"><style>
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{width:1200px;height:630px;overflow:hidden}}
body{{background:#0a0f1c;color:#e8eef9;font-family:'Leelawadee UI','Noto Sans Thai','Sarabun',Tahoma,sans-serif;
 position:relative;padding:64px 80px}}
.glow{{position:absolute;right:-180px;top:-220px;width:720px;height:720px;border-radius:50%;
 background:radial-gradient(circle,{c}33 0%,{c}10 40%,transparent 70%)}}
.bar{{position:absolute;left:0;top:0;bottom:0;width:14px;background:{c}}}
.top{{display:flex;align-items:center;justify-content:space-between;position:relative}}
.brand{{font-size:30px;font-weight:700;letter-spacing:.2px}}
.brand span{{color:#00e47a}}
.chip{{font-size:24px;font-weight:700;color:{c};border:2px solid {c};border-radius:999px;padding:8px 22px;background:{c}14}}
.box{{position:absolute;left:80px;right:80px;top:150px;height:330px;display:flex;flex-direction:column;justify-content:center}}
h1{{font-weight:700;line-height:1.28;font-size:var(--fs,60px);color:#fff;word-break:normal;line-break:strict}}
h2{{margin-top:22px;font-weight:400;line-height:1.4;font-size:var(--fs2,30px);color:#c9d5ea}}
.foot{{position:absolute;left:80px;right:80px;bottom:56px;display:flex;justify-content:space-between;
 font-size:24px;color:#9fb0cf}}
.foot b{{color:#e8eef9}}
</style></head><body>
<div class="glow"></div><div class="bar"></div>
<div class="top"><div class="brand">Bot<span>Kit</span> · บทความ</div><div class="chip">{cat}</div></div>
<div class="box" id="box"><h1 id="h">{h}</h1>{sub}</div>
<div class="foot"><span>โดย <b>Jark</b>{mins}</span><span><b>thailinebot.com</b>/blog</span></div>
<script>
// ย่อขนาดตัวอักษรจนหัวข้อพอดีกล่อง
const box=document.getElementById('box'), root=document.documentElement;
let fs={fs0};
function fit(){{root.style.setProperty('--fs',fs+'px');root.style.setProperty('--fs2',Math.max(26,Math.round(fs*0.5))+'px');}}
fit();
while(box.scrollHeight>box.clientHeight && fs>34){{fs-=2;fit();}}
window.ogDone=fs;
</script></body></html>"""


# วลีที่ไม่ควรถูกตัดขึ้นบรรทัดใหม่กลางคำ (ตัดคำไทยของเบราว์เซอร์บางทีตัดไม่สวย)
NOWRAP = ["300 ข้อความ/เดือน", "หมดอายุ", "รีสตาร์ต", "ไม่สแปม", "บนเว็บ", "ต่างกันยังไง",
          "ใช้ออฟไลน์ได้", "เลขเวอร์ชัน", "บอทไม่ตอบ", "state machine", "Search Console",
          "ธุรกิจออนไลน์", "ไม่ให้บิลบาน", "Meta App Review"]


def split_title(t: str):
    m = re.split(r"\s*[:—]\s+", t, maxsplit=1)
    if len(m) == 2 and len(m[0]) >= 12:   # หัวสั้นเกิน (เช่น "n8n") ใช้ทั้งประโยคเป็นหัว
        return m[0], m[1]
    return t, ""


def esc_title(t: str) -> str:
    out = html.escape(t)
    for w in NOWRAP:
        ew = html.escape(w)
        out = out.replace(ew, f'<span style="white-space:nowrap">{ew}</span>')
    return out


def page(p: dict) -> str:
    cat, color = CATS.get(p.get("category", ""), ("บทความ", "#22d3ee"))
    head, sub = split_title(p["title"])
    sub_html = f"<h2>{html.escape(sub)}</h2>" if sub else ""
    mins = f" · อ่าน {p['minutes']} นาที" if p.get("minutes") else ""
    fs0 = 78 if len(head) <= 30 else 68 if len(head) <= 48 else 60
    return TPL.format(c=color, cat=html.escape(cat), h=esc_title(head), sub=sub_html, mins=mins, fs0=fs0)


def main(argv):
    posts = json.load(open(os.path.join(ROOT, "blog", "posts.json"), encoding="utf-8"))
    os.makedirs(OUT, exist_ok=True)
    force = "--all" in argv
    only = [a for a in argv if not a.startswith("--")]
    todo = [p for p in posts if (not only or p["slug"] in only)
            and (force or only or not os.path.exists(os.path.join(OUT, p["slug"] + ".png")))]
    if not todo:
        print("ไม่มีอะไรต้องสร้าง")
        return
    with sync_playwright() as pw:
        browser = None
        for ch in ("msedge", "chrome", None):
            try:
                browser = pw.chromium.launch(channel=ch) if ch else pw.chromium.launch()
                break
            except Exception:
                continue
        pg = browser.new_page(viewport={"width": 1200, "height": 630})
        for p in todo:
            pg.set_content(page(p), wait_until="load")
            pg.wait_for_function("window.ogDone > 0")
            pg.evaluate("document.fonts.ready")
            pg.wait_for_timeout(200)
            path = os.path.join(OUT, p["slug"] + ".png")
            pg.screenshot(path=path)
            print("ok", p["slug"])
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1:])
