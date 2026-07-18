"""
FastWork Job Hunter — AI ดักจับงานที่ตรงสกิล
poll FastWork jobboard → กรอง keyword → Claude วิเคราะห์ + ร่างข้อเสนอ → LINE push
"""
import os, json, requests
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
    # dev
    "web app", "เว็บแอป", "api", "ระบบจอง", "จองคิว", "booking",
    "dashboard", "ระบบหลังบ้าน", "python", "supabase",
    # trading
    "forex", "เทรด", "trading", "signal", "สัญญาณ", "indicator", "mt4", "mt5",
]

# เกรด B — เฉียดสกิล (แจ้งเตือนแบบสรุปสั้น ให้ตัดสินใจเอง)
GRADE_B_KEYWORDS = [
    "google sheet", "google sheets", "กูเกิลชีท", "excel", "เอ็กเซล",
    "ระบบ", "เว็บไซต์", "website", "แอพ", "แอป", "app",
    "dashboard", "รายงาน", "สรุปข้อมูล", "ดึงข้อมูล", "scraping", "scrape",
    "เก็บข้อมูล", "ฐานข้อมูล", "database", "แจ้งเตือน", "notification",
    "โปรแกรม", "script", "สคริปต์", "เชื่อมต่อ", "integrate",
]

# keyword ที่ไม่เอา (งานไม่ตรงสาย)
EXCLUDE_KEYWORDS = [
    "ยิงแอด", "ads", "โฆษณา facebook", "กราฟฟิก", "graphic", "โลโก้", "logo",
    "ตัดต่อวิดีโอ", "ตัดต่อวีดีโอ", "แปลภาษา", "แปลเอกสาร", "เขียนบทความ", "seo",
]

_seen_job_ids: set = set()
_hunter_log: list = []   # เก็บผลล่าสุด 20 รายการ


def _fetch_jobs() -> list:
    r = requests.get(JOBBOARD_URL, timeout=15)
    r.raise_for_status()
    data = r.json()
    return data.get("data", [])


def _match_skills(job: dict) -> tuple:
    """คืน (grade, matched_keywords) — grade: 'A' / 'B' / None"""
    text = (job.get("description") or "").lower()
    tag = ((job.get("tag") or {}).get("name") or "").lower()
    full = f"{text} {tag}"

    for bad in EXCLUDE_KEYWORDS:
        if bad in full:
            return (None, [])

    matched_a = [kw for kw in SKILL_KEYWORDS if kw in full]
    if matched_a:
        return ("A", matched_a)

    matched_b = [kw for kw in GRADE_B_KEYWORDS if kw in full]
    if matched_b:
        return ("B", matched_b)

    return (None, [])


def _triage(client, job: dict, matched: list, notify_fn=None, uid: str = "") -> bool:
    """
    ด่านคัดด้วย Haiku (ถูกกว่า Sonnet หลายเท่า) — ตอบแค่ YES/NO

    ทำไมคุ้ม: keyword match หยาบมาก ของที่ผ่านมาส่วนใหญ่ไม่ใช่งานเรา
    ให้ Haiku คัดขยะทิ้งก่อน แล้วจ่ายค่า Sonnet เฉพาะงานที่มีลุ้นจริง
    ถ้า Haiku พัง → ปล่อยผ่าน (fail-open) ดีกว่าพลาดงานเพราะด่านคัดล่ม
    """
    import ai_guard
    desc = (job.get("description") or "")[:900]
    prompt = f"""งานฟรีแลนซ์นี้ตรงกับสกิลนี้ไหม: LINE Bot, Chatbot, AI Agent,
ระบบจองคิว, n8n automation, Web Dashboard, Python, Supabase, Forex bot

งาน: {desc}

ตอบคำเดียว: YES ถ้าพอทำได้ / NO ถ้าคนละสายเลย (เช่น กราฟิก ยิงแอด เขียนบทความ แปลภาษา)"""
    try:
        ans = ai_guard.call(client, prompt, max_tokens=5, smart=False,
                            notify_fn=notify_fn, line_user_id=uid)
        return "YES" in ans.upper()
    except Exception as e:
        print(f"[Hunter] triage ล้มเหลว ปล่อยผ่าน: {e}", flush=True)
        return True


