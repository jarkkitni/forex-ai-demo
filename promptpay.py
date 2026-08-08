"""
promptpay.py — สร้าง QR PromptPay ตามสเปก EMVCo ของธนาคารแห่งประเทศไทย

ทำไมสร้างเอง ไม่เรียก service ภายนอก:
  ยอดเงินและเบอร์/เลขบัตรของผู้รับเงินเป็นข้อมูลการเงิน ห้ามส่งออกนอกเซิร์ฟเวอร์เรา
  สเปกนี้เป็นมาตรฐานเปิด คำนวณเองได้ครบใน 60 บรรทัด ไม่ต้องพึ่งใคร

โครง payload (TLV — tag 2 หลัก + ความยาว 2 หลัก + ค่า):
  00 02 01                     Payload Format Indicator
  01 02 11|12                  11 = QR ใช้ซ้ำได้ (ไม่ระบุยอด) · 12 = ใช้ครั้งเดียว (ระบุยอด)
  29 xx                        ข้อมูลผู้รับเงิน PromptPay
     00 16 A000000677010111    Application ID ของ PromptPay
     01 13 0066xxxxxxxxx       เบอร์มือถือ (ตัด 0 หน้าออก ใส่ 0066)
     02 13 xxxxxxxxxxxxx       หรือเลขบัตรประชาชน 13 หลัก
  53 03 764                    สกุลเงิน THB (ISO 4217)
  54 xx <amount>               ยอดเงิน (ใส่เมื่อระบุยอด)
  58 02 TH                     ประเทศ
  63 04 <crc>                  CRC16-CCITT ของทุกอย่างข้างบน รวม "6304" ด้วย
"""

from __future__ import annotations

import base64
import io
import re

AID_PROMPTPAY = "A000000677010111"


def _tlv(tag: str, value: str) -> str:
    """หนึ่งช่อง TLV — ความยาวเป็นเลข 2 หลักเสมอ"""
    return f"{tag}{len(value):02d}{value}"


def crc16_ccitt(data: str) -> str:
    """CRC16-CCITT (XModem): poly 0x1021, init 0xFFFF — สเปกบังคับใช้ตัวนี้เท่านั้น"""
    crc = 0xFFFF
    for ch in data.encode("ascii"):
        crc ^= ch << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def normalize_target(target: str) -> tuple[str, str]:
    """
    คืน (tag, value) ของผู้รับเงิน
      เบอร์มือถือ 10 หลักขึ้นต้น 0  -> tag 01, 0066 + 9 หลักที่เหลือ
      เลขบัตรประชาชน 13 หลัก        -> tag 02
      เลขกระเป๋าเงิน 15 หลัก         -> tag 03
    ตัวคั่นทุกชนิด (เว้นวรรค ขีด วงเล็บ) ถูกตัดทิ้งก่อนเสมอ
    """
    digits = re.sub(r"\D", "", target or "")
    if len(digits) == 10 and digits.startswith("0"):
        return "01", "0066" + digits[1:]
    if len(digits) == 13:
        return "02", digits
    if len(digits) == 15:
        return "03", digits
    raise ValueError(
        f"เลขผู้รับเงินไม่ถูกรูปแบบ: ได้ {len(digits)} หลัก "
        "(ต้องเป็นเบอร์มือถือ 10 หลัก, เลขบัตรประชาชน 13 หลัก หรือเลขกระเป๋าเงิน 15 หลัก)"
    )


def build_payload(target: str, amount: float | None = None) -> str:
    """สร้างสตริง payload ที่เอาไปทำ QR ได้ทันที"""
    tag, value = normalize_target(target)

    # ระบุยอด = QR ใช้ได้ครั้งเดียว (12) กันลูกค้าสแกนซ้ำแล้วจ่ายผิดยอด
    parts = [
        _tlv("00", "01"),
        _tlv("01", "12" if amount else "11"),
        _tlv("29", _tlv("00", AID_PROMPTPAY) + _tlv(tag, value)),
        _tlv("53", "764"),
    ]
    if amount:
        parts.append(_tlv("54", f"{float(amount):.2f}"))
    parts.append(_tlv("58", "TH"))

    body = "".join(parts) + "6304"       # ต้องต่อ "6304" ก่อนคำนวณ CRC
    return body + crc16_ccitt(body)


def make_qr_data_uri(payload: str, box_size: int = 8) -> str:
    """คืน PNG เป็น data URI ให้ฝังใน <img> ได้ตรง ๆ — ไม่ต้องเขียนไฟล์ลงดิสก์"""
    import qrcode  # นำเข้าตรงนี้เพื่อให้ไฟล์นี้ import ได้แม้เครื่องยังไม่ได้ลง qrcode

    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=box_size, border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def make_payment_qr(target: str, amount: float | None = None) -> dict:
    """ปลายทางที่ api_server เรียกใช้ — คืนทั้ง payload และรูปพร้อมแสดง"""
    payload = build_payload(target, amount)
    return {"payload": payload, "image": make_qr_data_uri(payload), "amount": amount}
