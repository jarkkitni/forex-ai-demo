"""
ai_guard — คุมต้นทุน AI + กันระบบตายเงียบ

บทเรียน 18 ก.ค. 2026:
  ANTHROPIC_API_KEY หมดอายุตอน 17 ก.ค. → Job Hunter เช็คงาน 50 งานทุก 30 นาที
  แต่วิเคราะห์ไม่ได้เลยสักงาน และ *ไม่มีใครรู้* จนผ่านไป 1 วันเต็ม
  → งานเกรด A หลุดไปเท่าไหร่ไม่มีทางรู้

3 หน้าที่ของไฟล์นี้:
  1. call()       — เรียก Claude แบบมีเกราะ · AI ตาย = เด้ง LINE ทันที (ไม่สแปม)
  2. rate_limit() — กันคนยิง endpoint สาธารณะรัวๆ จนเงินหมด
  3. triage       — ใช้ Haiku คัดก่อน แล้วค่อยให้ Sonnet ทำงานหนัก (ถูกลงหลายเท่า)
"""
import os
import time
import traceback
import requests
from datetime import datetime, timezone

# รุ่นที่ใช้ — Haiku ถูกกว่ามาก ใช้คัดของ / Sonnet ฉลาดกว่า ใช้ตอนสำคัญ
MODEL_CHEAP = os.environ.get("AI_MODEL_CHEAP", "claude-haiku-4-5-20251001")
MODEL_SMART = os.environ.get("AI_MODEL_SMART", "claude-sonnet-4-5")

# ---- Groq (ฟรี) — ใช้เป็น tier="free" เริ่มต้นสำหรับบอทลูกค้าใหม่ + fallback ตอน Claude ล่ม ----
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# ---- Gemini — ชั้นสำรองที่ 3 (เพิ่ม 21 ก.ค. 2026 หลังเจอเคสจริง Claude หมดเครดิต + Groq โดน
# rate limit พร้อมกันวันเดียว ทำให้ทั้ง 2 ทางตันพร้อมกัน) คนละ provider คนละโควต้ากับทั้งคู่
# เลยไม่น่าจะล่มพร้อมกันด้วย — สมัคร key ฟรีที่ aistudio.google.com
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# หมายเหตุ 21 ก.ค. 2026: "gemini-2.0-flash" โควต้า free tier ของโปรเจกต์นี้คือ 0/0 (ไม่ได้รับเลย)
# ต้องใช้ "gemini-2.5-flash" ถึงจะมีโควต้าจริง — ตอนนี้เปิด billing (Tier 1) แล้วด้วย โควต้าสูงมาก
# 21 ก.ค. 2026 (รอบ 2): ลองยิงจริงหลังเปิด billing เจอ gemini-2.0-flash 404 Not Found (Google เลิกรองรับ
# ชื่อโมเดลนี้ไปแล้ว) — เปลี่ยนเป็น "ลองหลายโมเดลเรียงกัน" กันเคสแบบนี้ซ้ำ ถ้าตัวหลักโดนเลิกรองรับ/เปลี่ยนชื่อ
# อีกในอนาคต ระบบลองตัวถัดไปเองอัตโนมัติ ไม่ต้องรอแก้โค้ด+push+deploy ใหม่ทุกครั้ง
# ตั้ง env var GEMINI_MODEL เป็น comma-separated list เพื่อ override ลำดับ/รายชื่อได้ (ตัวแรกในลิสต์ = ลองก่อน)
GEMINI_MODELS = [m.strip() for m in
                 os.environ.get("GEMINI_MODEL", "gemini-2.5-flash,gemini-2.0-flash").split(",")
                 if m.strip()]
GEMINI_URL_TMPL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# ---- สถานะ AI แยกต่อโปรเจกต์ (slug) — กันบั๊ก 20 ก.ค.: เดิม _health เป็น dict ก้อนเดียวใช้ร่วมกันทุกบอท
# ทำให้ถ้าร้าน A ชน AI ล่มจนแจ้งเตือนไปแล้ว ระบบจะเงียบไม่แจ้งร้าน B อีก 6 ชม. แม้ร้าน B ล่มคนละเวลาคนละสาเหตุ
# → ต้องแยกสถานะ+cooldown ต่อ slug กันเดี๋ยวรับงานลูกค้าหลายเจ้าพร้อมกันแล้วเจ้าหนึ่งบังอีกเจ้า
_health_by_slug: dict = {}   # slug -> {ok, last_ok, last_error, last_error_at, last_provider, alerted_at, calls, fails}
ALERT_COOLDOWN = 3600 * 6     # เตือนซ้ำได้ทุก 6 ชม. พอ (ต่อ slug)
_DEFAULT_SLUG = "default"    # ใช้กับโค้ดเก่าที่ยังไม่ได้ส่ง slug มา (เช่นตอน migrate ครั้งแรก)


