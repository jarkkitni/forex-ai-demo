"""
blog.py — ส่วนบทความของ thailinebot.com (เพิ่ม 24 ต.ค. 2026 — เปลี่ยนเว็บไปทาง AdSense)

ทำไมแยกไฟล์: api_server.py ใหญ่ 350KB+ และมีระบบลูกค้าจริง (webhook Meta/LINE) อยู่ในนั้น
ส่วนบทความเป็นหน้าเว็บล้วน แยกออกมาให้แก้ได้โดยไม่ต้องแตะโค้ดบอท

โครงไฟล์:
  blog/posts.json          รายการบทความ (slug, title, desc, date, category, …) — เรียงใหม่สุดก่อนอัตโนมัติ
  blog/posts/<slug>.html   เนื้อหาบทความเป็น HTML ส่วน body (ไม่มี <html>/<head>)
  เพิ่มบทความใหม่ = เพิ่ม 1 แถวใน posts.json + 1 ไฟล์ใน posts/ (ไม่ต้องแก้โค้ด)
  "draft": true = ยังไม่แสดง ไม่อยู่ใน sitemap (เปิดดูได้ที่ /blog/<slug>?preview=1)

AdSense (ตั้งบน Render เท่านั้น ห้าม hardcode):
  ADSENSE_CLIENT = "ca-pub-xxxxxxxxxxxxxxxx" → แทรกสคริปต์ AdSense ในหน้าบทความ/หน้ารวม/About/Contact
                   และเปิด /ads.txt ให้อัตโนมัติ · ว่าง = ไม่แทรกอะไรเลย /ads.txt ตอบ 404
  ไม่วางโฆษณาในหน้าขายบริการ (/botkit, landing SEO) โดยตั้งใจ — กันโฆษณาคู่แข่งขึ้นหน้าขายของเราเอง
"""
from __future__ import annotations

import html as _html
import json
import os
import re
from datetime import date

from flask import abort, request

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blog")
SITE_NAME = "BotKit"
SITE_TAGLINE = "สอนใช้ AI และระบบอัตโนมัติ ภาษาไทย — จากงานจริง"
AUTHOR = "Jark"
CONTACT_EMAIL = "jarkkitni@gmail.com"
# รหัสผู้เผยแพร่ AdSense ของ thailinebot.com (สมัคร 25 ต.ค. 2026) — ไม่ใช่ความลับ (โชว์ในซอร์สทุกหน้าอยู่แล้ว)
# ตั้ง env ADSENSE_CLIENT เพื่อเปลี่ยน หรือตั้งเป็น "off" เพื่อปิดโฆษณาทั้งหมดโดยไม่ต้องแก้โค้ด
ADSENSE_CLIENT = os.environ.get("ADSENSE_CLIENT", "ca-pub-3663263203324308").strip()
if ADSENSE_CLIENT.lower() in ("off", "0", "none", "false"):
    ADSENSE_CLIENT = ""

CATEGORIES = {
    "chatbot": "แชทบอท LINE / Facebook",
    "automation": "n8n และระบบอัตโนมัติ",
    "ai": "ใช้ AI ทำงาน",
    "dev": "เขียนโค้ด & ดูแลระบบ",
    "payment": "รับเงินออนไลน์",
    "ads": "โฆษณา Google Ads",
    "seo": "SEO และหาลูกค้า",
}

_ctx: dict = {"base_url": "", "head_extra": lambda: "", "track": lambda: None, "hub_is_home": True}


# ---------------------------------------------------------------- data
def load_posts(include_drafts: bool = False) -> list[dict]:
    """อ่าน posts.json ทุกครั้ง (ไฟล์เล็ก) — แก้ไฟล์แล้วไม่ต้องรีสตาร์ตตอนรัน local"""
    try:
        with open(os.path.join(_DIR, "posts.json"), encoding="utf-8") as f:
            posts = json.load(f)
    except (OSError, ValueError) as e:
        print(f"[blog] อ่าน posts.json ไม่ได้: {e}", flush=True)
        return []
    if not include_drafts:
        posts = [p for p in posts if not p.get("draft")]
    return sorted(posts, key=lambda p: p.get("date", ""), reverse=True)


def _post_body(slug: str) -> str | None:
    if not slug.replace("-", "").isalnum():      # กัน path traversal
        return None
    path = os.path.join(_DIR, "posts", f"{slug}.html")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return f.read()


def sitemap_urls() -> list[tuple[str, str]]:
    """[(path, lastmod)] ให้ api_server เอาไปต่อท้าย sitemap.xml"""
    posts = load_posts()
    newest = posts[0]["date"] if posts else date.today().isoformat()
    urls = [("/blog", newest), ("/about", "2026-10-24"), ("/contact", "2026-10-24")]
    urls += [(f"/blog/{p['slug']}", p.get("updated", p["date"])) for p in posts]
    return urls


