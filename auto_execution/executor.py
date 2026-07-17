"""
Executor — ต่อ AI signal → RiskGuard → Broker
ปรัชญา: ทุกออเดอร์ต้องผ่าน RiskGuard เสมอ ไม่มีทางลัด

ชั้นล็อกเงินจริง (ต้องครบทั้ง 3 ถึงจะยิงเงินจริงได้):
  1. env AUTO_EXEC_MODE = "live"
  2. env AUTO_EXEC_CONFIRM = "I_UNDERSTAND_REAL_MONEY_RISK"
  3. ส่ง broker adapter ที่ is_live=True เข้ามาเอง
ขาดข้อใดข้อหนึ่ง → ตกกลับเป็น PAPER อัตโนมัติ
"""
import os
from datetime import datetime, timezone

from .risk_guard import RiskGuard, RiskConfig
from .broker_adapter import BrokerAdapter, PaperBroker

CONFIRM_PHRASE = "I_UNDERSTAND_REAL_MONEY_RISK"


class Executor:
    def __init__(self, risk_cfg: RiskConfig, broker: BrokerAdapter | None = None,
                 notify_fn=None, line_user_id: str = ""):
        self.guard = RiskGuard(risk_cfg)
        self.notify_fn = notify_fn          # ฟังก์ชัน push LINE (ใช้ _push_line เดิม)
        self.line_user_id = line_user_id
        self.log: list = []
        self.broker: BrokerAdapter = PaperBroker(starting_balance=risk_cfg.account_balance)

        self.broker = self._resolve_broker(broker)

    # ---------- ชั้นล็อกเงินจริง ----------
    def _resolve_broker(self, broker: BrokerAdapter | None) -> BrokerAdapter:
        if broker is None:
            return PaperBroker(starting_balance=self.guard.cfg.account_balance)

        if not broker.is_live:
            return broker

        mode = os.environ.get("AUTO_EXEC_MODE", "paper").lower()
        confirm = os.environ.get("AUTO_EXEC_CONFIRM", "")

        if mode != "live" or confirm != CONFIRM_PHRASE:
            self._audit("SAFETY", "ขอใช้โบรกเงินจริงแต่ยังไม่ปลดล็อก → ตกกลับเป็น PAPER")
            return PaperBroker(starting_balance=self.guard.cfg.account_balance)

        self._audit("SAFETY", f"⚠️ เปิดโหมดเงินจริงกับ {broker.name}")
        return broker

    @property
    def is_live(self) -> bool:
        return self.broker.is_live

    # ---------- flow หลัก ----------
    def handle_signal(self, signal: dict) -> dict:
        ok, reason = self.guard.check(signal)
        if not ok:
            self._audit("REJECT", reason, signal)
            return {"executed": False, "reason": reason, "mode": self._mode()}

        size = self.guard.position_size(signal)
        if size <= 0:
            self._audit("REJECT", "คำนวณขนาดไม้ได้ 0", signal)
            return {"executed": False, "reason": "ขนาดไม้เป็น 0", "mode": self._mode()}

        try:
            res = self.broker.place_order(
                pair=signal.get("pair", ""),
                side=signal["signal"],
                size=size,
                entry=float(signal["entry_price"]),
                sl=float(signal["stop_loss"]),
                tp=float(signal["take_profit"]),
            )
        except Exception as e:
            self._audit("ERROR", f"ยิงออเดอร์ล้มเหลว: {e}", signal)
            self._alert(f"🚨 Auto-Execution ผิดพลาด\n{e}\nระบบหยุดชั่วคราวเพื่อความปลอดภัย")
            self.guard.halt(f"เกิด error: {e}")
            return {"executed": False, "reason": str(e), "mode": self._mode()}

        if not res.get("success"):
            self._audit("ERROR", f"โบรกปฏิเสธ: {res.get('error')}", signal)
            return {"executed": False, "reason": res.get("error"), "mode": self._mode()}

        self.guard.record_open()
        self._audit("EXECUTE", f"เปิดไม้ {signal['signal']} {signal.get('pair')} size={size}", signal)
        self._alert(
            f"{'🔴 เงินจริง' if self.is_live else '📝 PAPER'} | เปิดไม้แล้ว\n"
            f"{signal.get('pair')} {signal['signal']} @ {signal['entry_price']}\n"
            f"SL {signal['stop_loss']} | TP {signal['take_profit']}\n"
            f"ขนาด {size} | ความมั่นใจ {signal.get('confidence')}%\n"
            f"ไม้วันนี้ {self.guard.state.trades_today}/{self.guard.cfg.max_trades_per_day}"
        )
        return {"executed": True, "mode": self._mode(), "order": res, "size": size}

    def close(self, order_id: str, exit_price: float | None = None) -> dict:
        try:
            res = (self.broker.close_order(order_id, exit_price)
                   if isinstance(self.broker, PaperBroker)
                   else self.broker.close_order(order_id))
        except Exception as e:
            self._audit("ERROR", f"ปิดไม้ล้มเหลว: {e}")
            return {"success": False, "error": str(e)}

        if res.get("success"):
            pnl = res.get("pnl", 0)
            self.guard.record_close(pnl)
            self._audit("CLOSE", f"ปิดไม้ {order_id} P/L={pnl}")
            if self.guard.state.halted:
                self._alert(f"🛑 ระบบหยุดเทรดวันนี้\n{self.guard.state.halt_reason}")
        return res

    def kill_switch(self, reason: str = "สั่งหยุดด้วยมือ") -> dict:
        """ปุ่มหยุดฉุกเฉิน — ใช้ได้ทุกเมื่อ (ตาม T&C ข้อ 4)"""
        self.guard.halt(reason)
        self._audit("HALT", reason)
        self._alert(f"🛑 Auto-Execution หยุดทำงาน\nเหตุผล: {reason}")
        return {"halted": True, "reason": reason}

    # ---------- helper ----------
    def _mode(self) -> str:
        return "LIVE" if self.is_live else "PAPER"

    def _audit(self, kind: str, msg: str, signal: dict | None = None):
        self.log.append({
            "time": datetime.now(timezone.utc).isoformat(),
            "kind": kind, "msg": msg,
            "pair": (signal or {}).get("pair"),
            "mode": self._mode(),
        })
        self.log = self.log[-100:]
        print(f"[AutoExec][{kind}] {msg}", flush=True)

    def _alert(self, text: str):
        if self.notify_fn and self.line_user_id:
            try:
                self.notify_fn(self.line_user_id, text)
            except Exception as e:
                print(f"[AutoExec] แจ้งเตือนล้มเหลว: {e}", flush=True)

    def status(self) -> dict:
        return {
            "mode": self._mode(),
            "broker": self.broker.name,
            "balance": self.broker.get_balance(),
            "open_positions": self.broker.get_positions(),
            "risk": self.guard.snapshot(),
            "recent_log": self.log[-10:],
        }
