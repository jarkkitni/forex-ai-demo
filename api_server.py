"""
ForexAI Pro — API Server
เชื่อม AI วิเคราะห์ + ราคา Forex/Crypto + LINE Notification
"""
import os, json, requests, traceback, hmac, hashlib, base64
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS
import anthropic

import fastwork_hunter

app  = Flask(__name__)
CORS(app)

# ====== ENV CONFIG ======
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")
LINE_TOKEN          = os.environ.get("LINE_TOKEN", "")
LINE_USER_ID        = os.environ.get("LINE_USER_ID", "")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
# ========================

signal_history   = []  # in-memory สัญญาณ (เก็บ 20 ล่าสุด)
registered_users = []  # userId ที่ลงทะเบียนผ่าน /webhook

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

    msg  = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text.strip()
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
    """วิเคราะห์ด้วย AI"""
    body       = request.get_json()
    pair       = body.get("pair", "EURUSD")
    price_data = body.get("price_data", {})

    if not ANTHROPIC_API_KEY:
        return jsonify({"success": False, "error": "ไม่ได้ตั้ง ANTHROPIC_API_KEY"}), 400

    try:
        result              = analyze_with_ai(pair, price_data)
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
        "registered_users":    len(registered_users),
        "signal_count":        len(signal_history),
        "hunter_log_count":    len(fastwork_hunter.get_hunter_log()),
    })


# ---------- FastWork Job Hunter ----------

@app.route("/api/hunter/check", methods=["GET", "POST"])
def hunter_check():
    """ดักจับงาน FastWork ที่ตรงสกิล → AI วิเคราะห์ + ร่างข้อเสนอ → LINE
    เรียกจาก cron ภายนอก (cron-job.org) ทุก 30 นาที"""
    if not ANTHROPIC_API_KEY or not LINE_TOKEN or not LINE_USER_ID:
        return jsonify({"success": False, "error": "missing env keys"}), 500
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        result = fastwork_hunter.run_hunter(client, _push_line, LINE_USER_ID)
        return jsonify({"success": True, **result})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/hunter/log", methods=["GET"])
def hunter_log():
    """ประวัติงานที่ตรวจล่าสุด"""
    return jsonify({"success": True, "log": fastwork_hunter.get_hunter_log()})


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