def _new_bucket() -> dict:
    return {
        "ok": True, "last_ok": None, "last_error": None, "last_error_at": None,
        "last_provider": None, "alerted_at": 0, "calls": 0, "fails": 0,
    }


def _bucket(slug: str) -> dict:
    return _health_by_slug.setdefault(slug or _DEFAULT_SLUG, _new_bucket())


def health(slug: str = None) -> dict:
    """ใส่ slug (เช่น 'lullabell', 'job_hunter', 'forex') = ดูสถานะเฉพาะโปรเจกต์นั้น
    ไม่ใส่ slug = สรุปรวมทุกโปรเจกต์ที่เคยเรียก AI (ok=False ถ้ามีตัวไหนพัง, last_error = ตัวที่พังล่าสุดจริง)
    ใช้กับ dashboard เก่า (/api/pulse, daily-summary) ที่อยากได้ไฟเขียว/แดงรวมดวงเดียว"""
    if slug:
        b = dict(_bucket(slug))
        b.pop("alerted_at", None)
        b["slug"] = slug
        b["groq_configured"] = bool(GROQ_API_KEY)
        b["gemini_configured"] = bool(GEMINI_API_KEY)
        return b

    if not _health_by_slug:
        return {"ok": True, "last_ok": None, "last_error": None, "last_error_at": None,
                "last_provider": None, "calls": 0, "fails": 0,
                "groq_configured": bool(GROQ_API_KEY), "gemini_configured": bool(GEMINI_API_KEY)}

    buckets = _health_by_slug.items()
    all_ok = all(b["ok"] for b in _health_by_slug.values())
    total_calls = sum(b["calls"] for b in _health_by_slug.values())
    total_fails = sum(b["fails"] for b in _health_by_slug.values())

    ok_buckets = [(s, b) for s, b in buckets if b.get("last_ok")]
    last_ok_slug, last_ok_bucket = max(ok_buckets, key=lambda x: x[1]["last_ok"]) if ok_buckets else (None, {})

    err_buckets = [(s, b) for s, b in _health_by_slug.items() if b.get("last_error_at")]
    last_err_slug, last_err_bucket = max(err_buckets, key=lambda x: x[1]["last_error_at"]) if err_buckets else (None, {})

    return {
        "ok": all_ok,
        "last_ok": last_ok_bucket.get("last_ok"),
        "last_provider": last_ok_bucket.get("last_provider"),
        "last_error": last_err_bucket.get("last_error"),
        "last_error_at": last_err_bucket.get("last_error_at"),
        "last_error_slug": last_err_slug,
        "calls": total_calls,
        "fails": total_fails,
        "groq_configured": bool(GROQ_API_KEY),
        "gemini_configured": bool(GEMINI_API_KEY),
    }


def health_all() -> dict:
    """คืนสถานะแยกทุกโปรเจกต์ {slug: health} — ใช้ทำ dashboard ละเอียดดูทีละร้าน"""
    return {slug: health(slug) for slug in list(_health_by_slug)}


GROQ_RETRY_MAX = 1          # จำนวนครั้งที่ลองใหม่ตอนโดน rate limit (429) ก่อนยอมแพ้ไป fallback
GROQ_RETRY_WAIT_CAP = 3.0   # วินาที — กันรอนานเกินจน Meta webhook timeout (Meta รอ ~20 วิ)


