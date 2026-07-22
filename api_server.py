"""
ForexAI Pro — API Server
เชื่อม AI วิเคราะห์ + ราคา Forex/Crypto + LINE Notification
"""
import os, re, json, requests, traceback, hmac, hashlib, base64
from datetime import datetime
from flask import Flask, jsonify, request, session, redirect
from flask_cors import CORS
import anthropic
import secrets as _secrets

import fastwork_hunter
import rss_hunter
import dialysis_api
import seo_tracker
import ai_guard
import meta_bot

app  = Flask(__name__)
CORS(app)

# ====== ENV CONFIG ======
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")
LINE_TOKEN          = os.environ.get("LINE_TOKEN", "")
LINE_USER_ID        = os.environ.get("LINE_USER_ID", "")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
# ---- session secret (สำหรับ TikTok OAuth state/PKCE) — ตั้ง FLASK_SECRET_KEY บน Render ถ้ามี ไม่งั้น derive จาก ANTHROPIC_API_KEY ชั่วคราว ----
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or hashlib.sha256((ANTHROPIC_API_KEY or "forex-ai-demo-fallback").encode()).hexdigest()
# ---- TikTok Content Posting API (แอป Claude ใน TikTok Developer Portal) ----
TIKTOK_CLIENT_KEY    = os.environ.get("TIKTOK_CLIENT_KEY", "")
TIKTOK_CLIENT_SECRET = os.environ.get("TIKTOK_CLIENT_SECRET", "")
# ---- Meta (Facebook Messenger + Instagram) ----
META_VERIFY_TOKEN   = os.environ.get("META_VERIFY_TOKEN", "")
META_PAGE_TOKEN     = os.environ.get("META_PAGE_TOKEN", "")
META_APP_SECRET     = os.environ.get("META_APP_SECRET", "")
META_SLUG           = os.environ.get("META_SLUG", "lullabell")
META_PAGE_ID        = os.environ.get("META_PAGE_ID", "783393614867196")  # เพจ Lullabell
N8N_POST_SECRET     = os.environ.get("N8N_POST_SECRET", "")  # กัน endpoint โพสต์ FB ถูกยิงมั่ว
# ---- Lullabell แยกดีพลอย (21 ก.ค. 2026) — forward event ของเพจนี้ไปยัง service เดี่ยวแทนที่จะ
# handle เองที่นี่ (ปลอดภัยขึ้น: secret/deploy lifecycle ของลูกค้าจริงไม่ผูกกับฟีเจอร์ทดลองอื่น)
# Callback URL ที่ตั้งไว้กับ Meta ยังเป็นของ service นี้เหมือนเดิม (Messenger รองรับแค่ 1 URL ต่อ 1 App)
# hybrid: ตั้ง LULLABELL_FORWARD_URL = แบบ A (แยก service); เว้นว่าง = แบบ B (ตอบในนี้ผ่าน multi-tenant) ----
LULLABELL_PAGE_ID    = os.environ.get("LULLABELL_PAGE_ID", "783393614867196")  # เพจ Lullabell (ค่าเดียวกับ META_PAGE_ID เดิม)
LULLABELL_FORWARD_URL = os.environ.get("LULLABELL_FORWARD_URL", "")  # เช่น https://lullabell-bot.onrender.com/webhook/meta
# ---- คิลสวิตช์ Hunter/RSS/autotrade (21 ก.ค. 2026) — งานเบื้องหลังพวกนี้เรียก Claude ทุก 30 นาที
# เผาเครดิต Anthropic จนหมด ทำให้บอทร้านลูกค้า (Lullabell) ที่ใช้ AI ตัวเดียวกันพลอยสะดุดไปด้วย
# default = ปิด (กันเผาเครดิต) — เปิดคืนภายหลังได้โดยตั้ง HUNTERS_ENABLED=1 บน Render ไม่ต้องแก้โค้ด ----
HUNTERS_ENABLED = os.environ.get("HUNTERS_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")
_HUNTERS_OFF_MSG = {"success": False, "disabled": True,
                    "error": "Hunter/autotrade ปิดชั่วคราว กันเผาเครดิต Claude — ตั้ง HUNTERS_ENABLED=1 บน Render เพื่อเปิดคืน"}
# ---- LINE OA ของ "ร้านลูกค้า" (เช่น @lullabell) — คนละตัวกับ LINE_TOKEN/LINE_CHANNEL_SECRET ด้านบนซึ่งเป็นของ ForexAI Pro เอง ----
LULLABELL_LINE_CHANNEL_SECRET = os.environ.get("LULLABELL_LINE_CHANNEL_SECRET", "")
LULLABELL_LINE_CHANNEL_TOKEN  = os.environ.get("LULLABELL_LINE_CHANNEL_TOKEN", "")
# ---- E-commerce admin proxy (แทน anon key ที่เคยฝังใน dashboard) ----
EC_ADMIN_PIN        = os.environ.get("EC_ADMIN_PIN", "")
# ========================

signal_history   = []  # in-memory สัญญาณ (เก็บ 20 ล่าสุด)
registered_users = []  # userId ที่ลงทะเบียนผ่าน /webhook — cache ในแรม + sync กับ Supabase (กันหายเวลา restart)


def _sb_ready() -> bool:
    return bool(seo_tracker.SUPABASE_URL and seo_tracker.SUPABASE_KEY)


def _sb_headers(extra: dict = None) -> dict:
    h = {"apikey": seo_tracker.SUPABASE_KEY,
         "Authorization": f"Bearer {seo_tracker.SUPABASE_KEY}",
         "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h


def _load_registered_users() -> None:
    """โหลด registered_users จาก Supabase ตอน boot — กัน list ว่างเปล่าหลัง Render restart"""
    if not _sb_ready():
        return
    try:
        r = requests.get(f"{seo_tracker.SUPABASE_URL}/rest/v1/registered_line_users?select=user_id",
                          headers=_sb_headers(), timeout=10)
        if r.ok:
            for row in r.json():
                uid = row.get("user_id")
                if uid and uid not in registered_users:
                    registered_users.append(uid)
            print(f"[api_server] โหลด registered_users จาก Supabase: {len(registered_users)} คน", flush=True)
    except Exception as e:
        print(f"[api_server] โหลด registered_users ล้มเหลว (ใช้ list ว่างไปก่อน): {e}", flush=True)


def _save_registered_user(user_id: str) -> None:
    """เขียนลง Supabase ทันทีที่มีคนลงทะเบียนใหม่ — best-effort ไม่บล็อกการตอบ LINE"""
    if not _sb_ready():
        return
    try:
        requests.post(f"{seo_tracker.SUPABASE_URL}/rest/v1/registered_line_users",
                      headers=_sb_headers({"Prefer": "resolution=ignore-duplicates,return=minimal"}),
                      json={"user_id": user_id}, timeout=8)
    except Exception as e:
        print(f"[api_server] บันทึก registered_user ลง Supabase ล้มเหลว: {e}", flush=True)


_load_registered_users()  # เรียกตอน import module — กู้ registered_users คืนหลัง restart

# ---- Visitor tracking (in-memory, รีเซ็ตเมื่อ restart) ----
visit_stats = {
    "total":       0,      # ครั้งทั้งหมดตั้งแต่ boot
    "today":       0,      # ครั้งของวันนี้ (UTC)
    "today_date":  "",     # วันที่ของ counter today
    "unique_ips":  set(),  # IP ไม่ซ้ำตั้งแต่ boot
    "last_visit":  "",     # เวลา visit ล่าสุด
}


def _track_visit():
    from datetime import timezone
    now   = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    if visit_stats["today_date"] != today:
        visit_stats["today_date"] = today
        visit_stats["today"] = 0
    visit_stats["total"] += 1
    visit_stats["today"] += 1
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0].strip()
    visit_stats["unique_ips"].add(ip)
    visit_stats["last_visit"] = now.strftime("%H:%M UTC")
    # บันทึกว่าคนนี้มาจากไหน — ใช้พิสูจน์ว่า SEO ทำงาน + ยิง LINE ตอนคนแรกมาจาก Google
    try:
        seo_tracker.log(request, push_fn=_push_line, line_user_id=LINE_USER_ID)
    except Exception as e:
        print(f"[SEO] log fail: {e}", flush=True)


# ---------- Price Helpers ----------

def fetch_forex(base: str, quote: str) -> dict:
    """ราคา Forex จาก frankfurter.app (ฟรี ไม่ต้อง key)"""
    r = requests.get(
        f"https://api.frankfurter.app/latest?from={base}&to={quote}", timeout=5
    )
    r.raise_for_status()
    d = r.json()
    price = d["rates"][quote]
    return {"price": price, "change_pct": 0.05, "base": base, "quote": quote}


def fetch_kraken(pair: str, result_key: str) -> dict:
    """ราคา Crypto จาก Kraken (ฟรีแท้ ไม่ต้อง key ไม่ block cloud)"""
    r = requests.get(
        f"https://api.kraken.com/0/public/Ticker?pair={pair}",
        timeout=10,
        headers={"Accept": "application/json"},
    )
    r.raise_for_status()
    d = r.json()
    if d.get("error"):
        raise Exception(f"Kraken error: {d['error']}")
    ticker     = d["result"][result_key]
    price      = float(ticker["c"][0])
    open_p     = float(ticker["o"])
    change_pct = ((price - open_p) / open_p) * 100 if open_p else 0.0
    volume     = float(ticker["v"][1])
    return {
        "price":      price,
        "change_pct": round(change_pct, 2),
        "high":       float(ticker["h"][1]),
        "low":        float(ticker["l"][1]),
        "volume":     volume,
    }


def fetch_btc() -> dict:
    return fetch_kraken("XBTUSD", "XXBTZUSD")


def fetch_eth() -> dict:
    return fetch_kraken("ETHUSD", "XETHZUSD")


# ---------- AI Analysis ----------

def analyze_with_ai(pair: str, price_data: dict) -> dict:
    client    = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    price_str = json.dumps(price_data, ensure_ascii=False, indent=2)
    prompt = f"""คุณเป็น AI วิเคราะห์ Forex และ Crypto มืออาชีพระดับ Institutional Trader

ข้อมูลตลาดปัจจุบัน ({pair}):
{price_str}

วิเคราะห์สถานการณ์ตลาดอย่างละเอียด แล้วให้สัญญาณการเทรด
ตอบเป็น JSON เท่านั้น (ไม่ต้องมีข้อความอื่น):
{{
  "signal": "BUY" หรือ "SELL" หรือ "HOLD",
  "confidence": ตัวเลข 0-100,
  "entry_price": ราคาเข้าที่แนะนำ (ตัวเลข),
  "stop_loss": ราคา stop loss (ตัวเลข),
  "take_profit": ราคา take profit (ตัวเลข),
  "risk_level": "LOW" หรือ "MEDIUM" หรือ "HIGH",
  "reasoning": "อธิบายเหตุผล 2-3 ประโยคภาษาไทย",
  "key_factors": ["ปัจจัย 1", "ปัจจัย 2", "ปัจจัย 3"],
  "market_sentiment": "BULLISH" หรือ "BEARISH" หรือ "NEUTRAL"
}}"""

    # ผ่าน ai_guard → AI ตายเมื่อไหร่ เด้ง LINE ทันที ไม่ตายเงียบอีก
    # slug="forex" กันการแจ้งเตือน/cooldown ชนกับบอทลูกค้าเจ้าอื่น (เช่น Lullabell)
    text = ai_guard.call(client, prompt, max_tokens=600, smart=True,
                         notify_fn=_push_line, line_user_id=LINE_USER_ID, slug="forex")
    s, e = text.find("{"), text.rfind("}") + 1
    return json.loads(text[s:e])


# ---------- LINE Helpers ----------

def _build_signal_message(sig: dict) -> str:
    emoji   = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(sig.get("signal", ""), "⚪")
    sent_th = {
        "BULLISH": "กระทิง 📈",
        "BEARISH": "หมี 📉",
        "NEUTRAL": "ทรงตัว ➡️",
    }.get(sig.get("market_sentiment", ""), "")
    factors = "\n".join(f"  • {f}" for f in sig.get("key_factors", []))
    return (
        f"{emoji} ForexAI Pro — Signal Alert\n\n"
        f"📊 คู่: {sig.get('pair','')}  |  ⚡ {sig.get('signal','')}\n"
        f"🎯 ความมั่นใจ: {sig.get('confidence','')}%  |  ⚠️ ความเสี่ยง: {sig.get('risk_level','')}\n"
        f"📈 Sentiment: {sent_th}\n\n"
        f"💰 Entry:        {sig.get('entry_price','')}\n"
        f"🛑 Stop Loss:  {sig.get('stop_loss','')}\n"
        f"✅ Take Profit:  {sig.get('take_profit','')}\n\n"
        f"🔑 ปัจจัยหลัก:\n{factors}\n\n"
        f"💡 {sig.get('reasoning','')}\n\n"
        f"🤖 Analyzed by Claude AI  |  ⏰ {sig.get('timestamp','')}\n"
        f"━━━━━━━━━━━━━━━━━"
    )


def _push_line(user_id: str, text: str) -> bool:
    """Push message ไปยัง user_id"""
    if not LINE_TOKEN or not user_id:
        return False
    r = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={
            "Authorization": f"Bearer {LINE_TOKEN}",
            "Content-Type":  "application/json",
        },
        json={"to": user_id, "messages": [{"type": "text", "text": text}]},
        timeout=10,
    )
    return r.status_code == 200


def _reply_line(reply_token: str, text: str):
    """ตอบกลับผ่าน reply token"""
    if not reply_token or not LINE_TOKEN:
        return
    try:
        requests.post(
            "https://api.line.me/v2/bot/message/reply",
            headers={
                "Authorization": f"Bearer {LINE_TOKEN}",
                "Content-Type":  "application/json",
            },
            json={"replyToken": reply_token, "messages": [{"type": "text", "text": text}]},
            timeout=10,
        )
    except Exception as e:
        print(f"[WARN] Reply failed: {e}", flush=True)


# ---------- API Routes ----------

@app.route("/api/prices", methods=["GET"])
def get_all_prices():
    """ดึงราคาทั้งหมดในครั้งเดียว"""
    try:
        data = {
            "EURUSD":    fetch_forex("EUR", "USD"),
            "GBPUSD":    fetch_forex("GBP", "USD"),
            "USDJPY":    fetch_forex("USD", "JPY"),
            "BTCUSD":    fetch_btc(),
            "ETHUSD":    fetch_eth(),
            "timestamp": datetime.now().strftime("%H:%M:%S"),
        }
        return jsonify({"success": True, "data": data})
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[ERROR] /api/prices: {e}\n{tb}", flush=True)
        return jsonify({"success": False, "error": str(e), "traceback": tb}), 500


