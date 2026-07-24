"""
SEO Tracker — จับว่าคนเข้าเว็บเรามาจากไหน

หัวใจ: ถ้ามีคนมาจาก google.com = SEO ทำงานแล้ว (ไม่ต้องรอ Search Console บอก)
เก็บลง Supabase table `seo_hits` (RLS ปิด anon — เข้าได้เฉพาะ service_role)
"""
import os
import re
import requests
from urllib.parse import quote, urlparse, parse_qs, unquote_plus
from datetime import datetime, timezone, timedelta

# ชื่อ cookie เก็บ "แหล่งแรกที่รู้จักเรา" (first-touch attribution)
# ต้องใช้ cookie เพราะตอนลูกค้ากดสั่งซื้อ referrer จะเป็นเว็บเราเอง = แหล่งจริงหายไปแล้ว
SRC_COOKIE = "nx_src"
COOKIE_DAYS = 30

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

# วันที่ส่ง sitemap ให้ Google — ใช้นับว่ารอมากี่วันแล้ว
SITEMAP_SUBMITTED = "2026-07-18"

# หน้าที่ทำ SEO ไว้ (ต้องตรงกับ SEO_PAGES ใน api_server.py)
SEO_PATHS = [
    "/line-bot", "/bot-jongkiw", "/chatbot-clinic",
    "/bot-ran-serm-suay", "/bot-ran-ahan", "/n8n-automation",
]

# path ปุ่ม "ทักไลน์จริง" (Lullabell) ในหน้า /portfolio — /go/lullabell-line ใน api_server.py
LULLABELL_LINE_CLICK_PATH = "/go/lullabell-line"

# บอท/crawler — ไม่นับเป็นคนจริง แต่บันทึกไว้ดูว่า Googlebot มาแล้วยัง
BOT_UA = re.compile(
    r"googlebot|bingbot|slurp|duckduckbot|baiduspider|yandex|facebookexternalhit|"
    r"twitterbot|linkedinbot|line-poker|applebot|ahrefsbot|semrushbot|crawler|spider|bot/",
    re.I,
)

_SOURCES = [
    ("google",   re.compile(r"google\.", re.I)),
    ("bing",     re.compile(r"bing\.com|msn\.com", re.I)),
    ("facebook", re.compile(r"facebook\.com|fb\.me|fbclid", re.I)),
    ("line",     re.compile(r"line\.me|liff\.line", re.I)),
    ("x",        re.compile(r"t\.co|twitter\.com|x\.com", re.I)),
    ("fastwork", re.compile(r"fastwork\.co", re.I)),
]


def _hdrs(extra: dict = None) -> dict:
    h = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def is_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)


def classify(referrer: str) -> str:
    """referrer → ชื่อแหล่งที่มา"""
    if not referrer:
        return "direct"
    for name, rx in _SOURCES:
        if rx.search(referrer):
            return name
    return "other"


def extract_query(referrer: str, req=None) -> str:
    """
    ดึงคำที่ลูกค้าค้นมา

    หมายเหตุตามจริง: Google ส่วนใหญ่ตัด ?q= ออกแล้ว (referrer policy = origin-only)
    เราจะได้แค่ 'https://www.google.com/' เฉยๆ — ดังนั้นคาดหวังว่าจะได้บ้างไม่ได้บ้าง
    Bing/Yahoo และ Google บางเคส (เช่นจากมือถือบางรุ่น) ยังส่งมาให้อยู่
    """
    # 1) จาก referrer โดยตรง
    if referrer:
        try:
            qs = parse_qs(urlparse(referrer).query)
            for k in ("q", "query", "p", "text", "wd"):
                if qs.get(k):
                    return unquote_plus(qs[k][0])[:120]
        except Exception:
            pass
    # 2) จาก URL ของเราเอง — เผื่อวันหลังใส่ ?kw= ในลิงก์ที่โปรโมทเอง
    if req is not None:
        for k in ("kw", "q", "utm_term"):
            v = req.args.get(k)
            if v:
                return v[:120]
    return ""


# กันยิง LINE ซ้ำ: จำไว้ใน memory ว่าเคยแจ้งแล้ว (รีเซ็ตตอน server restart แต่ยังมี DB กันอีกชั้น)
_organic_notified = False