# ---------------------------------------------------------------- layout
def _thai_date(iso: str) -> str:
    months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
              "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
    try:
        y, m, d = (int(x) for x in iso.split("-"))
        return f"{d} {months[m - 1]} {y + 543}"
    except (ValueError, IndexError):
        return iso


def _adsense_tag() -> str:
    if not ADSENSE_CLIENT:
        return ""
    return ('<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js'
            f'?client={_html.escape(ADSENSE_CLIENT)}" crossorigin="anonymous"></script>\n'
            f'<meta name="google-adsense-account" content="{_html.escape(ADSENSE_CLIENT)}">\n')


# ---- ช่องโฆษณาในบทความ (15 พ.ย. 2026) — ปิดไว้จนกว่า AdSense จะอนุมัติ ----
# ตั้ง env BLOG_AD_SLOTS บน Render หลังสร้าง ad unit แล้ว เช่น "a=1234567890,b=2345678901,c=3456789012"
#   a = ในบทความ หลังย่อหน้าแรก · b = กลางบทความ (เฉพาะบทความยาว) · c = Multiplex หลังกล่องผู้เขียน
# ว่าง = ไม่แสดงอะไรเลย (หน้าเหมือนพรีวิวทุกอย่าง ไม่มีกรอบว่าง)
def _ad_slots() -> dict:
    raw = os.environ.get("BLOG_AD_SLOTS", "")
    out = {}
    for part in raw.split(","):
        k, _, v = part.strip().partition("=")
        if k.strip() in ("a", "b", "c") and v.strip().isdigit():
            out[k.strip()] = v.strip()
    return out


def _ad(slot_key: str) -> str:
    sid = _ad_slots().get(slot_key)
    if not sid or not ADSENSE_CLIENT:
        return ""
    fmt = 'data-ad-format="autorelaxed"' if slot_key == "c" else 'data-ad-format="auto" data-full-width-responsive="true"'
    return (f'<aside class="ad ad-{slot_key}" aria-label="โฆษณา"><span class="ad-tag">โฆษณา</span>'
            f'<ins class="adsbygoogle" data-ad-client="{_html.escape(ADSENSE_CLIENT)}" data-ad-slot="{sid}" {fmt}></ins>'
            '<script>(adsbygoogle=window.adsbygoogle||[]).push({});</script></aside>')


def _wrap_tables(body_html: str) -> str:
    """ตารางกว้างเลื่อนแนวนอนได้ในกรอบของมันเอง — หน้าไม่ล้นจอบนมือถือ"""
    return re.sub(r"(<table\b.*?</table>)", r'<div class="tblwrap">\1</div>', body_html, flags=re.S)


