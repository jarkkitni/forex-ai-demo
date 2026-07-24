"""
FastWork Job Hunter — AI ดักจับงานที่ตรงสกิล
poll FastWork jobboard → กรอง keyword → Claude วิเคราะห์ + ร่างข้อเสนอ → LINE push
"""
import os, re, json, requests
import seo_tracker  # ใช้ SUPABASE_URL / SUPABASE_KEY ร่วมกัน (กันดักซ้ำข้าม restart)
from datetime import datetime, timezone

JOBBOARD_URL = "https://jobboard-api.fastwork.co/api/jobs"

# ====== สกิลที่เรารับงาน ======
# เกรด A — ตรงเป้า (แจ้งเตือนเต็มรูปแบบ + ร่างข้อเสนอ)
SKILL_KEYWORDS = [
    # bot & AI
    "bot", "บอท", "chatbot", "แชทบอท", "ai", "เอไอ", "ปัญญาประดิษฐ์",
    "line", "ไลน์", "oa",
    # automation
    "automation", "automate", "ออโต้", "อัตโนมัติ", "n8n", "workflow", "zapier", "make.com",
    # dev — เฉพาะที่บ่งชี้จองคิว/booking ตรงสาย เก็บไว้เป็น A
    "ระบบจอง", "จองคิว", "booking",
    # จากรีเสิร์ช Garuda 18 ก.ค. — แพทเทิร์นงานที่เคยพลาด (เช่น AI Agent ฿5,000 ตอนเปิดมี 0 ผู้เสนอ)
    "ai agent", "เอเจนท์",
    "scraping", "ดึงข้อมูล", "rich menu", "ริชเมนู",
    "ตรวจสลิป", "เช็คสลิป", "จองที่พัก", "จองห้อง", "จองโต๊ะ",
    # 24 ก.ค. 2026 — ย้าย "web app/เว็บแอป/api/dashboard/ระบบหลังบ้าน/python/supabase/ระบบ pos/
    # ขายหน้าร้าน/ระบบสมาชิก" ลงไปเกรด B แล้ว (ดูด้านล่าง) เพราะเป็นคำทั่วไปเกินไป งานเว็บ/แอปทั่วไป
    # เกือบทุกงานมีคำพวกนี้ปนอยู่แล้ว ทำให้หลุดเป็นเกรด A ทั้งที่ไม่ใช่สาย Chatbot/LINE OA/automation
    # ตามกลยุทธ์ "นกน้อยล่าเหยื่อ" (23 ก.ค. 2026) — เจอจริง 24 ก.ค.: งาน "เว็บกระจายงานทีม" ฿3,000
    # กับ "Full-Stack Developer ชลบุรี" ฿24,000 หลุดมาเป็นเกรด A ทั้งที่ไม่ตรงสายเราเลย
    # 22 ก.ค. 2026 — ถอด keyword สาย trading (forex/เทรด/trading/signal/สัญญาณ/
    # indicator/mt4/mt5) ออกจากลิสต์นี้แล้ว เพราะเราเลิกรับงานสายนี้ถาวร (ความเสี่ยง ก.ล.ต.)
    # เก็บไว้จะได้แต่การแจ้งเตือนงานที่รับไม่ได้ = เสียเวลาเปล่า + ล่อให้เผลอรับ
]

