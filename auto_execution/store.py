"""
ที่เก็บผลเทรดโหมดกระดาษ — Supabase table `paper_trades`

ทำไมต้องมี: PaperBroker เก็บ position ไว้ใน memory
Render restart เมื่อไหร่ = ผลเทรดหายหมด → ลูกค้าเปิดดูแล้วว่างเปล่า = ขายไม่ได้
ตัวนี้ทำให้ผลอยู่ถาวร เปิดดูย้อนหลังได้
"""
import os
import requests
from datetime import datetime, timezone

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
TABLE = "paper_trades"


def is_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)


def _h(extra: dict = None) -> dict:
    h = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
         "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h


def save_open(order: dict, signal: dict) -> None:
    """บันทึกตอนเปิดไม้"""
    if not is_configured():
        return
    requests.post(
        f"{SUPABASE_URL}/rest/v1/{TABLE}",
        headers=_h({"Prefer": "return=minimal"}),
        json={
            "order_id":   order["order_id"],
            "pair":       order.get("pair") or signal.get("pair"),
            "side":       order.get("side") or signal.get("signal"),
            "size":       order.get("size"),
            "entry":      order.get("entry"),
            "sl":         order.get("sl"),
            "tp":         order.get("tp"),
            "confidence": signal.get("confidence"),
            "reason":     (signal.get("reason") or signal.get("analysis") or "")[:500] or None,
            "status":     "open",
        },
        timeout=6,
    ).raise_for_status()


def save_close(order_id: str, exit_price: float, pnl: float, why: str) -> None:
    """บันทึกตอนปิดไม้"""
    if not is_configured():
        return
    requests.patch(
        f"{SUPABASE_URL}/rest/v1/{TABLE}?order_id=eq.{order_id}",
        headers=_h({"Prefer": "return=minimal"}),
        json={
            "status": "closed", "exit_price": exit_price,
            "pnl": round(pnl, 2), "close_reason": why,
            "closed_at": datetime.now(timezone.utc).isoformat(),
        },
        timeout=6,
    ).raise_for_status()


def _get(q: str) -> list:
    r = requests.get(f"{SUPABASE_URL}/rest/v1/{TABLE}?{q}", headers=_h(), timeout=8)
    r.raise_for_status()
    return r.json()


def open_trades() -> list:
    return _get("status=eq.open&order=opened_at.desc") if is_configured() else []


def recent(limit: int = 30) -> list:
    return _get(f"order=opened_at.desc&limit={limit}") if is_configured() else []


def summary(starting_balance: float = 10000.0) -> dict:
    """สรุปผล — ตัวเลขที่ลูกค้าอยากเห็น"""
    if not is_configured():
        return {"ok": False, "error": "ยังไม่ได้ตั้ง Supabase"}

    rows = _get("order=opened_at.desc&limit=500")
    closed = [r for r in rows if r["status"] == "closed"]
    opens = [r for r in rows if r["status"] == "open"]

    wins = [r for r in closed if (r.get("pnl") or 0) > 0]
    losses = [r for r in closed if (r.get("pnl") or 0) <= 0]
    pnl = sum(float(r.get("pnl") or 0) for r in closed)

    return {
        "ok": True,
        "starting_balance": starting_balance,
        "balance": round(starting_balance + pnl, 2),
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl / starting_balance * 100, 2) if starting_balance else 0,
        "total_closed": len(closed),
        "open_count": len(opens),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else 0,
        "best": round(max((float(r["pnl"]) for r in wins), default=0), 2),
        "worst": round(min((float(r["pnl"]) for r in losses), default=0), 2),
        "open_trades": opens,
        "trades": rows[:30],
    }
