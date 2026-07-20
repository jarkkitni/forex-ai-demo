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
from datetime import datetime, timezone

# รุ่นที่ใช้ — Haiku ถูกกว่ามาก ใช้คัดของ / Sonnet ฉลาดกว่า ใช้ตอนสำคัญ
MODEL_CHEAP = os.environ.get("AI_MODEL_CHEAP", "claude-haiku-4-5-20251001")
MODEL_SMART = os.environ.get("AI_MODEL_SMART", "claude-sonnet-4-5")

_health = {
    "ok": True,
    "last_ok": None,
    "last_error": None,
    "last_error_at": None,
    "alerted_at": 0,      # กันสแปม LINE
    "calls": 0,
    "fails": 0,
}
ALERT_COOLDOWN = 3600 * 6     # เตือนซ้ำได้ทุก 6 ชม. พอ


def health() -> dict:
    h = dict(_health)
    h.pop("alerted_at", None)
    return h


def _alert_dead(err: str, notify_fn, line_user_id: str) -> None:
    """AI เรียกไม่ได้ = ทุกอย่างหยุดทำงาน ต้องรู้เดี๋ยวนี้"""
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
        notify_fn(line_user_id, (
            "🚨 AI เรียกไม่ได้ — ระบบหยุดทำงาน!\n"
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
         notify_fn=None, line_user_id: str = "") -> str:
    """
    เรียก Claude แบบมีเกราะ — คืน text ดิบ
    smart=False → ใช้ Haiku (ถูก) · smart=True → Sonnet (ฉลาด)
    """
    _health["calls"] += 1
    try:
        msg = client.messages.create(
            model=MODEL_SMART if smart else MODEL_CHEAP,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        _health["ok"] = True
        _health["last_ok"] = datetime.now(timezone.utc).isoformat()
        return msg.content[0].text.strip()
    except Exception as e:
        _health["ok"] = False
        _health["fails"] += 1
        _health["last_error"] = str(e)[:200]
        _health["last_error_at"] = datetime.now(timezone.utc).isoformat()
        _alert_dead(str(e), notify_fn, line_user_id)
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
