"""
Broker Adapter — รองรับหลายโบรกเกอร์ผ่าน interface เดียว
เตรียมไว้ล่วงหน้าก่อนรู้คำตอบข้อ 1 ของลูกค้า (ใช้โบรกไหน)
พอลูกค้าตอบ → เสียบ adapter ที่ตรง โดยไม่ต้องแก้โค้ดส่วนอื่นเลย

สถานะ adapter:
- PaperBroker   : ✅ พร้อมใช้ (จำลอง ไม่แตะเงินจริง) — ค่าเริ่มต้นเสมอ
- OandaBroker   : 🚧 โครงพร้อม รอ API key (REST — รันบน Render/Linux ได้ตรง)
- MT5Broker     : 🚧 โครงพร้อม ต้องมี Windows VPS + MT5 terminal
"""
from abc import ABC, abstractmethod
from datetime import datetime, timezone
import uuid


class BrokerAdapter(ABC):
    """interface กลาง — ทุกโบรกต้อง implement ครบ"""
    name = "base"
    is_live = False   # ต้องเป็น True เฉพาะ adapter ที่แตะเงินจริง

    @abstractmethod
    def place_order(self, pair: str, side: str, size: float,
                    entry: float, sl: float, tp: float) -> dict: ...

    @abstractmethod
    def close_order(self, order_id: str) -> dict: ...

    @abstractmethod
    def get_positions(self) -> list: ...

    @abstractmethod
    def get_balance(self) -> float: ...

    def health(self) -> dict:
        return {"broker": self.name, "live": self.is_live, "ok": True}


class PaperBroker(BrokerAdapter):
    """
    โบรกจำลอง — ใช้ทดสอบระบบทั้งหมดโดยไม่มีเงินจริงเกี่ยวข้อง
    ตามข้อเสนอ: ต้องรัน demo อย่างน้อย 1-2 สัปดาห์ก่อนขึ้นเงินจริง
    """
    name = "paper"
    is_live = False

    def __init__(self, starting_balance: float = 10000.0):
        self.balance = starting_balance
        self.positions: dict = {}
        self.history: list = []

    def place_order(self, pair, side, size, entry, sl, tp) -> dict:
        oid = f"paper-{uuid.uuid4().hex[:8]}"
        self.positions[oid] = {
            "id": oid, "pair": pair, "side": side, "size": size,
            "entry": entry, "sl": sl, "tp": tp,
            "opened_at": datetime.now(timezone.utc).isoformat(),
        }
        return {"success": True, "order_id": oid, "mode": "PAPER", **self.positions[oid]}

    def close_order(self, order_id, exit_price: float | None = None) -> dict:
        pos = self.positions.pop(order_id, None)
        if not pos:
            return {"success": False, "error": "ไม่พบออเดอร์"}
        px = exit_price if exit_price is not None else pos["tp"]
        pnl = (px - pos["entry"]) * pos["size"] * (1 if pos["side"] == "BUY" else -1)
        self.balance += pnl
        rec = {**pos, "exit": px, "pnl": round(pnl, 2),
               "closed_at": datetime.now(timezone.utc).isoformat()}
        self.history.append(rec)
        return {"success": True, "mode": "PAPER", **rec}

    def get_positions(self) -> list:
        return list(self.positions.values())

    def get_balance(self) -> float:
        return round(self.balance, 2)


class OandaBroker(BrokerAdapter):
    """
    เส้นทางที่แนะนำถ้าลูกค้าเปิดกว้างเรื่องโบรก (ตามที่ Garuda วิเคราะห์)
    REST API ตรง → รันบน Render (Linux) ได้เลย ไม่ต้องมี Windows VPS
    TODO: implement เมื่อลูกค้ายืนยันโบรก + ให้ trade-only API key
    """
    name = "oanda"
    is_live = True

    def __init__(self, api_key: str, account_id: str, practice: bool = True):
        if not api_key or not account_id:
            raise ValueError("ต้องมี API key + account id")
        self.api_key = api_key
        self.account_id = account_id
        # practice=True → ยิงเข้า demo endpoint (fxpractice) ปลอดภัยกว่า
        self.base = ("https://api-fxpractice.oanda.com" if practice
                     else "https://api-fxtrade.oanda.com")
        self.practice = practice

    def place_order(self, pair, side, size, entry, sl, tp) -> dict:
        raise NotImplementedError("รอคำตอบลูกค้าข้อ 1 (โบรก) + trade-only API key")

    def close_order(self, order_id) -> dict:
        raise NotImplementedError

    def get_positions(self) -> list:
        raise NotImplementedError

    def get_balance(self) -> float:
        raise NotImplementedError


class MT5Broker(BrokerAdapter):
    """
    ใช้เมื่อลูกค้ายืนกรานใช้ MT4/MT5 เท่านั้น
    ข้อจำกัด (ตามที่ Garuda ชี้ไว้): ต้องมี MT5 terminal รันจริงบน Windows
    → ต้องเช่า Windows VPS แยก (~฿800-1,500/เดือน) เพิ่มจากค่าดูแล
    TODO: implement เมื่อยืนยันว่าไปทาง MT5
    """
    name = "mt5"
    is_live = True

    def __init__(self, login: int, server: str, password: str):
        raise NotImplementedError(
            "MT5 ต้องรันบน Windows VPS + ติดตั้ง MetaTrader5 package — "
            "รอยืนยันคำตอบข้อ 1 ก่อนลงทุนค่า VPS"
        )

    def place_order(self, pair, side, size, entry, sl, tp) -> dict: ...
    def close_order(self, order_id) -> dict: ...
    def get_positions(self) -> list: ...
    def get_balance(self) -> float: ...


def make_broker(kind: str = "paper", **kw) -> BrokerAdapter:
    """
    factory — ค่าเริ่มต้นคือ paper เสมอ (deny by default)
    เงินจริงต้องระบุ kind ชัดเจน + ผ่านการปลดล็อกใน executor อีกชั้น
    """
    kind = (kind or "paper").lower()
    if kind == "paper":
        return PaperBroker(**kw)
    if kind == "oanda":
        return OandaBroker(**kw)
    if kind == "mt5":
        return MT5Broker(**kw)
    raise ValueError(f"ไม่รู้จักโบรก: {kind}")
