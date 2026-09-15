"""ตรวจว่า Google tag ติดจริงบนหน้า landing/conversion ของแอด — ใช้ได้ทั้ง local และ URL สาธารณะ

    python tools/check_gtag.py http://127.0.0.1:5000 AW-TEST,G-TEST AW-TEST/LBL
    python tools/check_gtag.py https://thailinebot.com AW-123456789 AW-123456789/AbCdEf

อาร์กิวเมนต์ 2-3 (IDs / conversion label) ไม่ใส่ = อ่านจาก env GTAG_IDS / GOOGLE_ADS_CONV_ORDER
ถ้าทั้งสองทางว่าง = โหมด "ต้องไม่มี tag" (พฤติกรรมเดิมของเว็บ) — ไว้พิสูจน์ว่า env ว่างแล้วหน้าเว็บสะอาดจริง
exit 0 = ผ่านทุกหน้า, exit 1 = มีหน้าใดหน้าหนึ่งพลาด (พิมพ์รายการที่ขาดให้ดู)
"""
import os
import sys

import requests

# คอนโซลไทยบน Windows (cp874) ทำให้ print ข้อความไทยพัง — บังคับ utf-8 ก่อน
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PAGES = ["/", "/line-bot", "/line-bot-raka", "/bot-jongkiw"]   # หน้าแรก + landing ของ 3 ad group ใน campaign v1
GTM = "googletagmanager.com/gtag/js"


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    base = sys.argv[1].rstrip("/")
    ids = [x.strip() for x in (sys.argv[2] if len(sys.argv) > 2 else os.environ.get("GTAG_IDS", "")).split(",") if x.strip()]
    conv = (sys.argv[3] if len(sys.argv) > 3 else os.environ.get("GOOGLE_ADS_CONV_ORDER", "")).strip()
    expect_tag = bool(ids)
    print(f"base={base}  expect_tag={expect_tag}  ids={ids}  conv={conv or '-'}")

    failed = False
    for path in PAGES:
        url = base + path
        try:
            r = requests.get(url, timeout=30)
        except Exception as e:
            print(f"  ✗ {path}: request พัง — {e}")
            failed = True
            continue
        html = r.text
        missing = []
        if r.status_code != 200:
            missing.append(f"HTTP {r.status_code}")
        if expect_tag:
            if GTM not in html:
                missing.append("gtag.js script")
            for i in ids:
                if f"gtag('config','{i}')" not in html:
                    missing.append(f"config {i}")
            if conv and f'window.__adsConvOrder="{conv}"' not in html:
                missing.append("__adsConvOrder label")
            if "fastwork_click" not in html:
                missing.append("fastwork_click listener")
        else:
            # botkit.html มีคำว่า __adsConvOrder ในโค้ด submitOrder อยู่แล้ว (แค่อ่านค่า) — ห้ามใช้คำนั้นตัดสิน
            # ตัวชี้วัด "มี tag" = สคริปต์ gtag.js หรือบรรทัด gtag('js',…) ที่มีแค่ใน snippet เท่านั้น
            if GTM in html or "gtag('js'" in html:
                missing.append("มี tag ทั้งที่ env ว่าง")
        if missing:
            failed = True
            print(f"  ✗ {path}: " + ", ".join(missing))
        else:
            print(f"  ✓ {path}")
    print("FAIL" if failed else "PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
