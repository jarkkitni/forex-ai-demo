"""
RSS Hunter v2 — ดักงานจากนอก FastWork ผ่าน RSS (9 ต.ค. 2026)

แหล่งงาน:
  1. ค่าเริ่มต้น (งานต่างประเทศ จ่าย USD) — Reddit r/forhire, r/n8n, r/shopify, r/automation
     + หมวด Jobs ของฟอรัม n8n  ทั้งหมดเป็น RSS สาธารณะ ไม่ใช่การ scrape ไม่เสี่ยงโดนแบน
  2. RSS_FEEDS (env, คั่น comma) — เพิ่ม feed เอง เช่น Google Alerts ภาษาไทย
     ตั้ง RSS_DEFAULT_FEEDS=0 ถ้าไม่อยากได้ชุดค่าเริ่มต้น

ต่างจาก v1 (แก้บั๊กชุดเดียวกับที่ fastwork_hunter แก้ไปแล้ว ก.ค.-ส.ค. 2026):
  - จับคำด้วย fastwork_hunter._kw_hit (v1 ใช้ `in` ดิบ → "ไลน์" ไปโดน "ออนไลน์", "ai" โดน "chain")
  - mark seen เฉพาะงานที่ "จบเรื่อง" แล้ว (v1 mark ก่อนวิเคราะห์ → AI ล่ม = งานหายถาวร)
  - แกะ JSON ด้วย _extract_json (v1 พังเมื่อโมเดลมีข้อความนำหน้า)
  - จำงานที่เห็นแล้วใน Supabase hunter_seen_jobs (v1 จำแค่ในแรม → Render หลับ/ตื่นทีไร แจ้งซ้ำ)
  - ตัดโพสต์เก่ากว่า MAX_AGE_HOURS ทิ้ง (feed ใหม่จะไม่ระเบิดแจ้งงานเก่าทั้งหน้า)
  - ร่างข้อเสนอภาษาอังกฤษให้งานต่างประเทศ ภาษาไทยให้งานไทย

v3 (15 ต.ค. 2026):
  - เอาเฉพาะโพสต์ที่มีอีเมลให้สมัคร (RSS_REQUIRE_EMAIL=0 เพื่อปิด) — Claude ส่งอีเมลแทนได้, Reddit DM ไม่ได้
  - ตัดงานที่จำกัดประเทศนอกเอเชีย/ต้องเข้าออฟฟิศ 2 ด่าน: regex ก่อนเรียก AI + AI ตอบ location_ok
    (RSS_REGION_FILTER=0 เพื่อปิด) · งานที่พูดถึง Asia/SEA/ไทย/GMT+7 ได้ป้าย 📍 และดันเกรด B → A
  - ร่างข้อเสนอเป็นเนื้ออีเมล + หัวเรื่อง และห้าม AI แต่งประสบการณ์ที่ไม่มีจริง
"""
import os
import re
import html
import uuid
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import fastwork_hunter as fh

DEFAULT_FEEDS = [
    # รวม 4 subreddit เป็น request เดียว — ทดสอบจริง 9 ต.ค. 2026: ยิงแยก 4 ครั้งติดกัน
    # Reddit ตอบ 429 Too Many Requests ตั้งแต่ตัวที่ 2 (แหล่งที่มาของแต่ละโพสต์อ่านจาก <category>)
    "https://www.reddit.com/r/forhire+n8n+shopify+automation/new/.rss?limit=50",
    "https://community.n8n.io/c/jobs/13.rss",
]

_custom = [u.strip() for u in os.environ.get("RSS_FEEDS", "").split(",") if u.strip()]
_use_default = os.environ.get("RSS_DEFAULT_FEEDS", "1").strip().lower() not in ("0", "false", "no", "off")
FEEDS = list(dict.fromkeys(_custom + (DEFAULT_FEEDS if _use_default else [])))

MAX_AGE_HOURS = int(os.environ.get("RSS_MAX_AGE_HOURS", "48"))
UA = "sirimeta-job-hunter/2.0 (+https://forex-ai-demo.onrender.com/portfolio)"

