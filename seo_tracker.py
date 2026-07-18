"""
SEO Tracker — จับว่าคนเข้าเว็บเรามาจากไหน

หัวใจ: ถ้ามีคนมาจาก google.com = SEO ทำงานแล้ว (ไม่ต้องรอ Search Console บอก)
เก็บลง Supabase table `seo_hits` (RLS ปิด anon — เข้าได้เฉพาะ service_role)
"""
import os
import re
import requests
from datetime import datetime, timezone, timedelta

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

# วันที่ส่ง sitemap ให้ Google — ใช้นับว่ารอมากี่วันแล้ว
SITEMAP_SUBMITTED = "2026-07-18"

# หน้าที่ทำ SEO ไว้ (ต้องตรงกับ SEO_PAGES ใน api_server.py)
SEO_PATHS = [
    "/line-bot", "/bot-jongkiw", "/chatbot-clinic",
    "/bot-ran-serm-suay", "/bot-ran-ahan", "/n8n-automation",
]

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


def log(req) -> None:
    """บันทึก 1 hit — เรียกจาก _track_visit()"""
    if not is_configured():
        return

    path = req.path or "/"
    ref = req.headers.get("Referer", "") or ""
    ua = req.headers.get("User-Agent", "") or ""
    is_bot = bool(BOT_UA.search(ua))
    source = classify(ref)

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
            "is_bot": is_bot,
        },
        timeout=4,
    )


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
    since_7d = (now - timedelta(days=7)).isoformat()

    rows = _get(f"select=ts,path,source,is_bot&ts=gte.{since_7d}&order=ts.desc&limit=2000")
    humans = [r for r in rows if not r["is_bot"]]
    bots = [r for r in rows if r["is_bot"]]

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
    }