def _maybe_celebrate(source: str, path: str, query: str, push_fn, user_id: str) -> None:
    """คนแรกที่มาจาก Google = หมุดชัยชนะของ SEO — ยิง LINE บอกทันที"""
    global _organic_notified
    if _organic_notified or source not in ("google", "bing") or not push_fn or not user_id:
        return
    try:
        # เช็ค DB ว่าเคยมี organic มาก่อนหน้านี้ไหม (ถ้ามี = ไม่ใช่คนแรก ไม่ต้องแจ้ง)
        prev = _get("select=id&source=in.(google,bing)&is_bot=eq.false&order=id.asc&limit=2")
        if len(prev) > 1:          # >1 เพราะ row ของคนนี้ insert ไปแล้ว
            _organic_notified = True
            return
        _organic_notified = True
        push_fn(user_id, (
            "🎉🎉 SEO ติดแล้ว!\n"
            "━━━━━━━━━━━━\n"
            "มีคนค้นเจอเราใน Google เป็นคนแรก!\n\n"
            f"🔍 มาจาก: {source.title()}\n"
            f"📄 เข้าหน้า: {path}\n"
            + (f"💬 ค้นด้วยคำว่า: \"{query}\"\n" if query else
               "💬 คำค้น: Google ไม่ส่งมาให้ (ปกติ)\n")
            + "━━━━━━━━━━━━\n"
            "จากนี้งานจะเริ่มวิ่งมาหาเราเอง 💪\n"
            "https://forex-ai-demo.onrender.com/monitor"
        ))
    except Exception as e:
        print(f"[SEO] celebrate fail: {e}", flush=True)


def log(req, push_fn=None, line_user_id: str = "") -> None:
    """บันทึก 1 hit — เรียกจาก _track_visit()"""
    if not is_configured():
        return

    path = req.path or "/"
    ref = req.headers.get("Referer", "") or ""
    ua = req.headers.get("User-Agent", "") or ""
    is_bot = bool(BOT_UA.search(ua))
    source = classify(ref)
    query = extract_query(ref, req)

    # ถ้ามาจากเว็บเราเอง = คนเดินภายใน ไม่ใช่ traffic ใหม่ ข้ามไป
    if "forex-ai-demo.onrender.com" in ref:
        return
    # ข้ามหน้าภายในของเรา (monitor/hunter) — ไม่ใช่ traffic จริง
    if path.startswith(("/monitor", "/hunter", "/api")):
        return

    requests.post(
        f"{SUPABASE_URL}/rest/v1/seo_hits",
        headers=_hdrs({"Prefer": "return=minimal"}),
        json={
            "path": path[:200],
            "source": source,
            "referrer": ref[:400] or None,
            "query": query or None,
            "is_bot": is_bot,
        },
        timeout=4,
    )

    if not is_bot:
        _maybe_celebrate(source, path, query, push_fn, line_user_id)


def log_order(source: str, plan: str = "") -> None:
    """ลูกค้ากดสั่งซื้อจริง — บันทึกว่ามาจากแหล่งไหน (ใช้คำนวณ conversion)"""
    if not is_configured():
        return
    try:
        requests.post(
            f"{SUPABASE_URL}/rest/v1/seo_hits",
            headers=_hdrs({"Prefer": "return=minimal"}),
            json={"path": "/order", "source": source or "direct",
                  "query": plan[:120] or None, "is_bot": False, "is_order": True},
            timeout=4,
        )
    except Exception as e:
        print(f"[SEO] log_order fail: {e}", flush=True)


def log_line_click(source: str = "portfolio") -> None:
    """บันทึกคนกดปุ่ม "ทักไลน์จริง" (Lullabell) ในหน้า /portfolio — แยกจาก log() เพราะปุ่มนี้
    อยู่ในเว็บเราเอง referrer ตอนคลิกจะเป็นเว็บเราเองเสมอ ซึ่ง log() จะข้ามทิ้งเป็น "เดินในเว็บ"
    (ดูเงื่อนไข "forex-ai-demo.onrender.com" in ref ด้านบน) — มิเรอร์ log_order() ที่ POST ตรง
    เข้า seo_hits โดยไม่เช็ค referrer เหมือนกัน"""
    if not is_configured():
        return
    try:
        requests.post(
            f"{SUPABASE_URL}/rest/v1/seo_hits",
            headers=_hdrs({"Prefer": "return=minimal"}),
            json={"path": LULLABELL_LINE_CLICK_PATH, "source": source or "portfolio", "is_bot": False},
            timeout=4,
        )
    except Exception as e:
        print(f"[SEO] log_line_click fail: {e}", flush=True)