# ====== คำค้นงานต่างประเทศ (ใช้คู่กับชุดไทยของ fastwork_hunter) ======
# ⚠️ โพสต์ภาษาอังกฤษใช้ชุดนี้ "อย่างเดียว" ไม่ปนชุดไทย — ทดสอบจริง 9 ต.ค. 2026 กับ r/forhire:
#    คำทั่วไปในชุดไทย ("app", "website", "excel", "ai", "workflow") ดึงงานตัดต่อวิดีโอ/นักเขียน/
#    แอดมินก่อสร้างเข้ามา 6 จาก 6 งาน ไม่ตรงสายเลยสักงาน · "script" ก็ไปโดน "video script"
EN_GRADE_A = [
    "n8n", "make.com", "zapier", "automation", "automate", "automated",
    "chatbot", "ai agent", "ai agents", "ai automation", "scraper", "scraping", "web scraping",
    "shopify app", "shopify automation", "line bot", "telegram bot", "discord bot",
    "python script", "api integration", "google sheets", "airtable",
    "openai api", "claude api", "llm", "langchain",
]
EN_GRADE_B = [
    "python", "api", "shopify", "webhook", "supabase", "crm", "hubspot", "gohighlevel",
]
EN_EXCLUDE = [
    "nsfw", "mature content", "onlyfans", "adult content", "18+",
    "video editor", "video editing", "graphic designer", "voice actor", "copywriter",
]

# สัญญาณว่า "มีคนจะจ้าง" (ไม่ใช่บทความ/คนเสนอตัว)
HIRING_SIGNALS = [
    # ไทย
    "หาคนทำ", "หาคนรับ", "รับสมัคร", "ต้องการจ้าง", "จ้างทำ", "หาโปรแกรมเมอร์",
    "หาฟรีแลนซ์", "หาผู้รับเหมา", "มีใครทำ", "ใครรับทำ", "อยากได้ระบบ",
    # อังกฤษ
    "[hiring]", "hiring", "looking for", "need someone", "need a dev", "need help building",
    "seeking", "will pay", "paid gig", "paid project", "willing to pay",
    # ⚠️ ไม่ใส่ "budget"/"wanted" — r/shopify พูดคำนี้ในกระทู้ถามทั่วไปเยอะ = เผาค่า AI ฟรี
]
# คนเสนอตัว = คู่แข่ง ไม่ใช่ลูกค้า
OFFER_SIGNALS = ["[for hire]", "for hire", "[offer]", "[available]", "available for hire"]
NOISE = [
    "วิธีทำ", "สอนทำ", "คอร์สเรียน", "อบรม", "รีวิว", "โปรโมชั่น",
    "how to", "tutorial", "course", "showcase", "i built", "i made",
]

# ====== ตัวกรอง v3 (15 ต.ค. 2026): เอาเฉพาะงานที่ "สมัครทางอีเมลได้" + ไม่จำกัดประเทศนอกเอเชีย ======
# เหตุผล: Claude ส่งอีเมลสมัครแทนได้ทันทีผ่าน Gmail แต่เปิด Reddit ในเบราว์เซอร์ไม่ได้ (โดนบล็อก)
#   งานที่ต้องตอบใต้โพสต์/DM จึงต้องทำมือทุกครั้ง ส่วนงานที่ลูกค้าอยู่ US/EU only สมัครไปก็เสียเวลาเปล่า
# ปิดได้ด้วย env: RSS_REQUIRE_EMAIL=0 (กลับไปรับงาน DM ด้วย) · RSS_REGION_FILTER=0 (ไม่ตัดตามประเทศ)
REQUIRE_EMAIL = os.environ.get("RSS_REQUIRE_EMAIL", "1").strip().lower() not in ("0", "false", "no", "off")
REGION_FILTER = os.environ.get("RSS_REGION_FILTER", "1").strip().lower() not in ("0", "false", "no", "off")

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
# อีเมลที่ไม่ใช่ช่องทางสมัครงาน (ระบบ/ตัวอย่าง/ของแพลตฟอร์มเอง)
_EMAIL_IGNORE = ("example.com", "example.org", "noreply", "no-reply", "donotreply",
                 "reddit.com", "redditmail", "n8n.io", "sentry.io", "@email.com", "@domain.com")

