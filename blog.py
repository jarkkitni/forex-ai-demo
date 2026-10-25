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


CSS = """
:root{--bg:#0a0f1c;--bg2:#0e1526;--card:#121b30;--line:#1f2b46;--fg:#e8eef9;--muted:#9fb0cf;
--soft:#c9d5ea;--ac:#22d3ee;--ac2:#00e47a;--ink:#04151a}
*{box-sizing:border-box;margin:0;padding:0}
html{-webkit-text-size-adjust:100%}
body{background:var(--bg);color:var(--fg);font-family:'Segoe UI',system-ui,-apple-system,Tahoma,'Noto Sans Thai',sans-serif;
line-height:1.8;font-size:16px}
a{color:var(--ac)}
.top{border-bottom:1px solid var(--line);background:rgba(10,15,28,.92);position:sticky;top:0;z-index:5;backdrop-filter:blur(8px)}
.top .in{max-width:1080px;margin:0 auto;padding:12px 16px;display:flex;align-items:center;gap:18px;flex-wrap:wrap}
.brand{font-weight:800;font-size:18px;color:#fff;text-decoration:none;letter-spacing:-.2px}
.brand span{color:var(--ac2)}
.nav{display:flex;gap:4px;flex-wrap:wrap;margin-left:auto}
.nav a{color:var(--soft);text-decoration:none;font-size:14.5px;padding:6px 10px;border-radius:8px}
.nav a:hover,.nav a.on{background:var(--card);color:#fff}
.wrap{max-width:1080px;margin:0 auto;padding:36px 16px 64px}
.narrow{max-width:740px}
.hero h1{font-size:clamp(26px,5vw,40px);line-height:1.3;font-weight:800;letter-spacing:-.4px;margin-bottom:12px}
.hero h1 em{font-style:normal;color:var(--ac2)}
.hero p{color:var(--muted);font-size:17px;max-width:640px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:22px 0 8px}
.chip{border:1px solid var(--line);background:var(--bg2);color:var(--soft);font-size:13.5px;padding:5px 12px;
border-radius:999px;text-decoration:none}
.chip:hover,.chip.on{border-color:var(--ac);color:#fff}
h2.sec{font-size:20px;margin:40px 0 16px;color:#fff}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}
.post{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px;text-decoration:none;
color:var(--fg);display:flex;flex-direction:column;gap:8px;transition:border-color .15s,transform .15s}
.post:hover{border-color:var(--ac);transform:translateY(-2px)}
.post .cat{font-size:12.5px;color:var(--ac);font-weight:600}
.post h3{font-size:17.5px;line-height:1.5;color:#fff}
.post p{font-size:14.5px;color:var(--muted);line-height:1.65}
.post .meta{font-size:12.5px;color:#71819f;margin-top:auto}
.tools{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px}
.tool{background:var(--bg2);border:1px solid var(--line);border-radius:14px;padding:18px;text-decoration:none;color:var(--fg)}
.tool:hover{border-color:var(--ac2)}
.tool b{display:block;color:#fff;margin-bottom:4px}
.tool span{font-size:14px;color:var(--muted)}
.svc{margin-top:40px;background:linear-gradient(135deg,#0f2233,#111a30);border:1px solid var(--line);border-radius:16px;padding:22px}
.svc b{color:#fff}
.svc p{color:var(--muted);font-size:15px;margin:6px 0 12px}
.btn{display:inline-block;background:var(--ac2);color:#03130b;font-weight:700;text-decoration:none;
padding:10px 18px;border-radius:10px;font-size:15px}
/* article */
.crumb{font-size:13.5px;color:#71819f;margin-bottom:18px}
.crumb a{color:#9fb0cf;text-decoration:none}
article h1{font-size:clamp(25px,4.6vw,35px);line-height:1.38;font-weight:800;letter-spacing:-.3px;margin-bottom:12px}
.byline{color:#8394b4;font-size:14px;margin-bottom:26px;padding-bottom:18px;border-bottom:1px solid var(--line)}
.prose{font-size:17px;color:var(--soft)}
.prose>*+*{margin-top:16px}
.prose h2{font-size:22px;color:#fff;margin-top:38px;line-height:1.45}
.prose h3{font-size:18.5px;color:#fff;margin-top:28px}
.prose strong{color:#fff}
.prose ul,.prose ol{padding-left:24px}
.prose li+li{margin-top:6px}
.prose code{background:#0b1222;border:1px solid var(--line);border-radius:6px;padding:1px 6px;font-size:14.5px;
font-family:Consolas,'SFMono-Regular',monospace;color:#d6e4ff;word-break:break-word}
.prose pre{background:#0b1222;border:1px solid var(--line);border-radius:12px;padding:16px;overflow-x:auto;
font-size:14px;line-height:1.6}
.prose pre code{border:0;padding:0;background:none}
.prose blockquote,.prose .note{border-left:3px solid var(--ac);background:var(--bg2);padding:12px 16px;
border-radius:0 10px 10px 0;color:var(--soft)}
.prose .warn{border-left-color:#fbbf24}
.prose table{width:100%;border-collapse:collapse;font-size:15px;display:block;overflow-x:auto}
.prose th,.prose td{border-bottom:1px solid var(--line);padding:10px;text-align:left;vertical-align:top}
.prose th{color:#fff;font-size:14px}
.toc{background:var(--bg2);border:1px solid var(--line);border-radius:12px;padding:14px 18px;font-size:15px}
.toc b{color:#fff}
.related{margin-top:48px;padding-top:24px;border-top:1px solid var(--line)}
.about-box{margin-top:36px;background:var(--bg2);border:1px solid var(--line);border-radius:14px;padding:18px;font-size:15px;color:var(--muted)}
.about-box b{color:#fff}
footer.site{border-top:1px solid var(--line);color:#71819f;font-size:13.5px;line-height:1.9}
footer.site .in{max-width:1080px;margin:0 auto;padding:26px 16px 40px}
footer.site a{color:#9fb0cf;text-decoration:none}
footer.site a:hover{color:#fff}
.prose td code{white-space:nowrap;word-break:normal}
@media (max-width:560px){.top{position:static}.nav{margin-left:0;width:100%}.prose{font-size:16.5px}}
"""


