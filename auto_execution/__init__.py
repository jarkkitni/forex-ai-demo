"""
Auto-Execution Add-on (สถานะ: เตรียมล่วงหน้า รอคำตอบลูกค้า 3 ข้อ)
- ข้อเสนอ/ราคา/T&C: Garuda
- โครงสร้างโค้ด + safety layer: SiriAriyaMate

⚠️ ค่าเริ่มต้น = PAPER MODE เสมอ (ไม่แตะเงินจริง)
"""
from .risk_guard import RiskGuard, RiskConfig
from .broker_adapter import BrokerAdapter, PaperBroker, OandaBroker, MT5Broker, make_broker
from .executor import Executor, CONFIRM_PHRASE
from . import runner, store

__all__ = [
    "RiskGuard", "RiskConfig",
    "BrokerAdapter", "PaperBroker", "OandaBroker", "MT5Broker", "make_broker",
    "Executor", "CONFIRM_PHRASE",
    "runner", "store",
]