def _with_ads(body_html: str) -> str:
    """แทรกช่อง a หลังย่อหน้าแรก และช่อง b ก่อน h2 ที่อยู่กลางบทความ (เฉพาะบทความยาว ข้อความเกิน ~5,000 ตัวอักษร)"""
    a, b = _ad("a"), _ad("b")
    if not a and not b:
        return body_html
    if a and "</p>" in body_html:
        i = body_html.index("</p>") + 4
        body_html = body_html[:i] + a + body_html[i:]
    if b and len(re.sub(r"<[^>]+>", "", body_html)) > 5000:
        h2s = [m.start() for m in re.finditer(r"<h2[ >]", body_html)]
        if len(h2s) >= 3:
            j = h2s[len(h2s) // 2]
            body_html = body_html[:j] + b + body_html[j:]
    return body_html

CSS = """
/* Paper Notebook (15 พ.ย. 2026) — ชุดสีเดียวกับหน้า /botkit · โหมดมืดอัตโนมัติตามเครื่องผู้อ่าน
   ระยะห่างตามเลข Fibonacci 5/8/13/21/34/55 · คอลัมน์บทความ 680px */
:root{--bg:#F2F4EE;--bg2:#FBFCF8;--card:#FBFCF8;--line:#D9DED3;--fg:#0F2A20;--soft:#24392F;--muted:#5C6E64;
--ac:#0B8A4E;--ac2:#0B9A57;--sun:#F0A00F;--sun-soft:#FFF1D3;--chip:#DCF2E5;--code-bg:#0F2A20;--code-fg:#E6F2EA;
--inline-code:#E3EBE1;--svc:#0F2A20;--svc-fg:#E6F2EA;--hdr:rgba(242,244,238,.92);
--f-display:'Bai Jamjuree','Noto Sans Thai',system-ui,sans-serif;
--f-body:'IBM Plex Sans Thai Looped','Noto Sans Thai',system-ui,sans-serif;
--f-mono:'IBM Plex Mono',ui-monospace,Consolas,monospace;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#0E1713;--bg2:#15211B;--card:#15211B;--line:#26362E;--fg:#E6EFE9;
--soft:#C9D6CF;--muted:#8FA298;--ac:#3DD68C;--ac2:#3DD68C;--sun:#F5B53A;--sun-soft:#2B2414;--chip:#1B2C23;
--code-bg:#09110D;--code-fg:#D6E8DD;--inline-code:#1B2C23;--svc:#15211B;--svc-fg:#E6EFE9;--hdr:rgba(14,23,19,.92);color-scheme:dark}}
*{box-sizing:border-box;margin:0;padding:0}
html{-webkit-text-size-adjust:100%}
body{background:var(--bg);color:var(--fg);font-family:var(--f-body);line-height:1.8;font-size:16px;-webkit-font-smoothing:antialiased}
a{color:var(--ac)}
:focus-visible{outline:3px solid var(--sun);outline-offset:2px;border-radius:4px}
h1,h2,h3{font-family:var(--f-display);text-wrap:balance}
.top{border-bottom:1px solid var(--line);background:var(--hdr);position:sticky;top:0;z-index:5;backdrop-filter:blur(8px)}
.top .in{max-width:1080px;margin:0 auto;padding:0 16px;min-height:55px;display:flex;align-items:center;gap:21px;flex-wrap:wrap}
.brand{font-family:var(--f-display);font-weight:700;font-size:19px;color:var(--fg);text-decoration:none}
.brand span{color:var(--ac2)}
.nav{display:flex;gap:2px;flex-wrap:wrap;margin-left:auto}
.nav a{color:var(--muted);text-decoration:none;font-size:15px;padding:6px 10px;border-radius:8px}
.nav a:hover{color:var(--fg)}
.nav a.on{color:var(--fg);font-weight:600;box-shadow:inset 0 -2px 0 var(--ac2);border-radius:0}
.wrap{max-width:1080px;margin:0 auto;padding:34px 16px 89px}
.narrow{max-width:712px}
.hero h1{font-size:clamp(30px,5.4vw,46px);line-height:1.3;font-weight:700;letter-spacing:-.01em;margin-bottom:13px}
.hero h1 em{font-style:normal;background:linear-gradient(transparent 62%,var(--sun-soft) 62%);padding:0 .06em}
.hero p{color:var(--muted);font-size:17.5px;max-width:640px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:21px 0 8px}
.chip{border:1px solid var(--line);background:var(--card);color:var(--soft);font-size:14px;padding:5px 13px;border-radius:999px;text-decoration:none}
.chip:hover{border-color:var(--fg)}
.chip.on{border-color:var(--fg);color:var(--fg);box-shadow:inset 0 0 0 1px var(--fg);font-weight:600}
h2.sec{font-size:21px;margin:55px 0 21px;color:var(--fg)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:13px}
.post{background:var(--card);border:1px solid var(--line);border-radius:13px;padding:21px;text-decoration:none;
color:var(--fg);display:flex;flex-direction:column;gap:8px;transition:border-color .15s,transform .15s}
.post:hover{border-color:var(--fg);transform:translateY(-2px)}
.post .cat{font:500 12.5px var(--f-mono);color:var(--ac)}
.post h3{font-size:18px;line-height:1.45;font-weight:600;color:var(--fg)}
.post p{font-size:14.5px;color:var(--muted);line-height:1.65}
.post .meta{font:12.5px var(--f-mono);color:var(--muted);margin-top:auto}
.tools{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:13px}
.tool{background:var(--card);border:1px solid var(--line);border-radius:13px;padding:21px;text-decoration:none;color:var(--fg)}
.tool:hover{border-color:var(--fg)}
.tool b{display:block;color:var(--fg);margin-bottom:5px;font-family:var(--f-display);font-weight:600}
.tool span{font-size:14px;color:var(--muted)}
.tool .wake{display:block;font-style:normal;font-size:12.5px;color:var(--muted);margin-top:8px}
.svc{margin-top:55px;background:var(--svc);color:var(--svc-fg);border-radius:21px;padding:34px 21px}
.svc b{font-family:var(--f-display);font-size:21px;color:var(--svc-fg)}
.svc p{color:var(--svc-fg);opacity:.8;font-size:15px;margin:8px 0 21px}
.btn{display:inline-block;background:var(--sun);color:#0F2A20;font-weight:600;text-decoration:none;padding:11px 21px;border-radius:999px;font-size:15px}
.crumb{font:13px var(--f-mono);color:var(--muted);margin-bottom:13px}
.crumb a{color:var(--muted);text-decoration:none}
.crumb a:last-child{background:var(--chip);color:var(--ac);border-radius:999px;padding:2px 10px;margin-left:4px}
article h1{font-size:clamp(28px,5vw,38px);line-height:1.35;font-weight:700;letter-spacing:-.01em;margin-bottom:13px}
.byline{font:13px var(--f-mono);color:var(--muted);margin-bottom:34px;padding-bottom:21px;border-bottom:1px solid var(--line)}
.prose{font-size:17px;color:var(--soft)}
.prose>*+*{margin-top:21px}
.prose h2{font-size:24px;line-height:1.35;color:var(--fg);margin-top:55px}
.prose h3{font-size:19px;font-weight:600;line-height:1.4;color:var(--fg);margin-top:34px}
.prose strong{color:var(--fg);font-weight:600}
.prose ul,.prose ol{padding-left:1.3em}
.prose li+li{margin-top:5px}
.prose code{background:var(--inline-code);border-radius:5px;padding:1px 5px;font-size:14.5px;font-family:var(--f-mono);color:var(--fg);word-break:break-word}
.prose pre{background:var(--code-bg);color:var(--code-fg);border-radius:13px;padding:21px;overflow-x:auto;font-size:13.5px;line-height:1.6}
.prose pre code{background:none;padding:0;color:inherit;font-size:inherit}
.prose blockquote,.prose .note{border-left:3px solid var(--ac2);background:var(--card);padding:13px 21px;border-radius:0 13px 13px 0;color:var(--soft)}
.prose .warn{border-left-color:var(--sun);background:var(--sun-soft)}
.prose table{width:100%;border-collapse:collapse;font-size:15px}
.prose th,.prose td{border-bottom:1px solid var(--line);padding:8px 13px;text-align:left;vertical-align:top}
.prose th{color:var(--fg);font-family:var(--f-display);font-weight:600;border-bottom:2px solid var(--fg)}
.prose td code{white-space:nowrap;word-break:normal}
.tblwrap{overflow-x:auto}
.toc{background:var(--card);border:1px solid var(--line);border-radius:13px;padding:13px 21px;font-size:15px}
.toc b{color:var(--fg)}
.related{margin-top:55px}
.about-box{margin-top:55px;display:grid;grid-template-columns:auto 1fr;gap:13px;align-items:start;background:var(--card);
border:1px solid var(--line);border-radius:13px;padding:21px;font-size:15px;color:var(--soft);line-height:1.7}
.about-box .av{width:48px;height:48px;border-radius:50%;background:var(--fg);color:var(--bg);display:grid;place-items:center;font:700 20px var(--f-display)}
.about-box b{display:block;color:var(--fg);font-family:var(--f-display);font-size:17px}
.ad{margin:34px 0;text-align:center}
.ad-tag{display:block;font:11px var(--f-mono);color:var(--muted);letter-spacing:.06em;margin-bottom:5px}
.ad ins{display:block;min-height:280px}
.ad.ad-c{margin-top:55px}
@media (min-width:768px){.ad.ad-a ins{min-height:120px}}
footer.site{background:#0F2A20;color:#B9C8C0;font-size:13.5px;line-height:1.9}
footer.site .in{max-width:1080px;margin:0 auto;padding:34px 16px 55px}
footer.site b{color:#fff!important}
footer.site a{color:#fff;text-decoration:none}
footer.site a:hover{color:#F0A00F}
@media (max-width:560px){.top{position:static}.nav{margin-left:0;width:100%}.prose{font-size:16.5px}}
@media (prefers-reduced-motion:reduce){.post{transition:none}.post:hover{transform:none}}
"""


def _nav(active: str = "") -> str:
    items = [("/", "หน้าแรก", "home"), ("/blog", "บทความ", "blog"),
             ("/blog#tools", "เครื่องมือฟรี", "tools"), ("/botkit", "บริการ", "svc"),
             ("/about", "เกี่ยวกับเรา", "about"), ("/contact", "ติดต่อ", "contact")]
    on = ' class="on"'
    links = "".join(f'<a href="{h}"{on if k == active else ""}>{t}</a>' for h, t, k in items)
    return (f'<header class="top"><div class="in"><a class="brand" href="/">Bot<span>Kit</span></a>'
            f'<nav class="nav">{links}</nav></div></header>')


def site_header_html(active: str = "svc") -> str:
    """แถบเมนูบนสุดแบบแยกสไตล์ (คลาส bkh-*) — แปะบนหน้าขาย /botkit และหน้า landing บริการ
    ให้คนที่กด "บริการ" จากหน้าบทความกลับไปหน้าแรก/บทความได้ ไม่ใช้คลาสร่วมกับ CSS ของหน้านั้นเลย"""
    items = [("/", "หน้าแรก", "home"), ("/blog", "บทความ", "blog"),
             ("/blog#tools", "เครื่องมือฟรี", "tools"), ("/botkit", "บริการ", "svc"),
             ("/about", "เกี่ยวกับเรา", "about"), ("/contact", "ติดต่อ", "contact")]
    links = "".join(
        f'<a href="{h}" class="bkh-a{" bkh-on" if k == active else ""}">{t}</a>' for h, t, k in items)
    return (
        "<style>.bkh{position:relative;z-index:50;border-bottom:1px solid #1f2b46;background:rgba(10,15,28,.94)}"
        ".bkh-in{max-width:1080px;margin:0 auto;padding:10px 16px;display:flex;align-items:center;gap:14px;flex-wrap:wrap;"
        "font-family:'Segoe UI',system-ui,-apple-system,Tahoma,'Noto Sans Thai',sans-serif}"
        ".bkh-b{font-weight:800;font-size:18px;color:#fff;text-decoration:none}.bkh-b span{color:#00e47a}"
        ".bkh-n{display:flex;gap:4px;flex-wrap:wrap;margin-left:auto}"
        ".bkh-a{color:#c9d5ea;text-decoration:none;font-size:14.5px;padding:6px 10px;border-radius:8px;line-height:1.4}"
        ".bkh-a:hover,.bkh-on{background:#121b30;color:#fff}"
        "@media (max-width:560px){.bkh-n{margin-left:0;width:100%}}</style>"
        f'<header class="bkh"><div class="bkh-in"><a class="bkh-b" href="/">Bot<span>Kit</span></a>'
        f'<nav class="bkh-n">{links}</nav></div></header>'
    )


def site_footer_html() -> str:
    """footer มาตรฐาน — ลิงก์นโยบายครบทุกหน้า (AdSense/Google ตรวจตรงนี้)"""
    return f"""<footer class="site"><div class="in">
<b style="color:#c9d5ea">{SITE_NAME}</b> — {SITE_TAGLINE}<br>
<a href="/blog">บทความ</a> · <a href="/about">เกี่ยวกับเรา</a> · <a href="/contact">ติดต่อเรา</a> ·
<a href="/privacy">นโยบายความเป็นส่วนตัว</a> · <a href="/terms">ข้อกำหนดการใช้งาน</a> · <a href="/botkit">บริการรับทำบอท</a><br>
<span style="opacity:.8">ทะเบียนพาณิชย์เลขที่ 1509900302285 · ชื่อที่ใช้ในการประกอบพาณิชยกิจ: บอทคิท (BOTKIT)</span><br>
<span style="opacity:.6">LINE เป็นเครื่องหมายการค้าของ LY Corporation · Facebook/Instagram เป็นเครื่องหมายการค้าของ Meta Platforms, Inc. — เว็บนี้ไม่ได้เป็นส่วนหนึ่งของบริษัทดังกล่าว</span>
</div></footer>"""


def _page(*, title: str, desc: str, path: str, body: str, active: str = "",
          og_type: str = "website", extra_head: str = "", ads: bool = True,
          robots: str = "index, follow", og_image: str = "/static/og/home.png") -> str:
    base = _ctx["base_url"]
    url = f"{base}{path}"
    t, d = _html.escape(title), _html.escape(desc)
    return f"""<!DOCTYPE html><html lang="th"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
{_ctx['head_extra']()}{_adsense_tag() if ads else ''}<title>{t}</title>
<meta name="description" content="{d}">
<link rel="canonical" href="{url}">
<meta name="robots" content="{robots}">
<meta name="theme-color" content="#F2F4EE" media="(prefers-color-scheme: light)"><meta name="theme-color" content="#0E1713" media="(prefers-color-scheme: dark)">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bai+Jamjuree:wght@700&family=IBM+Plex+Sans+Thai+Looped:wght@400;600&family=IBM+Plex+Mono:wght@500&display=swap" rel="stylesheet">
<meta property="og:type" content="{og_type}"><meta property="og:locale" content="th_TH">
<meta property="og:site_name" content="{SITE_NAME}"><meta property="og:title" content="{t}">
<meta property="og:description" content="{d}"><meta property="og:url" content="{url}">
<meta property="og:image" content="{base}{og_image}">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:image" content="{base}{og_image}">
<link rel="alternate" type="application/rss+xml" title="{SITE_NAME}" href="{base}/blog/feed.xml">
{extra_head}<style>{CSS}</style></head><body>
{_nav(active)}
{body}
{site_footer_html()}
</body></html>"""


def _card(p: dict) -> str:
    cat = CATEGORIES.get(p.get("category", ""), "")
    mins = p.get("minutes")
    return (f'<a class="post" href="/blog/{p["slug"]}"><span class="cat">{_html.escape(cat)}</span>'
            f'<h3>{_html.escape(p["title"])}</h3><p>{_html.escape(p["desc"])}</p>'
            f'<span class="meta">{_thai_date(p["date"])}{f" · อ่าน {mins} นาที" if mins else ""}</span></a>')


TOOLS_HTML = """<div class="tools">
<a class="tool" href="/chatmaker/" target="_blank" rel="noopener"><b>💬 สร้างภาพแชทตัวอย่าง</b><span>พิมพ์บทสนทนาเองทั้งสองฝั่ง ได้ภาพหน้าจอแชทไว้ทำสไลด์/โฆษณา</span></a>
<a class="tool" href="https://smarthook-viral-video-ai.onrender.com/" target="_blank" rel="noopener"><b>🎬 สร้างคลิปเล่าเรื่องด้วย AI</b><span>พิมพ์พล็อตสั้นๆ ได้ภาพ เสียงพากย์ไทย และวิดีโอแนวตั้ง 9:16</span><em class="wake">⏳ เปิดครั้งแรกอาจรอ ~1 นาที ระบบกำลังตื่น</em></a>
<a class="tool" href="https://siladon-shop-demo.onrender.com/" target="_blank" rel="noopener"><b>🏺 ร้านค้าออนไลน์ + QR พร้อมเพย์</b><span>ลองระบบตะกร้าและหน้าชำระเงินที่เปลี่ยนสถานะเอง (โหมดสาธิต)</span><em class="wake">⏳ เปิดครั้งแรกอาจรอ ~1 นาที ระบบกำลังตื่น</em></a>
</div>"""


# ---------------------------------------------------------------- pages
def hub_page() -> str:
    posts = load_posts()
    cat = request.args.get("cat", "")
    if cat not in CATEGORIES:
        cat = ""
    shown = [p for p in posts if not cat or p.get("category") == cat]
    chips = '<a class="chip{}" href="/blog">ทั้งหมด</a>'.format(" on" if not cat else "")
    chips += "".join(
        f'<a class="chip{" on" if k == cat else ""}" href="/blog?cat={k}">{v}</a>'
        for k, v in CATEGORIES.items() if any(p.get("category") == k for p in posts)
    )
    cards = "".join(_card(p) for p in shown) or '<p style="color:var(--muted)">ยังไม่มีบทความในหมวดนี้</p>'
    body = f"""<main class="wrap">
<section class="hero"><h1>เรียน AI และระบบอัตโนมัติ<br><em>จากงานที่ใช้จริง</em></h1>
<p>บทความภาษาไทยเรื่อง LINE Bot, แชทบอท Facebook, n8n, การใช้ AI ทำงาน และการดูแลระบบ —
เขียนจากโปรเจกต์ที่รันจริงกับร้านค้าจริง รวมถึงจุดที่เคยพังและวิธีแก้</p></section>
<div class="chips">{chips}</div>
<h2 class="sec">บทความล่าสุด</h2>
<div class="grid">{cards}</div>
<h2 class="sec" id="tools">🧰 เครื่องมือฟรี</h2>
{TOOLS_HTML}
<div class="svc"><b>อยากได้บอทหรือระบบอัตโนมัติให้ร้านคุณ?</b>
<p>นอกจากบทความ เรารับทำ LINE Bot / บอทตอบแชท Facebook-IG / ระบบจองคิว / n8n automation ด้วย</p>
<a class="btn" href="/botkit">ดูบริการและราคา →</a></div>
</main>"""
    ld = {"@context": "https://schema.org", "@type": "WebSite", "name": SITE_NAME,
          "url": _ctx["base_url"] + "/", "inLanguage": "th"}
    return _page(title=f"{SITE_NAME} — {SITE_TAGLINE}",
                 desc="บทความภาษาไทยสอนทำ LINE Bot, แชทบอท Facebook, n8n automation และใช้ AI ทำงาน "
                      "จากประสบการณ์ทำระบบจริง พร้อมเครื่องมือฟรี",
                 # หน้าแรกกับ /blog เนื้อหาเดียวกัน → canonical ชี้ที่เดียว กัน duplicate content
                 path="/" if _ctx["hub_is_home"] and not cat else (f"/blog?cat={cat}" if cat else "/blog"),
                 body=body,
                 active="home" if request.path == "/" else "blog",
                 extra_head=f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>\n')


def post_page(slug: str) -> str:
    all_posts = load_posts(include_drafts=True)
    p = next((x for x in all_posts if x["slug"] == slug), None)
    if not p or (p.get("draft") and request.args.get("preview") != "1"):
        abort(404)
    body_html = _post_body(slug)
    if body_html is None:
        abort(404)
    base = _ctx["base_url"]
    cat = CATEGORIES.get(p.get("category", ""), "")
    related = [x for x in load_posts() if x["slug"] != slug and x.get("category") == p.get("category")]
    related += [x for x in load_posts() if x["slug"] != slug and x not in related]
    rel_html = "".join(_card(x) for x in related[:3])
    upd = p.get("updated")
    byline = f'โดย {AUTHOR} · {_thai_date(p["date"])}'
    if upd and upd != p["date"]:
        byline += f' · อัปเดต {_thai_date(upd)}'
    if p.get("minutes"):
        byline += f' · อ่าน {p["minutes"]} นาที'
    ld = [{
        "@context": "https://schema.org", "@type": "BlogPosting",
        "headline": p["title"], "description": p["desc"], "inLanguage": "th",
        "datePublished": p["date"], "dateModified": upd or p["date"],
        "author": {"@type": "Person", "name": AUTHOR, "url": f"{base}/about"},
        "publisher": {"@type": "Organization", "name": "บอทคิท (BOTKIT)", "url": base + "/"},
        "mainEntityOfPage": f"{base}/blog/{slug}",
    }, {
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "บทความ", "item": f"{base}/blog"},
            {"@type": "ListItem", "position": 2, "name": p["title"], "item": f"{base}/blog/{slug}"},
        ],
    }]
    extra = "".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False)}</script>\n' for x in ld)
    extra += f'<meta property="article:published_time" content="{p["date"]}">\n'
    body = f"""<main class="wrap narrow">
<div class="crumb"><a href="/blog">บทความ</a> › <a href="/blog?cat={p.get('category','')}">{_html.escape(cat)}</a></div>
<article><h1>{_html.escape(p['title'])}</h1>
<div class="byline">{byline}</div>
<div class="prose">{_with_ads(_wrap_tables(body_html))}</div></article>
<div class="about-box"><span class="av" aria-hidden="true">{AUTHOR[:1]}</span><div><b>{AUTHOR} · นักพัฒนา LINE Bot และระบบ AI อัตโนมัติ</b>
อยู่เชียงใหม่ ทำระบบตอบแชทและจองคิวให้ร้านค้าจริง บทความในเว็บนี้มาจากงานที่ลงมือทำเอง
<a href="/about">อ่านเพิ่มเกี่ยวกับผู้เขียน →</a></div></div>
{_ad("c")}
<section class="related"><h2 class="sec" style="margin-top:0">อ่านต่อ</h2><div class="grid">{rel_html}</div></section>
</main>"""
    robots = "noindex, nofollow" if p.get("draft") else "index, follow"
    return _page(title=f"{p['title']} | {SITE_NAME}", desc=p["desc"], path=f"/blog/{slug}",
                 body=body, active="blog", og_type="article", extra_head=extra, robots=robots,
                 og_image=_post_og(slug))