def _nav(active: str = "") -> str:
    items = [("/", "หน้าแรก", "home"), ("/blog", "บทความ", "blog"),
             ("/blog#tools", "เครื่องมือฟรี", "tools"), ("/botkit", "บริการ", "svc"),
             ("/about", "เกี่ยวกับเรา", "about"), ("/contact", "ติดต่อ", "contact")]
    on = ' class="on"'
    links = "".join(f'<a href="{h}"{on if k == active else ""}>{t}</a>' for h, t, k in items)
    return (f'<header class="top"><div class="in"><a class="brand" href="/">Bot<span>Kit</span></a>'
            f'<nav class="nav">{links}</nav></div></header>')


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
          robots: str = "index, follow") -> str:
    base = _ctx["base_url"]
    url = f"{base}{path}"
    t, d = _html.escape(title), _html.escape(desc)
    return f"""<!DOCTYPE html><html lang="th"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
{_ctx['head_extra']()}{_adsense_tag() if ads else ''}<title>{t}</title>
<meta name="description" content="{d}">
<link rel="canonical" href="{url}">
<meta name="robots" content="{robots}">
<meta name="theme-color" content="#0a0f1c">
<meta property="og:type" content="{og_type}"><meta property="og:locale" content="th_TH">
<meta property="og:site_name" content="{SITE_NAME}"><meta property="og:title" content="{t}">
<meta property="og:description" content="{d}"><meta property="og:url" content="{url}">
<meta property="og:image" content="{base}/static/og/home.png">
<meta name="twitter:card" content="summary_large_image">
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
<a class="tool" href="/chatmaker/"><b>💬 สร้างภาพแชทตัวอย่าง</b><span>พิมพ์บทสนทนาเองทั้งสองฝั่ง ได้ภาพหน้าจอแชทไว้ทำสไลด์/โฆษณา</span></a>
<a class="tool" href="https://smarthook-viral-video-ai.onrender.com/" rel="noopener"><b>🎬 สร้างคลิปเล่าเรื่องด้วย AI</b><span>พิมพ์พล็อตสั้นๆ ได้ภาพ เสียงพากย์ไทย และวิดีโอแนวตั้ง 9:16</span></a>
<a class="tool" href="https://siladon-shop-demo.onrender.com/" rel="noopener"><b>🏺 ร้านค้าออนไลน์ + QR พร้อมเพย์</b><span>ลองระบบตะกร้าและหน้าชำระเงินที่เปลี่ยนสถานะเอง (โหมดสาธิต)</span></a>
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
<div class="prose">{body_html}</div></article>
<div class="about-box"><b>เกี่ยวกับผู้เขียน</b> — {AUTHOR} นักพัฒนา LINE Bot และระบบ AI อัตโนมัติ
อยู่เชียงใหม่ ทำระบบตอบแชทและจองคิวให้ร้านค้าจริง บทความในเว็บนี้มาจากงานที่ลงมือทำเอง
<a href="/about">อ่านเพิ่ม</a></div>
<section class="related"><h2 class="sec" style="margin-top:0">อ่านต่อ</h2><div class="grid">{rel_html}</div></section>
</main>"""
    robots = "noindex, nofollow" if p.get("draft") else "index, follow"
    return _page(title=f"{p['title']} | {SITE_NAME}", desc=p["desc"], path=f"/blog/{slug}",
                 body=body, active="blog", og_type="article", extra_head=extra, robots=robots)


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
<tr><th>Facebook Page</th><td><a href="https://www.facebook.com/profile.php?id=100086195540576" rel="noopener">AI Claude Academy</a></td></tr>
<tr><th>Facebook ส่วนตัว</th><td><a href="https://www.facebook.com/jakkar.jakkar.39545" rel="noopener">Jark Krit</a></td></tr>
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
