#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
สร้างรูป OG (รูปที่ขึ้นตอนแชร์ลิงก์ลง FB/LINE) ให้หน้า SEO ทั้ง 6 หน้า

รันครั้งเดียวเวลาแก้ชื่อหน้า/สี — ไม่ได้รันตอนเสิร์ฟ
    python tools/make_og.py

ทำไมดึงข้อมูลจาก api_server: ชื่อหน้ากับสีประจำหน้าจะได้มีที่มาที่เดียว
ไม่ต้องมานั่งแก้ 2 ที่ให้ตรงกัน (แพทเทิร์นเดียวกับ demo_configs.json / portfolio.json)

วิธีเรนเดอร์: Edge headless --screenshot ตามแพทเทิร์นที่พิสูจน์แล้วใน Ai Agen\\capture2.ps1
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from api_server import SEO_PAGES, SEO_ACCENT, SEO_ACCENT_DEFAULT  # noqa: E402

W, H = 1200, 630
OUT_DIR = os.path.join(ROOT, "static", "og")

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_edge():
    for p in EDGE_CANDIDATES:
        if os.path.exists(p):
            return p
    sys.exit("❌ ไม่เจอ Microsoft Edge — แก้ EDGE_CANDIDATES ในไฟล์นี้")


def card_html(h1: str, ac: str, ink: str, glow: str) -> str:
    # ฟอนต์: Leelawadee UI / Tahoma = ฟอนต์ไทยที่มีอยู่ใน Windows ทุกเครื่อง
    # ถ้าใช้ฟอนต์ที่ไม่มีจริง Edge headless จะ fallback แล้วสระไทยลอย
    return f"""<!DOCTYPE html><html lang="th"><head><meta charset="UTF-8"><style>
*{{margin:0;padding:0;box-sizing:border-box;font-family:'Leelawadee UI',Tahoma,sans-serif}}
body{{width:{W}px;height:{H}px;overflow:hidden;color:#fff;display:flex;align-items:center;
     background:
       radial-gradient(760px 520px at 8% -12%,{glow.replace('.13)', '.42)')},transparent 62%),
       radial-gradient(620px 420px at 96% 108%,rgba(43,58,143,.34),transparent 60%),
       linear-gradient(#070b18,#05070f)}}
.wrap{{padding:0 76px;width:100%}}
.bar{{width:74px;height:7px;border-radius:4px;background:{ac};margin-bottom:34px}}
h1{{font-size:70px;line-height:1.22;font-weight:800;letter-spacing:-1px;max-width:1000px}}
h1 em{{font-style:normal;color:{ac}}}
.sub{{margin-top:26px;font-size:31px;color:#aebedd;font-weight:400}}
.row{{margin-top:44px;display:flex;align-items:center;gap:20px}}
.pill{{background:{ac};color:{ink};font-size:27px;font-weight:800;padding:15px 30px;border-radius:14px}}
.brand{{font-size:25px;color:#7d8dae}}
</style></head><body><div class="wrap">
<div class="bar"></div>
<h1>{h1}<br><em>ลองฟรีก่อนตัดสินใจ</em></h1>
<div class="sub">ตอบแชทอัตโนมัติ 24 ชม. · รับจองคิว · เก็บข้อมูลลูกค้าครบ</div>
<div class="row"><div class="pill">เริ่ม ฿590/เดือน</div>
<div class="brand">BotKit by Jark</div></div>
</div></body></html>"""


def main():
    edge = find_edge()
    os.makedirs(OUT_DIR, exist_ok=True)
    tmpdir = tempfile.mkdtemp(prefix="og_")
    made = []

    for slug, page in SEO_PAGES.items():
        ac, ink, glow = SEO_ACCENT.get(slug, SEO_ACCENT_DEFAULT)
        html_path = os.path.join(tmpdir, f"{slug}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(card_html(page["h1"], ac, ink, glow))

        # เขียนลง temp ที่ไม่มีช่องว่างในพาธก่อน แล้วค่อยย้าย (Edge งอแงกับพาธมีช่องว่าง)
        tmp_png = os.path.join(tmpdir, f"{slug}.png")
        # --headless=new เท่านั้น: โหมด --headless เดิมไม่เขียนไฟล์ออกมาเลยบนเครื่องนี้ (เงียบสนิท ไม่มี error)
        subprocess.run([
            edge, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
            "--hide-scrollbars", "--allow-file-access-from-files",
            f"--window-size={W},{H}", f"--screenshot={tmp_png}",
            "--virtual-time-budget=8000",
            "file:///" + html_path.replace("\\", "/"),
        ], capture_output=True, text=True)

        if not os.path.exists(tmp_png):
            print(f"❌ {slug}: Edge ไม่ได้สร้างไฟล์")
            continue
        dst = os.path.join(OUT_DIR, f"{slug}.png")
        with open(tmp_png, "rb") as src, open(dst, "wb") as out:
            out.write(src.read())
        made.append((slug, os.path.getsize(dst)))
        print(f"✅ {slug}.png  ({os.path.getsize(dst)/1024:.0f} KB)")

    print(f"\nเสร็จ {len(made)}/{len(SEO_PAGES)} ไฟล์ → {OUT_DIR}")
    if len(made) != len(SEO_PAGES):
        sys.exit(1)


if __name__ == "__main__":
    main()
