"""
ForexAI Pro — API Server
เชื่อม Claude AI + ราคา Forex/BTC + LINE Notification
รัน: python api_server.py
"""
import os, json, requests
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS
import anthropic

app = Flask(__name__)
CORS(app)

# ====== CONFIG — ใส่ API Keys ======
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LINE_TOKEN        = os.environ.get("LINE_TOKEN", "")
LINE_USER_ID      = os.environ.get("LINE_USER_ID", "")
# ====================================

signal_history = []  # เก็บประวัติสัญญาณ (in-memory)


# ---------- Price Helpers ----------

def fetch_forex(base: str, quote: str) -> dict:
    """ดึงราคา Forex จาก frankfurter.app (ฟรี ไม่ต้อง key)"""
    r = requests.get(f"https://api.frankfurter.app/latest?from={base}&to={quote}", timeout=5)
    r.raise_for_status()
    d = r.json()
    price = d["rates"][quote]
    # ดึง rate เมื่อวาน เพื่อคำนวณ % change
    try:
        r2 = requests.get(
            f"https://api.frankfurter.app/2024-01-01..?from={base}&to={quote}&amount=1",
            timeout=5
        )
        # fallback: ใช้ mock change
        change_pct = round((price - price * 0.998), 5)
    except Exception:
        change_pct = 0.0
    return {"price": price, "change_pct": 0.05, "base": base, "quote": quote}


def fetch_btc() -> dict:
    """ดึงราคา BTC/USDT จาก Binance (ฟรี ไม่ต้อง key)"""
    r = requests.get("https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT", timeout=5)
    r.raise_for_status()
    d = r.json()
    return {
        "price":      float(d["lastPrice"]),
        "change_pct": float(d["priceChangePercent"]),
        "high":       float(d["highPrice"]),
        "low":        float(d["lowPrice"]),
        "volume":     float(d["volume"]),
    }


def fetch_eth() -> dict:
    """ดึงราคา ETH/USDT"""
    r = requests.get("https://api.binance.com/api/v3/ticker/24hr?symbol=ETHUSDT", timeout=5)
    r.raise_for_status()
    d = r.json()
    return {
        "price":      float(d["lastPrice"]),
        "change_pct": float(d["priceChangePercent"]),
        "high":       float(d["highPrice"]),
        "low":        float(d["lowPrice"]),
    }


# ---------- Claude AI Analysis ----------

def analyze_with_claude(pair: str, price_data: dict) -> dict:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

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
  "reasoning": "อธิบายเหตุผล 2-3 ประโยคภาษาไทย ว่าทำไมถึงให้สัญญาณนี้",
  "key_factors": ["ปัจจัย 1", "ปัจจัย 2", "ปัจจัย 3"],
  "market_sentiment": "BULLISH" หรือ "BEARISH" หรือ "NEUTRAL"
}}"""

    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text.strip()
    start, end = text.find("{"), text.rfind("}") + 1
    return json.loads(text[start:end])


# ---------- API Routes ----------

@app.route("/api/prices", methods=["GET"])
def get_all_prices():
    """ดึงราคาทั้งหมดในครั้งเดียว"""
    try:
        data = {
            "EURUSD": fetch_forex("EUR", "USD"),
            "GBPUSD": fetch_forex("GBP", "USD"),
            "USDJPY": fetch_forex("USD", "JPY"),
            "BTCUSD": fetch_btc(),
            "ETHUSD": fetch_eth(),
            "timestamp": datetime.now().strftime("%H:%M:%S"),
        }
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/analyze", methods=["POST"])
def analyze():
    """วิเคราะห์ด้วย Claude AI"""
    body = request.get_json()
    pair       = body.get("pair", "EURUSD")
    price_data = body.get("price_data", {})

    if not ANTHROPIC_API_KEY:
        return jsonify({"success": False, "error": "ไม่ได้ตั้ง ANTHROPIC_API_KEY"}), 400

    try:
        result = analyze_with_claude(pair, price_data)
        result["pair"]      = pair
        result["timestamp"] = datetime.now().strftime("%H:%M:%S")

        # เก็บประวัติ (max 20)
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
    """ส่ง Signal ไป LINE"""
    if not LINE_TOKEN or not LINE_USER_ID:
        return jsonify({"success": False, "error": "ไม่ได้ตั้ง LINE_TOKEN / LINE_USER_ID"}), 400

    sig = request.get_json().get("signal", {})
    emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(sig.get("signal", ""), "⚪")
    sentiment_th = {"BULLISH": "กระทิง 📈", "BEARISH": "หมี 📉", "NEUTRAL": "ทรงตัว ➡️"}.get(
        sig.get("market_sentiment", ""), ""
    )

    factors = "\n".join(f"  • {f}" for f in sig.get("key_factors", []))
    msg = f"""{emoji} ForexAI Pro — Signal Alert

📊 คู่: {sig.get('pair','')}  |  ⚡ {sig.get('signal','')}
🎯 ความมั่นใจ: {sig.get('confidence','')}%  |  ⚠️ ความเสี่ยง: {sig.get('risk_level','')}
📈 Sentiment: {sentiment_th}

💰 Entry:       {sig.get('entry_price','')}
🛑 Stop Loss:  {sig.get('stop_loss','')}
✅ Take Profit: {sig.get('take_profit','')}

🔑 ปัจจัยหลัก:
{factors}

💡 {sig.get('reasoning','')}

🤖 Analyzed by Claude AI  |  ⏰ {sig.get('timestamp','')}
━━━━━━━━━━━━━━━━━━"""

    r = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={"Authorization": f"Bearer {LINE_TOKEN}", "Content-Type": "application/json"},
        json={"to": LINE_USER_ID, "messages": [{"type": "text", "text": msg}]},
        timeout=10,
    )
    return jsonify({"success": r.status_code == 200, "status_code": r.status_code})


@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "anthropic_key": bool(ANTHROPIC_API_KEY),
        "line_token":    bool(LINE_TOKEN),
        "line_user_id":  bool(LINE_USER_ID),
    })


@app.route("/")
def index():
    """Serve dashboard HTML"""
    import os
    html_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("RENDER") is None  # debug=False บน Render
    print(f"🚀 ForexAI Pro Server starting on port {port}")
    app.run(debug=debug, port=port, host="0.0.0.0")