# จำกัดพื้นที่นอกเอเชีย = ตัดทิ้ง (เขียนเป็น regex เพราะคำสั้นอย่าง "us" ต้องมีขอบเขตคำ)
REGION_BLOCK = [
    r"\b(?:us|u\.s\.|usa|uk|eu|canada|australia|europe|latam|north america)[- ]?(?:only|based only)\b",
    r"\bonly (?:us|u\.s\.|usa|uk|eu|canada|australia|europe|latam|north america)\b",
    r"\b(?:us|uk|eu|europe|canada|australia)[- ]based (?:candidates?|developers?|freelancers?|applicants?)\b",
    r"\bmust (?:be )?(?:based|located|reside|live) in (?:the )?(?:us|u\.s\.|usa|united states|uk|united kingdom|eu|europe|canada|australia|north america|latam)\b",
    r"\b(?:us|u\.s\.) (?:citizens?|residents?|persons?)\b",
    r"\b(?:w-?2|1099)\b", r"\bsecurity clearance\b",
    r"\b(?:on-?site|in[- ]person|in office|hybrid (?:role|position|work))\b",
    r"\bmust (?:work|be available|overlap)[^.]{0,40}\b(?:est|pst|cst|mst|et|pt|cet|gmt|bst)\b(?! *\+ *[5-9])",
]
_REGION_BLOCK_RE = [re.compile(p, re.I) for p in REGION_BLOCK]

# พูดถึงเอเชีย/ไทย/ทำได้ทุกที่ = บวกคะแนน (ดันเกรด B → A)
REGION_BOOST = [
    r"\basia\b", r"\bsoutheast asia\b", r"\bsea\b(?= ?(?:region|based|builders?|time))", r"\bapac\b",
    r"\bthailand\b", r"\bthai\b", r"\bbangkok\b", r"\bsingapore\b", r"\bmalaysia\b",
    r"\bphilippines\b", r"\bvietnam\b", r"\bindonesia\b",
    r"\b(?:gmt|utc) ?\+ ?[5-9]\b", r"\bworldwide\b", r"\banywhere\b", r"\bany time ?zone\b",
    r"ไทย", r"ประเทศไทย",
]
_REGION_BOOST_RE = [re.compile(p, re.I) for p in REGION_BOOST]


def _extract_emails(*texts: str) -> list:
    """ดึงอีเมลที่ใช้สมัครงานได้จากโพสต์ (รองรับแบบเลี่ยงบอท 'name [at] site [dot] com' ด้วย)"""
    joined = " ".join(t or "" for t in texts)
    joined = re.sub(r"\s*[\[\(]\s*at\s*[\]\)]\s*", "@", joined, flags=re.I)
    joined = re.sub(r"\s*[\[\(]\s*dot\s*[\]\)]\s*", ".", joined, flags=re.I)
    found = []
    for m in _EMAIL_RE.findall(joined):
        e = m.strip(".").lower()
        if any(bad in e for bad in _EMAIL_IGNORE):
            continue
        if e not in found:
            found.append(e)
    return found


def _region_blocked(text: str) -> str:
    """คืนข้อความที่เจอ ถ้างานจำกัดพื้นที่นอกเอเชีย / ต้องเข้าออฟฟิศ — ไม่เจอคืน ''"""
    for r in _REGION_BLOCK_RE:
        m = r.search(text)
        if m:
            return m.group(0)
    return ""


def _region_boost(text: str) -> list:
    return list(dict.fromkeys(m.group(0).lower() for r in _REGION_BOOST_RE for m in [r.search(text)] if m))


_log: list = []


def is_configured() -> bool:
    return bool(FEEDS)


def _clean(t: str) -> str:
    t = html.unescape(t or "")
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def _parse_time(s: str):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(s)
    except Exception:
        return None


def _source_name(url: str) -> str:
    m = re.search(r"reddit\.com/r/([^/]+)", url)
    if m:
        return f"r/{m.group(1)}"
    if "community.n8n.io" in url:
        return "n8n forum"
    if "google.com/alerts" in url:
        return "Google Alerts"
    return re.sub(r"^https?://(www\.)?", "", url).split("/")[0]