def _analyze_job(client, job: dict, matched: list) -> dict:
    """ให้ Claude (Sonnet) วิเคราะห์งาน + ร่างข้อเสนอ — เรียกเฉพาะงานที่ผ่านด่าน Haiku"""
    desc = (job.get("description") or "")[:2000]
    budget = job.get("budget") or "ไม่ระบุ"

    prompt = f"""คุณคือผู้ช่วยฟรีแลนซ์ของนักพัฒนา LINE Bot & AI Agent ชาวไทย

งานใหม่จาก FastWork:
---
{desc}
---
งบประมาณ: {budget}
keyword ที่ตรงสกิล: {", ".join(matched)}

สกิลของเรา: LINE Bot, Chatbot, AI Agent (Claude API), ระบบจองคิว, Forex AI Signal Bot,
n8n automation, Web Dashboard, Python, Supabase
จุดขาย: มี Demo ให้ลองจริงก่อนซื้อ (forex-ai-demo.onrender.com)

ตอบเป็น JSON เท่านั้น:
{{
  "fit_score": <0-100 ความตรงกับสกิลเรา>,
  "worth_it": <true/false คุ้มไหมเมื่อเทียบงบกับเนื้องาน>,
  "summary": "<สรุปงาน 1-2 ประโยค>",
  "risks": "<ความเสี่ยง/ข้อควรระวัง สั้นๆ>",
  "proposal": "<ร่างข้อเสนองานภาษาไทย สุภาพ ตรงประเด็น ~120 คำ ลงท้ายชวนคุย>"
}}"""

    msg = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()
    # ตัด markdown fence ถ้ามี
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    return json.loads(raw)


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


def run_hunter(anthropic_client, push_line_fn, line_user_id: str,
               min_score: int = 55, max_alerts: int = 3) -> dict:
    """
    รอบเดียวจบ: ดึงงาน → กรอง → วิเคราะห์ → push LINE
    คืน dict สรุปผล
    """
    global _seen_job_ids, _hunter_log

    jobs = _fetch_jobs()
    new_matched = []

    for job in jobs:
        jid = job.get("id")
        if not jid or jid in _seen_job_ids:
            continue
        if job.get("status") != "open":
            _seen_job_ids.add(jid)
            continue

        grade, matched = _match_skills(job)
        _seen_job_ids.add(jid)
        if grade:
            new_matched.append((job, grade, matched))

    # เกรด A ก่อนเสมอ
    new_matched.sort(key=lambda x: 0 if x[1] == "A" else 1)

    # จำกัดจำนวนที่วิเคราะห์ต่อรอบ (คุมค่า API)
    alerts_sent = 0
    results = []

    triaged_out = 0
    for job, grade, matched in new_matched[:max_alerts * 2]:
        if alerts_sent >= max_alerts:
            break

        # ด่าน 1: Haiku คัดขยะทิ้งก่อน (ถูก) — ผ่านแล้วค่อยจ่ายค่า Sonnet
        if not _triage(anthropic_client, job, matched, push_line_fn, line_user_id):
            triaged_out += 1
            print(f"[Hunter] Haiku คัดออก: {(job.get('title') or '')[:50]}", flush=True)
            continue

        # ด่าน 2: Sonnet วิเคราะห์เต็ม + ร่างข้อเสนอ (แพง แต่คุ้มเพราะกรองมาแล้ว)
        try:
            analysis = _analyze_job(anthropic_client, job, matched)
        except Exception as e:
            print(f"[Hunter] analyze failed: {e}", flush=True)
            continue

        score = analysis.get("fit_score", 0)
        entry = {
            "time": datetime.now(timezone.utc).isoformat(),
            "job_id": job.get("id"),
            "grade": grade,
            "title": (job.get("title") or "").strip()[:80],
            "budget": job.get("budget") or "-",
            "url": _job_url(job.get("id", "")),
            "score": score,
            "summary": analysis.get("summary", ""),
        }

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

    return {
        "checked": len(jobs),
        "new_matching": len(new_matched),
        "triaged_out": triaged_out,      # Haiku คัดออกกี่งาน = ประหยัดค่า Sonnet ไปเท่านั้น
        "analyzed": len(results),
        "alerts_sent": alerts_sent,
        "results": results,
    }


def get_hunter_log() -> list:
    return _hunter_log