def _post_og(slug: str) -> str:
    """รูปตัวอย่างลิงก์ของบทความ (สร้างด้วย tools/make_blog_og.py) — ไม่มีไฟล์ใช้รูปหน้าแรก"""
    f = os.path.join(os.path.dirname(_DIR), "static", "og", "blog", f"{slug}.png")
    return f"/static/og/blog/{slug}.png" if os.path.exists(f) else "/static/og/home.png"


def about_page() -> str:
    n = len(load_posts())
    body = f"""<main class="wrap narrow"><article><h1>เกี่ยวกับเรา</h1>
<div class="prose">
<p><strong>{SITE_NAME}</strong> เป็นเว็บบทความภาษาไทยเรื่องการใช้ AI และระบบอัตโนมัติในงานจริง
ดำเนินการโดย <strong>บอทคิท (BOTKIT)</strong> ทะเบียนพาณิชย์เลขที่ 1509900302285 จังหวัดเชียงใหม่</p>
<h2>ใครเขียน</h2>
<p>ผม {AUTHOR} เป็นนักพัฒนาอิสระ ทำ LINE Bot, บอทตอบแชท Facebook/Instagram, ระบบจองคิว,
ระบบรับเงิน QR พร้อมเพย์ และ workflow อัตโนมัติด้วย n8n ให้ร้านค้าและธุรกิจขนาดเล็ก
ระบบที่เขียนถึงในเว็บนี้ส่วนใหญ่เป็นระบบที่ผมทำและดูแลเองอยู่จริง</p>
<h2>ทำไมถึงเขียน</h2>
<p>บทความภาษาไทยเรื่องพวกนี้มักหยุดอยู่ที่ "วิธีตั้งค่าตามคู่มือ" แต่ปัญหาจริงมักเกิดหลังจากนั้น —
บอทเงียบโดยไม่มีข้อความ error, คีย์หมดอายุตอนตีสาม, โควตาข้อความเต็มกลางเดือน
เว็บนี้ตั้งใจเล่าส่วนนั้น: อะไรพัง ทำไมพัง และแก้ยังไง ให้คนที่ทำแบบเดียวกันไม่ต้องเสียเวลาซ้ำ</p>
<h2>หลักการเขียนของเรา</h2>
<ul>
<li>เขียนจากสิ่งที่ลองทำเองแล้ว ถ้าเป็นข้อมูลที่อาจเปลี่ยน (ราคา โควตา นโยบายแพลตฟอร์ม) จะบอกไว้ให้ตรวจกับแหล่งทางการอีกครั้ง</li>
<li>แก้บทความเมื่อข้อมูลเปลี่ยน และใส่วันที่อัปเดตไว้ที่หัวบทความ</li>
<li>ไม่รับเขียนรีวิวแบบจ่ายเงินแล้วชม ถ้ามีลิงก์แนะนำสินค้าที่เราได้ค่าคอมมิชชัน จะบอกไว้ชัดเจนในบทความนั้น</li>
</ul>
<p>ตอนนี้มีบทความ {n} เรื่อง และเพิ่มขึ้นทุกสัปดาห์ — <a href="/blog">ดูบทความทั้งหมด</a></p>
<h2>บริการ</h2>
<p>ถ้าอยากให้ทำระบบให้ ดูรายละเอียดได้ที่ <a href="/botkit">หน้าบริการ</a> หรือ <a href="/contact">ติดต่อเรา</a></p>
</div></article></main>"""
    return _page(title=f"เกี่ยวกับเรา | {SITE_NAME}",
                 desc="BotKit เว็บบทความภาษาไทยเรื่อง AI และระบบอัตโนมัติจากงานจริง ดำเนินการโดยบอทคิท (BOTKIT) เชียงใหม่",
                 path="/about", body=body, active="about")