# เกรด B — เฉียดสกิล (แจ้งเตือนแบบสรุปสั้น ให้ตัดสินใจเอง)
GRADE_B_KEYWORDS = [
    "google sheet", "google sheets", "กูเกิลชีท", "excel", "เอ็กเซล",
    # 24 ก.ค. 2026 — ย้ายมาจาก SKILL_KEYWORDS (เกรด A) เพราะทั่วไปเกินไป ไม่บ่งชี้สายบอท/LINE/
    # automation โดยเฉพาะ (ดู comment ที่ SKILL_KEYWORDS)
    "web app", "เว็บแอป", "api", "ระบบหลังบ้าน", "python", "supabase",
    "ระบบ pos", "ขายหน้าร้าน", "ระบบสมาชิก",
    # 22 ก.ค. 2026 — ถอด "ระบบ" เดี่ยวๆ ออก (วัดจริงจากกระดาน 50 งาน: จุดชนวน 6 งาน
    # เกี่ยวข้องจริง 0 งาน — ไปโดน "ระบบไฟฟ้า EV charger", "ระบบ pumps cooling",
    # "งาน HR อย่างเป็นระบบ", "ข้อมูลลูกค้าในระบบ") ใช้รูปเจาะจงแทน
    "ทำระบบ", "พัฒนาระบบ", "สร้างระบบ", "ระบบจัดการ", "ระบบอัตโนมัติ",
    "เว็บไซต์", "website", "แอพ", "แอป", "app",
    "dashboard", "รายงาน", "สรุปข้อมูล", "ดึงข้อมูล", "scraping", "scrape",
    "เก็บข้อมูล", "ฐานข้อมูล", "database", "แจ้งเตือน", "notification",
    "โปรแกรม", "script", "สคริปต์", "เชื่อมต่อ", "integrate",
]

# keyword ที่ไม่เอา (งานไม่ตรงสาย)
EXCLUDE_KEYWORDS = [
    "ยิงแอด", "ads", "โฆษณา facebook", "กราฟฟิก", "graphic", "โลโก้", "logo",
    "ตัดต่อวิดีโอ", "ตัดต่อวีดีโอ", "แปลภาษา", "แปลเอกสาร", "เขียนบทความ", "seo",
    # 22 ก.ค. 2026 — สายการเงิน/ลงทุน: เลิกรับถาวร (ความเสี่ยง ก.ล.ต. ไม่มีใบอนุญาต)
    # ใส่ไว้ใน EXCLUDE ไม่ใช่แค่ถอดออกจาก SKILL เพราะงานพวกนี้มักมีคำว่า "บอท"/"api"
    # ปนมาด้วย ถ้าไม่กันตรงนี้จะยังหลุดผ่านมาทาง keyword อื่น
    "forex", "เทรด", "trading", "mt4", "mt5", "indicator", "คริปโต", "crypto",
    "หุ้น", "ลงทุน", "binary option", "สัญญาณเทรด", "copy trade", "ea ",
]

_seen_job_ids: set = set()
_hunter_log: list = []   # เก็บผลล่าสุด 20 รายการ
_seen_loaded = False     # โหลด seen จาก DB แล้วหรือยัง (ต่อ process)