def _fetch_feed(url: str) -> list:
    r = requests.get(url, timeout=20, headers={"User-Agent": UA})
    r.raise_for_status()
    root = ET.fromstring(r.content)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    src = _source_name(url)
    out = []

    for e in root.findall("a:entry", ns):              # Atom (Reddit, Google Alerts)
        link_el = e.find("a:link", ns)
        raw_link = link_el.get("href") if link_el is not None else ""
        m = re.search(r"[?&]url=([^&]+)", raw_link)    # Google ห่อลิงก์จริงไว้ใน url=
        real = requests.utils.unquote(m.group(1)) if m else raw_link
        cat = e.find("a:category", ns)                 # Reddit แบบรวมหลายห้อง: บอกห้องจริงไว้ที่นี่
        if cat is not None and cat.get("label", "").startswith("r/"):
            src = cat.get("label")
        else:
            src = _source_name(url)
        out.append({
            "id": (e.findtext("a:id", "", ns) or real)[:300],
            "title": _clean(e.findtext("a:title", "", ns)),
            "summary": _clean(e.findtext("a:content", "", ns) or e.findtext("a:summary", "", ns)),
            "link": real,
            "published": _parse_time(e.findtext("a:published", "", ns) or e.findtext("a:updated", "", ns)),
            "source": src,
        })

    if not out:                                        # RSS 2.0 (ฟอรัม n8n / Discourse)
        for it in root.iter("item"):
            link = it.findtext("link", "")
            out.append({
                "id": (it.findtext("guid", "") or link)[:300],
                "title": _clean(it.findtext("title", "")),
                "summary": _clean(it.findtext("description", "")),
                "link": link,
                "published": _parse_time(it.findtext("pubDate", "")),
                "source": src,
            })
    return out


def _seen_id(item: dict) -> str:
    """แปลง id ของ feed เป็น UUID คงที่ — ใช้ตาราง hunter_seen_jobs เดียวกับ FastWork
    (job_id ของ FastWork เป็น UUID อยู่แล้ว จึงเก็บร่วมกันได้ไม่ว่าคอลัมน์จะเป็น text หรือ uuid)"""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, item["id"] or item["link"]))


def _is_thai(text: str) -> bool:
    thai = len(re.findall(r"[฀-๿]", text))
    return thai > 20 or (thai > 0 and thai / max(len(text), 1) > 0.15)


def _classify(item: dict) -> tuple:
    """คืน (grade, matched) — 'A' / 'B' / None"""
    title = item["title"].lower()
    text = f"{title} {item['summary'].lower()}"
    thai = _is_thai(text)

    for bad in fh.EXCLUDE_KEYWORDS + ([] if thai else EN_EXCLUDE):
        if fh._kw_hit(bad, text):
            return (None, [])
    if any(o in title for o in OFFER_SIGNALS):
        return (None, [])
    if any(fh._kw_hit(n, title) for n in NOISE):
        return (None, [])

    # r/forhire มีแท็กชัด — เอาเฉพาะ [Hiring]
    if item["source"] == "r/forhire" and "hiring" not in title:
        return (None, [])
    if not any(s in text for s in HIRING_SIGNALS):
        return (None, [])

    # v3: ต้องมีอีเมลให้สมัคร (เก็บไว้ใน item ให้ข้อความ LINE/ร่างอีเมลใช้ต่อ)
    item["emails"] = _extract_emails(item["title"], item["summary"])
    if REQUIRE_EMAIL and not item["emails"]:
        return (None, [])
    # v3: จำกัดประเทศนอกเอเชีย / ต้องเข้าออฟฟิศ = ตัดทิ้ง
    if REGION_FILTER and not thai and _region_blocked(text):
        return (None, [])
    boost = _region_boost(text)

    list_a = (fh.SKILL_KEYWORDS + EN_GRADE_A) if thai else EN_GRADE_A
    list_b = (fh.GRADE_B_KEYWORDS + EN_GRADE_B) if thai else EN_GRADE_B
    hit_a = [k for k in list_a if fh._kw_hit(k, text)]
    if hit_a:
        return ("A", list(dict.fromkeys(hit_a + [f"📍{b}" for b in boost])))
    hit_b = [k for k in list_b if fh._kw_hit(k, text)]
    if hit_b:
        # งานที่ระบุเอเชีย/ไทยชัดๆ คู่แข่งน้อยกว่า → ดันขึ้นเป็นเกรด A
        return ("A" if boost else "B", list(dict.fromkeys(hit_b + [f"📍{b}" for b in boost])))
    return (None, [])


