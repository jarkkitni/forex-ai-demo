"""
meta_bot.py — Facebook Messenger + Instagram DM handler สำหรับบอทร้านลูกค้า
ต่อ advisor จาก configs/<slug>.json เข้ากับ Meta Send API + AI ตอบ (ผ่าน ai_guard)

ENV ที่ใช้:
  META_VERIFY_TOKEN  — token ยืนยัน webhook (ตั้งเองให้ตรงกับที่กรอกในหน้า Meta)
  META_PAGE_TOKEN    — Page Access Token (ใช้ส่งข้อความทั้ง FB + IG ที่ผูกกับเพจ)
  META_APP_SECRET    — App Secret (ตรวจ signature X-Hub-Signature-256)
  META_SLUG          — ชื่อไฟล์ config ที่จะใช้ (ดีฟอลต์ "lullabell")

PAPER-SAFE: ไม่มีการเงิน ไม่มีลบข้อมูล — แค่รับ/ตอบข้อความ
"""
import os, json, hmac, hashlib, time
import requests

GRAPH = "https://graph.facebook.com/v21.0"

# ---- ความจำการสนทนาสั้นๆ ต่อผู้ส่ง (in-memory, รีเซ็ตเมื่อ restart) ----
_history: dict = {}      # sender_id -> [(role, text), ...]  เก็บ 8 เทิร์นล่าสุด
_hits: dict = {}         # sender_id -> [timestamps]  กัน spam
_MAX_TURNS = 8


def load_cfg(slug: str = "lullabell") -> dict:
    base = os.path.dirname(__file__)
    with open(os.path.join(base, "configs", f"{slug}.json"), encoding="utf-8") as f:
        return json.load(f)


def verify_signature(app_secret: str, body_bytes: bytes, header: str) -> bool:
    """ตรวจ X-Hub-Signature-256 — ถ้าไม่ได้ตั้ง secret ก็ผ่าน (dev)"""
    if not app_secret:
        return True
    if not header or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        app_secret.encode("utf-8"), body_bytes, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, header)


def _rate_ok(sender_id: str, limit: int = 40, window: int = 3600) -> bool:
    """กันคนยิงรัว — ดีฟอลต์ 40 ข้อความ/ชม./คน"""
    now = time.time()
    arr = [t for t in _hits.get(sender_id, []) if now - t < window]
    if len(arr) >= limit:
        _hits[sender_id] = arr
        return False
    arr.append(now)
    _hits[sender_id] = arr
    return True


def _menu_text(cfg: dict) -> str:
    """แปลง categories → เมนูข้อความกระชับ ให้ AI อ้างอิงราคาได้"""
    out = []
    for cat in cfg.get("categories", []):
        out.append(f"■ {cat.get('emoji','')} {cat.get('name','')} — {cat.get('desc','')}".strip())
        for grp in cat.get("groups", []):
            gname = grp.get("name", "")
            if gname:
                out.append(f"  · {gname}")
            for it in grp.get("items", []):
                n, p, d = it.get("n", ""), it.get("p", ""), it.get("d", "")
                line = f"    - {n}: {p}"
                if d:
                    line += f" ({d})"
                out.append(line)
        if cat.get("note"):
            out.append(f"  หมายเหตุ: {cat['note']}")
    return "\n".join(out)


def _system_prompt(cfg: dict) -> str:
    adv = cfg.get("advisor", {})
    c = cfg.get("contact", {})
    rules = adv.get("rules", [])
    rules_txt = "\n".join(f"- {r}" for r in rules) if isinstance(rules, list) else ""
    close_txt = "\n".join(f"- {x}" for x in cfg.get("close_lines", []))
    contact_txt = (
        f"โทร {c.get('phone','')} · LINE {c.get('line','')} · "
        f"ที่อยู่ {c.get('address','')} ({c.get('parking','')})"
    )
    return f"""คุณคือ "น้องเบลล์" ผู้ช่วยตอบแชทของร้าน {cfg.get('biz_full', cfg.get('biz_name',''))} {cfg.get('emoji','')}
สโลแกน: {cfg.get('tagline','')}

บทบาท: {adv.get('intro','')}

กติกาการตอบ:
{rules_txt}
- ตอบภาษาไทย สุภาพ อบอุ่น พรีเมียม ลงท้าย "ค่ะ/นะคะ" เหมาะกับร้านเสริมสวย
- สั้น กระชับ (2-5 บรรทัด) เพราะเป็นแชท — อย่ายาวเป็นพืด
- แนะนำบริการที่เหมาะจากเมนู อ้างราคาตามเมนูจริงเท่านั้น ห้ามแต่งราคาเอง
- ถ้าราคาขึ้นกับสภาพผม/ความยาว ให้บอกช่วงราคาแล้วชวนให้แอดมินประเมิน
- ถ้าลูกค้าสนใจจอง/ถามคิว → ชวนบอกวัน-เวลาที่สะดวก แล้วบอกว่าจะให้แอดมินยืนยันคิวให้
- ถ้าลูกค้าขอคุยคน/เรื่องซับซ้อนเกินเมนู → {adv.get('handoff_msg','ขอส่งต่อให้แอดมินนะคะ')} ({contact_txt})
- ห้ามสัญญาสิ่งที่ไม่มีในเมนู ห้ามให้คำแนะนำทางการแพทย์

ประโยคชวนปิดการขาย (ใช้ปรับได้):
{close_txt}

=== เมนูบริการและราคา (อ้างอิงเท่านั้น) ===
{_menu_text(cfg)}

ข้อมูลติดต่อร้าน: {contact_txt}
"""


