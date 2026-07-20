"""
RSS Hunter — ดักงานจากทั้งอินเทอร์เน็ตผ่าน Google Alerts RSS
ต่างจาก fastwork_hunter ที่ดักแค่ FastWork jobboard

วิธีตั้ง Google Alerts:
1. เข้า https://www.google.com/alerts
2. พิมพ์คำค้น เช่น: "หาคนทำ line bot"
3. กด Show options → Deliver to: RSS feed
4. กด Create Alert → copy ลิงก์ RSS
5. ใส่ใน env RSS_FEEDS (คั่นด้วย comma)

env:
  RSS_FEEDS = https://www.google.com/alerts/feeds/xxx/yyy,https://...
"""
import os
import re
import html
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

FEEDS = [u.strip() for u in os.environ.get("RSS_FEEDS", "").split(",") if u.strip()]

# ใช้ keyword ชุดเดียวกับ fastwork_hunter (import ตรงเพื่อไม่ให้หลุดกัน)
try:
    from fastwork_hunter import SKILL_KEYWORDS, GRADE_B_KEYWORDS, EXCLUDE_KEYWORDS
except Exception:
    SKILL_KEYWORDS, GRADE_B_KEYWORDS, EXCLUDE_KEYWORDS = [], [], []

# สัญญาณว่าเป็น "คนกำลังหาคนทำ" ไม่ใช่บทความ/โฆษณา
HIRING_SIGNALS = [
    "หาคนทำ", "หาคนรับ", "รับสมัคร", "ต้องการจ้าง", "จ้างทำ", "หาโปรแกรมเมอร์",
    "หาฟรีแลนซ์", "หาผู้รับเหมา", "มีใครทำ", "ใครรับทำ", "อยากได้ระบบ",
    "looking for", "hiring", "need someone", "wanted", "seeking",
]

# ตัดบทความ/ข่าว/โฆษณาออก
NOISE = [
    "วิธีทำ", "สอนทำ", "how to", "tutorial", "คอร์สเรียน", "อบรม",
    "รีวิว", "review", "ราคาถูกที่สุด", "โปรโมชั่น",
]

_seen: set = set()
_log: list = []


def is_configured() -> bool:
    return bool(FEEDS)


def _clean(t: str) -> str:
    t = re.sub(r"<[^>]+>", " ", t or "")
    t = html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def _fetch_feed(url: str) -> list:
    r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    root = ET.fromstring(r.content)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []

    # Google Alerts = Atom format
    for e in root.findall("a:entry", ns):
        link_el = e.find("a:link", ns)
        raw_link = link_el.get("href") if link_el is not None else ""
        # Google ห่อลิงก์จริงไว้ใน url= param
        m = re.search(r"[?&]url=([^&]+)", raw_link)
        real = requests.utils.unquote(m.group(1)) if m else raw_link
        out.append({
            "id": (e.findtext("a:id", "", ns) or real)[:200],
            "title": _clean(e.findtext("a:title", "", ns)),
            "summary": _clean(e.findtext("a:content", "", ns) or e.findtext("a:summary", "", ns)),
            "link": real,
            "published": e.findtext("a:published", "", ns),
        })

    # เผื่อ feed แบบ RSS 2.0
    if not out:
        for it in root.iter("item"):
            link = it.findtext("link", "")
            out.append({
                "id": it.findtext("guid", "") or link,
                "title": _clean(it.findtext("title", "")),
                "summary": _clean(it.findtext("description", "")),
                "link": link,
                "published": it.findtext("pubDate", ""),
            })
    return out


def _classify(item: dict) -> tuple:
    """คืน (grade, matched) — 'A' / 'B' / None"""
    text = f"{item['title']} {item['summary']}".lower()

    for bad in EXCLUDE_KEYWORDS:
        if bad in text:
            return (None, [])
    for n in NOISE:
        if n in text:
            return (None, [])

    # ต้องมีสัญญาณว่ากำลังหาคนทำ (กันบทความ/ข่าวหลุดเข้ามา)
    if not any(s in text for s in HIRING_SIGNALS):
        return (None, [])

    hit_a = [k for k in SKILL_KEYWORDS if k in text]
    if hit_a:
        return ("A", hit_a)
    hit_b = [k for k in GRADE_B_KEYWORDS if k in text]
    if hit_b:
        return ("B", hit_b)
    return (None, [])


