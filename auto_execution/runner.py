"""
Runner — ตัวที่ "สตาร์ทเครื่องยนต์" ที่เขียนไว้แล้ว

flow ต่อ 1 tick (cron ยิงมาทุก 15-30 นาที):
  1. ดึงราคาจริง
  2. เช็คไม้ที่เปิดอยู่ → ถ้าชน SL/TP → ปิด + บันทึก
  3. ให้ AI วิเคราะห์ → ถ้าได้ BUY/SELL และมั่นใจพอ → ผ่าน RiskGuard → เปิดไม้ + บันทึก

⚠️ PAPER MODE เสมอ — ไม่มีทางแตะเงินจริงจาก endpoint นี้
   (Executor จะตกกลับเป็น PaperBroker เองถ้าไม่ปลดล็อกครบ 3 ชั้น)
"""
import os
from datetime import datetime, timezone

from .risk_guard import RiskConfig
from .executor import Executor
from .broker_adapter import PaperBroker
from . import store

# ---- ค่าตั้งต้นของ demo (ตัวเลขสมมติ ใช้โชว์เท่านั้น) ----
DEMO_BALANCE = float(os.environ.get("AUTOTRADE_DEMO_BALANCE", "10000"))
DEMO_PAIRS = [p.strip() for p in
              os.environ.get("AUTOTRADE_PAIRS", "BTC/USD").split(",") if p.strip()]
MIN_CONFIDENCE = int(os.environ.get("AUTOTRADE_MIN_CONF", "70"))
MAX_OPEN = 3


def _cfg() -> RiskConfig:
    """
    ค่าความเสี่ยงของ demo — ของจริงต้องมาจากคำตอบลูกค้า 3 ข้อ
    (งบเทรด / ขาดทุนสูงสุดต่อวัน / โบรก) ห้ามใช้ default เงียบๆ กับเงินจริง
    """
    return RiskConfig(
        account_balance=DEMO_BALANCE,
        max_daily_loss=DEMO_BALANCE * 0.03,   # 3% ต่อวัน
        max_risk_per_trade_pct=1.0,
        max_open_positions=MAX_OPEN,
        max_trades_per_day=10,
        min_confidence=MIN_CONFIDENCE,
    )


def _hydrate(ex: Executor) -> None:
    """
    ดึงไม้ที่เปิดค้างจาก Supabase กลับเข้า PaperBroker
    จำเป็นเพราะ Render restart แล้ว memory หาย แต่ไม้ยังเปิดอยู่ใน DB
    """
    b = ex.broker
    if not isinstance(b, PaperBroker):
        return
    for t in store.open_trades():
        b.positions[t["order_id"]] = {
            "id": t["order_id"], "pair": t["pair"], "side": t["side"],
            "size": float(t["size"]), "entry": float(t["entry"]),
            "sl": float(t["sl"]), "tp": float(t["tp"]),
            "opened_at": t["opened_at"],
        }
    ex.guard.state.open_positions = len(b.positions)


def _hit(pos: dict, price: float) -> tuple:
    """ราคาปัจจุบันชน SL หรือ TP ของไม้นี้หรือยัง"""
    if pos["side"] == "BUY":
        if price >= pos["tp"]:
            return True, "TP"
        if price <= pos["sl"]:
            return True, "SL"
    else:  # SELL
        if price <= pos["tp"]:
            return True, "TP"
        if price >= pos["sl"]:
            return True, "SL"
    return False, ""


def tick(fetch_price_fn, analyze_fn, notify_fn=None, line_user_id: str = "") -> dict:
    """
    เดิน 1 รอบ — ถูกเรียกจาก /api/autotrade/tick (cron)
    fetch_price_fn(pair) -> {"price": float, ...}
    analyze_fn(pair, price_data) -> {"signal","confidence","entry_price","stop_loss","take_profit",...}
    """
    ex = Executor(_cfg(), broker=None, notify_fn=notify_fn, line_user_id=line_user_id)
    _hydrate(ex)

    out = {"time": datetime.now(timezone.utc).isoformat(), "mode": "PAPER",
           "closed": [], "opened": [], "skipped": []}

    for pair in DEMO_PAIRS:
        try:
            pd = fetch_price_fn(pair)
            price = float(pd["price"])
        except Exception as e:
            out["skipped"].append({"pair": pair, "why": f"ดึงราคาไม่ได้: {e}"})
            continue

        # --- 1) เช็คไม้ที่เปิดอยู่ก่อน (ปิดก่อนเปิดใหม่เสมอ) ---
        for oid, pos in list(ex.broker.positions.items()):
            if pos["pair"] != pair:
                continue
            done, why = _hit(pos, price)
            if not done:
                continue
            res = ex.close(oid, exit_price=price)
            if res.get("success"):
                try:
                    store.save_close(oid, price, res.get("pnl", 0), why)
                except Exception as e:
                    print(f"[AutoTrade] บันทึกปิดไม้ล้มเหลว: {e}", flush=True)
                out["closed"].append({"order_id": oid, "why": why, "pnl": res.get("pnl")})
                if notify_fn and line_user_id:
                    pnl = res.get("pnl", 0)
                    notify_fn(line_user_id, (
                        f"📝 PAPER | ปิดไม้ ({why})\n"
                        f"{pair} {pos['side']} @ {price}\n"
                        f"{'🟢 กำไร' if pnl > 0 else '🔴 ขาดทุน'} {pnl:+.2f} USD"
                    ))

        # --- 2) มีไม้เปิดอยู่แล้วในคู่นี้ ไม่เปิดซ้ำ ---
        if any(p["pair"] == pair for p in ex.broker.positions.values()):
            out["skipped"].append({"pair": pair, "why": "มีไม้เปิดอยู่แล้ว"})
            continue

        # --- 3) ให้ AI วิเคราะห์ ---
        try:
            sig = analyze_fn(pair, pd)
        except Exception as e:
            out["skipped"].append({"pair": pair, "why": f"AI วิเคราะห์ไม่ได้: {e}"})
            continue

        sig["pair"] = pair
        if sig.get("signal") not in ("BUY", "SELL"):
            out["skipped"].append({"pair": pair, "why": f"AI บอก {sig.get('signal', 'HOLD')}"})
            continue

        res = ex.handle_signal(sig)      # ← RiskGuard ตรวจตรงนี้ ไม่มีทางลัด
        if not res.get("executed"):
            out["skipped"].append({"pair": pair, "why": res.get("reason")})
            continue

        try:
            store.save_open(res["order"], sig)
        except Exception as e:
            print(f"[AutoTrade] บันทึกเปิดไม้ล้มเหลว: {e}", flush=True)
        out["opened"].append({
            "pair": pair, "side": sig["signal"], "entry": sig["entry_price"],
            "confidence": sig.get("confidence"), "order_id": res["order"]["order_id"],
        })

    out["risk"] = ex.guard.snapshot()
    return out


def state() -> dict:
    """สถานะสำหรับหน้า /demo/autotrade"""
    s = store.summary(DEMO_BALANCE)
    s["mode"] = "PAPER"
    s["pairs"] = DEMO_PAIRS
    s["min_confidence"] = MIN_CONFIDENCE
    return s
