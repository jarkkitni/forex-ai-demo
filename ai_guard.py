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
import requests
from datetime import datetime, timezone

# รุ่นที่ใช้ — Haiku ถูกกว่ามาก ใช้คัดของ / Sonnet ฉลาดกว่า ใช้ตอนสำคัญ
MODEL_CHEAP = os.environ.get("AI_MODEL_CHEAP", "claude-haiku-4-5-20251001")
MODEL_SMART = os.environ.get("AI_MODEL_SMART", "claude-sonnet-4-5")

# ---- Groq (ฟรี) — ใช้เป็น tier="free" เริ่มต้นสำหรับบอทลูกค้าใหม่ + fallback ตอน Claude ล่ม ----
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

_health = {
    "ok": True,
    "last_ok": None,
    "last_error": None,
    "last_error_at": None,
    "last_provider": None,   # "claude" | "groq" — ใช้ตัวไหนล่าสุด
    "alerted_at": 0,      # กันสแปม LINE
    "calls": 0,
    "fails": 0,
}
ALERT_COOLDOWN = 3600 * 6     # เตือนซ้ำได้ทุก 6 ชม. พอ


def health() -> dict:
    h = dict(_health)
    h.pop("alerted_at", None)
    h["groq_configured"] = bool(GROQ_API_KEY)
    return h


def _call_groq(prompt: str, max_tokens: int = 1000) -> str:
    """เรียก Groq (ฟรี, OpenAI-compatible endpoint) — ใช้ requests ตรงๆ ไม่ต้องเพิ่ม dependency ใหม่"""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY ยังไม่ได้ตั้ง — สมัครฟรีที่ console.groq.com แล้วใส่ค่าใน Render")
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
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def _alert(err: str, notify_fn, line_user_id: str, degraded: bool = False) -> None:
    """AI มีปัญหา — degraded=True หมายถึง Claude ล่มแต่ fallback ไป Groq ได้ (ลูกค้ายังได้คำตอบ แค่คุณภาพลดลงชั่วคราว)
    degraded=False หมายถึงทุกทางตันหมด ต้องรู้เดี๋ยวนี้"""
    now = time.time()
    if now - _health["alerted_at"] < ALERT_COOLDOWN:
        return
    if not (notify_fn and line_user_id):
        return
    _health["alerted_at"] = now

    hint = "เช็ค ANTHROPIC_API_KEY ใน Render"
    e = err.lower()
    if "authentication" in e or "401" in e or "invalid" in e:
        hint = "key ผิดหรือหมดอายุ → สร้างใหม่ (ตั้ง Expires: Never!) แล้วใส่ใน Render"
    elif "credit" in e or "quota" in e or "billing" in e or "429" in e:
        hint = "เครดิตหมด หรือชนเพดานที่ตั้งไว้ → เติมเงิน/ปรับ limit ใน Console"

    try:
        if degraded:
            notify_fn(line_user_id, (
                "⚠️ Claude ใช้งานไม่ได้ชั่วคราว — สลับไปใช้ Groq (ฟรี) แทนอัตโนมัติแล้ว\n"
                "━━━━━━━━━━━━\n"
                "บอทลูกค้ายังตอบได้ปกติ แค่คุณภาพคำตอบอาจลดลงเล็กน้อยชั่วคราว\n"
                "━━━━━━━━━━━━\n"
                f"❌ {err[:150]}\n\n"
                f"🔧 {hint}\n"
                "https://platform.claude.com/settings/workspaces/default/keys"
            ))
        else:
            notify_fn(line_user_id, (
                "🚨 AI เรียกไม่ได้ทั้ง Claude และ Groq — ระบบหยุดทำงาน!\n"
                "━━━━━━━━━━━━\n"
                "กระทบ:\n"
                "• บอทลูกค้า (Lullabell) — ตอบลูกค้าจริงไม่ได้ 😱 ลูกค้าจะได้ข้อความ fallback แทน\n"
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
         notify_fn=None, line_user_id: str = "", tier: str = "smart") -> str:
    """
    เรียก AI แบบมีเกราะ — คืน text ดิบ
    tier="smart" (ค่าเริ่มต้น) → ใช้ Claude (smart=True→Sonnet, False→Haiku) เป็นหลัก
                                  ถ้า Claude ล่ม (เครดิตหมด/quota/key พัง) จะ fallback ไป Groq (ฟรี) อัตโนมัติ กันบอทลูกค้าเงียบ
    tier="free"  → ใช้ Groq (ฟรี) เป็นหลักเลย ไม่แตะเครดิต Claude — ใช้กับบอทลูกค้าที่ยังไม่ได้อัปเกรดเป็นแพ็กเกจ AI ฉลาดขึ้น
    """
    _health["calls"] += 1

    if tier == "free":
        try:
            text = _call_groq(prompt, max_tokens)
            _health["ok"] = True
            _health["last_provider"] = "groq"
            _health["last_ok"] = datetime.now(timezone.utc).isoformat()
            return text
        except Exception as e:
            _health["ok"] = False
            _health["fails"] += 1
            _health["last_error"] = f"[groq] {str(e)[:190]}"
            _health["last_error_at"] = datetime.now(timezone.utc).isoformat()
            _alert(str(e), notify_fn, line_user_id, degraded=False)
            raise

    try:
        msg = client.messages.create(
            model=MODEL_SMART if smart else MODEL_CHEAP,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        _health["ok"] = True
        _health["last_provider"] = "claude"
        _health["last_ok"] = datetime.now(timezone.utc).isoformat()
        return msg.content[0].text.strip()
    except Exception as e:
        _health["fails"] += 1
        _health["last_error"] = str(e)[:200]
        _health["last_error_at"] = datetime.now(timezone.utc).isoformat()
        # Claude ล่ม → ลอง fallback ไป Groq ก่อนยอมแพ้ กันบอทลูกค้าเงียบไปเลย
        if GROQ_API_KEY:
            try:
                text = _call_groq(prompt, max_tokens)
                _health["ok"] = True
                _health["last_provider"] = "groq (fallback)"
                _health["last_ok"] = datetime.now(timezone.utc).isoformat()
                _alert(str(e), notify_fn, line_user_id, degraded=True)
                return text
            except Exception:
                pass  # fallback ก็พังด้วย ปล่อยให้ตกไป alert แบบเต็มข้างล่าง
        _health["ok"] = False
        _alert(str(e), notify_fn, line_user_id, degraded=False)
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