def contact_page() -> str:
    body = f"""<main class="wrap narrow"><article><h1>ติดต่อเรา</h1>
<div class="prose">
<p>มีคำถามเรื่องบทความ แจ้งข้อมูลผิด เสนอหัวข้อที่อยากให้เขียน หรือติดต่องาน ติดต่อได้ตามช่องทางนี้</p>
<table>
<tr><th>อีเมล</th><td><a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a> (ตอบภายใน 1–2 วันทำการ)</td></tr>
<tr><th>Facebook Page</th><td><a href="https://www.facebook.com/profile.php?id=61594739807940" target="_blank" rel="noopener">Anuman</a></td></tr>
<tr><th>Facebook ส่วนตัว</th><td><a href="https://www.facebook.com/jakkar.jakkar.39545" target="_blank" rel="noopener">Jark Krit</a></td></tr>
<tr><th>จ้างงาน</th><td><a href="/botkit#order">ฟอร์มสั่งทำระบบ</a> — กรอกไม่ถึง 1 นาที</td></tr>
</table>
<h2>ผู้ดำเนินการเว็บไซต์</h2>
<p>บอทคิท (BOTKIT) · ทะเบียนพาณิชย์เลขที่ 1509900302285 · จังหวัดเชียงใหม่ ประเทศไทย</p>
<p>เรื่องข้อมูลส่วนบุคคล ดู <a href="/privacy">นโยบายความเป็นส่วนตัว</a> · การใช้งานเว็บไซต์ ดู <a href="/terms">ข้อกำหนดการใช้งาน</a></p>
</div></article></main>"""
    return _page(title=f"ติดต่อเรา | {SITE_NAME}",
                 desc="ช่องทางติดต่อ BotKit — อีเมล Facebook และฟอร์มจ้างงาน",
                 path="/contact", body=body, active="contact")