def _get(params: str) -> list:
    r = requests.get(f"{SUPABASE_URL}/rest/v1/seo_hits?{params}",
                     headers=_hdrs(), timeout=8)
    r.raise_for_status()
    return r.json()


def summary() -> dict:
    """สรุปสถานะ SEO — ใช้โดย /api/seo"""
    if not is_configured():
        return {"ok": False, "error": "ยังไม่ได้ตั้ง Supabase"}

    now = datetime.now(timezone.utc)
    # ต้อง urlencode — timestamp มี '+' ที่ PostgREST จะอ่านเป็น space ถ้าไม่ encode
    since_7d = quote((now - timedelta(days=7)).isoformat(), safe="")

    rows = _get(f"select=ts,path,source,query,is_bot,is_order"
                f"&ts=gte.{since_7d}&order=ts.desc&limit=2000")
    orders = [r for r in rows if r["is_order"]]
    views = [r for r in rows if not r["is_order"]]
    humans = [r for r in views if not r["is_bot"]]
    bots = [r for r in views if r["is_bot"]]

    # นับตามแหล่งที่มา (เฉพาะคนจริง)
    by_source = {}
    for r in humans:
        by_source[r["source"]] = by_source.get(r["source"], 0) + 1

    # นับหน้า SEO ที่โดนเปิด
    by_page = {}
    for r in humans:
        if r["path"] in SEO_PATHS:
            by_page[r["path"]] = by_page.get(r["path"], 0) + 1

    organic = by_source.get("google", 0) + by_source.get("bing", 0)

    # กดปุ่ม "ทักไลน์จริง" (Lullabell) กี่ครั้ง — log_line_click() เขียน path นี้แยกไว้แล้ว
    line_clicks_7d = sum(1 for r in humans if r["path"] == LULLABELL_LINE_CLICK_PATH)

    # คำค้นที่พาคนมา (เท่าที่ search engine ยอมส่งมาให้)
    kw = {}
    for r in humans:
        if r.get("query") and r["source"] in ("google", "bing"):
            kw[r["query"]] = kw.get(r["query"], 0) + 1
    keywords = sorted(kw.items(), key=lambda x: -x[1])[:8]

    # Conversion — คนมาจากแต่ละแหล่ง กี่คนสั่งซื้อจริง
    orders_by_source = {}
    for r in orders:
        orders_by_source[r["source"]] = orders_by_source.get(r["source"], 0) + 1
    organic_orders = orders_by_source.get("google", 0) + orders_by_source.get("bing", 0)
    conv_rate = round(organic_orders / organic * 100, 1) if organic else 0.0

    # Googlebot เคยมาไหม (= Google รู้จักเว็บเราแล้ว)
    crawled = _get("select=ts&is_bot=eq.true&order=ts.desc&limit=1")
    crawled_at = crawled[0]["ts"] if crawled else None

    # คนแรกที่มาจาก Google เมื่อไหร่ (หมุดชัยชนะ)
    first = _get("select=ts&source=eq.google&is_bot=eq.false&order=ts.asc&limit=1")
    first_organic = first[0]["ts"] if first else None

    submitted = datetime.fromisoformat(SITEMAP_SUBMITTED).replace(tzinfo=timezone.utc)
    days = (now - submitted).days

    # สถานะ 4 ขั้น — ให้รู้ว่าตอนนี้อยู่ตรงไหน
    if first_organic:
        stage, label = 4, "มีคนค้นเจอเราแล้ว 🎉"
    elif crawled_at:
        stage, label = 3, "Google เก็บข้อมูลแล้ว รอขึ้นผลค้นหา"
    elif days >= 1:
        stage, label = 2, "ส่ง sitemap แล้ว รอ Google มาเก็บ"
    else:
        stage, label = 1, "เพิ่งตั้งค่าเสร็จ"

    return {
        "ok": True,
        "stage": stage,
        "stage_max": 4,
        "label": label,
        "days_since_sitemap": days,
        "organic_7d": organic,
        "humans_7d": len(humans),
        "bot_hits_7d": len(bots),
        "by_source": by_source,
        "by_page": by_page,
        "seo_pages": SEO_PATHS,
        "last_crawl": crawled_at,
        "first_organic": first_organic,
        "keywords": [{"kw": k, "n": n} for k, n in keywords],
        "orders_7d": len(orders),
        "organic_orders_7d": organic_orders,
        "orders_by_source": orders_by_source,
        "conversion_pct": conv_rate,
        "line_clicks_7d": line_clicks_7d,
    }