def generate_reply(client, cfg: dict, sender_id: str, user_text: str,
                   notify_fn=None, line_user_id: str = "") -> str:
    import ai_guard
    hist = _history.get(sender_id, [])
    convo = "\n".join(f"{'ลูกค้า' if r=='user' else 'น้องเบลล์'}: {t}" for r, t in hist)
    prompt = (
        _system_prompt(cfg)
        + "\n\n=== บทสนทนาก่อนหน้า ===\n" + (convo or "(ยังไม่มี)")
        + f"\n\nลูกค้าเพิ่งพิมพ์ว่า: \"{user_text}\"\n"
        + "ตอบกลับในฐานะน้องเบลล์ (ข้อความเดียว สั้น กระชับ):"
    )
    reply = ai_guard.call(client, prompt, max_tokens=400, smart=True,
                          notify_fn=notify_fn, line_user_id=line_user_id)
    # อัปเดตความจำ
    hist = hist + [("user", user_text), ("bot", reply)]
    _history[sender_id] = hist[-_MAX_TURNS * 2:]
    return reply


def send_message(page_token: str, recipient_id: str, text: str) -> tuple:
    """ส่งข้อความกลับผ่าน Meta Send API (ใช้ได้ทั้ง FB + IG ที่ผูกเพจ)"""
    if not page_token:
        return 0, "no page token"
    url = f"{GRAPH}/me/messages"
    try:
        r = requests.post(
            url,
            params={"access_token": page_token},
            json={
                "recipient": {"id": recipient_id},
                "messaging_type": "RESPONSE",
                "message": {"text": text[:1900]},
            },
            timeout=15,
        )
        return r.status_code, r.text[:300]
    except Exception as e:
        return 0, str(e)[:200]


def handle(data: dict, client, page_token: str, slug: str = "lullabell",
           notify_fn=None, line_user_id: str = "") -> dict:
    """
    รับ payload จาก Meta webhook → ตอบทุก message event
    รองรับทั้ง object 'page' (Messenger) และ 'instagram'
    """
    result = {"replied": 0, "skipped": 0}
    try:
        cfg = load_cfg(slug)
    except Exception as e:
        return {"error": f"config: {e}"}

    for entry in data.get("entry", []):
        events = entry.get("messaging", []) or entry.get("standby", [])
        for ev in events:
            sender = ev.get("sender", {}).get("id", "")
            msg = ev.get("message", {})
            # ข้าม echo (ข้อความที่เราส่งเอง) / ไม่มี text / ไม่มี sender
            if not sender or msg.get("is_echo") or "text" not in msg:
                result["skipped"] += 1
                continue
            user_text = (msg.get("text") or "").strip()
            if not user_text:
                result["skipped"] += 1
                continue
            if not _rate_ok(sender):
                result["skipped"] += 1
                continue
            try:
                reply = generate_reply(client, cfg, sender, user_text,
                                       notify_fn=notify_fn, line_user_id=line_user_id)
                send_message(page_token, sender, reply)
                result["replied"] += 1
            except Exception:
                # AI ตาย ai_guard เด้ง LINE ให้แล้ว — ส่งข้อความ fallback ให้ลูกค้าไม่เงียบ
                fb = cfg.get("advisor", {}).get("handoff_msg",
                     "ขออภัยค่ะ ระบบขัดข้องชั่วคราว เดี๋ยวแอดมินติดต่อกลับนะคะ 🤍")
                send_message(page_token, sender, fb)
                result["skipped"] += 1
    return result