def _call_groq(prompt: str, max_tokens: int = 1000) -> str:
    """เรียก Groq (ฟรี, OpenAI-compatible endpoint) — ใช้ requests ตรงๆ ไม่ต้องเพิ่ม dependency ใหม่
    20 ก.ค. เจอเคสจริง: ลูกค้าพิมพ์ถี่ 2 ข้อความติดกัน โดน Groq free tier rate limit (429) ตอบข้อความที่ 2
    ทั้งที่ไม่ได้ล่มจริง แค่ชนลิมิตความถี่ต่อนาทีเฉยๆ → เพิ่ม retry สั้นๆ ก่อนยอมแพ้ไป fallback
    (ใช้ Retry-After header จาก Groq ถ้ามีบอกมา ไม่งั้น backoff เอง) กันเด้งไป fallback บ่อยเกินจำเป็น"""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY ยังไม่ได้ตั้ง — สมัครฟรีที่ console.groq.com แล้วใส่ค่าใน Render")
    attempt = 0
    while True:
        r = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
            },
            timeout=30,
        )
        if r.status_code == 429 and attempt < GROQ_RETRY_MAX:
            try:
                wait = float(r.headers.get("Retry-After", 0))
            except (TypeError, ValueError):
                wait = 0
            wait = min(wait or 1.5 * (attempt + 1), GROQ_RETRY_WAIT_CAP)
            time.sleep(wait)
            attempt += 1
            continue
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()


def _call_gemini(prompt: str, max_tokens: int = 1000) -> str:
    """เรียก Gemini API ตรงๆผ่าน requests (ไม่เพิ่ม dependency ใหม่ แพทเทิร์นเดียวกับ Groq)
    ใช้เป็นชั้นสำรองที่ 3 หลัง Claude+Groq ล่มทั้งคู่ — คนละ provider คนละโควต้า ลดโอกาสตายพร้อมกันทั้งหมด

    ลองไล่ทีละโมเดลใน GEMINI_MODELS (ตัวแรกก่อน) — กันเคส 21 ก.ค. 2026 ที่ gemini-2.0-flash โดน Google
    เลิกรองรับกะทันหันจน 404 ทั้งที่ key/billing ปกติดี ถ้าตัวหลักใช้ไม่ได้ไม่ว่าเหตุผลอะไร (404 เลิกรองรับ,
    429 โควต้าเต็มเฉพาะโมเดลนั้น, ฯลฯ) ลองตัวถัดไปในลิสต์ต่อทันทีก่อนจะยอมแพ้จริงๆ

    thinkingConfig.thinkingBudget=0: ปิด "thinking" mode ของ gemini-2.5-flash (เปิดเป็นค่า default ถ้าไม่สั่งปิด)
    เจอจริง 21 ก.ค. 2026 (รอบ 3) หลังสลับให้ Gemini เป็นตัวหลัก — ลูกค้าถามขอดูโปรทั้งหมดพร้อมราคา แต่บอทตอบ
    สั้นห้วนแค่ประโยคเดียว ไม่มีรายชื่อโปร/ราคาเลย ทั้งที่ system prompt สั่งไว้ชัดเจน ตรวจ Render logs ไม่เจอ
    error อะไรเลย (ok=true, fails=0) แปลว่า Gemini ตอบสำเร็จแต่เนื้อหาห้วนเอง — สาเหตุคือ "thinking" tokens
    (การให้โมเดลคิดในใจก่อนตอบ) นับรวมอยู่ใน maxOutputTokens เดียวกับคำตอบจริง พอ thinking กินโควต้าไปเยอะ
    เหลือโควต้าให้คำตอบจริงน้อยจนถูกตัดจบก่อนจะทันเขียนรายการโปรครบ ปิด thinking ไปเลยเพราะงานนี้เป็นแชทบอท
    ตอบไว ไม่ต้องการ multi-step reasoning อยู่แล้ว (คำสั่งอยู่ครบใน system prompt แล้ว) — ปลอดภัยสำหรับ
    gemini-2.0-flash ด้วยเพราะโมเดลนี้ไม่รองรับ thinking อยู่แล้ว ใส่ param นี้ไปจะถูกเมิน ไม่พัง"""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY ยังไม่ได้ตั้ง — สร้างที่ aistudio.google.com แล้วใส่ค่าใน Render")
    last_exc: Exception | None = None
    for model in GEMINI_MODELS:
        url = GEMINI_URL_TMPL.format(model=model)
        try:
            r = requests.post(
                url,
                params={"key": GEMINI_API_KEY},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "maxOutputTokens": max_tokens,
                        "thinkingConfig": {"thinkingBudget": 0},
                    },
                },
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
            try:
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()
            except (KeyError, IndexError) as e:
                # Gemini ตอบ 200 มาได้แต่ไม่มีคำตอบที่ใช้ได้จริง (เช่น โดน safety filter บล็อก) —
                # ต้องถือว่าโมเดลนี้ใช้ไม่ได้ ไม่ใช่ถือว่าสำเร็จทั้งที่ไม่มีข้อความตอบ
                raise RuntimeError(f"Gemini ({model}) ตอบไม่มี candidates ที่ใช้ได้: {str(data)[:200]}") from e
        except Exception as e:
            print(f"[ai_guard] Gemini model '{model}' ใช้ไม่ได้ ({e}) — ลองโมเดลถัดไปในลิสต์", flush=True)
            last_exc = e
            continue
    raise RuntimeError(
        f"Gemini ทุกโมเดลใช้ไม่ได้หมด ({', '.join(GEMINI_MODELS)}): {last_exc}"
    ) from last_exc