def _analyze(client, item: dict, matched: list, notify_fn=None, uid: str = "") -> dict:
    thai = _is_thai(f"{item['title']} {item['summary']}")
    if thai:
        lang_rule = "proposal เป็นภาษาไทย สุภาพ ตรงประเด็น ~100 คำ"
        skills = ("LINE Bot, Chatbot, AI Agent, ระบบจองคิว, n8n automation, "
                  "Web Dashboard, Python, Supabase")
    else:
        lang_rule = ("proposal in natural, confident English, ~110 words, no fluff, "
                     "reference their specific problem, end with one short question")
        skills = ("n8n / Make / Zapier automation, AI agents & chatbots (Claude, OpenAI), "
                  "Python scraping & API integrations, Shopify + Google Sheets automation, "
                  "LINE / Telegram bots, Supabase dashboards")

    prompt = f"""You help a freelance automation developer based in Thailand find paid work.

A post from {item['source']}:
Title: {item['title']}
Body: {item['summary'][:1500]}
Link: {item['link']}
Matched keywords: {", ".join(matched)}

Developer skills: {skills}
Portfolio with live demos: https://forex-ai-demo.onrender.com/portfolio
The developer does NOT take trading / forex / crypto / investment work.

Many posts are discussions, tutorials or people offering their own services. Only a person
or company that wants to PAY someone for work counts as a real job.

The developer lives in Thailand (GMT+7) and works remotely only. Set "location_ok" to false
if the post requires a specific country/region outside Asia (e.g. US/EU only, US citizens),
on-site/in-person work, or full working hours in a far-off time zone. Otherwise true.

The developer will apply BY EMAIL (to {", ".join(item.get("emails") or []) or "the address in the post"}),
so the proposal is the body of that email. HONESTY RULE: never invent experience, numbers of
clients/students, years, certificates or results. Only claim the skills listed above and point
to the portfolio. If the post asks for specific info (rate, time zone, examples), answer each point.

Reply with JSON only, no other text:
{{
  "is_real_job": <true/false>,
  "location_ok": <true/false>,
  "fit_score": <0-100 how well it fits the skills>,
  "budget": "<budget if stated, else 'not stated'>",
  "summary_th": "<สรุปงานเป็นภาษาไทย 1-2 ประโยค>",
  "how_to_contact": "<how to apply/contact, from the post>",
  "email_subject": "<short email subject line for the application>",
  "proposal": "<{lang_rule}>"
}}"""
    raw = fh._ai(client, prompt, max_tokens=900, smart=True, notify_fn=notify_fn,
                 uid=uid, slug="rss_hunter")
    return fh._extract_json(raw)


def _msg(item: dict, a: dict, matched: list, grade: str) -> str:
    score = a.get("fit_score", 0)
    icon = "🔥" if score >= 80 else ("⭐" if score >= 60 else "💡")
    usd = "" if _is_thai(item["title"] + item["summary"]) else " 💵"
    return (
        f"{icon} งานจาก {item['source']}{usd} (เกรด {grade} · {score}/100)\n"
        f"━━━━━━━━━━━━\n"
        f"📰 {item['title'][:90]}\n"
        f"📋 {a.get('summary_th', '')}\n"
        f"💰 งบ: {a.get('budget', '-')}\n"
        f"🎯 ตรง: {', '.join(matched[:6])}\n"
        f"📧 สมัครทางอีเมล: {', '.join(item.get('emails') or []) or '-'}\n"
        f"📞 {a.get('how_to_contact', 'ดูในลิงก์')}\n"
        f"━━━━━━━━━━━━\n"
        f"✉️ หัวเรื่อง: {a.get('email_subject', '')}\n"
        f"✍️ ร่างอีเมล (copy ไปใช้ได้เลย หรือสั่ง Claude ส่งให้):\n\n{a.get('proposal', '')}\n"
        f"━━━━━━━━━━━━\n"
        f"🔗 {item['link']}"
    )


def _msg_offline(item: dict, matched: list, grade: str) -> str:
    """🐦 นกน้อยทำลัง — AI ล่มทุกเจ้าก็ยังแจ้งได้"""
    return (
        f"📬 งานจาก {item['source']} ตรง keyword (เกรด {grade})\n"
        f"━━━━━━━━━━━━\n"
        f"📰 {item['title'][:90]}\n"
        f"📝 {item['summary'][:220]}...\n"
        f"🎯 ตรง: {', '.join(matched[:6])}\n"
        f"📧 สมัครทางอีเมล: {', '.join(item.get('emails') or []) or '-'}\n"
        f"━━━━━━━━━━━━\n"
        f"⚠️ รอบนี้ AI ล่มทุกเจ้า — ยังไม่มีบทวิเคราะห์/ร่างข้อเสนอ\n"
        f"🔗 {item['link']}"
    )


