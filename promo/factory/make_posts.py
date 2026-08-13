#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""โรงงานโพสต์ — ปั๊มรูป + แคปชั่นวันละหลายโพสต์ โดยไม่ซ้ำของเดิม

วิธีใช้:
    python make_posts.py            # ได้ 5 โพสต์ (ค่าเริ่มต้น)
    python make_posts.py 3          # เอา 3 โพสต์
    python make_posts.py 5 --dry    # ดูว่าจะได้อะไรบ้าง ยังไม่เรนเดอร์รูป

ได้อะไร:
    out/YYYY-MM-DD/  →  รูป .png พร้อมโพสต์ + captions.txt (แคปชั่นครบทุกโพสต์)
                        + plan.md บอกว่าโพสต์ไหนลงที่ไหน เวลาไหน

ไม่กินโทเคน AI เลยสักตัว — เป็น Python + Chrome ล้วน
"""

import json, os, random, subprocess, sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from content import PRICE, SHOPS, PAINS, CAPTIONS, HASHTAGS, CHANNELS

HERE = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(HERE, "templates")
OUT = os.path.join(HERE, "out")
USED = os.path.join(HERE, "used.json")
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# แม่แบบไหนเหมาะกับคนอ่านกลุ่มไหน
FITS = {
    "receipt":      ["seller", "page"],
    "chat":         ["seller", "page", "tiktok"],
    "gp":           ["seller", "page", "tiktok"],
    "checklist":    ["seller", "page", "tiktok"],
    "before_after": ["seller", "page", "tech", "tiktok"],
}


# ─────────────────────────────────────────── ตัวช่วย
def load_used():
    if os.path.exists(USED):
        with open(USED, encoding="utf-8") as f:
            return set(tuple(x) for x in json.load(f))
    return set()


def save_used(used):
    with open(USED, "w", encoding="utf-8") as f:
        json.dump(sorted(list(used)), f, ensure_ascii=False, indent=1)


def fill(html, tokens):
    """แทน {{KEY}} — ถ้าเหลือ token ที่ไม่ได้แทน ให้ล้มทันที
    ดีกว่าปล่อยรูปที่มีคำว่า {{FOOT2}} โผล่กลางโพสต์ออกไปให้ลูกค้าเห็น"""
    for k, v in tokens.items():
        html = html.replace("{{%s}}" % k, str(v))
    if "{{" in html:
        leftover = html[html.index("{{"):html.index("{{") + 40]
        sys.exit(f"❌ ยังมี token ที่ไม่ได้แทนค่า: {leftover}")
    return html


def shoot(html_path, png_path, w=1080, h=1350):
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    f"--window-size={w},{h}", "--virtual-time-budget=6000",
                    f"--screenshot={png_path}",
                    "file:///" + html_path.replace("\\", "/").replace(" ", "%20")],
                   capture_output=True)
    return os.path.exists(png_path)


# ─────────────────────────────────────────── ตัวสร้าง token ของแต่ละแม่แบบ
def build_receipt(shop, pain):
    rows = [
        ("หน้าร้าน + ตะกร้า + หน้าจ่ายเงิน", f"{PRICE['start']}฿", False),
        ("รับเงินด้วย QR พร้อมเพย์", "รวมแล้ว", True),
        ("เงินเข้าปุ๊บ สถานะเปลี่ยนเอง", "รวมแล้ว", True),
        (f"ลงสินค้าให้ 20 รายการแรก", "รวมแล้ว", True),
        ("สอนใช้จนใช้เป็น", "รวมแล้ว", True),
        ("ค่าโดเมน + ค่าเช่าเว็บ ปีละ", f"{PRICE['yearly_low']}-{PRICE['yearly_high']}฿", False),
    ]
    rows_html = "".join(
        f'<div class="row"><span class="nm">{n}</span><span class="dots"></span>'
        f'<span class="vl{" free" if free else ""}">{v}</span></div>'
        for n, v, free in rows)
    gp = int(shop["month"].replace(",", "")) * PRICE["gp_percent"] // 100
    return dict(
        TITLE_A="ใบเสร็จที่", TITLE_EM=shop["name"].replace("ร้าน", "", 1) or "แม่ค้า",
        SUB=f'{shop["emoji"]} {shop["name"]} — {pain["fix"]}',
        RTITLE="ร้านค้าออนไลน์ของคุณเอง", META_R=f'สำหรับ{shop["name"]}',
        ROWS=rows_html, TOTAL=f"{PRICE['start']}฿",
        YEARLY=f"{PRICE['yearly_low']}-{PRICE['yearly_high']}฿",
        CMP_H="ถ้าไม่มีเว็บของตัวเอง", CMP_L="ค่า GP ที่โดนหักทุกเดือน",
        CMP_V=f"{gp:,}฿",
        CMP_NOTE=f'คิดจากยอดขาย {shop["month"]}฿/เดือน หักค่าธรรมเนียมแอปขายของ {PRICE["gp_percent"]}%<br>'
                 f'ขายเดือนแรกก็คืนทุนค่าทำเว็บแล้ว',
        THANKS="ลองกดซื้อในเว็บตัวอย่างก่อนได้", THANKS_EM="ไม่ต้องสมัคร ไม่เสียอะไร",
        FOOT1="กดลองเป็นลูกค้าดูเลย", FOOT_LINK=PRICE["demo"],
        FOOT2="รับทำเว็บตามสั่ง · ทักมาคุยได้ ดูให้ฟรีก่อนว่าเหมาะกับร้านแบบไหน",
    )


def build_chat(shop, pain):
    bubbles = [
        ("l", f'{shop["item"]} ราคาเท่าไหร่คะ'),
        ("l", "มีสีอื่นอีกไหมคะ ส่งกี่วันคะ"),
        ("r", f'{shop["price"]} ค่ะ ส่ง 2 วันค่ะ 🙏'),
        ("l", "โอนแล้วนะคะ รบกวนเช็คให้ด้วย"),
        ("slip", ""),
        ("r", "รอตรวจสักครู่นะคะ"),
    ]
    html = ""
    for kind, txt in bubbles:
        if kind == "slip":
            html += '<div class="slip"><div class="p"></div><div class="c">สลิป.jpg</div></div>'
        else:
            html += f'<div class="bub {kind}">{txt}</div>'
    return dict(
        HOOK=pain["hook"], TITLE_A=f'{shop["name"]}ที่ยังตอบเองทุกแชท',
        TITLE_EM="เสียเวลาไปกับเรื่องเดิมทุกวัน",
        SUB=f'{shop["emoji"]} ขาย{shop["item"]} {shop["qty"]} — ทุกออเดอร์ต้องผ่านมือเราหมด',
        CHAT_NAME="ลูกค้า (คนใหม่)", CHAT_TIME="23:47", BUBBLES=html,
        UNREAD="ยังไม่ได้ตอบอีก 12 แชท",
        PAIN_TITLE=pain["title"], PAIN_SUB=pain["sub"],
        FIX_TITLE="ถ้ามีเว็บของร้านเอง", FIX=pain["fix"],
        FOOT1=f'ลองกดเป็นลูกค้าดูเลย {PRICE["demo"]}',
        FOOT2="รับทำเว็บตามสั่ง · ทักมาคุยก่อนได้ ประเมินให้ฟรี ไม่กดดัน",
    )


def build_gp(shop, pain):
    month = int(shop["month"].replace(",", ""))
    gp = month * PRICE["gp_percent"] // 100
    year = gp * 12
    pts = [
        ("ไม่โดนหักต่อออเดอร์", "จ่ายค่าทำเว็บครั้งเดียว ขายเท่าไหร่ก็ไม่ถูกหักเพิ่ม"),
        ("ลูกค้าเป็นของเราเอง", "ได้ชื่อ เบอร์ ประวัติการซื้อ ไว้ทำโปรฯ ส่งหาเองได้"),
        ("ลิงก์ร้านเป็นของเรา", "แปะไบโอ วางตอนไลฟ์ ส่งในแชทได้เลย"),
    ]
    return dict(
        KICK=f'{shop["emoji"]} {shop["name"]}',
        TITLE="ยิ่งขายดี ยิ่งโดนหักเยอะ", TITLE_EM="ปีนึงหายไปเท่าไหร่ ลองคิดดู",
        ASSUME=f'คิดจากยอดขาย {shop["month"]}฿/เดือน หักค่าธรรมเนียม {PRICE["gp_percent"]}%',
        BAD_LABEL="ขายผ่านแอปมาร์เก็ตเพลส", BAD_NUM=f"{gp:,}฿", BAD_PER="ทุกเดือน ตลอดไป",
        BAD_NOTE=f"ปีนึงคือ {year:,}฿ · ยิ่งขายดียิ่งโดนหักเยอะ และวันที่เขาขึ้นค่าธรรมเนียม เราทำอะไรไม่ได้เลย",
        GOOD_LABEL="มีเว็บของร้านเอง", GOOD_NUM=f'{PRICE["start"]}฿', GOOD_PER="จ่ายครั้งเดียว",
        GOOD_NOTE=f'+ ค่าโดเมน/เช่าเว็บปีละ {PRICE["yearly_low"]}-{PRICE["yearly_high"]}฿ · ขายเท่าไหร่ก็ไม่โดนหักต่อออเดอร์',
        YEAR_L="ส่วนต่างปีแรก", YEAR_SUB="เอาไปลงโฆษณา ซื้อของเข้าร้าน หรือเก็บไว้เฉยๆ ก็ยังได้",
        YEAR_R=f"{max(year - int(PRICE['start'].replace(',', '')), 0):,}฿",
        POINTS="".join(f'<div class="pt"><span class="ic">✓</span><div><b>{a}</b> <span>{b}</span></div></div>'
                       for a, b in pts),
        SELF=f'คิดของร้านคุณเอง: ยอดขายต่อเดือน × {PRICE["gp_percent"]}% = ค่าธรรมเนียมที่จ่ายไปทุกเดือน',
        SELF_SUB="ถ้าตัวเลขที่ได้มากกว่าค่าทำเว็บ แปลว่าเว็บของตัวเองคืนทุนตั้งแต่เดือนแรก",
        FOOT1=f'ลองกดซื้อในเว็บตัวอย่างได้เลย {PRICE["demo"]}',
        FOOT2="รับทำเว็บตามสั่ง · ทักมาคุยก่อนได้ ไม่เหมาะก็บอกตรงๆ",
    )


def build_checklist(shop, pain):
    items = [
        (False, "ลูกค้าดูราคาและสต็อกเองได้", "ไม่ต้องรอเราพิมพ์ตอบทีละคน"),
        (False, "ลูกค้ากดสั่ง + จ่ายเงินเองได้", "ไม่ต้องทักมาคุยก่อนถึงจะซื้อได้"),
        (False, "เงินเข้าแล้วระบบรู้เอง", "ไม่ต้องให้ลูกค้าส่งสลิปมาให้ตรวจ"),
        (False, "มีลิงก์ร้านเป็นของตัวเอง", "แปะไบโอ วางตอนไลฟ์ ส่งในแชทได้"),
        (True,  "ตอนเรานอน ร้านยังขายได้", "ลูกค้าตี 2 ก็สั่งของได้เอง"),
    ]
    html = "".join(
        f'<div class="it"><div class="bx {"yes" if ok else "no"}">{"✓" if ok else "?"}</div>'
        f'<div class="tx">{t}<span>{s}</span></div></div>' for ok, t, s in items)
    return dict(
        TITLE=f'{shop["emoji"]} {shop["name"]}ของคุณ', TITLE_EM="พร้อมขายออนไลน์จริงหรือยัง",
        SUB="ลองเช็ก 5 ข้อนี้ดูครับ ติดกี่ข้อก็ไม่ผิด — แต่ข้อที่ติดคือเงินที่หลุดมือทุกวัน",
        ITEMS=html,
        VERDICT="ถ้าติดตั้งแต่ 2 ข้อขึ้นไป = ร้านคุณยังขายด้วยมือล้วน",
        VERDICT_SUB=f'{pain["title"]} — {pain["fix"]}',
        FOOT1="เว็บที่ทำครบทั้ง 5 ข้อ หน้าตาเป็นแบบนี้ ลองกดดู",
        FOOT_LINK=PRICE["demo"],
        FOOT2=f'รับทำเว็บตามสั่ง เริ่ม {PRICE["start"]} บาท · ทักมาคุยก่อนได้ ดูให้ฟรี',
    )


def build_before_after(shop, pain):
    other = [p for p in PAINS if p["key"] != pain["key"]][:2]
    pts = [pain] + other
    before_html = "".join(
        f'<div class="pt"><div class="ic">{p["icon"]}</div><div class="tx">{p["title"]}'
        f'<span>{p["sub"]}</span></div></div>' for p in pts)
    after = [
        ("🛒", "ลูกค้ากดซื้อเองได้ 24 ชม.", "ไม่ต้องรอเราตอบ ตอนเรานอนร้านก็ยังขายอยู่"),
        ("✅", "เงินเข้าปุ๊บ ระบบขึ้นให้เอง", "ไม่ต้องส่งสลิป ไม่ต้องนั่งตรวจอีกต่อไป"),
        ("🔗", "มีลิงก์ร้านเป็นของตัวเอง", "แปะไบโอ วางตอนไลฟ์ ส่งในแชทได้เลย"),
    ]
    after_html = "".join(
        f'<div class="pt"><div class="ic">{i}</div><div class="tx">{t}<span>{s}</span></div></div>'
        for i, t, s in after)
    return dict(
        B_TITLE=f'ก่อนมีเว็บของร้าน', B_SUB=f'{shop["emoji"]} {shop["name"]} — ทุกออเดอร์ต้องผ่านมือเราหมด',
        B_POINTS=before_html,
        CHAT_ITEM=f'{shop["item"]} ราคาเท่าไหร่คะ', CHAT_PRICE=f'{shop["price"]} ค่ะ ส่ง 2 วันค่ะ 🙏',
        MID=f'เปลี่ยนเป็นแบบนี้ เริ่ม {PRICE["start"]}.-',
        MID_SUB="จ่ายครั้งเดียว ได้เว็บที่รับเงินเองได้จริง ไม่ใช่แค่หน้าเว็บสวยๆ",
        A_TITLE="หลังมีเว็บของร้าน", A_SUB="ลูกค้าทำเองได้ทั้งหมด ตั้งแต่เลือกจนจ่ายเงิน",
        A_POINTS=after_html,
        FOOT1="รูปนี้คือระบบจริงที่เปิดใช้อยู่ · กดลองเป็นลูกค้าได้เลย",
        FOOT2=f'{PRICE["demo"]} · รับทำเว็บตามสั่ง ทักมาคุยก่อนได้ ดูให้ฟรี',
    )


BUILDERS = {"receipt": build_receipt, "chat": build_chat, "gp": build_gp,
            "checklist": build_checklist, "before_after": build_before_after}


# ─────────────────────────────────────────── แคปชั่น
def make_caption(audience, shop, pain, idx):
    pool = CAPTIONS[audience]
    body = pool[idx % len(pool)].format(
        shop=shop["name"], item=shop["item"], price=shop["price"], qty=shop["qty"],
        emoji=shop["emoji"], month=shop["month"], shop_tag=shop["name"].replace(" ", ""),
        pain_title=pain["title"], pain_title_plain=pain["title"].replace("นั่ง", ""),
        pain_sub=pain["sub"], fix=pain["fix"], hook=pain["hook"],
        demo=PRICE["demo"], start=PRICE["start"], gp=PRICE["gp_percent"],
    )
    tags = HASHTAGS[audience]
    return body + ("\n\n" + tags if tags else "")


# ─────────────────────────────────────────── main
def main():
    n = 5
    dry = "--dry" in sys.argv
    for a in sys.argv[1:]:
        if a.isdigit():
            n = int(a)

    used = load_used()
    rnd = random.Random()

    # เรียงคู่ที่ยังไม่เคยใช้ทั้งหมดก่อน แล้วค่อยสุ่มหยิบ — กันซ้ำจนกว่าคลังจะหมด
    combos = [(t, s["key"], p["key"]) for t in BUILDERS for s in SHOPS for p in PAINS]
    fresh = [c for c in combos if c not in used]
    if len(fresh) < n:
        print(f"⚠️  คลังเหลือ {len(fresh)} แบบ — ใช้หมดคลังแล้วจะเริ่มวนใหม่")
        used, fresh = set(), combos
    rnd.shuffle(fresh)

    day = date.today().isoformat()
    outdir = os.path.join(OUT, day)
    os.makedirs(outdir, exist_ok=True)

    captions, plan, made = [], [], 0
    today_tpl, today_pain = [], []   # กันโพสต์วันเดียวกันหน้าตาซ้ำ และพูดปัญหาเดิมซ้ำ
    for ch in CHANNELS[:n]:
        ok = lambda c: ch["audience"] in FITS[c[0]] and c not in used
        # ไล่จากเข้มไปหลวม: ไม่ซ้ำทั้งแม่แบบและปัญหา → ไม่ซ้ำแม่แบบ → เอาอะไรก็ได้ที่ยังไม่เคยใช้
        pick = (next((c for c in fresh if ok(c) and c[0] not in today_tpl and c[2] not in today_pain), None)
                or next((c for c in fresh if ok(c) and c[0] not in today_tpl), None)
                or next((c for c in fresh if ok(c)), None))
        if not pick:
            continue
        today_tpl.append(pick[0])
        today_pain.append(pick[2])
        tname, skey, pkey = pick
        used.add(pick)
        shop = next(s for s in SHOPS if s["key"] == skey)
        pain = next(p for p in PAINS if p["key"] == pkey)

        base = f'{made+1:02d}-{ch["key"]}-{tname}-{skey}-{pkey}'
        png = os.path.join(outdir, base + ".png")

        if not dry:
            with open(os.path.join(TPL, tname + ".html"), encoding="utf-8") as f:
                raw = f.read()
            tokens = BUILDERS[tname](shop, pain)
            # รูปประกอบอยู่ในโฟลเดอร์ promo/ แต่ไฟล์ html ชั่วคราวถูกเขียนใน out/<วันที่>/
            # จึงต้องอ้างที่อยู่เต็ม ไม่งั้นรูปหายตอนเรนเดอร์
            tokens["ASSET_DIR"] = "file:///" + os.path.dirname(HERE).replace("\\", "/").replace(" ", "%20")
            html = fill(raw, tokens)
            tmp = os.path.join(outdir, base + ".html")
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(html)
            ok = shoot(tmp, png)
            os.remove(tmp)
            if not ok:
                print(f"❌ เรนเดอร์ไม่สำเร็จ: {base}")
                continue

        cap = make_caption(ch["audience"], shop, pain, made)
        captions.append(f'{"="*70}\n[{made+1}] {ch["label"]}  ·  เวลาที่แนะนำ {ch["best_time"]}\n'
                        f'รูป: {base}.png\n{"="*70}\n{cap}\n')
        plan.append(f'| {made+1} | {ch["label"]} | {ch["best_time"]} | {tname} | {shop["name"]} | {pain["title"]} |')
        made += 1

    with open(os.path.join(outdir, "captions.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(captions))
    with open(os.path.join(outdir, "plan.md"), "w", encoding="utf-8") as f:
        f.write(f"# แผนโพสต์ {day}\n\n| # | ลงที่ไหน | เวลา | แม่แบบ | ร้าน | มุมที่ใช้ |\n"
                f"|---|---|---|---|---|---|\n" + "\n".join(plan) +
                "\n\n> รูปกับแคปชั่นอยู่ในโฟลเดอร์เดียวกันนี้ · ข้อความอยู่ใน captions.txt\n"
                "> โพสต์คนละกลุ่มกัน ห้ามยิงกลุ่มเดียวซ้ำวันเดียวกัน เดี๋ยวโดนแอดมินเตะ\n")
    save_used(used)

    print(f"✅ เตรียม {made} โพสต์แล้ว → {outdir}")
    print(f"   เหลือในคลังอีก {len(combos) - len(used)} แบบที่ยังไม่เคยใช้")
    for line in plan:
        print("  ", line)


if __name__ == "__main__":
    main()