def _alert(slug: str, err: str, notify_fn, line_user_id: str, degraded: bool = False,
           failed_provider: str = "Claude", fallback_provider: str = "Groq",
           next_fallback: str = None,
           all_dead_providers: str = "Claude, Groq, Gemini") -> None:
    """AI มีปัญหา — degraded=True หมายถึงตัวหลักล่มแต่ fallback ไปตัวสำรองได้ (ลูกค้ายังได้คำตอบ แค่คุณภาพลดลงชั่วคราว)
    degraded=False หมายถึงทุกทางตันหมด ต้องรู้เดี๋ยวนี้
    failed_provider/fallback_provider: ระบุทิศทางจริงที่เกิดขึ้น กันข้อความแจ้งเตือนผิดทิศ
    next_fallback: ชื่อชั้นสำรองถัดไปที่ยังเหลืออยู่จริง (ถ้ามี) — ใส่ให้ตรงเป๊ะตามลำดับ cascade จริงของแต่ละ tier
    ณ ตอนนี้ (21 ก.ค. 2026 รอบ 3) แทนที่จะเดาจากชื่อ provider (เคยฮาร์ดโค้ดว่า fallback_provider=="Gemini"
    คือชั้นสุดท้ายเสมอ ซึ่งพังทันทีที่สลับลำดับ cascade รอบนี้ — Gemini กลายเป็นตัวหลัก ไม่ใช่ชั้นสุดท้ายอีกแล้ว)
    ผู้เรียกต้องระบุ next_fallback ตรงๆ ให้ตรงกับ cascade จริงที่ใช้อยู่
    slug: กัน cooldown ของโปรเจกต์หนึ่งไปบังการแจ้งเตือนของอีกโปรเจกต์ — แต่ละ slug มี cooldown ของตัวเอง"""
    b = _bucket(slug)
    now = time.time()
    if now - b["alerted_at"] < ALERT_COOLDOWN:
        return
    if not (notify_fn and line_user_id):
        return
    b["alerted_at"] = now
    label = f"🏷️ ระบบ: {slug}\n" if slug and slug != _DEFAULT_SLUG else ""

    hint = "เช็ค ANTHROPIC_API_KEY ใน Render"
    e = err.lower()
    if "authentication" in e or "401" in e or "invalid" in e:
        hint = "key ผิดหรือหมดอายุ → สร้างใหม่ (ตั้ง Expires: Never!) แล้วใส่ใน Render"
    elif "credit" in e or "quota" in e or "billing" in e or "429" in e:
        hint = "เครดิตหมด หรือชนเพดานที่ตั้งไว้ → เติมเงิน/ปรับ limit ใน Console"

    try:
        if degraded:
            if next_fallback:
                safety_net = f"🛡️ ถ้า {fallback_provider} ก็ล่มด้วย ระบบจะลอง {next_fallback} เป็นชั้นสำรองถัดไปอัตโนมัติ"
            else:
                safety_net = f"🛡️ ถ้า {fallback_provider} ก็ล่มด้วย ลูกค้าจะได้คำตอบราคา/ที่อยู่จาก template อัตโนมัติแทน (นกน้อยทำลัง) ไม่เงียบแน่นอน"
            notify_fn(line_user_id, (
                f"{label}⚠️ {failed_provider} ใช้งานไม่ได้ชั่วคราว — สลับไปใช้ {fallback_provider} แทนอัตโนมัติแล้ว\n"
                "━━━━━━━━━━━━\n"
                "บอทลูกค้ายังตอบได้ปกติ แค่คุณภาพคำตอบอาจลดลงเล็กน้อยชั่วคราว\n"
                f"{safety_net}\n"
                "━━━━━━━━━━━━\n"
                f"❌ {err[:150]}\n\n"
                f"🔧 {hint}\n"
                "https://platform.claude.com/settings/workspaces/default/keys"
            ))
        else:
            notify_fn(line_user_id, (
                f"{label}🚨 AI เรียกไม่ได้ทั้ง {all_dead_providers} — ระบบหยุดทำงาน!\n"
                "━━━━━━━━━━━━\n"
                "กระทบ (ถ้าเป็น key/เครดิตหมดร่วมกัน จะกระทบทุกอย่างที่ใช้ AI):\n"
                "• บอทลูกค้า (Lullabell) — ตอบเองไม่ได้ 😱 แต่ถ้าลูกค้าถามราคา/ที่อยู่ จะได้คำตอบจริงจาก template อัตโนมัติแทน (นกน้อยทำลัง) คำถามอื่นจะได้ข้อความรอสักครู่\n"
                "• Job Hunter — ดักงานไม่ได้ 🔥\n"
                "• Forex analyze — วิเคราะห์ไม่ได้\n"
                "• Auto-Execution — เทรดกระดาษไม่ได้\n"
                "━━━━━━━━━━━━\n"
                f"❌ {err[:150]}\n\n"
                f"🔧 {hint}\n"
                "https://platform.claude.com/settings/workspaces/default/keys"
            ))
    except Exception as e2:
        print(f"[ai_guard] แจ้งเตือนล้มเหลว: {e2}", flush=True)