@app.route("/api/analyze", methods=["POST"])
def analyze():
    """
    วิเคราะห์ด้วย AI
    ⚠️ endpoint นี้เปิดสาธารณะ = ทุกครั้งที่ถูกเรียก เราจ่ายเงิน
       ต้องมี rate limit เสมอ ไม่งั้นคนเดียวยิงรัวคืนเดียวเงินหมด
    """
    body       = request.get_json()
    pair       = body.get("pair", "EURUSD")
    price_data = body.get("price_data", {})

    if not ANTHROPIC_API_KEY:
        return jsonify({"success": False, "error": "ไม่ได้ตั้ง ANTHROPIC_API_KEY"}), 400

    ok, left = ai_guard.rate_limit(ai_guard.client_ip(request),
                                   limit=int(os.environ.get("ANALYZE_LIMIT", "5")))
    if not ok:
        return jsonify({
            "success": False,
            "error": "วันนี้วิเคราะห์ครบโควตาแล้วครับ (5 ครั้ง/วัน) — พรุ่งนี้มาใหม่ได้เลย 😊 "
                     "อยากใช้แบบไม่จำกัด ทักมาคุยได้ครับ",
            "rate_limited": True,
        }), 429

    try:
        result              = analyze_with_ai(pair, price_data)
        result["quota_left"] = left
        result["pair"]      = pair
        result["timestamp"] = datetime.now().strftime("%H:%M:%S")

        signal_history.insert(0, result.copy())
        if len(signal_history) > 20:
            signal_history.pop()

        return jsonify({"success": True, "signal": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/history", methods=["GET"])
def get_history():
    return jsonify({"success": True, "history": signal_history[:10]})


@app.route("/api/send-line", methods=["POST"])
def send_line():
    """Broadcast Signal ไปยังทุก LINE userId ที่ลงทะเบียน"""
    # รวบรวม targets: env var + registered users
    targets: list[str] = []
    if LINE_USER_ID and LINE_USER_ID not in targets:
        targets.append(LINE_USER_ID)
    for uid in registered_users:
        if uid not in targets:
            targets.append(uid)

    if not targets:
        return jsonify({
            "success": False,
            "error":   "ไม่มี LINE User ID — Add OA แล้วพิมพ์ /start ก่อน",
        }), 400

    if not LINE_TOKEN:
        return jsonify({"success": False, "error": "ไม่ได้ตั้ง LINE_TOKEN"}), 400

    sig     = request.get_json().get("signal", {})
    msg     = _build_signal_message(sig)
    results = [{"uid": uid[:8] + "...", "ok": _push_line(uid, msg)} for uid in targets]
    ok_cnt  = sum(1 for r in results if r["ok"])

    return jsonify({
        "success": ok_cnt > 0,
        "sent":    ok_cnt,
        "total":   len(targets),
        "results": results,
    })


@app.route("/webhook", methods=["POST"])
def line_webhook():
    """LINE Webhook — auto-register userId เมื่อ follow หรือพิมพ์ /start"""
    body_bytes = request.get_data()
    body_str   = body_bytes.decode("utf-8")

    # ตรวจ signature (ถ้าตั้ง LINE_CHANNEL_SECRET)
    if LINE_CHANNEL_SECRET:
        sig      = request.headers.get("X-Line-Signature", "")
        digest   = hmac.new(
            LINE_CHANNEL_SECRET.encode("utf-8"), body_bytes, hashlib.sha256
        ).digest()
        expected = base64.b64encode(digest).decode()
        if sig != expected:
            return jsonify({"message": "invalid signature"}), 400

    try:
        events = json.loads(body_str).get("events", [])
    except Exception:
        return jsonify({"message": "bad json"}), 400

    for ev in events:
        user_id     = ev.get("source", {}).get("userId", "")
        etype       = ev.get("type", "")
        reply_token = ev.get("replyToken", "")
        already_reg = (user_id == LINE_USER_ID) or (user_id in registered_users)

        if etype == "follow":
            # ผู้ใช้ Add OA → register อัตโนมัติ
            if user_id and not already_reg:
                registered_users.append(user_id)
                _save_registered_user(user_id)
            _reply_line(
                reply_token,
                "⚡ ยินดีต้อนรับสู่ ForexAI Pro!\n\n"
                "✅ ลงทะเบียนสำเร็จ!\n\n"
                "📊 คุณจะได้รับสัญญาณเทรด EUR/USD, GBP/USD, BTC/USD\n"
                "จากระบบ AI วิเคราะห์อัตโนมัติ\n\n"
                "💡 กด 'ส่ง LINE' ในหน้า Dashboard เพื่อรับสัญญาณ",
            )

        elif etype == "message":
            msg_text = ev.get("message", {}).get("text", "").strip().lower()
            if msg_text in ["/start", "start", "/register", "register", "เริ่ม", "สมัคร"]:
                if user_id and not already_reg:
                    registered_users.append(user_id)
                    _save_registered_user(user_id)
                    _reply_line(
                        reply_token,
                        "✅ ลงทะเบียนสำเร็จ!\n\n"
                        "📱 คุณจะได้รับ ForexAI Signal แจ้งเตือนอัตโนมัติ\n\n"
                        "💡 แจ้งทีมงานว่าพร้อมรับสัญญาณแล้ว",
                    )
                elif already_reg:
                    _reply_line(reply_token, "✅ คุณลงทะเบียนแล้ว — รอรับสัญญาณได้เลย!")
            else:
                _reply_line(
                    reply_token,
                    "🤖 ForexAI Pro\n\n"
                    "พิมพ์ /start เพื่อลงทะเบียนรับสัญญาณ",
                )

    return jsonify({"message": "ok"})


@app.route("/api/line-users", methods=["GET"])
def get_line_users():
    """จำนวน LINE users ที่จะได้รับ Signal"""
    env_count = 1 if (LINE_USER_ID and LINE_USER_ID not in registered_users) else 0
    total     = len(registered_users) + env_count
    return jsonify({
        "success":       True,
        "registered":    len(registered_users),
        "total_targets": total,
    })


@app.route("/api/health")
def health():
    return jsonify({
        "status":              "ok",
        "anthropic_key":       bool(ANTHROPIC_API_KEY),
        "line_token":          bool(LINE_TOKEN),
        "line_user_id":        bool(LINE_USER_ID),
        "line_channel_secret": bool(LINE_CHANNEL_SECRET),
        "lullabell_line_ready": bool(LULLABELL_LINE_CHANNEL_SECRET and LULLABELL_LINE_CHANNEL_TOKEN),
        "registered_users":    len(registered_users),
        "signal_count":        len(signal_history),
        "hunter_log_count":    len(fastwork_hunter.get_hunter_log()),
    })


# ---------- FastWork Job Hunter ----------

@app.route("/api/hunter/check", methods=["GET", "POST"])
def hunter_check():
    """ดักจับงาน FastWork ที่ตรงสกิล → AI วิเคราะห์ + ร่างข้อเสนอ → LINE
    เรียกจาก cron ภายนอก (cron-job.org) ทุก 30 นาที"""
    if not HUNTERS_ENABLED:
        return jsonify(_HUNTERS_OFF_MSG), 200   # ปิดกันเผาเครดิต Claude (21 ก.ค. 2026)
    if not ANTHROPIC_API_KEY or not LINE_TOKEN or not LINE_USER_ID:
        return jsonify({"success": False, "error": "missing env keys"}), 500
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        result = fastwork_hunter.run_hunter(client, _push_line, LINE_USER_ID)
        _save_hunter_status(result)   # เก็บสถานะล่าสุดลง Supabase (โชว์บน Monitor)
        return jsonify({"success": True, **result})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


def _save_hunter_status(result: dict) -> None:
    """บันทึกสรุปการสแกนล่าสุดลง Supabase (persist ข้าม redeploy)"""
    if not (seo_tracker.SUPABASE_URL and seo_tracker.SUPABASE_KEY):
        return
    from datetime import timezone
    try:
        requests.patch(
            f"{seo_tracker.SUPABASE_URL}/rest/v1/hunter_status?id=eq.1",
            headers={"apikey": seo_tracker.SUPABASE_KEY,
                     "Authorization": f"Bearer {seo_tracker.SUPABASE_KEY}",
                     "Content-Type": "application/json", "Prefer": "return=minimal"},
            json={"last_check": datetime.now(timezone.utc).isoformat(),
                  "checked":      result.get("checked", 0),
                  "new_matching": result.get("new_matching", 0),
                  "triaged_out":  result.get("triaged_out", 0),
                  "analyzed":     result.get("analyzed", 0),
                  "alerts_sent":  result.get("alerts_sent", 0)},
            timeout=10)
    except Exception:
        pass  # เก็บสถานะพลาดไม่ควรทำให้ Hunter ล้ม


@app.route("/api/hunter/status", methods=["GET"])
def hunter_status():
    """สถานะ Hunter ล่าสุด (สำหรับการ์ดบน Monitor) — อ่านจาก Supabase"""
    try:
        r = requests.get(
            f"{seo_tracker.SUPABASE_URL}/rest/v1/hunter_status?id=eq.1&select=*",
            headers={"apikey": seo_tracker.SUPABASE_KEY,
                     "Authorization": f"Bearer {seo_tracker.SUPABASE_KEY}"},
            timeout=10)
        rows = r.json() if r.ok else []
        st = rows[0] if rows else {}
    except Exception:
        st = {}
    return jsonify({"success": True, **st})


@app.route("/api/hunter/log", methods=["GET"])
def hunter_log():
    """ประวัติงานที่ตรวจล่าสุด (FastWork + RSS รวมกัน)"""
    log = fastwork_hunter.get_hunter_log() + rss_hunter.get_log()
    log.sort(key=lambda e: e.get("time", ""), reverse=True)
    return jsonify({"success": True, "log": log[:20]})


@app.route("/api/hunter/rss", methods=["GET", "POST"])
def hunter_rss():
    """ดักงานจากทั้งเน็ตผ่าน Google Alerts RSS (cron ยิงทุก 30 นาที)"""
    if not HUNTERS_ENABLED:
        return jsonify(_HUNTERS_OFF_MSG), 200   # ปิดกันเผาเครดิต Claude (21 ก.ค. 2026)
    if not rss_hunter.is_configured():
        return jsonify({"success": False, "error": "ยังไม่ได้ตั้ง RSS_FEEDS"}), 503
    if not ANTHROPIC_API_KEY or not LINE_TOKEN or not LINE_USER_ID:
        return jsonify({"success": False, "error": "missing env keys"}), 500
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        return jsonify(rss_hunter.run(client, _push_line, LINE_USER_ID))
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/stats", methods=["GET"])
def get_stats():
    """สถิติรวมสำหรับ Desktop Widget"""
    return jsonify({
        "success":          True,
        "visits_total":     visit_stats["total"],
        "visits_today":     visit_stats["today"],
        "unique_visitors":  len(visit_stats["unique_ips"]),
        "last_visit":       visit_stats["last_visit"],
        "line_users":       len(registered_users) + (1 if LINE_USER_ID else 0),
        "signal_count":     len(signal_history),
        "hunter_checked":   len(fastwork_hunter.get_hunter_log()),
        "hunter_alerts":    sum(1 for e in fastwork_hunter.get_hunter_log() if e.get("alerted")),
    })


@app.route("/api/roadmap", methods=["GET"])
def get_roadmap():
    """แผนงานระยะสั้น-กลาง-ยาว (โชว์ใน NEXUS Monitor)"""
    try:
        p = os.path.join(os.path.dirname(__file__), "roadmap.json")
        with open(p, "r", encoding="utf-8") as f:
            return jsonify({"success": True, **json.load(f)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 404


@app.route("/api/status", methods=["GET"])
def get_status_card():
    """การ์ดสถานะงาน (Garuda สร้าง data → SiriAriyaMate render)"""
    try:
        p = os.path.join(os.path.dirname(__file__), "status_card_data.json")
        with open(p, "r", encoding="utf-8") as f:
            return jsonify({"success": True, **json.load(f)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 404


@app.route("/hunter")
def hunter_tracker():
    """Reverse Hunter — ตัวช่วยหาร้าน + จดร้านที่ทัก + สคริปต์ (เครื่องมือภายใน)"""
    p = os.path.join(os.path.dirname(__file__), "hunter_tracker.html")
    with open(p, "r", encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/monitor")
def monitor():
    """NEXUS Monitor — Dashboard สำหรับแท็บเล็ต/มือถือ (PWA)"""
    html_path = os.path.join(os.path.dirname(__file__), "monitor.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/pitch/chef")
def pitch_chef():
    """Demo พรีเซนต์ลูกค้า AI Executive Assistant (Chef/Restaurant) — เปิดได้ทั้ง PC/แท็บเล็ต"""
    html_path = os.path.join(os.path.dirname(__file__), "pitch_chef.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/pitch/chef/notes")
def pitch_chef_notes():
    """Cheat sheet มือถือ/แท็บเล็ต คู่กับ /pitch/chef สำหรับดูระหว่างพรีเซนต์สด"""
    html_path = os.path.join(os.path.dirname(__file__), "pitch_chef_notes.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/manifest.json")
def manifest():
    return jsonify({
        "name": "NEXUS Monitor",
        "short_name": "NEXUS",
        "start_url": "/monitor",
        "display": "standalone",
        "background_color": "#060a16",
        "theme_color": "#060a16",
        "icons": [{
            "src": "https://storage.googleapis.com/fastwork-asset/web/images/logo/fastwork/v2/default.svg",
            "sizes": "any", "type": "image/svg+xml"
        }],
    })


def _load_demo_configs() -> dict:
    p = os.path.join(os.path.dirname(__file__), "demo_configs.json")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _render_demo(biz: str) -> str:
    """สร้างหน้า demo จาก template เดียว + config ของแต่ละธุรกิจ"""
    cfg = _load_demo_configs()[biz]
    # แปลง services list → map ที่ frontend ใช้
    cfg["services_map"] = {
        s["name"]: {"emoji": s["emoji"], "price": s["price"], "bg": s["bg"]}
        for s in cfg["services"]
    }
    tpl_path = os.path.join(os.path.dirname(__file__), "demo_generic.html")
    with open(tpl_path, "r", encoding="utf-8") as f:
        html = f.read()
    return (html
            .replace("__CONFIG_JSON__", json.dumps(cfg, ensure_ascii=False))
            .replace("__BIZ_NAME__", cfg["biz_name"])
            .replace("__EMOJI__", cfg["emoji"])
            .replace("__TAGLINE__", cfg["tagline"]))


@app.route("/demo/dialysis")
def demo_dialysis():
    """Demo ระบบบันทึกฟอกไต — flow ต่างจาก demo อื่น (พยาบาลบันทึก ไม่ใช่ลูกค้าจอง)"""
    _track_visit()
    p = os.path.join(os.path.dirname(__file__), "demo_dialysis.html")
    with open(p, "r", encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}


# ---------- Dialysis API (ต่อ Supabase จริง) ----------

def _pin_ok() -> bool:
    """ตรวจรหัสศูนย์จาก header — กันคนนอกเข้าถึงข้อมูลคนไข้"""
    if not dialysis_api.CENTER_PIN:
        return True  # ยังไม่ตั้งรหัส = โหมดเปิด (ต้องตั้งก่อนใช้จริง)
    return request.headers.get("X-Center-Pin", "") == dialysis_api.CENTER_PIN


def _need_pin():
    return jsonify({"success": False, "error": "unauthorized", "need_pin": True}), 401


@app.route("/api/dialysis/config", methods=["GET"])
def dialysis_config():
    """บอก frontend ว่าต่อ DB ได้ไหม + ต้องใส่รหัสไหม + ค่าคงที่ของศูนย์"""
    return jsonify({
        "success": True,
        "db_connected": dialysis_api.is_configured(),
        "pin_required": bool(dialysis_api.CENTER_PIN),
        "filters": dialysis_api.FILTERS,
        "cutoff_pct": dialysis_api.CUTOFF_PCT,
        "max_reuse": dialysis_api.MAX_REUSE,
    })


@app.route("/api/dialysis/login", methods=["POST"])
def dialysis_login():
    """ตรวจรหัสศูนย์ + ชื่อผู้บันทึก"""
    d = request.get_json(force=True) or {}
    pin = str(d.get("pin", ""))
    nurse = str(d.get("nurse", "")).strip()
    if not nurse:
        return jsonify({"success": False, "error": "กรุณาระบุชื่อผู้บันทึก"}), 400
    if dialysis_api.CENTER_PIN and pin != dialysis_api.CENTER_PIN:
        return jsonify({"success": False, "error": "รหัสไม่ถูกต้อง"}), 401
    return jsonify({"success": True, "nurse": nurse[:60]})


@app.route("/api/dialysis/patients", methods=["GET"])
def dialysis_patients():
    if not _pin_ok():
        return _need_pin()
    if not dialysis_api.is_configured():
        return jsonify({"success": False, "error": "ยังไม่ได้ตั้งค่า Supabase"}), 503
    try:
        return jsonify({"success": True, "patients": dialysis_api.list_patients()})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/dialysis/patients", methods=["POST"])
def dialysis_create_patient():
    if not _pin_ok():
        return _need_pin()
    if not dialysis_api.is_configured():
        return jsonify({"success": False, "error": "ยังไม่ได้ตั้งค่า Supabase"}), 503
    try:
        d = request.get_json(force=True) or {}
        p = dialysis_api.create_patient(
            name=d.get("name", ""), hn=d.get("hn", ""),
            schedule=d.get("schedule", ""), note=d.get("note", ""),
        )
        return jsonify({"success": True, "patient": p})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/dialysis/patients/<patient_id>", methods=["PATCH"])
def dialysis_update_patient(patient_id):
    """แก้วันฟอกไตคนไข้เดิม (ก่อนหน้านี้ตั้งได้แค่ตอนสร้างคนไข้ใหม่)"""
    if not _pin_ok():
        return _need_pin()
    if not dialysis_api.is_configured():
        return jsonify({"success": False, "error": "ยังไม่ได้ตั้งค่า Supabase"}), 503
    try:
        d = request.get_json(force=True) or {}
        p = dialysis_api.update_patient_schedule(patient_id, d.get("schedule", ""))
        return jsonify({"success": True, "patient": p})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/dialysis/visits", methods=["POST"])
def dialysis_save_visit():
    if not _pin_ok():
        return _need_pin()
    if not dialysis_api.is_configured():
        return jsonify({"success": False, "error": "ยังไม่ได้ตั้งค่า Supabase"}), 503
    try:
        saved = dialysis_api.save_visit(request.get_json(force=True) or {})
        return jsonify({"success": True, "visit": saved})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/dialysis/visits", methods=["GET"])
def dialysis_recent_visits():
    if not _pin_ok():
        return _need_pin()
    if not dialysis_api.is_configured():
        return jsonify({"success": False, "error": "ยังไม่ได้ตั้งค่า Supabase"}), 503
    try:
        return jsonify({"success": True, "visits": dialysis_api.recent_visits()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/dialysis/tomorrow", methods=["GET"])
def dialysis_tomorrow():
    """พรุ่งนี้ใครมาบ้าง"""
    if not dialysis_api.is_configured():
        return jsonify({"success": False, "error": "ยังไม่ได้ตั้งค่า Supabase"}), 503
    try:
        return jsonify({"success": True, "patients": dialysis_api.tomorrow_list()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/demo/<biz>")
def demo_by_biz(biz):
    """Demo ตามประเภทธุรกิจ: /demo/beauty /demo/clinic /demo/restaurant /demo/spa"""
    _track_visit()
    try:
        return _render_demo(biz), 200, {"Content-Type": "text/html; charset=utf-8"}
    except KeyError:
        avail = ", ".join(_load_demo_configs().keys())
        return f"ไม่พบ demo '{biz}' — ที่มี: {avail}", 404
    except Exception as e:
        traceback.print_exc()
        return f"error: {e}", 500


botkit_orders = []  # cache ในแรม — source of truth จริงคือ Supabase table botkit_orders (กันหายเวลา restart)


def _save_botkit_order(order: dict) -> None:
    """เขียน order ลง Supabase ทันที — best-effort ไม่บล็อกการแจ้ง LINE"""
    if not _sb_ready():
        return
    try:
        requests.post(f"{seo_tracker.SUPABASE_URL}/rest/v1/botkit_orders",
                      headers=_sb_headers({"Prefer": "return=minimal"}),
                      json={k: order.get(k) for k in
                            ("source", "shop_name", "biz_type", "contact_name",
                             "contact", "plan", "page", "need", "status")},
                      timeout=8)
    except Exception as e:
        print(f"[api_server] บันทึก botkit_order ลง Supabase ล้มเหลว: {e}", flush=True)


def _load_botkit_orders(limit: int = 10) -> list:
    """อ่าน order ล่าสุดจาก Supabase (source of truth) — ถ้า Supabase ใช้ไม่ได้ fallback ไป list ในแรม"""
    if _sb_ready():
        try:
            r = requests.get(
                f"{seo_tracker.SUPABASE_URL}/rest/v1/botkit_orders"
                f"?select=*&order=created_at.desc&limit={limit}",
                headers=_sb_headers(), timeout=10)
            if r.ok:
                return r.json()
        except Exception as e:
            print(f"[api_server] อ่าน botkit_orders จาก Supabase ล้มเหลว, ใช้ cache ในแรมแทน: {e}", flush=True)
    return botkit_orders[:limit]


def _count_botkit_orders_new() -> int:
    if _sb_ready():
        try:
            r = requests.get(
                f"{seo_tracker.SUPABASE_URL}/rest/v1/botkit_orders?select=id&status=eq.new",
                headers=_sb_headers({"Prefer": "count=exact"}), timeout=10)
            if r.ok:
                return int(r.headers.get("Content-Range", "0").split("/")[-1] or 0)
        except Exception as e:
            print(f"[api_server] นับ botkit_orders ใหม่จาก Supabase ล้มเหลว, ใช้ cache ในแรมแทน: {e}", flush=True)
    return len([o for o in botkit_orders if o.get("status") == "new"])

BIZ_LABEL = {
    "beauty": "ร้านเสริมสวย", "clinic": "คลินิกความงาม",
    "spa": "สปา/นวด", "restaurant": "ร้านอาหาร",
    "booking": "ธุรกิจที่ต้องจองคิว/นัดหมาย",
    "general": "ธุรกิจทั่วไป / LINE Bot ตอบแชท",
    "automation": "n8n Automation / AI Agent",
    "other": "อื่นๆ",
}

SRC_LABEL = {
    "google": "🔍 Google (SEO ทำงาน!)", "bing": "🔎 Bing (SEO ทำงาน!)",
    "facebook": "📘 Facebook", "line": "💬 LINE", "x": "✕ X",
    "fastwork": "💼 FastWork", "direct": "🔗 พิมพ์ลิงก์ตรง", "other": "🌐 อื่นๆ",
}


BASE_URL = "https://forex-ai-demo.onrender.com"

# หน้า landing ตามคำค้นหา (SEO) — เนื้อหาต่างกัน แต่ชี้มาที่ /botkit
SEO_PAGES = {
    "line-bot": {
        "h1": "รับทำ LINE Bot สำหรับธุรกิจ",
        "title": "รับทำ LINE Bot ราคาเริ่ม ฿590/เดือน | ตอบแชท + จองคิวอัตโนมัติ",
        "desc": "รับทำ LINE Bot / LINE OA สำหรับร้านค้า คลินิก ร้านอาหาร ตอบแชทอัตโนมัติ 24 ชม. รับจองคิว แจ้งเตือนเข้า LINE ลองฟรีก่อนตัดสินใจ",
        "kw": "รับทำ line bot, line oa, line messaging api, บอทไลน์, ไลน์บอทร้านค้า",
        "lead": "ให้ LINE ของร้านตอบลูกค้าเองได้ 24 ชม. — ถามราคา ดูบริการ จองคิว ครบจบในแชท",
        "points": [
            "ตอบแชทอัตโนมัติทันที ไม่ต้องมีคนเฝ้า",
            "รับจองคิว เก็บชื่อ-เบอร์-เวลา ส่งให้แอดมิน",
            "Rich Menu + Flex Message สวยงาม",
            "เชื่อม LINE OA ที่มีอยู่แล้วได้เลย",
        ],
        "sections": [
            {
                "h2": "😩 ทำไมเพจ/LINE ของธุรกิจถึงตอบแชทไม่ทัน",
                "body": """
<p><strong>คนเดียวทำทุกอย่าง</strong> — เจ้าของร้านต้องขาย ต้องผลิต ต้องส่งของ
มือถือเด้งแจ้งเตือนทั้งวัน กว่าจะเปิดอ่านอีกที ลูกค้าถามไปหลายเจ้าแล้วเลือกเจ้าที่ตอบก่อน</p>

<p><strong>คำถามซ้ำเดิมทุกวัน</strong> — "ราคาเท่าไหร่", "มีของไหม", "ส่งยังไง", "เปิดกี่โมง"
วันนึงพิมพ์คำตอบเดิมเป็นสิบรอบ เสียเวลาที่ควรเอาไปโฟกัสงานจริง</p>

<p><strong>ทักตอนดึก ตอบตอนเช้า</strong> — พฤติกรรมคนไทยส่วนใหญ่ทักถามตอนกลางคืน
ก่อนนอน แต่ร้านนอนไปแล้ว พอตื่นมาตอบ ลูกค้าเปลี่ยนใจไปที่อื่นแล้วครึ่งนึง</p>

<div class="note">💡 LINE Bot ไม่ได้มาแทนคน — มันมาตอบแทนตอนที่คนตอบไม่ทัน
แล้วส่งต่อเคสที่ต้องคุยจริงจังให้เจ้าของร้านทันที</div>
""",
            },
            {
                "h2": "🤖 LINE Bot ของเราต่างจากบอทตอบอัตโนมัติทั่วไปยังไง",
                "body": """
<p><strong>ไม่ใช่แค่ auto-reply</strong> — บอททั่วไปตอบข้อความคีย์เวิร์ดตายตัว
แต่บอทของเราเข้าใจสิ่งที่ลูกค้าพิมพ์แบบธรรมชาติ ถามเป็นประโยคก็ยังตอบตรงประเด็นได้</p>

<p><strong>เก็บข้อมูลลูกค้าให้ครบ</strong> — จองคิว สั่งของ สอบถาม ทุกอย่างถูกบันทึกเป็นระเบียบ
ไม่ใช่แชทกระจัดกระจายที่ตามหาทีหลังไม่เจอ</p>

<p><strong>Rich Menu ใช้งานง่าย</strong> — ลูกค้าเปิดแชทมาเจอเมนูปุ่มกดสวยงาม
กดดูราคา กดจองคิว กดดูที่อยู่ ได้เลยโดยไม่ต้องพิมพ์อะไร</p>
""",
            },
            {
                "h2": "🛠 เริ่มใช้งานยังไง",
                "body": """
<p>ไม่ต้องมีความรู้เทคนิคเลยครับ ระบบรันฝั่งเรา ร้านแค่ใช้ LINE OA ตามปกติ</p>
<p><strong>เตรียมแค่:</strong> LINE OA ของร้าน (ไม่มีสมัครฟรีได้), ข้อมูลสินค้า/บริการ + ราคา,
คำถามที่ลูกค้าถามบ่อยที่สุด 5-10 ข้อ</p>
<p><strong>ขั้นตอน:</strong> ส่งข้อมูลมา → ตั้งค่าให้ 2-3 วัน → ทดลองก่อนเปิดใช้จริง</p>
""",
            },
        ],
        "chat": [
            ("n", "23:10 น. — เจ้าของร้านนอนแล้ว"),
            ("u", "สวัสดีครับ สนใจสินค้าตัวนี้ครับ มีของไหม"),
            ("b", "สวัสดีค่ะ 😊 ตอนนี้มีของพร้อมส่งค่ะ<br>"
                  "ราคา 590 บาท ส่งฟรีเมื่อซื้อครบ 1,000 บาทค่ะ"),
            ("u", "สั่งได้เลยไหมครับ"),
            ("b", "ได้เลยค่ะ 🛍️ ขอชื่อ ที่อยู่ และเบอร์โทรหน่อยนะคะ"),
            ("u", "สมชาย 08x-xxx-xxxx กรุงเทพฯ ครับ"),
            ("b", "รับออเดอร์เรียบร้อยค่ะ ✅<br>คุณสมชาย · 1 ชิ้น · 590฿<br>"
                  "แอดมินจะทักยืนยันและแจ้งเลขพัสดุอีกทีนะคะ ขอบคุณค่ะ 🙏"),
            ("n", "⚡ LINE เจ้าของร้านเด้งแจ้งเตือนทันที"),
            ("b", "🔔 มีออเดอร์ใหม่!<br>คุณสมชาย · 590฿ · 08x-xxx-xxxx"),
            ("n", "เช้าวันถัดมา เจ้าของร้านเปิดมาเจอออเดอร์รอแล้ว 📦"),
        ],
        "plans": [
            ("Starter", "฿590", "ตอบแชทอัตโนมัติ + ส่งข้อมูลสินค้า/บริการ"),
            ("Pro ⭐", "฿1,290", "เพิ่มรับจองคิว/รับออเดอร์ (นิยมสุด)"),
            ("Business", "฿2,900", "หลายทีม/หลายสาขา แยกการจัดการได้"),
        ],
        "faq": [
            ("ต้องมี LINE OA มาก่อนไหม",
             "ไม่จำเป็นครับ ถ้ายังไม่มีเราสอนสมัครให้ฟรีใช้เวลา 10 นาที "
             "ถ้ามีอยู่แล้วก็เชื่อมของเดิมได้เลย ไม่ต้องเปลี่ยนไลน์ใหม่"),
            ("บอทตอบผิดจะแก้ยังไง",
             "แจ้งเรามาได้ตลอดครับ ปกติแก้ให้ภายในวันเดียวกัน ไม่มีค่าใช้จ่ายเพิ่ม"),
            ("เหมาะกับธุรกิจแบบไหน",
             "เหมาะกับร้านค้า/บริการที่มีคำถามซ้ำๆ เยอะ เช่น ราคา สต็อก เวลาเปิด-ปิด "
             "ไม่ว่าจะขายของ รับจองคิว หรือให้บริการก็ปรับให้ตรงกับธุรกิจได้"),
            ("ราคาเริ่มต้นเท่าไหร่ มีค่าติดตั้งไหม",
             "เริ่ม ฿590/เดือน ไม่มีค่าติดตั้ง ไม่มีสัญญาผูกมัด ยกเลิกได้ทุกเมื่อ"),
            ("ใช้เวลาติดตั้งกี่วัน",
             "ปกติ 2-3 วัน นับจากวันที่ส่งข้อมูลสินค้า/บริการมาให้ครบ"),
            ("มีค่าใช้จ่ายเพิ่มจาก LINE ไหม",
             "LINE OA มีโควตาข้อความฟรี 300 ข้อความ/เดือน เพียงพอสำหรับร้านทั่วไป "
             "ถ้าเกินจะมีค่าใช้จ่ายฝั่ง LINE เอง เราแจ้งให้ทราบล่วงหน้าเสมอ"),
            ("ขอทดลองก่อนได้ไหม",
             "ได้เลยครับ กดดูตัวอย่างระบบจริงด้านบนได้เลย ไม่ต้องสมัคร ไม่ต้องให้เบอร์"),
        ],
    },
    "bot-jongkiw": {
        "h1": "รับทำระบบจองคิวออนไลน์",
        "title": "รับทำระบบจองคิวออนไลน์ ผ่าน LINE/Facebook | เริ่ม ฿590/เดือน",
        "desc": "ระบบจองคิวอัตโนมัติผ่านแชท ลูกค้าจองเองได้ 24 ชม. เก็บข้อมูลครบ แจ้งเตือนแอดมินทันที เหมาะกับร้านเสริมสวย คลินิก สปา",
        "kw": "ระบบจองคิว, จองคิวออนไลน์, ระบบนัดหมาย, booking system, จองคิวผ่านไลน์",
        "lead": "ลูกค้าจองคิวเองได้ตลอด 24 ชม. — ไม่มีคิวหลุด ไม่ต้องนั่งเฝ้าแชท",
        "points": [
            "ลูกค้าเลือกบริการ-วัน-เวลาเองในแชท",
            "เก็บชื่อ เบอร์ บริการ อัตโนมัติ",
            "แจ้งเตือนเจ้าของร้านทันทีที่มีคนจอง",
            "ดูคิวทั้งหมดในหน้าเดียว",
        ],
        "sections": [
            {
                "h2": "😩 ปัญหาของระบบจองคิวแบบเดิม",
                "body": """
<p><strong>โทรจอง แต่สายไม่ว่าง</strong> — ช่วงพีคคนโทรเข้ามาพร้อมกัน รับสายไม่ทัน
ลูกค้าโทรไม่ติดก็โทรหาที่อื่นแทน เสียคิวไปฟรีๆ</p>

<p><strong>จดคิวมือ คิวชนกัน</strong> — จดในสมุดหรือแชทกระจัดกระจาย
บางทีลืมจด บางทีจดผิดเวลา สุดท้ายคิวชนกัน ลูกค้าคนนึงต้องรอ</p>

<p><strong>ลูกค้าลืมว่าจองไว้</strong> — จองแล้วไม่มีการเตือน พอถึงวันนัดไม่มา
เก้าอี้ว่าง เวลาที่ควรได้ลูกค้าคนอื่นก็เสียไปฟรี</p>

<div class="note">💡 ระบบจองคิวออนไลน์ตัดปัญหาพวกนี้ทั้งหมด — ลูกค้าจองเอง เห็นคิวที่ว่างจริง
ระบบเตือนก่อนถึงวันนัด และเจ้าของร้านเห็นคิวทั้งหมดในที่เดียว</div>
""",
            },
            {
                "h2": "🤖 ระบบทำงานยังไง",
                "body": """
<p><strong>ลูกค้าจองเองในแชท</strong> — เลือกบริการ เลือกวัน เลือกเวลาที่ว่าง
กรอกชื่อ-เบอร์ ระบบยืนยันทันที ไม่ต้องรอใครมารับสาย</p>

<p><strong>กันคิวชนอัตโนมัติ</strong> — เวลาที่มีคนจองแล้วจะไม่โผล่ให้คนอื่นเลือกซ้ำ
ไม่มีทางที่สองคิวจะชนกันอีกต่อไป</p>

<p><strong>เตือนก่อนถึงวันนัด</strong> — ส่งข้อความเตือนลูกค้าก่อนถึงเวลานัด
ลดอัตราการไม่มาตามนัด (no-show) ได้มาก</p>
""",
            },
            {
                "h2": "🛠 ติดตั้งใช้เวลาแค่ไหน",
                "body": """
<p>เตรียมแค่รายการบริการที่เปิดให้จอง + เวลาทำการที่รับคิว ส่งมาให้เรา
ตั้งค่าเสร็จภายใน 2-3 วัน ทดลองก่อนเปิดใช้จริงกับลูกค้า</p>
<p>ปรับเวลา เพิ่ม/ลดบริการทีหลังได้ตลอด ไม่มีค่าใช้จ่ายเพิ่ม</p>
""",
            },
        ],
        "chat": [
            ("n", "ช่วงเที่ยง — สายเข้าพร้อมกัน 3 คู่"),
            ("u", "สวัสดีค่ะ อยากจองคิวพรุ่งนี้ค่ะ"),
            ("b", "สวัสดีค่ะ 😊 พรุ่งนี้ว่างช่วง 10:00, 13:30 และ 16:00 น. ค่ะ<br>"
                  "สนใจช่วงไหนคะ"),
            ("u", "ขอ 13:30 ค่ะ"),
            ("b", "ได้ค่ะ ✅ ขอชื่อกับเบอร์ติดต่อหน่อยนะคะ"),
            ("u", "แนน 08x-xxx-xxxx ค่ะ"),
            ("b", "จองเรียบร้อยค่ะ 🎉<br>คุณแนน · พรุ่งนี้ 13:30 น.<br>"
                  "ระบบจะส่งข้อความเตือนอีกครั้งก่อนถึงเวลานัดค่ะ"),
            ("n", "⚡ เจ้าของร้านเห็นคิวใหม่ทันทีในหน้าจัดการคิว"),
            ("b", "🔔 มีคิวใหม่! คุณแนน · 13:30 น. พรุ่งนี้"),
            ("n", "ก่อนถึงเวลานัด 1 ชม. — ระบบส่งเตือนอัตโนมัติ"),
            ("b", "⏰ แจ้งเตือน: คุณแนนมีนัด 13:30 น. อีก 1 ชม.ค่ะ"),
        ],
        "plans": [
            ("Starter", "฿590", "จองคิวพื้นฐาน 1 บริการ/ตาราง"),
            ("Pro ⭐", "฿1,290", "หลายบริการ + เตือนก่อนนัด (นิยมสุด)"),
            ("Business", "฿2,900", "หลายสาขา/หลายคิวพร้อมกัน"),
        ],
        "faq": [
            ("ลูกค้าจองซ้อนกันได้ไหม",
             "ไม่ได้ครับ ระบบล็อกเวลาที่มีคนจองแล้วทันที คนอื่นจะไม่เห็นช่วงเวลานั้นให้เลือกซ้ำ"),
            ("ยกเลิก/เลื่อนคิวได้ไหม",
             "ได้ครับ ลูกค้าทักแจ้งในแชทได้เลย หรือเจ้าของร้านจัดการให้จากฝั่งแอดมินก็ได้"),
            ("ต้องมีเว็บไซต์ก่อนไหม",
             "ไม่ต้องครับ จองผ่านแชท LINE/Facebook ได้เลย ไม่ต้องมีเว็บหรือแอปแยก"),
            ("ราคาเท่าไหร่",
             "เริ่ม ฿590/เดือน ไม่มีค่าติดตั้ง ยกเลิกได้ทุกเมื่อ"),
            ("รองรับกี่คิวต่อวัน",
             "ไม่จำกัดครับ ระบบรองรับได้ตามจำนวนช่วงเวลาที่ร้านเปิดให้จอง"),
            ("ใช้เวลาติดตั้งกี่วัน",
             "2-3 วัน นับจากวันที่ส่งรายการบริการและเวลาทำการมาให้"),
            ("เหมาะกับธุรกิจแบบไหนบ้าง",
             "เหมาะกับธุรกิจที่ต้องนัดหมายล่วงหน้า เช่น ร้านเสริมสวย คลินิก สปา ร้านซ่อม "
             "หรือบริการให้คำปรึกษาต่างๆ"),
        ],
    },
    "chatbot-clinic": {
        "h1": "รับทำ Chatbot สำหรับคลินิก",
        "title": "รับทำ Chatbot คลินิก + ระบบนัดหมาย | ตอบคำถามคนไข้อัตโนมัติ",
        "desc": "Chatbot สำหรับคลินิกความงาม ทันตกรรม กายภาพ ตอบคำถามราคา คัดกรองคนไข้ นัดหมายอัตโนมัติ พร้อมระบบบันทึกข้อมูลคนไข้",
        "kw": "chatbot คลินิก, ระบบคลินิก, บอทคลินิกความงาม, ระบบนัดหมายคนไข้",
        "lead": "ให้บอทตอบคำถามราคา คัดกรองคนไข้ และนัดหมายแทนแอดมิน",
        "points": [
            "ตอบคำถามราคา/บริการ ที่ถูกถามซ้ำๆ",
            "คัดกรองคนไข้ก่อนส่งต่อให้แพทย์",
            "ระบบนัดหมาย + เตือนก่อนถึงวันนัด",
            "มีระบบบันทึกข้อมูลคนไข้ให้ด้วย (ออปชั่น)",
        ],
        "sections": [
            {
                "h2": "😩 ทำไมคลินิกถึงเสียคนไข้ให้คู่แข่ง",
                "body": """
<p><strong>คำถามราคาที่ถามซ้ำทุกวัน</strong> — "โบท็อกซ์ราคาเท่าไหร่", "ฟิลเลอร์แพงไหม"
แอดมินต้องพิมพ์คำตอบเดิมวันละหลายสิบครั้ง เวลาที่ควรใช้ดูแลคนไข้หน้าคลินิกกลับหมดไปกับการตอบแชท</p>

<p><strong>คนไข้ถามตอนดึก ตัดสินใจตอนนั้น</strong> — คนส่วนใหญ่หาข้อมูลคลินิกความงามตอนกลางคืน
ถ้าไม่มีคนตอบทันที เขาเลื่อนไปดูคลินิกถัดไปในเฟซบุ๊กทันที</p>

<p><strong>นัดหมายสับสน คนไข้ลืมนัด</strong> — จดนัดในสมุดหรือแชท ไม่มีระบบเตือน
คนไข้ลืมมาตามนัด เวลาที่จองไว้ก็เสียไปฟรีๆ</p>

<div class="note">💡 บอทคลินิกไม่ได้มาแทนแพทย์หรือพยาบาล — มันมาตอบคำถามพื้นฐานและคัดกรองเบื้องต้น
เพื่อให้ทีมงานโฟกัสกับคนไข้ที่พร้อมตัดสินใจจริงๆ</div>
""",
            },
            {
                "h2": "🤖 บอทช่วยคลินิกตรงไหนบ้าง",
                "body": """
<p><strong>ตอบราคา/บริการแทน</strong> — ส่งเมนูบริการพร้อมราคาให้ลูกค้าดูเองได้ทันที
ไม่ต้องรอแอดมินว่าง</p>

<p><strong>คัดกรองคนไข้เบื้องต้น</strong> — ถามอาการ/ความต้องการเบื้องต้นก่อนส่งต่อให้แพทย์
ทำให้แพทย์คุยกับคนไข้ที่มีข้อมูลพร้อมแล้ว ประหยัดเวลาทั้งสองฝ่าย</p>

<p><strong>นัดหมาย + เตือนอัตโนมัติ</strong> — คนไข้จองคิวเอง ระบบเตือนก่อนถึงวันนัด
ลดอัตราคนไข้ไม่มาตามนัดได้มาก</p>

<div class="note">⚠️ บอทจะไม่ตอบคำถามทางการแพทย์เฉพาะเจาะจง (เช่น "หน้าแบบหนูควรทำอะไร")
คำถามลักษณะนี้จะถูกส่งต่อให้แพทย์/พยาบาลตอบเองทันที เพื่อความปลอดภัยของคนไข้</div>
""",
            },
            {
                "h2": "🛠 ติดตั้งยังไง ต้องเตรียมอะไร",
                "body": """
<p>เตรียม 3 อย่าง: เมนูบริการ+ราคา, คำถามที่คนไข้ถามบ่อยที่สุด, เวลาทำการที่รับนัด
ส่งมาให้เรา ตั้งค่าเสร็จภายใน 2-3 วัน ทดลองก่อนเปิดใช้จริง</p>
<p>ต้องการระบบบันทึกข้อมูลคนไข้เพิ่มเติม (ประวัติการรักษา) มีเป็นออปชั่นเสริมแยกต่างหาก</p>
""",
            },
        ],
        "chat": [
            ("n", "21:30 น. — คลินิกปิดแล้ว"),
            ("u", "สวัสดีค่ะ อยากทราบราคาโบท็อกซ์ค่ะ"),
            ("b", "สวัสดีค่ะ 😊 โบท็อกซ์ของคลินิกมีดังนี้ค่ะ<br>"
                  "• หน้าผาก 3,500฿<br>• หางตา 2,500฿<br>• กราม 4,500฿<br>"
                  "<br>สนใจจุดไหนคะ"),
            ("u", "อยากทำหน้าผากค่ะ เจ็บไหมคะ"),
            ("b", "เจ็บเล็กน้อยค่ะ ใช้เวลาประมาณ 15 นาที ไม่ต้องพักฟื้น "
                  "หากมีคำถามเรื่องอาการเฉพาะบุคคล แพทย์จะให้คำแนะนำอีกครั้งตอนปรึกษาค่ะ"),
            ("u", "ขอจองคิวพรุ่งนี้บ่ายค่ะ"),
            ("b", "ได้ค่ะ ✅ ขอชื่อกับเบอร์ติดต่อหน่อยนะคะ"),
            ("u", "แนน 08x-xxx-xxxx ค่ะ"),
            ("b", "จองเรียบร้อยค่ะ 🎉<br>คุณแนน · โบท็อกซ์หน้าผาก · พรุ่งนี้บ่าย<br>"
                  "ทีมงานจะทักยืนยันอีกครั้งนะคะ"),
            ("n", "⚡ แอดมินเห็นนัดใหม่ทันทีในระบบ"),
            ("b", "🔔 มีนัดใหม่! คุณแนน · โบท็อกซ์หน้าผาก · พรุ่งนี้บ่าย"),
        ],
        "plans": [
            ("Starter", "฿590", "ตอบราคา/บริการ + คัดกรองเบื้องต้น"),
            ("Pro ⭐", "฿1,290", "เพิ่มระบบนัดหมาย + เตือนก่อนนัด (นิยมสุด)"),
            ("Business", "฿2,900", "หลายสาขา/หลายแพทย์ แยกคิวได้"),
        ],
        "faq": [
            ("บอทตอบคำถามทางการแพทย์ได้ไหม",
             "บอทตอบได้เฉพาะคำถามทั่วไป เช่น ราคา ขั้นตอนคร่าวๆ เวลาทำการ "
             "คำถามที่ต้องใช้ดุลยพินิจทางการแพทย์จะส่งต่อให้แพทย์/พยาบาลตอบเองทันที"),
            ("ข้อมูลคนไข้ปลอดภัยไหม",
             "ข้อมูลที่เก็บผ่านแชทเป็นข้อมูลติดต่อพื้นฐาน (ชื่อ เบอร์ บริการที่สนใจ) เท่านั้น "
             "หากต้องการระบบบันทึกประวัติการรักษาแบบเต็มรูปแบบ มีแพ็กเกจเสริมแยกต่างหาก"),
            ("ราคาเริ่มต้นเท่าไหร่",
             "เริ่ม ฿590/เดือน ไม่มีค่าติดตั้ง คลินิกส่วนใหญ่เลือก Pro ฿1,290 เพราะได้ระบบนัดหมายด้วย"),
            ("ใช้เวลาติดตั้งกี่วัน",
             "2-3 วัน นับจากวันที่ส่งเมนูบริการและคำถามที่พบบ่อยมาให้"),
            ("เชื่อมกับ LINE OA ที่มีคนไข้เก่าอยู่แล้วได้ไหม",
             "ได้ครับ เชื่อมของเดิมได้เลย ไม่ต้องสร้าง LINE OA ใหม่ คนไข้เก่าไม่หาย"),
            ("แก้ราคาหรือบริการทีหลังได้ไหม",
             "ได้ตลอดครับ ทักแจ้งได้เลย ไม่มีค่าใช้จ่ายเพิ่ม ปกติแก้ให้ภายในวันเดียวกัน"),
            ("ขอทดลองก่อนได้ไหม",
             "ได้เลยครับ กดดูตัวอย่างระบบจริงด้านบนได้เลย ไม่ต้องสมัคร"),
        ],
    },
    "bot-ran-serm-suay": {
        "h1": "รับทำบอทตอบแชทร้านเสริมสวย",
        "title": "รับทำบอทร้านเสริมสวย ตอบแชท + จองคิว | ร้านทำผม เล็บ ขนตา",
        "desc": "บอทตอบแชทสำหรับร้านเสริมสวย ร้านทำผม ร้านเล็บ ต่อขนตา ตอบราคา ส่งรูปผลงาน รับจองคิวอัตโนมัติ 24 ชม. เริ่ม ฿590/เดือน",
        "kw": "บอทร้านเสริมสวย, บอทร้านทำผม, บอทร้านเล็บ, จองคิวร้านเสริมสวย, ระบบร้านทำผม",
        "lead": "ลูกค้าทักตอนดึก ตอนคิวเต็มมือ ก็มีคนตอบ — บอทส่งราคา ผลงาน และรับจองคิวให้",
        "points": [
            "ส่งเมนูบริการ + ราคา ให้ลูกค้าดูเอง",
            "ส่งรูปผลงานเป็นแคตตาล็อกเลื่อนดูได้",
            "รับจองคิว เก็บชื่อ-เบอร์-วัน-เวลา",
            "แจ้งเตือนเจ้าของร้านทันทีที่มีคนจอง",
        ],
        # ---- เนื้อหาลึก (ตอบคำถามจริงของเจ้าของร้าน ไม่ใช่โฆษณา) ----
        "sections": [
            {
                "h2": "😩 ร้านเสริมสวยเสียลูกค้าตอนไหน — 3 ช่วงนี้",
                "body": """
<p><strong>1. ตอนมือไม่ว่าง</strong> — กำลังสระผม ทำสี ต่อขนตาอยู่ มือเปียก มือถือวางไกล
ลูกค้าทักมาถามราคา ตอบไม่ได้ กว่าจะว่างอีก 40 นาที เขาไปร้านอื่นแล้ว</p>

<p><strong>2. ตอนกลางคืน</strong> — คนส่วนใหญ่เลือกร้านเสริมสวยตอน 3-5 ทุ่ม
ก่อนนอนเลื่อนเจอเพจ ทักถามราคา แต่ร้านปิดไปแล้ว ตอบเช้าอีกที เขาจองร้านอื่นไปแล้ว</p>

<p><strong>3. วันหยุดร้าน</strong> — ร้านหยุดจันทร์ แต่ลูกค้าไม่รู้ ทักมาเงียบไป 1 วัน
เขาไม่ได้คิดว่า "ร้านหยุด" เขาคิดว่า <em>"ร้านนี้ไม่สนใจลูกค้า"</em></p>

<div class="note">💡 <strong>ลองนับดูเล่นๆ</strong> — เดือนนึงมีลูกค้าทักมาแล้วเราตอบช้ากี่คน?
สมมติ 10 คน ตัดครึ่งว่าจะจองจริง 5 คน × ค่าบริการเฉลี่ย 800 บาท =
<strong>เดือนละ 4,000 บาทที่หลุดมือ</strong> ทั้งที่ลูกค้าเดินมาหาถึงหน้าประตูแล้ว</div>
""",
            },
            {
                "h2": "🤖 บอทเข้ามาช่วยตรงไหน",
                "body": """
<p>บอทไม่ได้มาแทนช่างครับ — <strong>มันมาทำงานที่ช่างทำไม่ได้ตอนมือไม่ว่าง</strong> เท่านั้น</p>

<p><strong>ตอบราคาแทน</strong> — ลูกค้าถาม "ทำสีเท่าไหร่คะ" บอทส่งเมนูราคาทั้งหมดให้เลือกดูเอง
ไม่ต้องพิมพ์ซ้ำวันละ 20 รอบ</p>

<p><strong>ส่งรูปผลงานแทน</strong> — "มีแบบไหนบ้างคะ" บอทส่งแคตตาล็อกรูปเลื่อนดูได้
ลูกค้าเลือกแบบที่ชอบแล้วกดจองต่อได้เลยในแชทเดียว</p>

<p><strong>รับจองคิวแทน</strong> — เก็บชื่อ เบอร์ บริการ วัน เวลา ครบ
แล้ว<strong>เด้งเข้า LINE เจ้าของร้านทันที</strong> — เจ้าของแค่รอรับคิวที่จองเข้ามา</p>

<p><strong>ตอบเรื่องจุกจิกแทน</strong> — ร้านอยู่ไหน จอดรถตรงไหน เปิดกี่โมง หยุดวันไหน
รับบัตรไหม มีที่จอดไหม — คำถามพวกนี้กินเวลาวันละหลายสิบนาที บอทจัดการได้หมด</p>

<div class="note">⚠️ <strong>สิ่งที่บอททำไม่ได้ — บอกตรงๆ</strong><br>
ลูกค้าที่อยากปรึกษาว่า "หน้าแบบหนูเหมาะกับผมทรงไหน" ต้องให้ช่างตอบเองครับ
บอทจะส่งต่อให้เจ้าของทันที ไม่พยายามตอบมั่ว — เพราะตอบมั่วเสียลูกค้ายิ่งกว่าไม่ตอบ</div>
""",
            },
            {
                "h2": "🛠 ติดตั้งยังไง ต้องเตรียมอะไรบ้าง",
                "body": """
<p>เจ้าของร้าน<strong>ไม่ต้องมีความรู้เทคนิคเลย</strong> ไม่ต้องลงโปรแกรม ไม่ต้องซื้อเซิร์ฟเวอร์
ระบบรันอยู่ฝั่งเรา ร้านแค่ใช้ LINE ตามปกติ</p>

<p><strong>สิ่งที่ต้องเตรียม มีแค่ 3 อย่าง:</strong></p>
<ul>
<li>LINE OA ของร้าน (ไม่มีก็สมัครฟรีได้ เราสอนให้ 10 นาทีเสร็จ)</li>
<li>เมนูบริการ + ราคา (ส่งมาเป็นรูป เป็นข้อความ หรือพิมพ์ในแชทก็ได้)</li>
<li>รูปผลงาน 5-10 รูป (ดึงจากเพจร้านได้เลย)</li>
</ul>

<p><strong>ขั้นตอน:</strong> ส่งข้อมูลมา → เราตั้งค่าให้ 2-3 วัน →
ส่งลิงก์ให้ทดลองก่อน → พอใจแล้วค่อยเปิดใช้จริงกับลูกค้า</p>

<p>อยากแก้ราคา เพิ่มบริการ เปลี่ยนรูปทีหลัง — ทักมาบอกได้ตลอด ไม่คิดเพิ่ม</p>
""",
            },
        ],
        # ตัวอย่างบทสนทนา — ให้เห็นภาพว่าจริงๆ มันทำงานยังไง
        "chat": [
            ("n", "22:40 น. — ร้านปิดไปแล้ว 2 ชั่วโมง"),
            ("u", "สวัสดีค่ะ ทำสีผมราคาเท่าไหร่คะ"),
            ("b", "สวัสดีค่ะ 😊 ทำสีผมของร้านเรามีดังนี้ค่ะ<br>"
                  "• ทำสีทั้งหัว 1,200฿<br>• ไฮไลท์ 1,800฿<br>• ย้อมโคน 700฿<br>"
                  "<br>สนใจแบบไหนคะ กดดูรูปผลงานได้เลยค่ะ 👇"),
            ("u", "ขอดูไฮไลท์หน่อยค่ะ"),
            ("b", "ได้เลยค่ะ 💇‍♀️ [ส่งแคตตาล็อกรูป 8 แบบ เลื่อนดูได้]<br>"
                  "ชอบแบบไหนกดจองคิวได้เลยนะคะ"),
            ("u", "จองวันเสาร์บ่าย 2 ได้ไหมคะ"),
            ("b", "ได้ค่ะ ✅ ขอชื่อกับเบอร์ติดต่อหน่อยนะคะ"),
            ("u", "แนน 08x-xxx-xxxx ค่ะ"),
            ("b", "จองเรียบร้อยค่ะ 🎉<br>คุณแนน · ไฮไลท์ · เสาร์ 14:00 น.<br>"
                  "เดี๋ยวร้านทักยืนยันอีกทีนะคะ ขอบคุณค่ะ 🙏"),
            ("n", "⚡ ขณะเดียวกัน — LINE เจ้าของร้านเด้งทันที"),
            ("b", "🔔 มีคิวจองใหม่!<br>คุณแนน · ไฮไลท์ 1,800฿<br>เสาร์ 14:00 น. · 08x-xxx-xxxx"),
            ("n", "เจ้าของร้านนอนหลับอยู่ — แต่คิวเข้ามาแล้ว 💰"),
        ],
        "plans": [
            ("Starter", "฿590", "ร้านเล็ก ตอบราคา + ส่งผลงาน"),
            ("Pro ⭐", "฿1,290", "ร้านที่ต้องการรับจองคิวด้วย (นิยมสุด)"),
            ("Business", "฿2,900", "หลายสาขา / หลายช่าง แยกคิวได้"),
        ],
        "faq": [
            ("บอทตอบแทนหมดเลยเหรอ ลูกค้าจะรู้สึกไม่ดีไหม",
             "บอทตอบเฉพาะคำถามซ้ำๆ อย่างราคา รูปผลงาน เวลาเปิด-ปิด จองคิว ครับ "
             "ถ้าลูกค้าถามอะไรที่ต้องให้ช่างตอบ บอทจะส่งต่อให้เจ้าของทันที "
             "จากประสบการณ์ ลูกค้าชอบมากกว่าเดิมด้วยซ้ำ เพราะได้คำตอบทันทีไม่ต้องรอ"),
            ("ต้องมี LINE OA ก่อนไหม ไม่มีทำยังไง",
             "ไม่มีก็ได้ครับ สมัครฟรี ใช้เวลา 10 นาที เราสอนให้ทีละขั้น "
             "หรือถ้ามี LINE OA อยู่แล้วก็เชื่อมของเดิมได้เลย ไม่ต้องสร้างใหม่ ลูกค้าเก่าไม่หาย"),
            ("ราคาเท่าไหร่ มีค่าติดตั้งไหม",
             "เริ่ม ฿590/เดือน ไม่มีค่าติดตั้ง ไม่มีค่าแรกเข้า ยกเลิกได้ทุกเมื่อ ไม่มีสัญญาผูกมัด "
             "แพ็กเกจที่ร้านเสริมสวยเลือกมากสุดคือ Pro ฿1,290 เพราะรับจองคิวได้ด้วย"),
            ("ใช้เวลากี่วันถึงใช้งานได้",
             "2-3 วันครับ นับจากวันที่ส่งเมนูราคากับรูปผลงานมาให้ "
             "เราจะส่งลิงก์ให้ทดลองก่อน พอใจแล้วค่อยเปิดใช้จริง"),
            ("แก้ราคาหรือเพิ่มบริการทีหลังได้ไหม",
             "ได้ตลอดครับ ทักมาบอกได้เลย ไม่คิดเงินเพิ่ม ปกติแก้ให้ภายในวันเดียวกัน"),
            ("มีค่า LINE API เพิ่มไหม",
             "LINE OA มีโควตาข้อความฟรี 300 ข้อความ/เดือน ซึ่งพอสำหรับร้านทั่วไป "
             "ถ้าเกินมีค่าใช้จ่ายฝั่ง LINE เอง เราจะแจ้งก่อนเสมอ ไม่มีบวกเพิ่มจากเรา"),
            ("ร้านผมมีหลายสาขา / หลายช่าง ทำได้ไหม",
             "ได้ครับ แพ็กเกจ Business ฿2,900 แยกคิวตามสาขาหรือตามช่างได้ "
             "ลูกค้าเลือกช่างที่ชอบได้เลย และแต่ละคนเห็นเฉพาะคิวตัวเอง"),
            ("ขอลองก่อนได้ไหม",
             "ได้เลยครับ กดปุ่ม 💇 Demo ด้านบนได้เลย ทักคุยเหมือนเป็นลูกค้าจริง "
             "ไม่ต้องสมัคร ไม่ต้องให้เบอร์ ลองเล่นได้เต็มที่ครับ"),
        ],
    },
    "bot-ran-ahan": {
        "h1": "รับทำบอทตอบแชทร้านอาหาร",
        "title": "รับทำบอทร้านอาหาร จองโต๊ะ + สั่งกลับบ้าน | ตอบแชทอัตโนมัติ",
        "desc": "บอทตอบแชทร้านอาหาร คาเฟ่ ส่งเมนู รับจองโต๊ะ รับออเดอร์กลับบ้าน ตอบคำถามที่จอด เวลาเปิด-ปิด อัตโนมัติ 24 ชม.",
        "kw": "บอทร้านอาหาร, จองโต๊ะออนไลน์, ระบบร้านอาหาร, บอทคาเฟ่, รับออเดอร์อัตโนมัติ",
        "lead": "ช่วงพีคมือไม่ว่าง — ให้บอทส่งเมนู รับจองโต๊ะ ตอบคำถามซ้ำๆ แทน",
        "points": [
            "ส่งเมนู + ราคา ให้ลูกค้าดูในแชท",
            "รับจองโต๊ะ เก็บชื่อ-เบอร์-จำนวนคน-เวลา",
            "รับออเดอร์กลับบ้าน",
            "ตอบคำถามซ้ำๆ (ที่จอด เวลาเปิด โปร)",
        ],
        "sections": [
            {
                "h2": "😩 ช่วงพีคร้านอาหาร — ตอนที่เสียลูกค้ามากที่สุด",
                "body": """
<p><strong>ช่วงเที่ยง/เย็น มือไม่ว่างเลย</strong> — ครัวยุ่ง โต๊ะเต็ม พนักงานวิ่งเสิร์ฟ
ไม่มีใครว่างมาตอบแชทถามเมนู ราคา หรือรับจองโต๊ะ</p>

<p><strong>ลูกค้าอยากจองโต๊ะแต่โทรไม่ติด</strong> — ช่วงพีคสายเข้าเยอะ รับไม่ทัน
ลูกค้าโทรไม่ติดก็เปลี่ยนใจไปร้านอื่นที่จองง่ายกว่า</p>

<p><strong>คำถามเดิมทุกวัน</strong> — "มีที่จอดรถไหม" "รับเด็กไหม" "วันนี้เปิดกี่โมง"
พนักงานต้องตอบซ้ำๆ ทั้งที่ควรโฟกัสกับลูกค้าในร้าน</p>

<div class="note">💡 บอทช่วยรับภาระตรงนี้แทน — ส่งเมนู รับจองโต๊ะ ตอบคำถามจุกจิก
ให้พนักงานโฟกัสกับลูกค้าที่อยู่ในร้านได้เต็มที่</div>
""",
            },
            {
                "h2": "🤖 บอทช่วยร้านอาหารตรงไหนบ้าง",
                "body": """
<p><strong>ส่งเมนูพร้อมราคา</strong> — ลูกค้าถาม "มีเมนูอะไรบ้าง" บอทส่งเมนูทั้งหมดให้ดู
เลือกได้เองไม่ต้องรอพนักงานว่าง</p>

<p><strong>รับจองโต๊ะอัตโนมัติ</strong> — เก็บชื่อ เบอร์ จำนวนคน วัน เวลา
แจ้งเตือนร้านทันทีที่มีคนจอง ไม่ต้องรับสายเอง</p>

<p><strong>รับออเดอร์กลับบ้าน</strong> — ลูกค้าสั่งอาหารผ่านแชทได้เลย
ระบุเมนู จำนวน เวลามารับ ครบในที่เดียว</p>
""",
            },
            {
                "h2": "🛠 ติดตั้งใช้เวลาแค่ไหน",
                "body": """
<p>เตรียมเมนู+ราคา, จำนวนโต๊ะที่รับจองได้ต่อรอบ, คำถามที่ลูกค้าถามบ่อย
ส่งมาให้เรา ตั้งค่าเสร็จภายใน 2-3 วัน ทดลองก่อนเปิดใช้จริง</p>
<p>เปลี่ยนเมนู ปรับราคา เพิ่มโปรโมชั่นทีหลังได้ตลอด ไม่มีค่าใช้จ่ายเพิ่ม</p>
""",
            },
        ],
        "chat": [
            ("n", "ศุกร์เย็น — ร้านเต็มทุกโต๊ะ"),
            ("u", "สวัสดีค่ะ ขอจองโต๊ะพรุ่งนี้เย็น 4 คนค่ะ"),
            ("b", "สวัสดีค่ะ 😊 พรุ่งนี้เย็นว่างช่วง 18:00 และ 19:30 น. ค่ะ<br>"
                  "สนใจช่วงไหนคะ"),
            ("u", "ขอ 18:00 ค่ะ"),
            ("b", "ได้ค่ะ ✅ ขอชื่อกับเบอร์ติดต่อหน่อยนะคะ"),
            ("u", "แนน 08x-xxx-xxxx ค่ะ"),
            ("b", "จองเรียบร้อยค่ะ 🎉<br>คุณแนน · โต๊ะ 4 ที่นั่ง · พรุ่งนี้ 18:00 น.<br>"
                  "ขอบคุณที่เลือกร้านเรานะคะ 🙏"),
            ("n", "⚡ ทางร้านเห็นการจองใหม่ทันที"),
            ("b", "🔔 มีการจองโต๊ะใหม่! คุณแนน · 4 ที่นั่ง · พรุ่งนี้ 18:00 น."),
            ("n", "พนักงานเตรียมโต๊ะไว้ล่วงหน้าได้เลย ไม่ต้องรับสาย"),
        ],
        "plans": [
            ("Starter", "฿590", "ส่งเมนู + ตอบคำถามพื้นฐาน"),
            ("Pro ⭐", "฿1,290", "เพิ่มรับจองโต๊ะ + รับออเดอร์กลับบ้าน (นิยมสุด)"),
            ("Business", "฿2,900", "หลายสาขา แยกคิว/โต๊ะแต่ละสาขาได้"),
        ],
        "faq": [
            ("รับจองโต๊ะได้กี่โต๊ะพร้อมกัน",
             "ไม่จำกัดครับ ตั้งค่าตามจำนวนโต๊ะจริงของร้าน ระบบกันโต๊ะชนกันอัตโนมัติ"),
            ("รับออเดอร์กลับบ้านผ่านบอทได้เลยไหม",
             "ได้ครับ อยู่ในแพ็กเกจ Pro ขึ้นไป ลูกค้าสั่งอาหาร ระบุเวลามารับได้ในแชทเดียว"),
            ("เปลี่ยนเมนูบ่อยๆ ได้ไหม",
             "ได้ตลอดครับ ทักแจ้งได้เลย ไม่มีค่าใช้จ่ายเพิ่ม ปกติแก้ให้ภายในวันเดียวกัน"),
            ("ราคาเริ่มต้นเท่าไหร่",
             "เริ่ม ฿590/เดือน ไม่มีค่าติดตั้ง ยกเลิกได้ทุกเมื่อ"),
            ("ใช้เวลาติดตั้งกี่วัน",
             "2-3 วัน นับจากวันที่ส่งเมนูและข้อมูลร้านมาให้ครบ"),
            ("รองรับหลายสาขาไหม",
             "รองรับครับ แพ็กเกจ Business แยกการจองและเมนูตามแต่ละสาขาได้"),
            ("ขอทดลองก่อนได้ไหม",
             "ได้เลยครับ กดดูตัวอย่างระบบจริงด้านบนได้เลย ไม่ต้องสมัคร"),
        ],
    },
    "n8n-automation": {
        "h1": "รับทำ n8n Automation + AI",
        "title": "รับทำ n8n Automation + AI Agent | ลดงานซ้ำซาก แจ้งเตือน LINE",
        "desc": "รับสร้างระบบ automation ด้วย n8n + AI (Claude) เชื่อม Google Sheet, LINE, API ลดงาน manual แจ้งเตือนอัตโนมัติ เริ่ม ฿1,500",
        "kw": "n8n, automation, รับทำ automation, ระบบอัตโนมัติ, make.com, zapier, ai agent, rpa",
        "lead": "เปลี่ยนงานซ้ำซากให้เป็นระบบที่ AI คิดและตัดสินใจให้ — ทำงานแทนคุณ 24 ชม.",
        "points": [
            "เชื่อม Google Form/Sheet → LINE/Email อัตโนมัติ",
            "AI (Claude) วิเคราะห์และสรุปข้อมูลให้",
            "ดักจับข้อมูลจากเว็บ/API → ส่งรายงานเข้า LINE",
            "แจ้งเตือน error + retry อัตโนมัติ",
        ],
        "sections": [
            {
                "h2": "😩 งานซ้ำซากที่กินเวลาทุกวันโดยไม่รู้ตัว",
                "body": """
<p><strong>Copy-paste ข้อมูลข้ามระบบ</strong> — ข้อมูลจาก Google Form ต้องเอาไปกรอกใน Sheet
แล้วเอาไปแจ้งทีมใน LINE อีกที ทำมือทุกครั้ง เสียเวลาและพลาดง่าย</p>

<p><strong>เช็คข้อมูล/สต็อก/ราคาด้วยมือ</strong> — ต้องเข้าไปเช็คเว็บหรือระบบซ้ำๆ ทุกวัน
เพื่อดูว่ามีอะไรเปลี่ยนแปลงบ้าง ทั้งที่งานนี้ให้ระบบทำแทนได้</p>

<p><strong>แจ้งเตือนทีมช้า</strong> — เหตุการณ์สำคัญเกิดขึ้นแล้วแต่กว่าจะมีคนเห็นและแจ้งทีม
ผ่านไปหลายชั่วโมง โอกาสตอบสนองทันเวลาก็หายไป</p>

<div class="note">💡 งานพวกนี้ไม่ต้องใช้คนทำซ้ำทุกวัน — เขียนระบบ automation ครั้งเดียว
ให้มันทำงานแทนตลอดไป แจ้งเตือนเฉพาะตอนที่คนต้องตัดสินใจจริงๆ</div>
""",
            },
            {
                "h2": "🤖 n8n + AI Agent ช่วยอะไรได้บ้าง",
                "body": """
<p><strong>เชื่อมระบบต่างๆ เข้าด้วยกัน</strong> — Google Form/Sheet, LINE, Email, API ภายนอก
ไหลข้อมูลถึงกันอัตโนมัติ ไม่ต้อง copy-paste มือ</p>

<p><strong>AI วิเคราะห์และสรุปให้</strong> — ใช้ Claude อ่านข้อมูลที่เข้ามา สรุปประเด็นสำคัญ
หรือแม้แต่ตัดสินใจเบื้องต้นตามเงื่อนไขที่ตั้งไว้ ก่อนส่งรายงานเข้า LINE</p>

<p><strong>ดักจับความเปลี่ยนแปลงอัตโนมัติ</strong> — เฝ้าดูเว็บ/API แทนคน
พอมีอะไรเปลี่ยนแปลงที่ตรงเงื่อนไข ส่งแจ้งเตือนเข้า LINE ทันที ไม่ต้องรอใครมาเช็ค</p>

<p><strong>จัดการ error ให้เอง</strong> — ถ้าขั้นตอนไหนล้มเหลว ระบบ retry อัตโนมัติ
และแจ้งเตือนถ้ายังแก้ไม่ได้ ไม่ปล่อยให้งานหายไปเงียบๆ</p>
""",
            },
            {
                "h2": "🛠 เริ่มต้นยังไง",
                "body": """
<p>เล่าให้เราฟังว่างานซ้ำซากที่อยากให้ระบบทำแทนคืออะไร มีระบบ/แหล่งข้อมูลอะไรที่ต้องเชื่อมกันบ้าง
เราจะประเมินและออกแบบ workflow ให้ ใช้เวลาตั้งค่า 2-5 วันแล้วแต่ความซับซ้อน</p>
<p>ทดลองใช้งานจริงก่อน ปรับแก้เงื่อนไขได้จนกว่าจะตรงกับที่ต้องการ</p>
""",
            },
        ],
        "chat": [
            ("n", "ทุกเช้า 8 โมง — ระบบทำงานให้อัตโนมัติ"),
            ("u", "มีลูกค้ากรอกฟอร์มสนใจสินค้าเข้ามาใหม่"),
            ("b", "🤖 ตรวจพบข้อมูลใหม่ใน Google Form"),
            ("b", "📊 บันทึกลง Sheet เรียบร้อย + วิเคราะห์ด้วย AI แล้ว"),
            ("b", "🔔 สรุปส่งเข้า LINE ทีมขาย:<br>"
                  "ลูกค้า: คุณแนน · สนใจ: แพ็กเกจ Pro<br>"
                  "งบประมาณ: 1,000-1,500฿/เดือน · ความเร่งด่วน: สูง"),
            ("n", "ทีมขายเห็นทันที ไม่ต้องเปิด Sheet เช็คเอง"),
            ("u", "(ตัวอย่างอีกเคส) ราคาสินค้าคู่แข่งเปลี่ยนบนเว็บ"),
            ("b", "🤖 ระบบดักจับความเปลี่ยนแปลงบนเว็บที่ตั้งเฝ้าไว้"),
            ("b", "🔔 แจ้งเตือน: ราคาคู่แข่งลดลง 10% — ส่งเข้า LINE ทีมทันที"),
        ],
        "plans": [
            ("Starter", "฿1,500", "Automation 1 workflow (เช่น Form → LINE)"),
            ("Pro ⭐", "฿3,500", "หลาย workflow + AI วิเคราะห์/สรุปข้อมูล (นิยมสุด)"),
            ("Business", "฿7,900", "ระบบซับซ้อน หลายระบบเชื่อมกัน + ดูแลต่อเนื่อง"),
        ],
        "faq": [
            ("n8n คืออะไร ต่างจาก Zapier/Make ยังไง",
             "n8n คือเครื่องมือสร้างระบบอัตโนมัติเชื่อมต่อแอปต่างๆ เข้าด้วยกัน คล้าย Zapier/Make "
             "แต่ยืดหยุ่นกว่า ปรับแต่ง logic ซับซ้อนได้มากกว่า และรวม AI Agent เข้าไปในขั้นตอนได้โดยตรง"),
            ("ต้องมีความรู้เขียนโค้ดไหม",
             "ไม่ต้องครับ ฝั่งคุณแค่บอกว่าต้องการให้ระบบทำอะไร เราออกแบบและตั้งค่า workflow ให้ทั้งหมด"),
            ("เชื่อมกับระบบที่มีอยู่แล้วได้ไหม",
             "ได้ครับ n8n เชื่อมต่อได้กับแอป/API ส่วนใหญ่ เช่น Google Workspace, LINE, Facebook, "
             "ฐานข้อมูล, ระบบบัญชี และ API ที่เขียนขึ้นเอง"),
            ("ราคาขึ้นอยู่กับอะไร",
             "ขึ้นอยู่กับความซับซ้อนของ workflow และจำนวนระบบที่ต้องเชื่อมกัน "
             "เริ่มต้น ฿1,500 สำหรับ workflow เดียว ไปจนถึง Business สำหรับระบบที่ซับซ้อนหลายส่วน"),
            ("ใช้เวลาสร้างนานแค่ไหน",
             "2-5 วันแล้วแต่ความซับซ้อน งานง่ายๆ เช่น Form → LINE ทำเสร็จได้ใน 2 วัน"),
            ("ถ้าระบบ error จะรู้ได้ยังไง",
             "ระบบ retry อัตโนมัติก่อน ถ้ายังไม่สำเร็จจะแจ้งเตือนเข้า LINE ทันที ไม่ปล่อยให้งานหายเงียบๆ"),
            ("แก้ไข workflow ทีหลังได้ไหม",
             "ได้ครับ ปรับเงื่อนไข เพิ่ม/ลดขั้นตอนทีหลังได้ตลอด มีค่าใช้จ่ายตามความซับซ้อนของงานที่แก้"),
            ("ขอคุยรายละเอียดงานก่อนได้ไหม",
             "ได้เลยครับ ทักมาอธิบายงานที่ต้องการ เราจะประเมินและเสนอแนวทางให้ก่อนเริ่มทำ"),
        ],
    },
}


def _rich_blocks(p: dict) -> tuple:
    """
    เนื้อหาลึกเฉพาะหน้า — มีเฉพาะหน้าที่เขียนจริงจังแล้ว
    หน้าที่ยังไม่มี key พวกนี้จะ render แบบเดิม (ไม่พัง)
    """
    # 1) เนื้อหาบทความ (ตอบคำถามจริงของลูกค้า ไม่ใช่โฆษณา)
    secs = "".join(
        f"<h2>{s['h2']}</h2>{s['body']}" for s in p.get("sections", [])
    )

    # 2) ตัวอย่างบทสนทนาจริง — ให้เห็นภาพว่าบอททำงานยังไง
    chat = ""
    if p.get("chat"):
        bubbles = "".join(
            f'<div class="msg {who}">{txt}</div>' for who, txt in p["chat"]
        )
        chat = (f'<h2>💬 ลูกค้าทักมาตอน 4 ทุ่ม — บอทตอบให้แบบนี้</h2>'
                f'<div class="chat">{bubbles}</div>')

    # 3) ตารางราคา
    tbl = ""
    if p.get("plans"):
        rows = "".join(
            f'<tr><td><b>{n}</b></td><td class="pr">{pr}</td><td>{d}</td></tr>'
            for n, pr, d in p["plans"]
        )
        tbl = ('<h2>💰 ราคา</h2><table class="tb">'
               '<tr><th>แพ็กเกจ</th><th>ราคา/เดือน</th><th>เหมาะกับ</th></tr>'
               f'{rows}</table>')

    # 4) FAQ + JSON-LD FAQPage (ช่วยให้ Google โชว์คำถามใต้ผลค้นหา)
    faq_html, faq_ld = "", ""
    if p.get("faq"):
        items = "".join(
            f'<div class="q">{q}</div><div class="a">{a}</div>' for q, a in p["faq"]
        )
        faq_html = f'<h2>❓ คำถามที่เจ้าของร้านถามบ่อย</h2><div class="faq">{items}</div>'
        qa = ",".join(
            json.dumps({
                "@type": "Question", "name": q,
                "acceptedAnswer": {"@type": "Answer", "text": re.sub(r"<[^>]+>", "", a)},
            }, ensure_ascii=False)
            for q, a in p["faq"]
        )
        faq_ld = ('<script type="application/ld+json">'
                  f'{{"@context":"https://schema.org","@type":"FAQPage","mainEntity":[{qa}]}}'
                  '</script>')
    return secs, chat, tbl, faq_html, faq_ld


# slug ของหน้า SEO → biz_type ที่ตรงกัน (ใช้พรีเซ็ตฟอร์ม /botkit#order ให้ตรงบริบทที่ลูกค้ามาจาก)
SEO_SLUG_BIZ = {
    "line-bot": "general", "bot-jongkiw": "booking", "chatbot-clinic": "clinic",
    "bot-ran-serm-suay": "beauty", "bot-ran-ahan": "restaurant", "n8n-automation": "automation",
}


def _seo_page(slug: str) -> str:
    p = SEO_PAGES[slug]
    pts = "".join(f"<li>{x}</li>" for x in p["points"])
    botkit_url = f"/botkit?biz={SEO_SLUG_BIZ.get(slug, '')}#order" if SEO_SLUG_BIZ.get(slug) else "/botkit"
    secs, chat, tbl, faq_html, faq_ld = _rich_blocks(p)
    demos = "".join(
        f'<a class="d" href="/demo/{k}" target="_blank">{v["emoji"]} {v["biz_name"]}</a>'
        for k, v in _load_demo_configs().items()
    )
    # ลิงก์ไปหน้าอื่น (internal linking ช่วย SEO)
    others = "".join(
        f' · <a href="/{k}">{v["h1"]}</a>'
        for k, v in SEO_PAGES.items() if k != slug
    )
    return f"""<!DOCTYPE html><html lang="th"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{p['title']}</title>
<meta name="description" content="{p['desc']}">
<meta name="keywords" content="{p['kw']}">
<link rel="canonical" href="{BASE_URL}/{slug}">
<meta name="robots" content="index, follow">
<meta property="og:type" content="website">
<meta property="og:locale" content="th_TH">
<meta property="og:title" content="{p['title']}">
<meta property="og:description" content="{p['desc']}">
<meta property="og:url" content="{BASE_URL}/{slug}">
<script type="application/ld+json">
{{"@context":"https://schema.org","@type":"Service","name":"{p['h1']}",
"description":"{p['desc']}","areaServed":{{"@type":"Country","name":"Thailand"}},
"provider":{{"@type":"Person","name":"Jark","jobTitle":"LINE Bot & AI Agent Developer"}},
"offers":{{"@type":"Offer","price":"590","priceCurrency":"THB"}}}}
</script>
{faq_ld}
<style>
*{{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',system-ui,Tahoma,sans-serif}}
body{{background:#060a16;color:#e2e8f0;line-height:1.6}}
.w{{max-width:800px;margin:0 auto;padding:40px 20px 60px}}
h1{{font-size:clamp(26px,5vw,38px);font-weight:800;margin-bottom:14px;line-height:1.3}}
h1 span{{color:#00e47a}}
.lead{{font-size:17px;color:#9fb0d0;margin-bottom:26px}}
ul{{list-style:none;margin:22px 0}}
li{{padding:9px 0 9px 30px;position:relative;font-size:15.5px;color:#c7d3e8}}
li::before{{content:"✓";position:absolute;left:0;color:#00e47a;font-weight:800;font-size:17px}}
h2{{font-size:20px;margin:32px 0 12px}}
.demos{{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0 30px}}
.d{{background:#0e1526;border:1px solid #1c2740;border-radius:12px;padding:12px 16px;
   text-decoration:none;color:#e2e8f0;font-weight:600;font-size:14px}}
.d:hover{{border-color:#00e47a}}
.cta{{display:inline-block;background:#00e47a;color:#03130b;padding:15px 32px;border-radius:12px;
     font-weight:800;text-decoration:none;font-size:16px;margin-top:8px}}
.price{{background:#0e1526;border:1px solid #1c2740;border-radius:14px;padding:18px;margin:24px 0}}
.price b{{color:#00e47a;font-size:22px}}
footer{{margin-top:40px;padding-top:22px;border-top:1px solid #1c2740;color:#5b6b8c;font-size:13px}}
footer a{{color:#22d3ee}}
p{{color:#c7d3e8;font-size:15.5px;margin:12px 0}}
h2{{color:#fff}}
strong{{color:#00e47a}}
/* ตัวอย่างแชท */
.chat{{background:#0e1526;border:1px solid #1c2740;border-radius:14px;padding:16px;margin:16px 0}}
.msg{{max-width:80%;padding:10px 14px;border-radius:14px;margin:8px 0;font-size:14.5px;line-height:1.5}}
.msg.u{{background:#1c2740;color:#e2e8f0;margin-left:auto;border-bottom-right-radius:4px}}
.msg.b{{background:#00e47a;color:#03130b;border-bottom-left-radius:4px;font-weight:500}}
.msg.n{{background:none;color:#5b6b8c;font-size:12.5px;text-align:center;max-width:100%;padding:4px}}
/* ตารางราคา */
.tb{{width:100%;border-collapse:collapse;margin:16px 0;font-size:14.5px}}
.tb th{{text-align:left;padding:11px;border-bottom:2px solid #1c2740;color:#9fb0d0;font-size:13px}}
.tb td{{padding:12px 11px;border-bottom:1px solid #1c2740;color:#c7d3e8}}
.tb .pr{{color:#00e47a;font-weight:800;white-space:nowrap}}
/* FAQ */
.faq{{margin:16px 0}}
.q{{font-weight:700;color:#fff;font-size:15.5px;margin-top:18px}}
.q::before{{content:"Q. ";color:#00e47a}}
.a{{color:#9fb0d0;font-size:15px;margin-top:6px;padding-left:2px}}
.note{{background:#0e1526;border-left:3px solid #00e47a;border-radius:0 10px 10px 0;
      padding:13px 16px;margin:18px 0;font-size:14.5px;color:#c7d3e8}}
</style></head><body><div class="w">
<h1>{p['h1']}<br><span>ลองฟรีก่อนตัดสินใจ</span></h1>
<p class="lead">{p['lead']}</p>
<ul>{pts}</ul>

<h2>🎪 ลองเล่นระบบจริงได้เลย</h2>
<p style="color:#9fb0d0;font-size:14.5px">กดเข้าไปคุยกับบอทได้เลย เหมือนเป็นลูกค้าจริง ไม่ต้องสมัคร</p>
<div class="demos">{demos}</div>

{secs}
{chat}
{tbl}

<div class="price">
  💰 <b>เริ่มต้น ฿590/เดือน</b><br>
  <span style="color:#9fb0d0;font-size:14px">ไม่มีค่าติดตั้ง · ยกเลิกได้ทุกเมื่อ · ไม่ผูกมัด</span>
</div>

<a class="cta" href="{botkit_url}">ดูแพ็กเกจทั้งหมด →</a>

{faq_html or '''<h2>❓ คำถามที่พบบ่อย</h2>
<ul>
  <li>ไม่ต้องมีเซิร์ฟเวอร์ ไม่ต้องมีความรู้เทคนิค — เราดูแลให้หมด</li>
  <li>ไม่มีค่า API เพิ่ม — Facebook/Instagram/LINE API ฟรี</li>
  <li>ใช้งานได้ภายใน 2-3 วัน</li>
  <li>ยกเลิกได้ทุกเมื่อ ไม่มีสัญญาผูกมัด</li>
</ul>'''}

<footer>
  BotKit by Jark — LINE Bot &amp; AI Agent Developer<br>
  <a href="/botkit">ดูแพ็กเกจทั้งหมด</a>{others}<br>
  <a href="https://www.facebook.com/profile.php?id=100086195540576" target="_blank" rel="noopener">📘 AI Claude Academy (Facebook Page)</a> ·
  <a href="https://www.facebook.com/jakkar.jakkar.39545" target="_blank" rel="noopener">👤 Jark Krit (Facebook)</a>
</footer>
</div></body></html>"""


@app.route("/<slug>")
def seo_landing(slug):
    """หน้า landing ตามคำค้นหา (SEO)"""
    if slug not in SEO_PAGES:
        from flask import abort
        abort(404)
    _track_visit()
    return _seo_page(slug), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/sitemap.xml")
def sitemap():
    urls = ["/", "/botkit"] + [f"/{k}" for k in SEO_PAGES] + \
           [f"/demo/{k}" for k in _load_demo_configs()]
    today = datetime.now().strftime("%Y-%m-%d")
    items = "".join(
        f"<url><loc>{BASE_URL}{u}</loc><lastmod>{today}</lastmod>"
        f"<changefreq>weekly</changefreq>"
        f"<priority>{'1.0' if u in ('/botkit','/') else '0.8'}</priority></url>"
        for u in urls
    )
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           f'{items}</urlset>')
    return xml, 200, {"Content-Type": "application/xml; charset=utf-8"}


@app.after_request
def _stamp_source(resp):
    """
    ปั๊ม cookie จำ 'แหล่งแรกที่รู้จักเรา' ไว้ 30 วัน
    ทำไมต้องมี: ตอนลูกค้ากดสั่งซื้อ referrer จะเป็นเว็บเราเอง → ไม่รู้ว่าเขามาจาก Google
    cookie นี้เก็บแค่ชื่อแหล่ง (google/facebook/...) ไม่มีข้อมูลส่วนตัวใดๆ
    """
    try:
        if not request.cookies.get(seo_tracker.SRC_COOKIE) and not request.path.startswith("/api"):
            src = seo_tracker.classify(request.headers.get("Referer", "") or "")
            if "forex-ai-demo.onrender.com" not in (request.headers.get("Referer") or ""):
                resp.set_cookie(seo_tracker.SRC_COOKIE, src, max_age=86400 * seo_tracker.COOKIE_DAYS,
                                samesite="Lax", secure=True)
    except Exception:
        pass
    return resp


# ---------- Auto-Execution (PAPER MODE เท่านั้น) ----------

_PAIR_FETCH = {
    "BTC/USD": fetch_btc,
    "ETH/USD": fetch_eth,
    "EUR/USD": lambda: fetch_forex("EUR", "USD"),
    "GBP/USD": lambda: fetch_forex("GBP", "USD"),
    "USD/JPY": lambda: fetch_forex("USD", "JPY"),
}


def _autotrade_price(pair: str) -> dict:
    fn = _PAIR_FETCH.get(pair.upper())
    if not fn:
        raise ValueError(f"ยังไม่รองรับคู่ {pair}")
    return fn()


@app.route("/api/autotrade/tick", methods=["GET", "POST"])
def autotrade_tick():
    """
    cron ยิงมาทุก 15-30 นาที → เดิน 1 รอบ
    ⚠️ PAPER เท่านั้น — Executor ตกกลับเป็น PaperBroker เองถ้าไม่ปลดล็อกครบ 3 ชั้น
    """
    if not HUNTERS_ENABLED:
        return jsonify(_HUNTERS_OFF_MSG), 200   # ปิดกันเผาเครดิต Claude (analyze_with_ai) (21 ก.ค. 2026)
    from auto_execution import runner
    try:
        return jsonify({"success": True, **runner.tick(
            fetch_price_fn=_autotrade_price,
            analyze_fn=analyze_with_ai,
            notify_fn=_push_line,
            line_user_id=LINE_USER_ID,
        )})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)[:300]}), 200


@app.route("/api/autotrade/state")
def autotrade_state():
    """ผลเทรดกระดาษทั้งหมด — ใช้โดยหน้า /demo/autotrade"""
    from auto_execution import runner
    try:
        return jsonify(runner.state())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 200


@app.route("/demo/autotrade")
def demo_autotrade():
    """หน้าให้ลูกค้าเปิดดูผลเทรดกระดาษแบบสด"""
    _track_visit()
    p = os.path.join(os.path.dirname(__file__), "demo_autotrade.html")
    with open(p, "r", encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}


# ---------- Demo ลูกค้าจริง (config แยกร้าน) ----------

@app.route("/static/<path:sub>")
def client_static(sub):
    """รูปผลงานของลูกค้า"""
    from flask import send_from_directory
    return send_from_directory(os.path.join(os.path.dirname(__file__), "static"), sub)


@app.route("/demo/client/<slug>")
def demo_client(slug):
    """
    Demo ของลูกค้าจริง — อ่าน configs/<slug>.json แล้วยัดเข้า demo_salon.html
    เพิ่มร้านใหม่ = เพิ่มไฟล์ config ไฟล์เดียว ไม่ต้องแตะโค้ด
    """
    from flask import abort
    base = os.path.dirname(__file__)
    # อ่าน config ผ่าน meta_bot (DB-first + file fallback) — ร้านใหม่ที่มีแค่ config ใน DB เปิด demo ได้เลย
    if "/" in slug or ".." in slug or not meta_bot.cfg_exists(slug):
        abort(404)
    _track_visit()
    cfg = meta_bot.load_cfg(slug)
    with open(os.path.join(base, "demo_salon.html"), "r", encoding="utf-8") as f:
        html = f.read()
    for k, v in {
        "__BIZ_NAME__": cfg.get("biz_name", ""),
        "__TAGLINE__": cfg.get("tagline", ""),
        "__EMOJI__": cfg.get("emoji", "✨"),
        "__ACCENT__": cfg.get("accent", "#c08268"),
        "__ACCENT_SOFT__": cfg.get("accent_soft", "#f6ece6"),
        "__CONFIG__": json.dumps(cfg, ensure_ascii=False),
    }.items():
        html = html.replace(k, v)
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/demo/chat/<slug>")
def demo_chat_page(slug):
    """
    Demo แชทจำลองหน้าจอ LINE — ใช้ AI จริงตัวเดียวกับที่ตอบลูกค้าจริง (ผ่าน meta_bot)
    ต่างจาก /demo/client/<slug> (demo_salon.html) ตรงที่นี่เป็น AI จริง ไม่ใช่สคริปต์ปุ่มกด
    """
    from flask import abort
    base = os.path.dirname(__file__)
    # อ่าน config ผ่าน meta_bot (DB-first + file fallback) — preview ร้านใหม่จาก DB ได้ทันทีหลังกรอกฟอร์ม
    if "/" in slug or ".." in slug or not meta_bot.cfg_exists(slug):
        abort(404)
    _track_visit()
    cfg = meta_bot.load_cfg(slug)
    with open(os.path.join(base, "demo_chat_template.html"), "r", encoding="utf-8") as f:
        html = f.read()
    for k, v in {
        "{{BIZ_NAME}}": cfg.get("biz_name", ""),
        "{{TAGLINE}}": cfg.get("tagline", ""),
        "{{EMOJI}}": cfg.get("emoji", "✨"),
        "{{ACCENT}}": cfg.get("accent", "#06C755"),
        "{{ACCENT_SOFT}}": cfg.get("accent_soft", "#e3f2e1"),
        "{{SLUG}}": slug,
        "{{GREETING_JSON}}": json.dumps(cfg.get("greeting", "สวัสดีค่ะ"), ensure_ascii=False),
    }.items():
        html = html.replace(k, v)
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/api/demo/chat/<slug>", methods=["POST"])
def demo_chat_api(slug):
    """
    รับข้อความจากหน้า demo แชท → ตอบด้วย AI จริง (ใช้ advisor logic เดียวกับ meta_bot)
    ⚠️ endpoint นี้เปิดสาธารณะ = ทุกครั้งที่ถูกเรียก เราจ่ายเงิน — ต้องมี rate limit เสมอ
    """
    # อ่าน config ผ่าน meta_bot (DB-first + file fallback) — demo แชทของร้านใหม่จาก DB ใช้ได้ทันที
    if "/" in slug or ".." in slug or not meta_bot.cfg_exists(slug):
        return jsonify({"success": False, "error": "ไม่พบร้านนี้"}), 404
    if not ANTHROPIC_API_KEY:
        return jsonify({"success": False, "error": "ไม่ได้ตั้ง ANTHROPIC_API_KEY"}), 400

    ok, left = ai_guard.rate_limit(ai_guard.client_ip(request) + f":demo:{slug}",
                                   limit=int(os.environ.get("DEMO_CHAT_LIMIT", "20")))
    if not ok:
        return jsonify({
            "success": False,
            "error": "ลองพิมพ์ไปเยอะแล้ววันนี้ครับ 😊 พรุ่งนี้ลองใหม่ได้ หรือทักเราคุยต่อได้เลย",
            "rate_limited": True,
        }), 429

    d = request.get_json(force=True) or {}
    user_text = (d.get("message") or "").strip()[:500]
    session_id = (d.get("session_id") or "anon").strip()[:80]
    if not user_text:
        return jsonify({"success": False, "error": "ไม่มีข้อความ"}), 400

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        cfg = meta_bot.load_cfg(slug)
        reply, promo_choices = meta_bot.generate_reply(client, cfg, f"demo:{slug}:{session_id}", user_text,
                                        notify_fn=_push_line, line_user_id=LINE_USER_ID, slug=slug)
        return jsonify({"success": True, "reply": reply, "promo_choices": promo_choices or []})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": "ขออภัยค่ะ ระบบขัดข้องชั่วคราว"}), 500


@app.route("/api/links")
def api_links():
    """ประตูทุกบานที่ต้องเข้าไปทำงาน (แก้ที่ links.json)"""
    try:
        p = os.path.join(os.path.dirname(__file__), "links.json")
        with open(p, "r", encoding="utf-8") as f:
            return jsonify({"ok": True, **json.load(f)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 200


@app.route("/api/board")
def api_board():
    """เงินเข้า-ออก + งานค้าง (แก้ที่ board.json)"""
    try:
        p = os.path.join(os.path.dirname(__file__), "board.json")
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        d["orders_new"] = _count_botkit_orders_new()
        return jsonify({"ok": True, **d})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 200


@app.route("/api/pulse")
def api_pulse():
    """
    ไฟสถานะระบบทั้งหมดในที่เดียว — เขียว/แดง รู้ทันทีว่ามีอะไรตายไหม
    เกิดจากบทเรียน 18 ก.ค.: Job Hunter ตายเงียบ 1 วันเต็มโดยไม่มีใครรู้
    """
    from datetime import timezone
    h = ai_guard.health()
    out = {"ok": True, "checks": []}

    # 1) AI ยังหายใจไหม — ตัวนี้ตาย = ทุกอย่างตายตาม
    out["checks"].append({
        "name": "AI (Claude)", "ok": bool(ANTHROPIC_API_KEY) and h["ok"],
        "detail": ("ปกติ" if h["ok"] else f"ล้มเหลว: {(h.get('last_error') or '')[:60]}")
                  if ANTHROPIC_API_KEY else "ไม่ได้ตั้ง key",
        "fix": "https://platform.claude.com/settings/billing",
    })

    # 2) Auto-Execution เดินอยู่ไหม
    try:
        from auto_execution import runner
        s = runner.state()
        out["checks"].append({
            "name": "Auto-Execution", "ok": bool(s.get("ok")),
            "detail": f"PAPER · เปิด {s.get('open_count',0)} ไม้ · ปิดแล้ว {s.get('total_closed',0)}",
        })
    except Exception as e:
        out["checks"].append({"name": "Auto-Execution", "ok": False, "detail": str(e)[:60]})

    # 3) SEO ถึงขั้นไหน
    try:
        s = seo_tracker.summary()
        out["checks"].append({
            "name": "SEO", "ok": bool(s.get("ok")),
            "detail": s.get("label", "-") if s.get("ok") else "ยังไม่พร้อม",
        })
    except Exception:
        out["checks"].append({"name": "SEO", "ok": False, "detail": "-"})

    # 4) Supabase ต่อติดไหม
    out["checks"].append({
        "name": "ฐานข้อมูล", "ok": seo_tracker.is_configured(),
        "detail": "Supabase เชื่อมแล้ว" if seo_tracker.is_configured() else "ไม่ได้ตั้งค่า",
    })

    out["all_ok"] = all(c["ok"] for c in out["checks"])
    out["ai_calls"] = h.get("calls", 0)
    out["ai_fails"] = h.get("fails", 0)
    return jsonify(out)


def _build_daily_summary_text() -> str:
    """รวมสถานะธุรกิจสั้นๆ — เงิน/ดีล, roadmap, hunter, SEO, AI health"""
    lines = ["📊 สรุปสถานะธุรกิจวันนี้", "━━━━━━━━━━━━"]

    try:
        p = os.path.join(os.path.dirname(__file__), "board.json")
        with open(p, "r", encoding="utf-8") as f:
            board = json.load(f)
        won = [d for d in board.get("deals", []) if d.get("state") == "won"]
        won_total = sum(d.get("amount", 0) for d in won)
        urgent = [x for x in board.get("pending", []) if x.get("urgent")]
        lines.append(f"💰 ปิดแล้ว {len(won)} ดีล (฿{won_total:,}) · ค้างด่วน {len(urgent)} เรื่อง")
        for u in urgent[:3]:
            lines.append(f"  ⚠️ {(u.get('t') or '')[:60]}")
    except Exception:
        lines.append("💰 อ่าน board.json ไม่ได้")

    try:
        p = os.path.join(os.path.dirname(__file__), "roadmap.json")
        with open(p, "r", encoding="utf-8") as f:
            roadmap = json.load(f)
        active = next((ph for ph in roadmap.get("phases", []) if ph.get("status") == "active"), None)
        if active:
            lines.append(f"🎯 เป้าตอนนี้: {(active.get('goal') or '')[:70]}")
    except Exception:
        pass

    try:
        checked = len(fastwork_hunter.get_hunter_log())
        alerts = sum(1 for e in fastwork_hunter.get_hunter_log() if e.get("alerted"))
        lines.append(f"🕵️ Job Hunter: เช็คแล้ว {checked} งาน · แจ้งเตือน {alerts} งาน")
    except Exception:
        pass

    try:
        s = seo_tracker.summary()
        lines.append(f"🔍 SEO: {s.get('label', '-') if s.get('ok') else 'ยังไม่พร้อม'}")
    except Exception:
        pass

    try:
        h = ai_guard.health()
        lines.append(f"🤖 AI: {'ปกติ ✅' if h.get('ok') else '❌ มีปัญหา — เช็คด่วน'}")
    except Exception:
        pass

    lines.append("━━━━━━━━━━━━")
    lines.append("เปิด /monitor เพื่อดูรายละเอียดเต็ม")
    return "\n".join(lines)


@app.route("/api/daily-summary", methods=["GET", "POST"])
def daily_summary():
    """สรุปสถานะธุรกิจประจำวัน ส่ง LINE ให้เจ้าของ — เรียกจาก scheduled task ทุกเช้า"""
    if not LINE_TOKEN or not LINE_USER_ID:
        return jsonify({"success": False, "error": "missing LINE env keys"}), 500
    try:
        text = _build_daily_summary_text()
        ok = _push_line(LINE_USER_ID, text)
        return jsonify({"success": ok, "message": text})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/gemini-diag")
def api_gemini_diag():
    """วินิจฉัย Gemini 404 (22 ก.ค. 2026) — ถาม Google ตรงๆ ว่า key นี้ใช้โมเดลไหนได้บ้าง
    แล้วเทียบกับที่เราตั้งไว้ ตอบได้ทันทีว่าปัญหาอยู่ที่ "ชื่อโมเดลล้าสมัย" หรือ "key/โปรเจกต์"
    — ไม่คืนค่า key ออกไป คืนแค่ชื่อโมเดลกับ error message"""
    try:
        return jsonify(ai_guard.gemini_diag())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 500


@app.route("/api/ai-health")
def api_ai_health():
    """AI ยังหายใจอยู่ไหม — ใช้ดูบน Monitor + ให้ cron เช็คได้
    ?slug=lullabell = ดูเฉพาะร้านนั้น | ?all=1 = ดูแยกทุกร้าน {slug: health} | ไม่ใส่ = สรุปรวมทุกร้าน (ของเดิม)"""
    if request.args.get("all"):
        out = ai_guard.health_all()
        out["has_key"] = bool(ANTHROPIC_API_KEY)
        out["model_smart"] = ai_guard.MODEL_SMART
        out["model_cheap"] = ai_guard.MODEL_CHEAP
        return jsonify(out)
    slug = request.args.get("slug") or None
    h = ai_guard.health(slug)
    h["has_key"] = bool(ANTHROPIC_API_KEY)
    h["model_smart"] = ai_guard.MODEL_SMART
    h["model_cheap"] = ai_guard.MODEL_CHEAP
    return jsonify(h)


@app.route("/api/seo")
def api_seo():
    """สถานะ SEO — คนมาจาก Google กี่คน, Googlebot มาแล้วยัง"""
    try:
        return jsonify(seo_tracker.summary())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 200


@app.route("/robots.txt")
def robots():
    txt = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /monitor\n"          # จอภายใน ไม่ให้ index
        "Disallow: /hunter\n"           # เครื่องมือภายใน
        "Disallow: /demo/dialysis\n"    # มีข้อมูลคนไข้ ห้าม index เด็ดขาด
        "Disallow: /api/\n"
        f"\nSitemap: {BASE_URL}/sitemap.xml\n"
    )
    return txt, 200, {"Content-Type": "text/plain; charset=utf-8"}


# ไฟล์ยืนยันความเป็นเจ้าของเว็บ ของ Google Search Console — ห้ามลบ!
GSC_TOKEN = "google4f947fb5ceb78f37"


@app.route(f"/{GSC_TOKEN}.html")
def google_verify():
    return (f"google-site-verification: {GSC_TOKEN}.html", 200,
            {"Content-Type": "text/html; charset=utf-8"})


# ไฟล์ยืนยันความเป็นเจ้าของเว็บ ของ TikTok Developer Portal (แอป Claude) — ห้ามลบ!
TIKTOK_VERIFY_FILE = "tiktokBmkFqhvxApalltojJvDf2rJpKZwVGl7O.txt"
TIKTOK_VERIFY_TOKEN = "BmkFqhvxApalltojJvDf2rJpKZwVGl7O"


@app.route(f"/{TIKTOK_VERIFY_FILE}")
def tiktok_verify():
    return (f"tiktok-developers-site-verification={TIKTOK_VERIFY_TOKEN}", 200,
            {"Content-Type": "text/plain; charset=utf-8"})


@app.route("/api/meta-health")
def meta_health():
    """เช็คสุขภาพ token บอท Meta (Lullabell) — ใช้บนการ์ด Monitor
    ถ้าตั้ง META_APP_SECRET จะบอกวันหมดอายุ token ด้วย"""
    if not META_PAGE_TOKEN:
        return jsonify({"ok": False, "error": "no META_PAGE_TOKEN"})
    out = {"ok": False}
    try:
        r = requests.get(f"{meta_bot.GRAPH}/me",
                         params={"access_token": META_PAGE_TOKEN, "fields": "name,id"},
                         timeout=10)
        d = r.json()
        if r.ok:
            out["ok"] = True
            out["page"] = d.get("name")
        else:
            out["error"] = ((d.get("error") or {}).get("message") or "")[:200]
        # ถ้ามี app secret → ถาม Meta ตรงๆ ว่า token หมดอายุเมื่อไหร่ (0 = ไม่มีกำหนด)
        if META_APP_SECRET:
            app_id = os.environ.get("META_APP_ID", "1558681259271673")
            rd = requests.get(f"{meta_bot.GRAPH}/debug_token",
                              params={"input_token": META_PAGE_TOKEN,
                                      "access_token": f"{app_id}|{META_APP_SECRET}"},
                              timeout=10)
            dd = (rd.json().get("data") or {}) if rd.ok else {}
            out["expires_at"] = dd.get("expires_at")                    # 0 = never
            out["data_access_expires_at"] = dd.get("data_access_expires_at")
            out["scopes"] = dd.get("scopes", [])
            out["has_publish_scope"] = "pages_manage_posts" in out["scopes"]
    except Exception as e:
        out["error"] = str(e)[:200]
    return jsonify(out)


@app.route("/api/n8n/facebook-post", methods=["POST"])
def n8n_facebook_post():
    """n8n เรียกมาเพื่อโพสต์แคปชั่นลงเพจ Facebook ตรงผ่าน Graph API
    บายพาส Postiz (มีบั๊ก hardcode scope เก่า read_insights ที่ Meta เลิกรองรับแล้ว)
    ต้องส่ง secret ให้ตรงกับ N8N_POST_SECRET ที่ตั้งไว้บน Render"""
    if not N8N_POST_SECRET:
        return jsonify({"success": False, "error": "N8N_POST_SECRET ยังไม่ได้ตั้งบน Render"}), 503
    body = request.get_json(silent=True) or {}
    got_secret = (body.get("secret") or "").strip()
    if got_secret != N8N_POST_SECRET.strip():
        # ไม่โชว์ค่าจริงเพื่อความปลอดภัย แต่บอกความยาวช่วย debug เคส copy-paste เผลอมีช่องว่าง/ตัดตัวอักษร
        return jsonify({
            "success": False, "error": "invalid secret",
            "hint": f"ได้รับ {len(got_secret)} ตัวอักษร ต้องการ {len(N8N_POST_SECRET.strip())} ตัวอักษร"
        }), 403
    message = (body.get("message") or "").strip()
    if not message:
        return jsonify({"success": False, "error": "missing message"}), 400
    ok, result = meta_bot.post_to_facebook_page(
        META_PAGE_TOKEN, META_PAGE_ID, message, link=body.get("link"))
    if ok:
        return jsonify({"success": True, "post_id": result})
    return jsonify({"success": False, "error": result}), 502


@app.route("/webhook/meta", methods=["GET", "POST"])
def meta_webhook():
    """Facebook Messenger + Instagram DM webhook สำหรับบอทร้านลูกค้า (Lullabell)"""
    # --- GET: ยืนยัน webhook (hub challenge) ---
    if request.method == "GET":
        if (request.args.get("hub.mode") == "subscribe"
                and request.args.get("hub.verify_token") == META_VERIFY_TOKEN
                and META_VERIFY_TOKEN):
            return request.args.get("hub.challenge", ""), 200
        return "forbidden", 403

    # --- POST: รับ event ข้อความ ---
    body = request.get_data()
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not meta_bot.verify_signature(META_APP_SECRET, body, sig):
        return "bad signature", 403
    try:
        data = json.loads(body or b"{}")
    except Exception:
        return "bad json", 400

    # ---- Lullabell แยกดีพลอยแล้ว (21 ก.ค. 2026): ถ้า event นี้มาจากเพจ Lullabell ให้ forward
    # raw body + signature ไปยัง service เดี่ยวแทน ไม่ handle เองที่นี่ (กันตอบซ้ำ 2 รอบ)
    # ลายเซ็นยัง valid ที่ปลายทางเพราะ META_APP_SECRET เป็นค่าเดียวกัน (App เดียวกัน)
    # ทำงานเฉพาะเมื่อตั้ง LULLABELL_FORWARD_URL — ถ้าไม่ตั้ง Lullabell ตอบในนี้ตามปกติ (multi-tenant)
    if LULLABELL_FORWARD_URL:
        entry_ids = {str(e.get("id", "")) for e in data.get("entry", [])}
        if LULLABELL_PAGE_ID in entry_ids:
            try:
                requests.post(LULLABELL_FORWARD_URL, data=body,
                              headers={"X-Hub-Signature-256": sig,
                                       "Content-Type": request.headers.get("Content-Type", "application/json")},
                              timeout=8)
            except Exception as e:
                traceback.print_exc()
                print("[meta_webhook] forward to lullabell-bot failed:", str(e)[:200])
            return "EVENT_RECEIVED", 200

    # ตอบเฉพาะ object ที่เกี่ยวกับข้อความ (page = Messenger, instagram = IG DM)
    if data.get("object") in ("page", "instagram"):
        try:
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            meta_bot.handle(data, client, page_token=META_PAGE_TOKEN,
                            slug=META_SLUG, notify_fn=_push_line,
                            line_user_id=LINE_USER_ID)
        except Exception as e:
            traceback.print_exc()
            # ตอบ 200 เสมอ ไม่งั้น Meta จะ retry รัวๆ
            print("[meta_webhook] error:", str(e)[:200])
    return "EVENT_RECEIVED", 200


@app.route("/api/admin/warm-attachment")
def api_admin_warm_attachment():
    """อัปโหลดรูป (เช่น การ์ดแผนที่ร้าน) เข้า Meta แบบ reusable ครั้งเดียว ได้ attachment_id กลับมา
    ใส่ใน config (contact.map_attachment_id) แทนการส่ง url ตรงๆ ทุกครั้ง — กัน Meta fetch url เราไม่ทัน
    ตอน Render free tier เพิ่งตื่นจาก spin-down (สาเหตุ error #100/2018007 'Upload failed' ที่เจอ 20 ก.ค.)
    เรียกครั้งเดียวตอนตั้งค่า ป้องกันด้วย META_VERIFY_TOKEN เดิม (ของที่มีอยู่แล้ว ไม่ต้องเพิ่ม secret ใหม่)
    รองรับ ?image_url=<url> override เพื่อ diagnose ว่าปัญหาเจาะจงกับ url ของเรา หรือเป็นที่ token/permission ฝั่ง Meta
    self_fetch = เราลองโหลด url นั้นเองก่อน (เห็น status/content-type/size จริงตามที่ Meta น่าจะเห็น)"""
    token = request.args.get("token", "")
    if not token or token != META_VERIFY_TOKEN or not META_VERIFY_TOKEN:
        return jsonify({"ok": False, "error": "unauthorized"}), 403
    slug = request.args.get("slug", "lullabell")
    override_url = request.args.get("image_url", "")
    # platform=instagram → อัปโหลดแยกสำหรับ IG โดยเฉพาะ (attachment_id ปกติ/ไม่ระบุ platform ผูกกับ FB
    # เท่านั้น IG resolve ไม่ได้ — เจอจริง 21 ก.ค. รูปขึ้น FB แต่ไม่ขึ้น IG)
    platform = request.args.get("platform", "")
    # multi-tenant (21 ก.ค. 2026): ร้านใหม่ที่ไม่ใช่ Lullabell ต้อง warm ด้วย page_token ของร้านตัวเอง
    # ไม่ใช่ META_PAGE_TOKEN — ถ้าไม่ใส่ ?page_token= มา ใช้ META_PAGE_TOKEN เดิม (พฤติกรรมเดิมเป๊ะ)
    override_token = request.args.get("page_token", "") or META_PAGE_TOKEN
    try:
        cfg = meta_bot.load_cfg(slug)
        image_url = override_url or cfg.get("contact", {}).get("map_image", "")
        if not image_url:
            return jsonify({"ok": False, "error": "no map_image in config"}), 400

        self_fetch = {}
        try:
            hr = requests.get(image_url, timeout=15, headers={"User-Agent": "facebookexternalhit/1.1"})
            self_fetch = {
                "status": hr.status_code,
                "content_type": hr.headers.get("Content-Type"),
                "content_length": hr.headers.get("Content-Length") or len(hr.content),
            }
        except Exception as e:
            self_fetch = {"error": str(e)[:200]}

        status, resp = meta_bot.upload_reusable_attachment(override_token, image_url, platform=platform)
        ok = status == 200
        attachment_id = None
        if ok:
            try:
                attachment_id = json.loads(resp).get("attachment_id")
            except Exception:
                pass
        return jsonify({"ok": ok, "status": status, "response": resp, "attachment_id": attachment_id,
                         "image_url": image_url, "self_fetch": self_fetch})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 500


@app.route("/api/admin/token-info")
def api_admin_token_info():
    """เช็ค scope/สิทธิ์จริงของ META_PAGE_TOKEN ผ่าน Meta debug_token API
    ตั้งใจ diagnose error (#100) Upload failed / 2018007 ที่เกิดกับทุก url (แม้ url ภายนอกที่รู้ว่า
    ใช้ได้แน่ๆ ก็พังเหมือนกัน — ตัดปัจจัย url/hosting ของเราทิ้งไปแล้ว 20 ก.ค.) เหลือทางที่เป็นไปได้คือ
    token หมด scope/permission สำหรับส่ง attachment (pages_messaging ระดับ Advanced Access)
    ป้องกันด้วย META_VERIFY_TOKEN เดิม"""
    token = request.args.get("token", "")
    if not token or token != META_VERIFY_TOKEN or not META_VERIFY_TOKEN:
        return jsonify({"ok": False, "error": "unauthorized"}), 403
    # multi-tenant (21 ก.ค. 2026): เช็ค token ของร้านอื่นได้ด้วย ?page_token= override (ไม่ใส่ = META_PAGE_TOKEN เดิม)
    check_token = request.args.get("page_token", "") or META_PAGE_TOKEN
    try:
        r = requests.get(f"{meta_bot.GRAPH}/debug_token",
                          params={"input_token": check_token, "access_token": check_token},
                          timeout=15)
        return jsonify({"status": r.status_code, "data": r.json()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 500


@app.route("/api/admin/add-shop-page", methods=["POST"])
def api_admin_add_shop_page():
    """ลงทะเบียน page_id ใหม่ -> slug/page_token ในตาราง shop_pages (multi-tenant routing,
    นกน้อยพิมพ์รัง เฟส 2 — 21 ก.ค. 2026) ทำให้รับร้านใหม่ = แค่เพิ่มแถวข้อมูล ไม่ต้อง deploy
    service ใหม่/ตั้ง env var ชุดใหม่ต่อร้านอีกต่อไป (แต่ configs/{slug}.json ยังต้อง commit เข้า repo
    เหมือนเดิม — ยังไม่ได้ย้าย config เข้า DB รอบนี้)
    ป้องกันด้วย META_VERIFY_TOKEN เดิม (ของที่มีอยู่แล้ว ไม่ต้องเพิ่ม secret ใหม่)
    body: {"token": "...", "page_id": "...", "slug": "...", "page_token": "...",
           "platform": "facebook|instagram" (ไม่บังคับ), "note": "..." (ไม่บังคับ)}"""
    body = request.get_json(silent=True) or {}
    token = request.args.get("token", "") or body.get("token", "")
    if not token or token != META_VERIFY_TOKEN or not META_VERIFY_TOKEN:
        return jsonify({"ok": False, "error": "unauthorized"}), 403
    page_id = (body.get("page_id") or "").strip()
    slug = (body.get("slug") or "").strip()
    page_token = (body.get("page_token") or "").strip()
    if not (page_id and slug and page_token):
        return jsonify({"ok": False, "error": "need page_id, slug, page_token"}), 400
    ok, err = meta_bot.upsert_page_mapping(
        page_id, slug, page_token,
        platform=body.get("platform", ""), note=body.get("note", ""))
    return jsonify({"ok": ok, "error": err or None})


@app.route("/api/admin/list-shop-pages")
def api_admin_list_shop_pages():
    """ดู mapping page_id -> slug ปัจจุบันทั้งหมดใน shop_pages — ไว้เช็คตอนตั้งค่า/ดีบัก
    ป้องกันด้วย META_VERIFY_TOKEN เดิม (ตัด page_token จริงออกจาก response กันหลุด แสดงแค่ 8 ตัวท้าย)"""
    token = request.args.get("token", "")
    if not token or token != META_VERIFY_TOKEN or not META_VERIFY_TOKEN:
        return jsonify({"ok": False, "error": "unauthorized"}), 403
    rows = meta_bot.list_page_mappings()
    safe_rows = [{**r, "page_token": f"...{(r.get('page_token') or '')[-8:]}"} for r in rows]
    return jsonify({"ok": True, "count": len(safe_rows), "shops": safe_rows})


@app.route("/api/admin/reload-page-map", methods=["POST"])
def api_admin_reload_page_map():
    """บังคับรีเฟรช cache ในแรมของ page map ทันที (ข้าม TTL 5 นาที) — เรียกทันทีหลัง add-shop-page
    ตอนตั้งค่าร้านใหม่ จะได้ไม่ต้องรอ ป้องกันด้วย META_VERIFY_TOKEN เดิม"""
    token = request.args.get("token", "")
    if not token or token != META_VERIFY_TOKEN or not META_VERIFY_TOKEN:
        return jsonify({"ok": False, "error": "unauthorized"}), 403
    meta_bot._load_page_map(force=True)
    return jsonify({"ok": True, "loaded": len(meta_bot._page_map)})


@app.route("/webhook/line/lullabell", methods=["POST"])
def lullabell_line_webhook():
    """LINE OA webhook ของร้านลูกค้า (@lullabell) — ใช้ AI advisor ตัวเดียวกับ /webhook/meta
    คนละ endpoint กับ /webhook เดิม (นั่นคือ LINE OA ของ ForexAI Pro เอง — คนละ Channel Secret/Token)"""
    body = request.get_data()
    sig = request.headers.get("X-Line-Signature", "")
    if not meta_bot.verify_line_signature(LULLABELL_LINE_CHANNEL_SECRET, body, sig):
        return jsonify({"message": "invalid signature"}), 403
    try:
        data = json.loads(body or b"{}")
    except Exception:
        return jsonify({"message": "bad json"}), 400

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        meta_bot.handle_line(data, client, channel_token=LULLABELL_LINE_CHANNEL_TOKEN,
                              slug=META_SLUG, notify_fn=_push_line,
                              line_user_id=LINE_USER_ID)
    except Exception as e:
        traceback.print_exc()
        print("[lullabell_line_webhook] error:", str(e)[:200])
    return jsonify({"message": "ok"}), 200


# ===== E-commerce admin proxy (ปลอดภัย: service role + PIN แทน anon key) =====
def _ec_pin_ok() -> bool:
    pin = request.args.get("pin", "") or (request.get_json(silent=True) or {}).get("pin", "")
    return bool(EC_ADMIN_PIN) and pin == EC_ADMIN_PIN


def _ec_sb_headers() -> dict:
    return {"apikey": seo_tracker.SUPABASE_KEY,
            "Authorization": f"Bearer {seo_tracker.SUPABASE_KEY}",
            "Content-Type": "application/json"}


@app.route("/api/ec/orders")
def ec_orders():
    if not _ec_pin_ok():
        return jsonify({"error": "unauthorized"}), 403
    r = requests.get(f"{seo_tracker.SUPABASE_URL}/rest/v1/ec_orders?select=*&order=created_at.desc",
                     headers=_ec_sb_headers(), timeout=15)
    return (r.text, r.status_code, {"Content-Type": "application/json"})


@app.route("/api/ec/order-items")
def ec_order_items():
    if not _ec_pin_ok():
        return jsonify({"error": "unauthorized"}), 403
    oid = re.sub(r"[^0-9]", "", request.args.get("order_id", ""))
    if not oid:
        return jsonify({"error": "bad order_id"}), 400
    r = requests.get(f"{seo_tracker.SUPABASE_URL}/rest/v1/ec_order_items?order_id=eq.{oid}&select=*",
                     headers=_ec_sb_headers(), timeout=15)
    return (r.text, r.status_code, {"Content-Type": "application/json"})


@app.route("/api/ec/products")
def ec_products_proxy():
    if not _ec_pin_ok():
        return jsonify({"error": "unauthorized"}), 403
    r = requests.get(f"{seo_tracker.SUPABASE_URL}/rest/v1/ec_products?select=*&order=id.asc",
                     headers=_ec_sb_headers(), timeout=15)
    return (r.text, r.status_code, {"Content-Type": "application/json"})


@app.route("/api/ec/order-status", methods=["POST"])
def ec_order_status():
    if not _ec_pin_ok():
        return jsonify({"error": "unauthorized"}), 403
    d = request.get_json(force=True) or {}
    oid = re.sub(r"[^0-9]", "", str(d.get("id", "")))
    status = d.get("status", "")
    if not oid or status not in ("pending", "confirmed", "shipping", "delivered", "cancelled"):
        return jsonify({"error": "bad id/status"}), 400
    r = requests.patch(f"{seo_tracker.SUPABASE_URL}/rest/v1/ec_orders?id=eq.{oid}",
                       headers={**_ec_sb_headers(), "Prefer": "return=minimal"},
                       json={"status": status}, timeout=15)
    return (r.text or "{}", r.status_code, {"Content-Type": "application/json"})


@app.route("/privacy")
def privacy_page():
    """Privacy Policy — จำเป็นสำหรับ Meta App Review (ห้ามลบ)"""
    p = os.path.join(os.path.dirname(__file__), "privacy.html")
    with open(p, "r", encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/data-deletion")
def data_deletion_page():
    """Data Deletion Instructions — จำเป็นสำหรับ Meta App Review (ห้ามลบ)"""
    p = os.path.join(os.path.dirname(__file__), "data_deletion.html")
    with open(p, "r", encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/portfolio")
def portfolio_page():
    """หน้า Portfolio รวมผลงาน (ส่งลูกค้า FastWork) — render จาก portfolio.json · เพิ่มผลงาน = แก้ JSON · ห้ามลบ"""
    base = os.path.dirname(__file__)
    with open(os.path.join(base, "portfolio.html"), "r", encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(base, "portfolio.json"), "r", encoding="utf-8") as f:
        data = f.read()
    html = html.replace("/*__PORTFOLIO_DATA__*/ {}", data)
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/posttoday")
def posttoday_page():
    """Landing สำหรับแอป TikTok Content Posting (Website URL ที่ยื่น App Review) — ห้ามลบ"""
    p = os.path.join(os.path.dirname(__file__), "posttoday.html")
    with open(p, "r", encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/posttoday/privacy")
def posttoday_privacy_page():
    """Privacy Policy สำหรับ TikTok App Review — ห้ามลบ"""
    p = os.path.join(os.path.dirname(__file__), "posttoday_privacy.html")
    with open(p, "r", encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/posttoday/terms")
def posttoday_terms_page():
    """Terms of Service สำหรับ TikTok App Review — ห้ามลบ"""
    p = os.path.join(os.path.dirname(__file__), "posttoday_terms.html")
    with open(p, "r", encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}


# ===== TikTok OAuth (PKCE) — Redirect URI ที่ยื่นใน TikTok Developer Portal (แอป Claude) — ห้ามลบ =====
# ต้องตั้ง env vars บน Render: TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET (ค่าเดียวกับใน Developer Portal > Credentials)

@app.route("/posttoday/login")
def posttoday_login():
    """เริ่ม OAuth2 PKCE flow — ปุ่ม 'Connect TikTok' บนเว็บกดมาที่นี่"""
    if not (TIKTOK_CLIENT_KEY):
        return "TikTok ยังไม่ได้ตั้งค่า (ขาด TIKTOK_CLIENT_KEY ใน env)", 500

    state = _secrets.token_urlsafe(16)
    code_verifier = _secrets.token_urlsafe(64)
    code_challenge = hashlib.sha256(code_verifier.encode()).hexdigest()

    session["tiktok_state"] = state
    session["tiktok_code_verifier"] = code_verifier

    redirect_uri = f"{BASE_URL}/posttoday/callback"
    auth_url = "https://www.tiktok.com/v2/auth/authorize/?" + "&".join(
        f"{k}={requests.utils.quote(str(v), safe='')}" for k, v in {
            "client_key": TIKTOK_CLIENT_KEY,
            "scope": "video.publish,video.upload,user.info.basic",
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }.items()
    )
    return redirect(auth_url)


@app.route("/posttoday/callback")
def posttoday_callback():
    """รับ OAuth callback จาก TikTok → แลก code เป็น token → แสดงผลสำเร็จ — ห้ามลบ (คือ Redirect URI ที่ยื่นไว้)"""
    error = request.args.get("error")
    if error:
        return f"<h2>❌ TikTok ปฏิเสธการเชื่อมต่อ: {error}</h2><a href='/posttoday'>กลับ</a>", 400

    code = request.args.get("code")
    state = request.args.get("state")
    if not code or not state or state != session.get("tiktok_state"):
        return "<h2>❌ state ไม่ตรงกัน หรือไม่มี code (session อาจหมดอายุ ลองเชื่อมต่อใหม่)</h2><a href='/posttoday'>กลับ</a>", 400

    code_verifier = session.get("tiktok_code_verifier", "")
    redirect_uri = f"{BASE_URL}/posttoday/callback"

    try:
        resp = requests.post(
            "https://open.tiktokapis.com/v2/oauth/token/",
            data={
                "client_key": TIKTOK_CLIENT_KEY,
                "client_secret": TIKTOK_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        data = resp.json()
    except Exception as e:
        return f"<h2>❌ แลก token ไม่สำเร็จ: {e}</h2><a href='/posttoday'>กลับ</a>", 500

    if resp.status_code != 200 or "access_token" not in data:
        return f"<h2>❌ แลก token ไม่สำเร็จ</h2><pre>{json.dumps(data, indent=2, ensure_ascii=False)}</pre><a href='/posttoday'>กลับ</a>", 400

    # เคลียร์ state/verifier หลังใช้เสร็จ (แต่เก็บ access_token ไว้ใช้ต่อตอนเลือกวิดีโอ+publish)
    session.pop("tiktok_state", None)
    session.pop("tiktok_code_verifier", None)
    session["tiktok_access_token"] = data["access_token"]
    session["tiktok_open_id"] = data.get("open_id", "")

    display_name = ""
    try:
        u = requests.get(
            "https://open.tiktokapis.com/v2/user/info/",
            params={"fields": "display_name,username"},
            headers={"Authorization": f"Bearer {data['access_token']}"},
            timeout=15,
        ).json().get("data", {}).get("user", {})
        display_name = u.get("display_name", "")
    except Exception:
        pass

    return f"""<!DOCTYPE html><html lang="th"><head><meta charset="UTF-8">
    <title>เชื่อมต่อ TikTok สำเร็จ</title>
    <style>body{{font-family:sans-serif;background:#0d1117;color:#e9edf2;display:flex;height:100vh;align-items:center;justify-content:center;text-align:center}}
    a{{color:#4ea1ff}} .btn{{display:inline-block;margin-top:18px;padding:12px 26px;background:#fe2c55;color:#fff;
    border-radius:999px;text-decoration:none;font-weight:700}}</style></head><body>
    <div><h2>✓ เชื่อมต่อ TikTok สำเร็จ{f' — สวัสดีคุณ {display_name}' if display_name else ''}</h2>
    <a class="btn" href="/posttoday/publish">ถัดไป: เลือกวิดีโอ →</a>
    <p style="margin-top:14px"><a href="/posttoday">กลับหน้าแรก</a></p></div>
    </body></html>""", 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/posttoday/publish", methods=["GET"])
def posttoday_publish_page():
    """หน้าเลือกวิดีโอ + แคปชั่น + privacy level (ดึงตัวเลือกจริงจาก TikTok creator_info) — ห้ามลบ"""
    token = session.get("tiktok_access_token")
    if not token:
        return redirect("/posttoday/login")

    try:
        r = requests.post(
            "https://open.tiktokapis.com/v2/post/publish/creator_info/query/",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
            timeout=20,
        )
        cinfo = r.json().get("data", {}) or {}
    except Exception as e:
        return f"<h2>❌ ดึงข้อมูลบัญชี TikTok ไม่สำเร็จ: {e}</h2><a href='/posttoday'>กลับ</a>", 500

    privacy_options = cinfo.get("privacy_level_options") or ["SELF_ONLY"]
    nickname = cinfo.get("creator_nickname", "")
    options_html = "\n".join(
        f'<option value="{p}">{p}</option>' for p in privacy_options
    )

    return f"""<!DOCTYPE html><html lang="th"><head><meta charset="UTF-8">
<title>เลือกวิดีโอ — PostToday</title>
<style>
:root{{--bg:#0e0e14;--card:#181822;--accent:#fe2c55;--accent2:#25f4ee;--text:#f4f4f6;--muted:#a0a0b0}}
*{{box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);
display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0;padding:24px}}
.card{{background:var(--card);border:1px solid #23232f;border-radius:16px;padding:36px;max-width:460px;width:100%}}
h2{{margin-top:0}}
.muted{{color:var(--muted);font-size:14px;margin-bottom:20px}}
label{{display:block;margin:16px 0 6px;font-size:14px;font-weight:600}}
input[type=text],select{{width:100%;padding:10px;border-radius:8px;border:1px solid #2a2a38;background:#0e0e14;color:var(--text)}}
input[type=file]{{width:100%}}
.chk{{display:flex;align-items:center;gap:8px;margin-top:10px;font-size:14px;color:var(--muted)}}
button{{margin-top:24px;width:100%;padding:13px;border:none;border-radius:999px;background:var(--accent);
color:#fff;font-weight:700;font-size:16px;cursor:pointer}}
.note{{margin-top:14px;font-size:12px;color:var(--muted)}}
</style></head><body>
<div class="card">
  <h2>🎬 เลือกวิดีโอโพสต์{f' — {nickname}' if nickname else ''}</h2>
  <p class="muted">แอปนี้ยังไม่ผ่านการอนุมัติจาก TikTok (unaudited) วิดีโอที่โพสต์จะถูกบังคับให้เป็นแบบส่วนตัว (มองเห็นได้เฉพาะตัวเอง) เสมอ ตามกติกาของ TikTok</p>
  <form action="/posttoday/publish" method="POST" enctype="multipart/form-data">
    <label>ไฟล์วิดีโอ</label>
    <input type="file" name="video" accept="video/*" required>

    <label>แคปชั่น</label>
    <input type="text" name="title" maxlength="150" placeholder="เขียนแคปชั่นสั้นๆ">

    <label>Privacy level</label>
    <select name="privacy_level" required>
      <option value="" disabled selected>-- เลือก --</option>
      {options_html}
    </select>

    <div class="chk"><input type="checkbox" name="disable_comment" id="dc"><label for="dc" style="margin:0">ปิดคอมเมนต์</label></div>
    <div class="chk"><input type="checkbox" name="disable_duet" id="dd"><label for="dd" style="margin:0">ปิด Duet</label></div>
    <div class="chk"><input type="checkbox" name="disable_stitch" id="ds"><label for="ds" style="margin:0">ปิด Stitch</label></div>

    <button type="submit">🚀 Publish ไป TikTok</button>
  </form>
  <p class="note">ใช้ TikTok Content Posting API (video.publish / video.upload) — อัปโหลดตรงไปยังบัญชี TikTok ของคุณเอง</p>
</div>
</body></html>""", 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/posttoday/publish", methods=["POST"])
def posttoday_publish_submit():
    """รับไฟล์วิดีโอ → เรียก TikTok video/init → อัปโหลดไบต์ไปยัง upload_url — ห้ามลบ"""
    token = session.get("tiktok_access_token")
    if not token:
        return redirect("/posttoday/login")

    video_file = request.files.get("video")
    privacy_level = request.form.get("privacy_level", "")
    title = request.form.get("title", "")[:150]
    if not video_file or not video_file.filename:
        return "<h2>❌ ไม่พบไฟล์วิดีโอ</h2><a href='/posttoday/publish'>กลับ</a>", 400
    if not privacy_level:
        return "<h2>❌ ต้องเลือก privacy level</h2><a href='/posttoday/publish'>กลับ</a>", 400

    video_bytes = video_file.read()
    video_size = len(video_bytes)
    if video_size == 0:
        return "<h2>❌ ไฟล์วิดีโอว่างเปล่า</h2><a href='/posttoday/publish'>กลับ</a>", 400

    init_payload = {
        "post_info": {
            "title": title,
            "privacy_level": privacy_level,
            "disable_duet": "disable_duet" in request.form,
            "disable_comment": "disable_comment" in request.form,
            "disable_stitch": "disable_stitch" in request.form,
            "video_cover_timestamp_ms": 1000,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": video_size,
            "chunk_size": video_size,
            "total_chunk_count": 1,
        },
    }

    try:
        init_resp = requests.post(
            "https://open.tiktokapis.com/v2/post/publish/video/init/",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
            json=init_payload,
            timeout=30,
        )
        init_data = init_resp.json()
    except Exception as e:
        return f"<h2>❌ เริ่มโพสต์ไม่สำเร็จ: {e}</h2><a href='/posttoday/publish'>กลับ</a>", 500

    err = init_data.get("error", {})
    if err.get("code") not in (None, "ok"):
        return f"<h2>❌ TikTok ปฏิเสธ: {err.get('code')} — {err.get('message')}</h2><a href='/posttoday/publish'>กลับ</a>", 400

    publish_id = init_data.get("data", {}).get("publish_id", "")
    upload_url = init_data.get("data", {}).get("upload_url", "")
    if not upload_url:
        return f"<h2>❌ ไม่ได้ upload_url กลับมา</h2><pre>{json.dumps(init_data, ensure_ascii=False, indent=2)}</pre><a href='/posttoday/publish'>กลับ</a>", 400

    try:
        put_resp = requests.put(
            upload_url,
            data=video_bytes,
            headers={
                "Content-Type": "video/mp4",
                "Content-Range": f"bytes 0-{video_size - 1}/{video_size}",
            },
            timeout=120,
        )
    except Exception as e:
        return f"<h2>❌ อัปโหลดวิดีโอไม่สำเร็จ: {e}</h2><a href='/posttoday/publish'>กลับ</a>", 500

    if put_resp.status_code >= 300:
        return f"<h2>❌ อัปโหลดวิดีโอไม่สำเร็จ (HTTP {put_resp.status_code})</h2><pre>{put_resp.text[:800]}</pre><a href='/posttoday/publish'>กลับ</a>", 400

    return f"""<!DOCTYPE html><html lang="th"><head><meta charset="UTF-8">
    <title>โพสต์สำเร็จ — PostToday</title>
    <style>body{{font-family:sans-serif;background:#0d1117;color:#e9edf2;display:flex;height:100vh;
    align-items:center;justify-content:center;text-align:center}}a{{color:#4ea1ff}}</style></head><body>
    <div><h2>🚀 อัปโหลดวิดีโอสำเร็จแล้ว!</h2>
    <p>publish_id: <code>{publish_id}</code></p>
    <p style="color:#a0a0b0;font-size:14px;max-width:420px">โพสต์นี้เป็นแบบส่วนตัว (SELF_ONLY) เพราะแอปยังไม่ผ่านการอนุมัติจาก TikTok —
    เปิดแอป TikTok ของคุณเพื่อดูผล (Inbox หรือโปรไฟล์)</p>
    <p style="margin-top:14px"><a href="/posttoday">กลับหน้าแรก</a></p></div>
    </body></html>""", 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/botkit")
def botkit_page():
    """หน้าขาย BotKit (self-serve เฟส 1)"""
    _track_visit()
    p = os.path.join(os.path.dirname(__file__), "botkit.html")
    with open(p, "r", encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/api/botkit/order", methods=["POST"])
def botkit_order():
    """รับ order จากฟอร์ม → เด้ง LINE หาเจ้าของทันที"""
    from datetime import timezone
    try:
        d = request.get_json(force=True) or {}
        if not d.get("shop_name") or not d.get("contact"):
            return jsonify({"success": False, "error": "ข้อมูลไม่ครบ"}), 400

        # แหล่งที่พาลูกค้าคนนี้มา (จาก cookie ที่ปั๊มไว้ตอนเข้าเว็บครั้งแรก)
        src = request.cookies.get(seo_tracker.SRC_COOKIE, "direct")

        order = {
            "time":        datetime.now(timezone.utc).isoformat(),
            "source":      src,
            "shop_name":   str(d.get("shop_name", ""))[:100],
            "biz_type":    str(d.get("biz_type", ""))[:30],
            "contact_name": str(d.get("contact_name", ""))[:60],
            "contact":     str(d.get("contact", ""))[:60],
            "plan":        str(d.get("plan", ""))[:30],
            "page":        str(d.get("page", ""))[:200],
            "need":        str(d.get("need", ""))[:500],
            "status":      "new",
        }
        botkit_orders.insert(0, order)
        del botkit_orders[50:]
        _save_botkit_order(order)                   # persist ลง Supabase กันหายเวลา restart
        seo_tracker.log_order(src, order["plan"])   # นับ conversion

        biz = BIZ_LABEL.get(order["biz_type"], order["biz_type"] or "-")
        demo_url = (f"https://forex-ai-demo.onrender.com/demo/{order['biz_type']}"
                    if order["biz_type"] in ("beauty", "clinic", "spa", "restaurant")
                    else "https://forex-ai-demo.onrender.com/botkit")

        msg = (
            f"🔥 ลูกค้าใหม่จาก BotKit!\n"
            f"━━━━━━━━━━━━\n"
            f"🏪 ร้าน: {order['shop_name']}\n"
            f"📂 ประเภท: {biz}\n"
            f"💳 สนใจ: {order['plan']}\n"
            f"👤 {order['contact_name']} | {order['contact']}\n"
            + (f"📱 เพจ: {order['page']}\n" if order["page"] else "")
            + (f"💬 ต้องการ: {order['need']}\n" if order["need"] else "")
            + f"📡 มาจาก: {SRC_LABEL.get(src, src)}\n"
            + f"━━━━━━━━━━━━\n"
            f"🎪 demo สายนี้: {demo_url}\n"
            f"⏰ ทักกลับภายใน 24 ชม.!"
        )
        _push_line(LINE_USER_ID, msg)
        return jsonify({"success": True})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/botkit/orders", methods=["GET"])
def botkit_order_list():
    """รายการ order ล่าสุด (โชว์ใน NEXUS Monitor) — อ่านจาก Supabase ก่อน fallback cache ในแรม"""
    orders = _load_botkit_orders(10)
    return jsonify({"success": True, "count": len(orders), "orders": orders})


@app.route("/botkit/setup")
def botkit_setup_page():
    """หน้าฟอร์มกรอกข้อมูลร้าน → สร้างบอทเอง (นกน้อยพิมพ์รัง ชั้น 1 — self-serve provisioning)"""
    _track_visit()
    p = os.path.join(os.path.dirname(__file__), "botkit-setup.html")
    with open(p, "r", encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}


def _valid_slug(slug: str) -> bool:
    """slug = a-z 0-9 - เท่านั้น ยาว 2-30 (กัน path traversal + ชื่อไฟล์เพี้ยน)"""
    return (2 <= len(slug) <= 30) and all(c.islower() or c.isdigit() or c == "-" for c in slug)


def _build_cfg_from_form(d: dict) -> dict:
    """ประกอบ config dict ตามโครง configs/_TEMPLATE.json จากข้อมูลฟอร์ม
    การันตี promo path: ถ้าไม่มีกลุ่มไหนถูกติ๊กเป็นโปรเลย ตั้งกลุ่มแรกที่มีรายการให้เป็น hot อัตโนมัติ"""
    contact_in = d.get("contact") or {}
    categories, any_hot = [], False
    for i, c in enumerate(d.get("categories") or []):
        groups = []
        for g in (c.get("groups") or []):
            items = [{"n": str(it.get("n", "")).strip(), "p": str(it.get("p", "")).strip()}
                     for it in (g.get("items") or []) if str(it.get("n", "")).strip()]
            if not items:
                continue
            grp = {"name": (str(g.get("name", "")).strip() or "บริการ"), "items": items}
            if g.get("hot"):
                grp["hot"] = True
                any_hot = True
            groups.append(grp)
        if groups:
            categories.append({
                "id": (str(c.get("id", "")).strip() or f"cat{i+1}"),
                "name": (str(c.get("name", "")).strip() or "บริการ"),
                "emoji": str(c.get("emoji", "")).strip(),
                "groups": groups,
            })
    if categories and not any_hot:
        categories[0]["groups"][0]["hot"] = True   # กันบอทตอบ "ยังไม่มีโปร" ตอนถูกถามหาโปร

    return {
        "_client": str(d.get("_client", "")).strip(),
        "_ai_name": str(d.get("ai_name", "")).strip(),          # underscore = โค้ดไม่อ่าน เก็บไว้อ้างอิง
        "_handoff_cases": str(d.get("handoff_cases", "")).strip(),
        "ai_tier": "free",
        "biz_name": str(d.get("biz_name", "")).strip(),
        "biz_full": str(d.get("biz_full", "")).strip(),
        "emoji": (str(d.get("emoji", "")).strip() or "✨"),
        "tagline": str(d.get("tagline", "")).strip(),
        "accent": (str(d.get("accent", "")).strip() or "#c08268"),
        "accent_soft": (str(d.get("accent_soft", "")).strip() or "#f6ece6"),
        "book_word": (str(d.get("book_word", "")).strip() or "จองคิว"),
        "staff_word": (str(d.get("staff_word", "")).strip() or "ช่าง"),
        "greeting": str(d.get("greeting", "")).strip(),
        "contact": {
            "line": str(contact_in.get("line", "")).strip(),
            "phone": str(contact_in.get("phone", "")).strip(),
            "fb": str(contact_in.get("fb", "")).strip(),
            "ig": str(contact_in.get("ig", "")).strip(),
            "address": str(contact_in.get("address", "")).strip(),
            "map_link": str(contact_in.get("map_link", "")).strip(),
            "parking": str(contact_in.get("parking", "")).strip(),
            "landmarks": [str(x).strip() for x in (contact_in.get("landmarks") or []) if str(x).strip()],
        },
        "gift": str(d.get("gift", "")).strip(),
        "perks": str(d.get("perks", "")).strip(),
        "friend_promo": str(d.get("friend_promo", "")).strip(),
        "categories": categories,
        "works": [],
        "advisor": {
            "intro": (str(d.get("advisor_intro", "")).strip()
                      or "เล่าให้เราฟังได้เลยค่ะ อยากได้บริการแบบไหน เดี๋ยวแนะนำให้"),
            "rules": [],
            "handoff_msg": (str(d.get("handoff_msg", "")).strip()
                            or "ขอส่งต่อให้แอดมินตัวจริงดูแลต่อนะคะ รอสักครู่ค่ะ"),
            "retry_msg": (str(d.get("retry_msg", "")).strip()
                          or "รบกวนรอสักครู่นะคะ กำลังตรวจสอบให้อยู่ค่ะ"),
        },
        "close_lines": [(str(d.get("close_line", "")).strip()
                         or "สนใจบริการไหนบอกได้เลยนะคะ เดี๋ยวจัดคิวให้ค่ะ")],
    }


@app.route("/api/botkit/provision", methods=["POST"])
def botkit_provision():
    """รับข้อมูลร้านจากฟอร์ม → สร้าง config เก็บลง shop_configs (Supabase) → บอทมีเนื้อหาพร้อม preview
    ปลอดภัยแม้เปิดสาธารณะ: config เปล่าๆ ไม่มีผลกับลูกค้าจริงจนกว่า dev จะผูกเพจ Facebook (shop_pages)
    ยังคงต้องเชื่อม Meta แบบ manual เหมือนเดิม — endpoint นี้แค่ตัดงานพิมพ์ JSON ของ dev ออกไป"""
    from datetime import timezone
    try:
        d = request.get_json(force=True) or {}
        slug = str(d.get("slug", "")).strip().lower()
        if not _valid_slug(slug):
            return jsonify({"success": False, "error": "slug ต้องเป็น a-z 0-9 - ยาว 2-30 ตัว"}), 400
        # กัน form สาธารณะเขียนทับร้านที่ dev ดูแลเป็นไฟล์ (เช่น lullabell) — ไฟล์ = dev-managed
        base = os.path.dirname(__file__)
        if os.path.exists(os.path.join(base, "configs", f"{slug}.json")):
            return jsonify({"success": False, "error": f"slug '{slug}' สงวนไว้แล้ว เลือกชื่ออื่น"}), 409
        if not str(d.get("biz_name", "")).strip() or not str(d.get("greeting", "")).strip():
            return jsonify({"success": False, "error": "ต้องกรอกชื่อร้าน + ข้อความทักทาย"}), 400

        cfg = _build_cfg_from_form(d)
        if not cfg["categories"]:
            return jsonify({"success": False, "error": "ต้องมีเมนู/บริการอย่างน้อย 1 รายการ"}), 400

        ok, err = meta_bot.save_config(slug, cfg)
        if not ok:
            return jsonify({"success": False, "error": f"บันทึกไม่สำเร็จ: {err}"}), 502

        base_url = "https://forex-ai-demo.onrender.com"
        chat_url = f"{base_url}/demo/chat/{slug}"
        contact_name = str(d.get("contact_name", "")).strip()
        contact = str(d.get("contact_phone", "")).strip() or cfg["contact"]["line"] or cfg["contact"]["phone"]
        msg = (
            f"🐣 ร้านใหม่กรอกฟอร์มสร้างบอท!\n"
            f"━━━━━━━━━━━━\n"
            f"🏪 {cfg['biz_name']} (slug: {slug})\n"
            f"🍱 เมนู {sum(len(g['items']) for c in cfg['categories'] for g in c['groups'])} รายการ\n"
            + (f"👤 {contact_name} | {contact}\n" if (contact_name or contact) else "")
            + f"━━━━━━━━━━━━\n"
            f"👀 ลอง preview: {chat_url}\n"
            f"⚠️ ยังไม่ผูกเพจ — ต่อ Facebook (admin→token→add-shop-page) ก่อนใช้จริง"
        )
        try:
            _push_line(LINE_USER_ID, msg)
        except Exception:
            pass   # เด้ง LINE พลาดไม่ควรทำให้ provision ล้ม (config บันทึกไปแล้ว)
        return jsonify({"success": True, "slug": slug, "chat_url": chat_url})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)[:300]}), 500


@app.route("/api/demos", methods=["GET"])
def list_demos():
    """รายการ demo ทั้งหมด (ไว้โชว์ในหน้ารวม/ส่งลูกค้า)"""
    cfgs = _load_demo_configs()
    demos = [
        {"slug": k, "name": v["biz_name"], "emoji": v["emoji"],
         "tagline": v["tagline"], "url": f"/demo/{k}"}
        for k, v in cfgs.items()
    ]
    # demo พิเศษ (flow ต่างจาก template ทั่วไป)
    demos.append({
        "slug": "dialysis", "name": "ศูนย์ไตเทียม", "emoji": "🏥",
        "tagline": "ฟอกไต · บันทึกรอบ + ติดตามตัวกรอง", "url": "/demo/dialysis",
    })
    return jsonify({"success": True, "demos": demos})


@app.route("/beauty")
def beauty_demo():
    """ลิงก์เดิมที่ส่งลูกค้าไปแล้ว — คงไว้ ห้ามลบ (ชี้ไป /demo/beauty)"""
    _track_visit()
    try:
        return _render_demo("beauty"), 200, {"Content-Type": "text/html; charset=utf-8"}
    except Exception:
        # fallback ไฟล์เดิม เผื่อ template ใหม่พัง
        html_path = os.path.join(os.path.dirname(__file__), "demo_beauty_salon.html")
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/")
def index():
    _track_visit()
    html_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}


if __name__ == "__main__":
    port  = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("RENDER") is None
    print(f"🚀 ForexAI Pro Server — port {port}")
    app.run(debug=debug, port=port, host="0.0.0.0")