def run(anthropic_client, push_line_fn, line_user_id: str,
        min_score: int = 60, max_alerts: int = 2) -> dict:
    """สแกนทุก feed → กรอง → AI วิเคราะห์ → LINE  (กติกา mark seen เหมือน fastwork_hunter)"""
    global _log
    if not FEEDS:
        return {"success": False, "error": "ไม่มี feed ให้สแกน"}

    fh._load_seen()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)

    items, errors = [], []
    for f in FEEDS:
        try:
            items += _fetch_feed(f)
        except Exception as e:
            errors.append(f"{_source_name(f)}: {str(e)[:80]}")

    hits, closed = [], []
    for it in items:
        sid = _seen_id(it)
        if sid in fh._seen_job_ids:
            continue
        pub = it["published"]
        if pub is not None and pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        if pub is not None and pub < cutoff:
            continue                       # เก่าเกิน ไม่สน และไม่ต้องจำ (หลุด feed ไปเองเร็วๆ นี้)
        grade, matched = _classify(it)
        if grade:
            hits.append((it, sid, grade, matched))
        else:
            closed.append(sid)             # ไม่ตรง = จบเรื่องทันที

    for sid in closed:
        fh._seen_job_ids.add(sid)
    fh._save_seen(closed)

    hits.sort(key=lambda x: 0 if x[2] == "A" else 1)
    sent, failed, results, settled = 0, 0, [], []
    considered = 0

    for it, sid, grade, matched in hits[:max_alerts * 3]:
        if sent >= max_alerts:
            break
        considered += 1
        entry = {
            "time": datetime.now(timezone.utc).isoformat(),
            "source": it["source"], "grade": grade,
            "title": it["title"][:80], "url": it["link"],
        }
        try:
            a = _analyze(anthropic_client, it, matched, push_line_fn, line_user_id)
        except Exception as e:
            print(f"[RSS] analyze ล้ม → ส่งแบบ offline: {e}", flush=True)
            ok = (push_line_fn(line_user_id, _msg_offline(it, matched, grade),
                               buttons={"url": it["link"]})
                  if grade == "A" else None)
            entry.update({"score": None, "summary": "(offline — AI ล่ม)", "alerted": bool(ok)})
            if ok:
                sent += 1
                settled.append(sid)
            elif ok is None:
                settled.append(sid)        # เกรด B ตอน AI ล่ม ไม่ส่ง = ปล่อยผ่าน
            else:
                failed += 1
            results.append(entry)
            continue

        score = a.get("fit_score", 0)
        entry.update({"score": score, "summary": a.get("summary_th", ""),
                      "is_real_job": a.get("is_real_job", False)})

        entry["emails"] = it.get("emails") or []
        entry["location_ok"] = a.get("location_ok", True)
        # location_ok: ด่านที่ 2 ต่อจาก regex — AI จับเคสที่เขียนอ้อมๆ เช่น "need someone in Austin"
        if (a.get("is_real_job") and score >= min_score
                and (not REGION_FILTER or a.get("location_ok", True) is not False)):
            ok = push_line_fn(line_user_id, _msg(it, a, matched, grade),
                              buttons={"copy": a.get("proposal", ""), "url": it["link"]})
        else:
            ok = None                      # ตัดสินแล้วว่าไม่แจ้ง

        entry["alerted"] = bool(ok)
        if ok:
            sent += 1
            settled.append(sid)
        elif ok is None:
            settled.append(sid)
        else:
            failed += 1                    # LINE ส่งไม่ออก → ไม่ mark รอบหน้าลองใหม่
        results.append(entry)

    for sid in settled:
        fh._seen_job_ids.add(sid)
    fh._save_seen(settled)
    _log = (_log + results)[-20:]

    return {
        "success": True, "feeds": len(FEEDS), "items": len(items),
        "new_matching": len(hits), "analyzed": len(results),
        "alerts_sent": sent, "alert_failed": failed,
        "deferred": len(hits) - considered,
        "errors": errors, "results": results,
    }


def get_log() -> list:
    return _log