def call(client, prompt: str, max_tokens: int = 1000, smart: bool = True,
         notify_fn=None, line_user_id: str = "", tier: str = "smart", slug: str = "") -> str:
    """
    เรียก AI แบบมีเกราะ — คืน text ดิบ
    tier="smart" (ค่าเริ่มต้น) → ใช้ Claude (smart=True→Sonnet, False→Haiku) เป็นหลัก
                                  ถ้า Claude ล่ม (เครดิตหมด/quota/key พัง) จะ fallback ไป Groq (ฟรี) อัตโนมัติ กันบอทลูกค้าเงียบ
    tier="free"  → ใช้ Gemini เป็นหลักเลย — ใช้กับบอทลูกค้าที่ยังไม่ได้อัปเกรดเป็นแพ็กเกจ AI ฉลาดขึ้น
                                  ถ้า Gemini ล่ม (ทุกโมเดลในลิสต์พังหมด/quota เต็ม) จะ fallback ไป Groq (ฟรี) อัตโนมัติ กันบอทเงียบสนิท
                                  ไม่แตะ Claude เลยตอนนี้
                                  (21 ก.ค. 2026 รอบ 3: sIRImeta ขอเปลี่ยนให้ Gemini เป็นตัวหลักแทน Groq — เพิ่งเปิด billing
                                  Gemini แล้วโควต้าสูงมาก + คุณภาพคำตอบดีกว่า Groq ส่วน Groq เก็บไว้เป็นสำรองชั้นเดียว (ฟรี กันเผื่อ
                                  Gemini โดน quota/rate limit ชั่วครู่) ตัด Claude Haiku ออกจากคิวนี้ไปแล้วด้วย เพราะเครดิตหมด
                                  เรียกกี่ครั้งก็พังทุกครั้งแน่ๆ เก็บไว้มีแต่เสียเวลาฟรี ยิ่งช้ายิ่งเสี่ยง Meta ส่ง webhook ซ้ำ)
    slug: ชื่อโปรเจกต์/ร้าน (เช่น "lullabell", "job_hunter", "forex") — แยกสถานะ+cooldown แจ้งเตือนต่อร้าน
          กันร้าน A ล่มจนแจ้งเตือนไปแล้ว บังไม่ให้ร้าน B ได้รับแจ้งเตือนอีก 6 ชม. ทั้งที่คนละปัญหาคนละเวลา
          ไม่ใส่ = ใช้ bucket "default" ร่วมกัน (ของเก่าที่ยังไม่ได้ migrate)
    """
    b = _bucket(slug)
    b["calls"] += 1

    if tier == "free":
        try:
            text = _call_gemini(prompt, max_tokens)
            b["ok"] = True
            b["last_provider"] = "gemini"
            b["last_ok"] = datetime.now(timezone.utc).isoformat()
            return text
        except Exception as e:
            b["fails"] += 1
            b["last_error"] = f"[gemini] {str(e)[:190]}"
            b["last_error_at"] = datetime.now(timezone.utc).isoformat()
            # Gemini ล่ม → ลอง fallback ไป Groq (ฟรี) ก่อนยอมแพ้ กันบอทลูกค้าเงียบไปเลย — ไม่แตะ Claude เลย
            if GROQ_API_KEY:
                try:
                    text = _call_groq(prompt, max_tokens)
                    b["ok"] = True
                    b["last_provider"] = "groq (fallback)"
                    b["last_ok"] = datetime.now(timezone.utc).isoformat()
                    _alert(slug, str(e), notify_fn, line_user_id, degraded=True,
                           failed_provider="Gemini", fallback_provider="Groq")
                    return text
                except Exception as e2:
                    print(f"[ai_guard] Groq fallback ก็ล้มด้วย (slug={slug}): {e2}", flush=True)
                    traceback.print_exc()
            b["ok"] = False
            _alert(slug, str(e), notify_fn, line_user_id, degraded=False,
                   all_dead_providers="Gemini, Groq")
            raise

    try:
        msg = client.messages.create(
            model=MODEL_SMART if smart else MODEL_CHEAP,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        b["ok"] = True
        b["last_provider"] = "claude"
        b["last_ok"] = datetime.now(timezone.utc).isoformat()
        return msg.content[0].text.strip()
    except Exception as e:
        b["fails"] += 1
        b["last_error"] = str(e)[:200]
        b["last_error_at"] = datetime.now(timezone.utc).isoformat()
        # Claude ล่ม → ลอง fallback ไป Groq ก่อนยอมแพ้ กันบอทลูกค้าเงียบไปเลย
        if GROQ_API_KEY:
            try:
                text = _call_groq(prompt, max_tokens)
                b["ok"] = True
                b["last_provider"] = "groq (fallback)"
                b["last_ok"] = datetime.now(timezone.utc).isoformat()
                _alert(slug, str(e), notify_fn, line_user_id, degraded=True, next_fallback="Gemini")
                return text
            except Exception as e2:
                # เดิม except เปล่าไม่ log อะไรเลย — จุดคู่กับ fallback Claude Haiku ด้านบน
                # (เคส Claude ล่มก่อน แล้ว fallback ไป Groq ก็ล้มด้วย) log ไว้กันหาสาเหตุไม่ได้เหมือนกัน
                print(f"[ai_guard] Groq fallback ก็ล้มด้วย (slug={slug}): {e2}", flush=True)
                traceback.print_exc()
        # Claude + Groq ล่มทั้งคู่ → ลอง Gemini (ชั้นสำรองที่ 3 คนละ provider คนละโควต้า) ก่อนยอมแพ้จริงๆ
        # (เพิ่ม 21 ก.ค. 2026 — เคสจริง Claude หมดเครดิต + Groq โดน rate limit พร้อมกันวันเดียว ทำให้ทาง
        # ตันพร้อมกันทั้งคู่ ลูกค้าโดน fallback message ล้วนๆ ทั้งที่ยังมี AI ตัวที่ 3 ใช้ได้อยู่)
        if GEMINI_API_KEY:
            try:
                text = _call_gemini(prompt, max_tokens)
                b["ok"] = True
                b["last_provider"] = "gemini (fallback)"
                b["last_ok"] = datetime.now(timezone.utc).isoformat()
                _alert(slug, str(e), notify_fn, line_user_id, degraded=True,
                       failed_provider="Claude + Groq", fallback_provider="Gemini")
                return text
            except Exception as e3:
                print(f"[ai_guard] Gemini fallback ก็ล้มด้วย (slug={slug}): {e3}", flush=True)
                traceback.print_exc()
        b["ok"] = False
        _alert(slug, str(e), notify_fn, line_user_id, degraded=False)
        raise


# ---------- Rate limit (กันคนยิงรัวจนเงินหมด) ----------

_hits: dict = {}     # ip -> [timestamps]


def rate_limit(ip: str, limit: int = 5, window: int = 86400) -> tuple:
    """
    คืน (ผ่านไหม, เหลือกี่ครั้ง)
    ค่าเริ่มต้น 5 ครั้ง/IP/วัน — คนดูจริงพอ คนยิงสคริปต์ไม่พอ
    """
    now = time.time()
    arr = [t for t in _hits.get(ip, []) if now - t < window]
    if len(arr) >= limit:
        _hits[ip] = arr
        return False, 0
    arr.append(now)
    _hits[ip] = arr
    if len(_hits) > 5000:                       # กัน memory บวม
        for k in list(_hits)[:1000]:
            _hits.pop(k, None)
    return True, limit - len(arr)


def client_ip(req) -> str:
    return req.headers.get("X-Forwarded-For", req.remote_addr or "?").split(",")[0].strip()
