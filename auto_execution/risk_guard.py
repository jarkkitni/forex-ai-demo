"""
RiskGuard — ชั้นความปลอดภัยของ Auto-Execution
ปรัชญา: ปฏิเสธไว้ก่อน (deny by default) — ทุกออเดอร์ต้องผ่านด่านนี้ก่อนถึงโบรกเกอร์
อ้างอิงเงื่อนไขจาก: auto_execution_proposal_draft (Garuda, 17 ก.ค. 2026)
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone, date
from typing import Optional


@dataclass
class RiskConfig:
    """ค่าที่ต้องกรอกจากคำตอบลูกค้า 3 ข้อ (ห้ามใช้ default เงียบๆ กับเงินจริง)"""
    account_balance: float                 # ข้อ 2: งบเทรด
    max_daily_loss: float                  # ข้อ 3: ขาดทุนสูงสุด/วัน (จำนวนเงิน)
    max_risk_per_trade_pct: float = 1.0    # เสี่ยงต่อไม้ (% ของพอร์ต) — มาตรฐาน 1-2%
    max_open_positions: int = 3
    max_trades_per_day: int = 10
    min_confidence: int = 70               # คะแนน AI ขั้นต่ำที่ยอมให้ยิง
    require_sl_tp: bool = True             # บังคับเสมอ — ห้ามปิด


@dataclass
class DailyState:
    day: date = field(default_factory=lambda: datetime.now(timezone.utc).date())
    realized_pnl: float = 0.0
    trades_today: int = 0
    open_positions: int = 0
    halted: bool = False
    halt_reason: str = ""

    def roll_if_new_day(self):
        today = datetime.now(timezone.utc).date()
        if self.day != today:
            self.day = today
            self.realized_pnl = 0.0
            self.trades_today = 0
            self.halted = False
            self.halt_reason = ""


class RiskGuard:
    def __init__(self, cfg: RiskConfig):
        self.cfg = cfg
        self.state = DailyState()

    # ---------- ด่านตรวจก่อนยิงออเดอร์ ----------
    def check(self, signal: dict) -> tuple[bool, str]:
        """คืน (ผ่านไหม, เหตุผล)"""
        s = self.state
        s.roll_if_new_day()

        if s.halted:
            return False, f"ระบบหยุดทำงานวันนี้: {s.halt_reason}"

        # 1) บังคับ SL/TP — ไม่มีข้อยกเว้น
        if self.cfg.require_sl_tp:
            if not signal.get("stop_loss") or not signal.get("take_profit"):
                return False, "ปฏิเสธ: ออเดอร์ไม่มี SL/TP"

        # 2) สัญญาณต้องเป็น BUY/SELL เท่านั้น
        if signal.get("signal") not in ("BUY", "SELL"):
            return False, f"ข้าม: สัญญาณเป็น {signal.get('signal')}"

        # 3) ความมั่นใจ AI ต้องถึงเกณฑ์
        conf = signal.get("confidence", 0)
        if conf < self.cfg.min_confidence:
            return False, f"ข้าม: ความมั่นใจ {conf}% < เกณฑ์ {self.cfg.min_confidence}%"

        # 4) Max Daily Loss Cutoff (เงื่อนไขบังคับตามข้อเสนอ)
        if s.realized_pnl <= -abs(self.cfg.max_daily_loss):
            self.halt(f"ถึงขีดขาดทุนสูงสุดของวัน ({self.cfg.max_daily_loss:,.0f})")
            return False, s.halt_reason

        # 5) จำนวนไม้/วัน
        if s.trades_today >= self.cfg.max_trades_per_day:
            return False, f"ปฏิเสธ: ครบโควตา {self.cfg.max_trades_per_day} ไม้/วันแล้ว"

        # 6) ไม้ที่เปิดค้างพร้อมกัน
        if s.open_positions >= self.cfg.max_open_positions:
            return False, f"ปฏิเสธ: มีไม้เปิดค้าง {s.open_positions} ไม้ (สูงสุด {self.cfg.max_open_positions})"

        # 7) ระยะ SL ต้องสมเหตุสมผล (กัน SL = ราคาเข้า)
        entry = float(signal.get("entry_price", 0) or 0)
        sl = float(signal.get("stop_loss", 0) or 0)
        if entry <= 0 or sl <= 0 or abs(entry - sl) < entry * 0.0001:
            return False, "ปฏิเสธ: ระยะ SL ผิดปกติ"

        return True, "ผ่าน"

    # ---------- คำนวณขนาดไม้จากความเสี่ยงที่ยอมรับได้ ----------
    def position_size(self, signal: dict) -> float:
        entry = float(signal["entry_price"])
        sl = float(signal["stop_loss"])
        risk_amount = self.cfg.account_balance * (self.cfg.max_risk_per_trade_pct / 100)
        risk_per_unit = abs(entry - sl)
        if risk_per_unit <= 0:
            return 0.0
        return round(risk_amount / risk_per_unit, 4)

    # ---------- บันทึกผลหลังปิดไม้ ----------
    def record_open(self):
        self.state.trades_today += 1
        self.state.open_positions += 1

    def record_close(self, pnl: float):
        self.state.open_positions = max(0, self.state.open_positions - 1)
        self.state.realized_pnl += pnl
        if self.state.realized_pnl <= -abs(self.cfg.max_daily_loss):
            self.halt(f"ถึงขีดขาดทุนสูงสุดของวัน ({self.cfg.max_daily_loss:,.0f})")

    def halt(self, reason: str):
        """Kill switch — หยุดเทรดทันที (เรียกเองได้ตลอดเวลา)"""
        self.state.halted = True
        self.state.halt_reason = reason

    def resume(self):
        self.state.halted = False
        self.state.halt_reason = ""

    def snapshot(self) -> dict:
        s = self.state
        return {
            "day": s.day.isoformat(),
            "realized_pnl": round(s.realized_pnl, 2),
            "trades_today": s.trades_today,
            "open_positions": s.open_positions,
            "halted": s.halted,
            "halt_reason": s.halt_reason,
            "max_daily_loss": self.cfg.max_daily_loss,
            "loss_used_pct": round(abs(min(s.realized_pnl, 0)) / abs(self.cfg.max_daily_loss) * 100, 1)
                             if self.cfg.max_daily_loss else 0,
        }