def feed_xml() -> str:
    base = _ctx["base_url"]
    items = "".join(
        f"<item><title>{_html.escape(p['title'])}</title><link>{base}/blog/{p['slug']}</link>"
        f"<guid>{base}/blog/{p['slug']}</guid><pubDate>{p['date']}</pubDate>"
        f"<description>{_html.escape(p['desc'])}</description></item>"
        for p in load_posts()[:20]
    )
    return ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
            f"<title>{SITE_NAME}</title><link>{base}/blog</link><description>{SITE_TAGLINE}</description>"
            f"<language>th</language>{items}</channel></rss>")


def ads_txt() -> str | None:
    if not ADSENSE_CLIENT:
        return None
    pub = ADSENSE_CLIENT.replace("ca-", "", 1)
    return f"google.com, {pub}, DIRECT, f08c47fec0942fa0\n"


# ---------------------------------------------------------------- wiring
def init(app, *, base_url: str, head_extra=None, track=None, hub_is_home: bool = True) -> None:
    """ผูก route เข้ากับ Flask app — เรียกครั้งเดียวจาก api_server.py
    hub_is_home = หน้าแรกเป็นหน้ารวมบทความด้วยหรือเปล่า (ใช้ตั้ง canonical ของ /blog)"""
    _ctx["base_url"] = base_url.rstrip("/")
    _ctx["hub_is_home"] = hub_is_home
    if head_extra:
        _ctx["head_extra"] = head_extra
    if track:
        _ctx["track"] = track
    html_hdr = {"Content-Type": "text/html; charset=utf-8"}

    def _t():
        try:
            _ctx["track"]()
        except Exception as e:      # สถิติพังต้องไม่ทำหน้าเว็บพัง
            print(f"[blog] track fail: {e}", flush=True)

    @app.route("/blog")
    @app.route("/blog/")
    def blog_hub():
        _t()
        return hub_page(), 200, html_hdr

    @app.route("/blog/feed.xml")
    def blog_feed():
        return feed_xml(), 200, {"Content-Type": "application/rss+xml; charset=utf-8"}

    @app.route("/blog/<slug>")
    def blog_post(slug):
        _t()
        return post_page(slug), 200, html_hdr

    @app.route("/about")
    def about():
        _t()
        return about_page(), 200, html_hdr

    @app.route("/contact")
    def contact():
        _t()
        return contact_page(), 200, html_hdr

    @app.route("/ads.txt")
    def ads():
        txt = ads_txt()
        if txt is None:
            abort(404)
        return txt, 200, {"Content-Type": "text/plain; charset=utf-8"}
