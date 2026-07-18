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
import rss_hunter
import dialysis_api
import seo_tracker

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
    """ประวัติงานที่ตรวจล่าสุด (FastWork + RSS รวมกัน)"""
    log = fastwork_hunter.get_hunter_log() + rss_hunter.get_log()
    log.sort(key=lambda e: e.get("time", ""), reverse=True)
    return jsonify({"success": True, "log": log[:20]})


@app.route("/api/hunter/rss", methods=["GET", "POST"])
def hunter_rss():
    """ดักงานจากทั้งเน็ตผ่าน Google Alerts RSS (cron ยิงทุก 30 นาที)"""
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


botkit_orders = []  # เก็บ order ในหน่วยความจำ (เฟส 1 — ยังไม่ต่อ DB)

BIZ_LABEL = {
    "beauty": "ร้านเสริมสวย", "clinic": "คลินิกความงาม",
    "spa": "สปา/นวด", "restaurant": "ร้านอาหาร", "other": "อื่นๆ",
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
    },
}


def _seo_page(slug: str) -> str:
    p = SEO_PAGES[slug]
    pts = "".join(f"<li>{x}</li>" for x in p["points"])
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
</style></head><body><div class="w">
<h1>{p['h1']}<br><span>ลองฟรีก่อนตัดสินใจ</span></h1>
<p class="lead">{p['lead']}</p>
<ul>{pts}</ul>

<h2>🎪 ลองเล่นระบบจริงได้เลย</h2>
<p style="color:#9fb0d0;font-size:14.5px">กดเข้าไปคุยกับบอทได้เลย เหมือนเป็นลูกค้าจริง ไม่ต้องสมัคร</p>
<div class="demos">{demos}</div>

<div class="price">
  💰 <b>เริ่มต้น ฿590/เดือน</b><br>
  <span style="color:#9fb0d0;font-size:14px">ไม่มีค่าติดตั้ง · ยกเลิกได้ทุกเมื่อ · ไม่ผูกมัด</span>
</div>

<a class="cta" href="/botkit">ดูแพ็กเกจทั้งหมด →</a>

<h2>❓ คำถามที่พบบ่อย</h2>
<ul>
  <li>ไม่ต้องมีเซิร์ฟเวอร์ ไม่ต้องมีความรู้เทคนิค — เราดูแลให้หมด</li>
  <li>ไม่มีค่า API เพิ่ม — Facebook/Instagram/LINE API ฟรี</li>
  <li>ใช้งานได้ภายใน 2-3 วัน</li>
  <li>ยกเลิกได้ทุกเมื่อ ไม่มีสัญญาผูกมัด</li>
</ul>

<footer>
  BotKit by Jark — LINE Bot &amp; AI Agent Developer<br>
  <a href="/botkit">ดูแพ็กเกจทั้งหมด</a>{others}
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
    """รายการ order ล่าสุด (โชว์ใน NEXUS Monitor)"""
    return jsonify({"success": True, "count": len(botkit_orders), "orders": botkit_orders[:10]})


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