def _analyze(client, item: dict, matched: list) -> dict:
    import json as _json
    prompt = f"""คุณคือผู้ช่วยฟรีแลนซ์ของนักพัฒนา LINE Bot & AI Agent ชาวไทย

เจอโพสต์นี้จากอินเทอร์เน็ต (ผ่าน Google Alerts):
หัวข้อ: {item['title']}
เนื้อหา: {item['summary'][:1200]}
ลิงก์: {item['link']}
keyword ที่ตรง: {", ".join(matched)}

สกิลเรา: LINE Bot, Chatbot, AI Agent (Claude), ระบบจองคิว, ระบบคลินิก/บันทึกข้อมูล,
n8n automation, Forex AI Signal Bot, Web Dashboard, Python, Supabase
จุดขาย: มี demo ให้ลองจริงก่อนซื้อ

ระวัง: โพสต์จากเน็ตอาจเป็นบทความ/โฆษณา/ข่าว ไม่ใช่คนหาจ้างจริง — ถ้าไม่ใช่คนหาจ้าง ให้ fit_score ต่ำ

ตอบ JSON เท่านั้น:
{{
  "is_real_job": <true/false เป็นคนหาจ้างจริงไหม>,
  "fit_score": <0-100>,
  "summary": "<สรุป 1-2 ประโยค>",
  "how_to_contact": "<ติดต่อยังไง จากข้อมูลที่มี>",
  "proposal": "<ร่างข้อความเสนอตัว ~100 คำ สุภาพ ตรงประเด็น>"
}}"""
    msg = client.messages.create(
        model="claude-sonnet-4-5", max_tokens=900,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    return _json.loads(raw)


def _msg(item: dict, a: dict, matched: list) -> str:
    score = a.get("fit_score", 0)
    icon = "🔥" if score >= 80 else "⭐"
    return (
        f"{icon} เจองานจากเน็ต! ({score}/100)\n"
        f"━━━━━━━━━━━━\n"
        f"📰 {item['title'][:70]}\n"
        f"📋 {a.get('summary','')}\n"
        f"🎯 ตรง: {', '.join(matched[:4])}\n"
        f"📞 ติดต่อ: {a.get('how_to_contact','ดูในลิงก์')}\n"
        f"━━━━━━━━━━━━\n"
        f"✍️ ร่างข้อความ:\n\n{a.get('proposal','')}\n"
        f"━━━━━━━━━━━━\n"
        f"🔗 {item['link']}"
    )


def run(anthropic_client, push_line_fn, line_user_id: str,
        min_score: int = 60, max_alerts: int = 2) -> dict:
    """สแกน RSS ทุก feed → กรอง → AI วิเคราะห์ → LINE"""
    global _seen, _log
    if not FEEDS:
        return {"success": False, "error": "ยังไม่ได้ตั้ง RSS_FEEDS"}

    items, errors = [], []
    for f in FEEDS:
        try:
            items += _fetch_feed(f)
        except Exception as e:
            errors.append(str(e)[:80])

    new_hits = []
    for it in items:
        if not it["id"] or it["id"] in _seen:
            continue
        _seen.add(it["id"])
        grade, matched = _classify(it)
        if grade:
            new_hits.append((it, grade, matched))

    new_hits.sort(key=lambda x: 0 if x[1] == "A" else 1)
    sent, results = 0, []

    for it, grade, matched in new_hits[:max_alerts * 2]:
        if sent >= max_alerts:
            break
        try:
            a = _analyze(anthropic_client, it, matched)
        except Exception as e:
            print(f"[RSS] analyze fail: {e}", flush=True)
            continue

        score = a.get("fit_score", 0)
        entry = {
            "time": datetime.now(timezone.utc).isoformat(),
            "source": "rss",
            "grade": grade,
            "title": it["title"][:80],
            "url": it["link"],
            "score": score,
            "summary": a.get("summary", ""),
            "is_real_job": a.get("is_real_job", False),
        }
        if a.get("is_real_job") and score >= min_score:
            ok = push_line_fn(line_user_id, _msg(it, a, matched))
            entry["alerted"] = ok
            sent += 1 if ok else 0
        else:
            entry["alerted"] = False

        results.append(entry)
        _log = (_log + [entry])[-20:]

    return {
        "success": True, "feeds": len(FEEDS), "items": len(items),
        "new_matching": len(new_hits), "analyzed": len(results),
        "alerts_sent": sent, "errors": errors, "results": results,
    }


def get_log() -> list:
    return _log