def _sb_headers() -> dict:
    return {
        "apikey": seo_tracker.SUPABASE_KEY,
        "Authorization": f"Bearer {seo_tracker.SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


def _load_seen() -> None:
    """โหลด job_id ที่เคยเห็นจาก Supabase (ครั้งเดียวต่อ process) — กันดักซ้ำหลัง Render restart"""
    global _seen_job_ids, _seen_loaded
    if _seen_loaded:
        return
    _seen_loaded = True
    if not (seo_tracker.SUPABASE_URL and seo_tracker.SUPABASE_KEY):
        return
    try:
        r = requests.get(
            f"{seo_tracker.SUPABASE_URL}/rest/v1/hunter_seen_jobs?select=job_id",
            headers=_sb_headers(), timeout=15)
        if r.ok:
            _seen_job_ids |= {str(row["job_id"]) for row in r.json()}
            print(f"[Hunter] โหลด seen จาก DB: {len(_seen_job_ids)} งาน", flush=True)
    except Exception as e:
        print(f"[Hunter] load seen fail: {e}", flush=True)


def _save_seen(ids: list) -> None:
    """บันทึก job_id ใหม่ลง Supabase (ตัวซ้ำข้ามให้ ไม่ error)"""
    if not ids or not (seo_tracker.SUPABASE_URL and seo_tracker.SUPABASE_KEY):
        return
    try:
        payload = [{"job_id": str(i)} for i in ids]
        requests.post(
            f"{seo_tracker.SUPABASE_URL}/rest/v1/hunter_seen_jobs",
            headers={**_sb_headers(), "Prefer": "resolution=ignore-duplicates"},
            data=json.dumps(payload), timeout=15)
    except Exception as e:
        print(f"[Hunter] save seen fail: {e}", flush=True)


def _fetch_jobs() -> list:
    r = requests.get(JOBBOARD_URL, timeout=15)
    r.raise_for_status()
    data = r.json()
    return data.get("data", [])


# กับดัก substring ของคำไทย — ภาษาไทยไม่เว้นวรรค ใช้ \b ไม่ได้ ต้องระบุคำที่ห้ามนำหน้าเอง
# (เจอจริง 22 ก.ค. 2026: "ไลน์" ไปแมตช์ "ออนไลน์" = 9 จาก 16 งานที่ผ่านด่านเป็นงานแอดมิน/
#  เซลส์/HR ที่แค่เขียนว่า "สื่อออนไลน์" ไม่เกี่ยวกับ LINE เลย)
_THAI_PREFIX_TRAPS = {
    "ไลน์": ("ออน",),
}

_KW_RE_CACHE: dict = {}


def _kw_hit(kw: str, text: str) -> bool:
    """keyword โผล่ใน text แบบ "เป็นคำจริง" ไหม — ไม่ใช่เศษคำที่บังเอิญตัวอักษรตรง

    ทำไมต้องมี (22 ก.ค. 2026): เดิมใช้ `kw in text` ดิบๆ ทำให้
      'ai'   ไปโดน  n[ai]ve thai / ch[ai]n integration
      'ไลน์'  ไปโดน  ออน[ไลน์]        ← ตัวการหลัก 9 งาน
      'ads'  ไปโดน  l[ead]s
    ผลคือด่านแรกปล่อยขยะเข้ามาเต็ม แล้วไปเผาโควตา AI triage ทิ้งทุกรอบ
    ซ้ำร้ายงานขยะยังไปกินโควตา max_alerts*2 เบียดงานจริงออกด้วย

    วิธี:
      - keyword ที่มีอักษรละติน → บังคับขอบคำ (ห้ามมีตัวอักษร/ตัวเลขละตินติดหัวท้าย)
      - keyword ไทยล้วน → ใช้ substring ตามเดิม (ไทยไม่มีขอบคำ) แต่กรองกับดักที่รู้จัก
    """
    if not re.search(r"[a-z0-9]", kw):          # ไทยล้วน
        if kw not in text:
            return False
        for bad_prefix in _THAI_PREFIX_TRAPS.get(kw, ()):
            # ตัดเฉพาะตำแหน่งที่ติดกับดัก ถ้ายังเหลือที่อื่นถือว่าเจอจริง
            if all(text[max(0, m.start() - len(bad_prefix)):m.start()] == bad_prefix
                   for m in re.finditer(re.escape(kw), text)):
                return False
        return True

    rx = _KW_RE_CACHE.get(kw)
    if rx is None:
        rx = _KW_RE_CACHE[kw] = re.compile(
            r"(?<![a-z0-9])" + re.escape(kw.strip()) + r"(?![a-z0-9])")
    return bool(rx.search(text))


def _match_skills(job: dict) -> tuple:
    """คืน (grade, matched_keywords) — grade: 'A' / 'B' / None"""
    text = (job.get("description") or "").lower()
    tag = ((job.get("tag") or {}).get("name") or "").lower()
    full = f"{text} {tag}"

    for bad in EXCLUDE_KEYWORDS:
        if _kw_hit(bad, full):
            return (None, [])

    matched_a = [kw for kw in SKILL_KEYWORDS if _kw_hit(kw, full)]
    if matched_a:
        return ("A", matched_a)

    matched_b = [kw for kw in GRADE_B_KEYWORDS if _kw_hit(kw, full)]
    if matched_b:
        return ("B", matched_b)

    return (None, [])


def _extract_json(raw: str) -> dict:
    """แกะ JSON จากคำตอบโมเดลแบบทนสกปรก

    ทำไมต้องมี: ตั้งแต่ 22 ก.ค. 2026 Hunter ใช้โมเดลฟรี (Gemini/Groq) แทน Claude
    ซึ่งชอบแถมข้อความนำ ("นี่คือ JSON ครับ:") หรือห่อ markdown fence มาด้วย
    โค้ดเดิมเช็คแค่ `raw.startswith("```")` → พังทันทีถ้ามีข้อความนำหน้า fence

    วิธี: หา { ตัวแรก แล้วนับวงเล็บจนครบคู่ (ข้ามวงเล็บที่อยู่ในสตริง/ถูก escape)
    """
    s = raw.strip()
    start = s.find("{")
    if start < 0:
        raise ValueError(f"ไม่พบ JSON ในคำตอบ: {s[:120]}")

    depth, in_str, esc = 0, False, False
    for i, ch in enumerate(s[start:], start):
        if esc:
            esc = False
            continue
        if ch == "\\" and in_str:
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(s[start:i + 1])
    raise ValueError(f"JSON ไม่ครบวงเล็บ: {s[:120]}")


def _triage(client, job: dict, matched: list, notify_fn=None, uid: str = "") -> bool:
    """
    ด่านคัดขยะก่อนวิเคราะห์เต็ม — ตอบแค่ YES/NO

    ทำไมคุ้ม: keyword match หยาบมาก ของที่ผ่านมาส่วนใหญ่ไม่ใช่งานเรา
    คัดทิ้งก่อน แล้วค่อยจ่ายค่าวิเคราะห์เต็มเฉพาะงานที่มีลุ้นจริง
    ถ้าด่านนี้พัง → ปล่อยผ่าน (fail-open) ดีกว่าพลาดงานเพราะด่านคัดล่ม

    tier="free" (22 ก.ค. 2026) = Gemini → Groq ไม่แตะ Claude เลย
    เครดิต Anthropic หมดตั้งแต่ 21 ก.ค. เรียกไปก็พังทุกครั้ง เสียเวลารอ timeout ฟรีๆ
    """
    import ai_guard
    desc = (job.get("description") or "")[:900]
    prompt = f"""งานฟรีแลนซ์นี้ตรงกับสกิลนี้ไหม: LINE Bot, Chatbot, AI Agent,
ระบบจองคิว, n8n automation, Web Dashboard, Python, Supabase

งาน: {desc}

ตอบคำเดียว: YES ถ้าพอทำได้ / NO ถ้าคนละสายเลย (เช่น กราฟิก ยิงแอด เขียนบทความ แปลภาษา
หรืองานสายเทรด/ลงทุน/คริปโต ซึ่งเราไม่รับแล้ว)"""
    try:
        ans = ai_guard.call(client, prompt, max_tokens=5, smart=False, tier="free",
                            notify_fn=notify_fn, line_user_id=uid, slug="job_hunter")
        return "YES" in ans.upper()
    except Exception as e:
        print(f"[Hunter] triage ล้มเหลว ปล่อยผ่าน: {e}", flush=True)
        return True


def _analyze_job(client, job: dict, matched: list, notify_fn=None, uid: str = "") -> dict:
    """วิเคราะห์งาน + ร่างข้อเสนอ — เรียกเฉพาะงานที่ผ่านด่านคัด"""
    import ai_guard
    desc = (job.get("description") or "")[:2000]
    budget = job.get("budget") or "ไม่ระบุ"

    prompt = f"""คุณคือผู้ช่วยฟรีแลนซ์ของนักพัฒนา LINE Bot & AI Agent ชาวไทย

งานใหม่จาก FastWork:
---
{desc}
---
งบประมาณ: {budget}
keyword ที่ตรงสกิล: {", ".join(matched)}

สกิลของเรา: LINE Bot, Chatbot, AI Agent, บอทตอบแชท Facebook/Instagram,
ระบบจองคิว, n8n automation, Web Dashboard, Python, Supabase
จุดขาย: มี Demo ให้ลองจริงก่อนซื้อ (forex-ai-demo.onrender.com/portfolio)

ตอบเป็น JSON เท่านั้น ห้ามมีข้อความอื่นนอก JSON:
{{
  "fit_score": <0-100 ความตรงกับสกิลเรา>,
  "worth_it": <true/false คุ้มไหมเมื่อเทียบงบกับเนื้องาน>,
  "summary": "<สรุปงาน 1-2 ประโยค>",
  "risks": "<ความเสี่ยง/ข้อควรระวัง สั้นๆ>",
  "proposal": "<ร่างข้อเสนองานภาษาไทย สุภาพ ตรงประเด็น ~120 คำ ลงท้ายชวนคุย>"
}}"""

    raw = ai_guard.call(client, prompt, max_tokens=1000, smart=True, tier="free",
                        notify_fn=notify_fn, line_user_id=uid, slug="job_hunter")
    return _extract_json(raw)


def _job_url(job_id: str) -> str:
    return f"https://jobboard.fastwork.co/jobs/{job_id}"


def _build_line_message(job: dict, analysis: dict, matched: list) -> str:
    """ข้อความเต็ม — งานเกรด A"""
    job_id = job.get("id", "")
    score = analysis.get("fit_score", 0)
    stars = "🔥" if score >= 80 else ("⭐" if score >= 60 else "💡")
    budget = job.get("budget") or "ไม่ระบุ"

    return (
        f"{stars} งานใหม่ตรงสกิล! ({score}/100)\n"
        f"━━━━━━━━━━━━\n"
        f"📋 {analysis.get('summary','')}\n"
        f"💰 งบ: {budget}\n"
        f"🎯 ตรง: {', '.join(matched[:5])}\n"
        f"⚠️ {analysis.get('risks','-')}\n"
        f"━━━━━━━━━━━━\n"
        f"✍️ ร่างข้อเสนอ (copy ไปใช้ได้เลย):\n\n"
        f"{analysis.get('proposal','')}\n"
        f"━━━━━━━━━━━━\n"
        f"🔗 กดยื่นงานเลย:\n{_job_url(job_id)}"
    )


def _build_line_message_short(job: dict, analysis: dict, matched: list) -> str:
    """ข้อความสั้น — งานเกรด B (เฉียดสกิล ให้ตัดสินใจเอง)"""
    job_id = job.get("id", "")
    score = analysis.get("fit_score", 0)
    budget = job.get("budget") or "ไม่ระบุ"

    return (
        f"💼 งานเฉียดสกิล (เกรด B) — {score}/100\n"
        f"📋 {analysis.get('summary','')}\n"
        f"💰 งบ: {budget} | 🎯 {', '.join(matched[:3])}\n"
        f"สนใจไหม? ดูงาน:\n{_job_url(job_id)}"
    )


def _score_offline(job: dict, matched: list, grade: str) -> int:
    """🐦 นกน้อยทำลัง — ให้คะแนนงานโดยไม่เรียก AI เลยแม้แต่ตัวเดียว

    ใช้ตอน AI ทุกเจ้าล่มพร้อมกัน (Gemini + Groq) — หลักการเดียวกับ
    meta_bot._offline_fallback_answer(): ยอมได้คำตอบหยาบกว่า ดีกว่าเงียบสนิท

    สูตร: เกรด A ตั้งต้น 60 / เกรด B ตั้งต้น 40
          + จำนวน keyword ที่ตรง (ตัวละ 5 สูงสุด 20)
          + งบสูง = คุ้มกว่า (>= 10k +15, >= 5k +10, >= 2k +5)
    """
    score = 60 if grade == "A" else 40
    score += min(len(matched) * 5, 20)

    budget_txt = str(job.get("budget") or "")
    digits = "".join(c for c in budget_txt if c.isdigit())
    if digits:
        try:
            amount = int(digits[:7])
            if amount >= 10000:
                score += 15
            elif amount >= 5000:
                score += 10
            elif amount >= 2000:
                score += 5
        except ValueError:
            pass
    return min(score, 95)


def _build_line_message_offline(job: dict, matched: list, grade: str, score: int) -> str:
    """🐦 นกน้อยทำลัง — ข้อความแจ้งเตือนที่ไม่ต้องพึ่ง AI

    ตั้งใจไม่ใส่ "สรุปงาน" เพราะสรุปเองไม่ได้ถ้าไม่มี AI — ใส่ description ดิบแทน
    แล้วบอกตรงๆ ว่ารอบนี้ AI ช่วยไม่ได้ จะได้ไม่เข้าใจผิดว่าระบบวิเคราะห์มาแล้ว
    """
    job_id = job.get("id", "")
    budget = job.get("budget") or "ไม่ระบุ"
    title = (job.get("title") or "").strip()[:80]
    desc = (job.get("description") or "").strip().replace("\n", " ")[:200]

    return (
        f"📬 งานใหม่ตรง keyword (เกรด {grade} · ~{score}/100)\n"
        f"━━━━━━━━━━━━\n"
        f"📋 {title}\n"
        f"📝 {desc}...\n"
        f"💰 งบ: {budget}\n"
        f"🎯 ตรง: {', '.join(matched[:5])}\n"
        f"━━━━━━━━━━━━\n"
        f"⚠️ รอบนี้ AI ล่มทุกเจ้า — ยังไม่มีบทวิเคราะห์/ร่างข้อเสนอ\n"
        f"แต่ส่งมาก่อนเพราะงานดีรอไม่ได้ อ่านเองแล้วตัดสินใจได้เลย\n"
        f"🔗 {_job_url(job_id)}"
    )


def run_hunter(anthropic_client, push_line_fn, line_user_id: str,
               min_score: int = 55, max_alerts: int = 3) -> dict:
    """
    รอบเดียวจบ: ดึงงาน → กรอง → วิเคราะห์ → push LINE
    คืน dict สรุปผล
    """
    global _seen_job_ids, _hunter_log

    _load_seen()   # โหลดที่เคยเห็นจาก DB ก่อน (รอด Render restart)
    prime = not _seen_job_ids   # DB ว่าง = รอบแรกสุด → seed งานปัจจุบันเฉยๆ ไม่แจ้งเตือน (กันเด้งซ้ำงานเก่า)
    jobs = _fetch_jobs()
    new_matched = []
    newly_seen = []

    # 🔴 แก้บั๊ก 22 ก.ค. 2026 — "งานหายเงียบเพราะโดน mark ว่าเห็นแล้วทั้งที่ยังไม่ได้ดู"
    # เดิม: mark seen ทุกงานตรงนี้เลย แต่ด้านล่างพิจารณาแค่ max_alerts*2 (=6) งานแรก
    #       → รอบที่เจองานตรง 16 งาน มี 10 งานถูกทิ้งถาวร รอบหน้าก็ข้ามเพราะ dedup
    #       (เคสจริง: รอบ 22 ก.ค. 19:00 new_matching=16 แต่ดูจริงแค่ 6)
    # ใหม่: งานที่ "ไม่ตรงสกิล / ปิดรับแล้ว" mark seen ได้เลย (ไม่มีวันกลับมาสนใจ)
    #       ส่วนงานที่ตรงสกิล **ยังไม่ mark** จนกว่าจะพิจารณาจริงเสร็จ (ดูท้ายฟังก์ชัน)
    for job in jobs:
        jid = job.get("id")
        if not jid or str(jid) in _seen_job_ids:
            continue

        if job.get("status") == "open":
            grade, matched = _match_skills(job)
            if grade and not prime:
                new_matched.append((job, grade, matched))
                continue   # ยังไม่ mark seen — รอพิจารณาก่อน

        _seen_job_ids.add(str(jid))
        newly_seen.append(jid)

    _save_seen(newly_seen)   # บันทึก id ที่ปิดจบแล้วลง DB — รอบหน้าจะไม่ดักซ้ำ

    if prime:
        print(f"[Hunter] prime รอบแรก: seed {len(newly_seen)} งานปัจจุบัน (ไม่แจ้งเตือน)", flush=True)
        return {"checked": len(jobs), "new_matching": 0, "primed": len(newly_seen),
                "analyzed": 0, "alerts_sent": 0, "results": []}

    # เกรด A ก่อนเสมอ
    new_matched.sort(key=lambda x: 0 if x[1] == "A" else 1)

    # จำกัดจำนวนที่วิเคราะห์ต่อรอบ (คุมค่า API)
    alerts_sent = 0
    results = []

    triaged_out = 0
    offline_alerts = 0
    considered_ids = []      # งานที่ "ดูจริง" แล้ว — เฉพาะพวกนี้ถึงจะ mark seen ได้
    for job, grade, matched in new_matched[:max_alerts * 2]:
        if alerts_sent >= max_alerts:
            break
        considered_ids.append(job.get("id"))

        # ด่าน 1: คัดขยะทิ้งก่อน (ถูก) — ผ่านแล้วค่อยจ่ายค่าวิเคราะห์เต็ม
        if not _triage(anthropic_client, job, matched, push_line_fn, line_user_id):
            triaged_out += 1
            print(f"[Hunter] คัดออก: {(job.get('title') or '')[:50]}", flush=True)
            continue

        entry = {
            "time": datetime.now(timezone.utc).isoformat(),
            "job_id": job.get("id"),
            "grade": grade,
            "title": (job.get("title") or "").strip()[:80],
            "budget": job.get("budget") or "-",
            "url": _job_url(job.get("id", "")),
        }

        # ด่าน 2: วิเคราะห์เต็ม + ร่างข้อเสนอ
        try:
            analysis = _analyze_job(anthropic_client, job, matched, push_line_fn, line_user_id)
        except Exception as e:
            # 🐦 นกน้อยทำลัง — AI ล่มทุกเจ้า ห้ามทิ้งงานเงียบ
            # (บั๊กเดิม 21 ก.ค. 2026: ตรงนี้เป็น `continue` เฉยๆ งานที่ผ่านด่านคัดมาแล้ว
            #  เลยหลุดหายไปโดยไม่มีใครรู้ — analyzed:0 alerts_sent:0 ทั้งที่มีงานตรงสกิลจริง)
            print(f"[Hunter] analyze ล้ม → ส่งแบบ offline แทน: {e}", flush=True)
            score = _score_offline(job, matched, grade)
            ok = push_line_fn(line_user_id,
                              _build_line_message_offline(job, matched, grade, score))
            entry.update({"score": score, "summary": "(offline — AI ล่ม)",
                          "ai": False, "alerted": ok})
            if ok:
                alerts_sent += 1
                offline_alerts += 1
            results.append(entry)
            _hunter_log = (_hunter_log + [entry])[-20:]
            continue

        score = analysis.get("fit_score", 0)
        entry.update({"score": score, "summary": analysis.get("summary", ""), "ai": True})

        # เกรด A คะแนน ≥70 → ข้อความเต็ม + ข้อเสนอ
        # เกรด A/B คะแนน 55-69 → ข้อความสั้น
        if score >= 70 and grade == "A":
            ok = push_line_fn(line_user_id, _build_line_message(job, analysis, matched))
            entry["alerted"] = ok
            alerts_sent += 1 if ok else 0
        elif score >= min_score:
            ok = push_line_fn(line_user_id, _build_line_message_short(job, analysis, matched))
            entry["alerted"] = ok
            alerts_sent += 1 if ok else 0
        else:
            entry["alerted"] = False

        results.append(entry)
        _hunter_log = (_hunter_log + [entry])[-20:]

    # mark seen เฉพาะงานที่พิจารณาจริงในรอบนี้ — ที่เหลือปล่อยไว้ให้รอบหน้าเก็บต่อ
    for jid in considered_ids:
        _seen_job_ids.add(str(jid))
    _save_seen(considered_ids)

    deferred = len(new_matched) - len(considered_ids)
    if deferred:
        # ห้ามเงียบ — ถ้าไม่ log ไว้ ตัวเลข alerts_sent จะดูเหมือน "ดูครบแล้ว" ทั้งที่ยังเหลือ
        print(f"[Hunter] ยกยอดไปรอบหน้า {deferred} งาน "
              f"(ตรงสกิล {len(new_matched)} · ดูจริงรอบนี้ {len(considered_ids)})", flush=True)

    return {
        "checked": len(jobs),
        "new_matching": len(new_matched),
        "triaged_out": triaged_out,      # คัดออกกี่งาน = ประหยัดค่าวิเคราะห์ไปเท่านั้น
        "analyzed": len(results),
        "alerts_sent": alerts_sent,
        "offline_alerts": offline_alerts,  # กี่งานที่แจ้งได้ทั้งที่ AI ล่ม (นกน้อยทำลัง)
        "deferred": deferred,              # ยกยอดไปรอบหน้ากี่งาน (ต้องเป็น 0 ในภาวะปกติ)
        "results": results,
    }


def get_hunter_log() -> list:
    return _hunter_log
