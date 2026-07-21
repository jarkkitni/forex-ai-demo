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
import os, json, hmac, hashlib, time, re, traceback
from datetime import datetime, timezone
import requests
import seo_tracker  # ใช้ SUPABASE_URL / SUPABASE_KEY ร่วมกัน (multi-tenant page routing, เหมือน fastwork_hunter)

GRAPH = "https://graph.facebook.com/v21.0"

# ---- ความจำการสนทนาสั้นๆ ต่อผู้ส่ง (in-memory, รีเซ็ตเมื่อ restart) ----
_history: dict = {}      # sender_id -> [(role, text), ...]  เก็บ 8 เทิร์นล่าสุด
_hits: dict = {}         # sender_id -> [timestamps]  กัน spam
_MAX_TURNS = 8

# ---- กันตอบซ้ำตอน Meta ส่ง webhook event เดิมมาซ้ำ (in-memory, รีเซ็ตเมื่อ restart) ----
# เจอจริง 21 ก.ค. 2026 (IG): ตอน AI cascade ช้า (Claude/Groq ล่มพร้อมกัน ต้องลองหลาย provider
# กว่าจะจบ) Render ตอบ Meta ไม่ทัน Meta เลยส่ง webhook event เดิมซ้ำมาให้อีก (เห็นจาก log
# "POST /webhook/meta" 3 ครั้งซ้อนกันภายใน 1 วินาที สำหรับข้อความเดียว) — handle() เดิมประมวลผล
# ทุก event ที่เข้ามาโดยไม่เช็คว่าเคยตอบไปแล้วหรือยัง ทำให้ลูกค้าได้คำตอบซ้ำหลายข้อความ (แต่ละครั้ง
# AI สุ่มตอบไม่เหมือนกันด้วย ดูเหมือนบอทเพี้ยน/ตอบมั่ว) Meta เองก็บอกไว้ในเอกสารว่า delivery เป็น
# "at-least-once" ผู้ใช้ต้องกันซ้ำเองด้วย message id (mid) — เพิ่ม dedup ตรงนี้แก้ที่ต้นตอเลย
_processed_events: dict = {}   # event_key -> timestamp ที่ประมวลผล
_DEDUP_TTL = 600                # เก็บ key ไว้ 10 นาทีพอ (Meta ไม่น่า retry นานขนาดนั้น) กันหน่วยความจำบวมไม่จำกัด


def _already_processed(key: str) -> bool:
    """เช็ค+บันทึกว่า event นี้เคยประมวลผลไปแล้วหรือยัง (กัน Meta ส่ง webhook ซ้ำ)
    คืน True ถ้าเคยแล้ว (ให้ข้ามได้เลย), False ถ้ายังไม่เคย (บันทึกไว้แล้วเดินหน้าต่อได้)"""
    if not key:
        return False  # ไม่มี key ให้เช็ค (เช่น event แปลกๆ) — ประมวลผลไปตามปกติ ไม่เสี่ยงบล็อกผิด
    now = time.time()
    # กวาดทิ้ง key เก่าเกิน TTL ทุกครั้งที่เรียก กันหน่วยความจำโตไม่จำกัดโดยไม่ต้องมี background job แยก
    for k in [k for k, t in _processed_events.items() if now - t > _DEDUP_TTL]:
        del _processed_events[k]
    if key in _processed_events:
        return True
    _processed_events[key] = now
    return False

# ---- แท็กจับคิว — AI แปะท้ายข้อความเวลาลูกค้าบอกวัน-เวลาที่ต้องการจอง ----
_BOOKING_RE = re.compile(r'\n?\[\[BOOKING:\s*(.*?)\s*\]\]', re.S)
_BOOKING_FIELDS = ("บริการ", "วันที่", "เวลา", "ชื่อ", "เบอร์")

# ---- แท็กเลือกโปร — AI แปะท้ายข้อความเวลาแนะนำโปร 2 อย่างขึ้นไป ให้ลูกค้ากดเลือกแทนพิมพ์ ----
_PROMO_RE = re.compile(r'\n?\[\[PROMO:\s*(.*?)\s*\]\]', re.S)
_PROMO_TITLE_MAX = 20  # ขีดจำกัด title ปุ่ม quick reply ของ Meta

# ---- Ice Breakers — ปุ่มคำถามให้เลือกกดตอนลูกค้าใหม่เปิดแชทครั้งแรก ----
# question = ข้อความปุ่มที่ลูกค้าเห็น (ตั้งค่าจริงผ่าน setup_ice_breakers.py ยิงไปที่ Meta)
# payload  = รหัสที่ Meta ส่งกลับมาตอนลูกค้ากด (ไม่ใช่ข้อความ ต้อง map เอง)
ICE_BREAKERS = [
    {"question": "ดูราคา/โปรโมชั่น", "payload": "IB_PRICE"},
    {"question": "อยากจองคิว", "payload": "IB_BOOKING"},
    {"question": "ที่อยู่/เวลาเปิด", "payload": "IB_LOCATION"},
    {"question": "มีบริการอะไรบ้าง", "payload": "IB_SERVICES"},
]
# payload -> ข้อความที่จะป้อนให้ AI ประมวลผลต่อ เหมือนลูกค้าพิมพ์เอง
_ICE_BREAKER_TEXT = {
    "IB_PRICE": "ขอดูราคาและโปรโมชั่นทั้งหมดค่ะ",
    "IB_BOOKING": "อยากจองคิวค่ะ",
    "IB_LOCATION": "ขอที่อยู่ร้านและเวลาเปิด-ปิดค่ะ",
    "IB_SERVICES": "มีบริการอะไรบ้างคะ",
}

# ---- Quick Replies — ปุ่มลัด 4 ตัวเลือกเดิม แนบไปกับทุกข้อความที่บอทตอบ ----
# ต่างจาก Ice Breakers (โผล่แค่ตอนเปิดแชทครั้งแรก) ตัวนี้ติดมากับทุกคำตอบ กดแทนพิมพ์ได้ตลอดบทสนทนา
QUICK_REPLIES = [
    {"content_type": "text", "title": qb["question"], "payload": qb["payload"]}
    for qb in ICE_BREAKERS
]

# ---- เวอร์ชันอังกฤษของปุ่มลัด — ใช้ payload เดิมเป๊ะ (แค่ label เปลี่ยน) กันลูกค้าต่างชาติเจอปุ่มไทย ----
ICE_BREAKERS_EN = [
    {"question": "Prices / Promotions", "payload": "IB_PRICE"},
    {"question": "Book an appointment", "payload": "IB_BOOKING"},
    {"question": "Address / Hours", "payload": "IB_LOCATION"},
    {"question": "Our services", "payload": "IB_SERVICES"},
]
_ICE_BREAKER_TEXT_EN = {
    "IB_PRICE": "Please show me all prices and promotions.",
    "IB_BOOKING": "I'd like to book an appointment.",
    "IB_LOCATION": "Can I get the address and opening hours?",
    "IB_SERVICES": "What services do you offer?",
}
QUICK_REPLIES_EN = [
    {"content_type": "text", "title": qb["question"], "payload": qb["payload"]}
    for qb in ICE_BREAKERS_EN
]

_THAI_CHAR_RE = re.compile(r'[฀-๿]')


def _is_thai(text: str) -> bool:
    """เดาภาษาแบบง่ายจากตัวอักษรไทย — ใช้เลือกชุดปุ่ม Quick Reply (ไทย/อังกฤษ) ให้ตรงกับภาษาที่ลูกค้าใช้ล่าสุด
    ไม่มีตัวอักษรไทยเลย = ถือว่าเป็นอังกฤษ (หรือภาษาอื่นที่ AI จะตอบเป็นอังกฤษตามกติกาเริ่มต้น)"""
    return bool(_THAI_CHAR_RE.search(text or ""))


_LOCATION_RE = re.compile(
    r'ที่อยู่|แผนที่|ทางมา|เส้นทาง|เดินทางมา|อยู่ที่ไหน|อยู่ตรงไหน|อยู่ไหน|อยู่แถวไหน|'
    r'\bmap\b|\blocation\b|\baddress\b|\bdirection', re.I
)


def _is_location_query(text: str) -> bool:
    """เดาว่าลูกค้ากำลังถามเรื่องที่อยู่/ทางมาร้านไหม — ใช้ตัดสินใจว่าจะแนบรูปการ์ดแผนที่ (map-card) ไปด้วยหรือเปล่า
    คำตอบพลาด (false positive/negative) ไม่ร้ายแรง แค่ไม่ได้แนบรูป/แนบเกิน ไม่กระทบคำตอบข้อความหลัก"""
    return bool(_LOCATION_RE.search(text or ""))


_PRICE_QUERY_RE = re.compile(
    r'ราคา|โปร|เท่าไหร่|เท่าไร|กี่บาท|เมนู|บริการอะไร|มีอะไรบ้าง|มีบริการ|ทำอะไรได้บ้าง|'
    r'\bprice\b|\bpromotion\b|\bpromo\b|\bcost\b|how much|\bmenu\b', re.I
)


def _is_price_query(text: str) -> bool:
    """เดาว่าลูกค้ากำลังถามราคา/โปรโมชั่น/เมนูไหม — ใช้เฉพาะตอน AI ล่มสนิท (ทั้ง Claude และ Groq ตายพร้อมกัน)
    เพื่อเลือกตอบจาก template ราคาจริงแทนข้อความ "รอสักครู่" เฉยๆ คำตอบพลาด (false positive) ไม่ร้ายแรง
    แค่ได้ราคาแถมมาเกินคำถามจริง ไม่ใช่เรื่องใหญ่"""
    return bool(_PRICE_QUERY_RE.search(text or ""))


# คำว่า "โปร"/"promo" เป๊ะๆ — เข้มกว่า _PRICE_QUERY_RE ด้านบนเจตนา (ซึ่งครอบคลุมกว้างกว่ารวม "ราคา"/"เมนู"/
# "บริการอะไร" ด้วย) ตัวนี้ใช้เฉพาะกรณีต้องการันตีคำตอบ 100% ไม่ผ่าน AI เลย (21 ก.ค. 2026 ตามคำขอ sIRImeta
# "ห้ามเงียบ/ปล่อยว่าง/ตอบแค่รอสักครู่ ตอนลูกค้าถามโปรโมชั่น") ต้องแคบกว่าเดิมเพื่อไม่ไปครอบคำถามราคาเฉพาะ
# บริการที่ควรให้ AI ตอบตามบริบท (เช่น "ทำสีราคาเท่าไหร่" ไม่มีคำว่า "โปร" เลย จะไม่โดนจับ ยังไป AI เหมือนเดิม)
_PROMO_QUERY_RE = re.compile(r'โปร|\bpromo\w*', re.I)


def _is_promo_query(text: str) -> bool:
    """เดาว่าลูกค้าถามหา "โปรโมชั่น" ตรงๆ ไหม (คำว่า โปร/โปรโมชั่น/promo/promotion) — ใช้เป็น fast-path
    การันตีคำตอบ 100% เสมอ ไม่ว่า AI จะปกติ/ล่ม/ตอบห้วน ไม่ใช่แค่ตอน AI ล่มสนิทเหมือน _is_price_query"""
    return bool(_PROMO_QUERY_RE.search(text or ""))


_BOLD_DIGIT_MAP = str.maketrans("0123456789", "𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗")


def _bold_price(price_text: str) -> str:
    """แปลงเฉพาะตัวเลขในสตริงราคาให้เป็น Unicode bold digit (เช่น "2,990.-" → "𝟐,𝟗𝟗𝟬.-")
    ใช้แทนตัวหนาสไตล์ Markdown (**) ที่ Messenger ไม่รองรับ — Unicode bold เป็นตัวอักษรจริงๆ คนละตัวกับเลขปกติ
    เลยโชว์เป็นตัวหนาได้ในทุกแอปรวมถึง Messenger โดยไม่ต้องพึ่งการ render markdown เลย
    ทำแบบ deterministic ล้วนๆ (str.translate ตรงๆ ไม่ผ่าน AI) การันตีราคาไม่มีวันเพี้ยนหรือพัง"""
    return (price_text or "").translate(_BOLD_DIGIT_MAP)


def _parse_booking_tag(text: str) -> tuple:
    """แยกแท็ก [[BOOKING: ...]] ออกจากข้อความที่จะส่งลูกค้า คืน (ข้อความสะอาด, dict หรือ None)"""
    m = _BOOKING_RE.search(text or "")
    if not m:
        return (text or "").strip(), None
    clean = _BOOKING_RE.sub("", text).strip()
    fields = {}
    for pair in m.group(1).split("|"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            k, v = k.strip(), v.strip()
            if k in _BOOKING_FIELDS and v and v != "-":
                fields[k] = v
    # ต้องมีอย่างน้อย "วันที่" หรือ "เวลา" ถึงจะถือว่าเป็นคิวจริง กันเคส AI แปะแท็กมาลอยๆ
    if not (fields.get("วันที่") or fields.get("เวลา")):
        return clean, None
    return clean, fields


def _parse_promo_tag(text: str) -> tuple:
    """แยกแท็ก [[PROMO: ชื่อ1 | ชื่อ2 | ...]] ออกจากข้อความ คืน (ข้อความสะอาด, list ชื่อโปร หรือ None)
    ใช้ตอน AI แนะนำโปรหลายอย่าง — แปลงเป็นปุ่ม quick reply ให้ลูกค้ากดเลือกแทนพิมพ์"""
    m = _PROMO_RE.search(text or "")
    if not m:
        return (text or "").strip(), None
    clean = _PROMO_RE.sub("", text).strip()
    names = [n.strip()[:_PROMO_TITLE_MAX] for n in m.group(1).split("|") if n.strip()]
    names = names[:8]  # กันปุ่มเยอะเกินไป (รวมกับปุ่มอื่นต้องไม่เกิน 13 ตามสเปก Meta)
    return clean, names or None


def _build_promo_quick_replies(names: list) -> list:
    """สร้างปุ่ม quick reply จากรายชื่อโปร — กดแล้ว Meta จะส่ง title ปุ่มกลับมาเป็นข้อความลูกค้าเอง
    (ไม่ต้อง map payload->ข้อความเหมือน Ice Breaker เพราะ title คือข้อความอยู่แล้ว)"""
    return [{"content_type": "text", "title": n, "payload": f"PROMO_{i}"} for i, n in enumerate(names)]


# ---- Config store: DB-first + file fallback + TTL cache (นกน้อยพิมพ์รัง ชั้น 2 — 21 ก.ค. 2026) ----
# เดิม config ของร้านอ่านจากไฟล์ configs/{slug}.json อย่างเดียว → ร้านใหม่ต้อง commit ไฟล์ทุกครั้ง
# ทำให้ฟอร์มเว็บ (รันบน Render ดิสก์ ephemeral) สร้างร้านใหม่เองไม่ได้
# ย้ายมาอ่านจากตาราง shop_configs (Supabase) ก่อน — ฟอร์มเขียน row ใหม่ได้เลย ไม่ต้อง deploy
# หาใน DB ไม่เจอ = fallback อ่านไฟล์เดิม (Lullabell/ร้านที่ยังเป็นไฟล์รอดเสมอ แม้ตาราง shop_configs
# จะยังไม่มี/ยังไม่มี row) — วินัย fallback-first เหมือน resolve_page()
_cfg_cache: dict = {}          # slug -> {"cfg": dict, "at": float}
_CFG_TTL = 60                  # cache config ในแรม 60 วิ กัน DB ถูกยิงทุกข้อความที่ลูกค้าทัก


def _load_cfg_from_db(slug: str):
    """คืน dict config จาก shop_configs ถ้ามี (active=true) — ไม่มี/พลาด/DB ปิด = None (ให้ fallback ไฟล์)"""
    if not (seo_tracker.SUPABASE_URL and seo_tracker.SUPABASE_KEY):
        return None
    try:
        r = requests.get(
            f"{seo_tracker.SUPABASE_URL}/rest/v1/shop_configs"
            f"?slug=eq.{slug}&active=eq.true&select=config&limit=1",
            headers=_sb_headers(), timeout=15)
        if r.ok:
            rows = r.json()
            if rows:
                return rows[0].get("config")
    except Exception as e:
        print(f"[meta_bot] load cfg from DB fail slug={slug}: {e}", flush=True)
    return None


def _load_cfg_from_file(slug: str) -> dict:
    base = os.path.dirname(__file__)
    with open(os.path.join(base, "configs", f"{slug}.json"), encoding="utf-8") as f:
        return json.load(f)


def load_cfg(slug: str = "lullabell") -> dict:
    """อ่าน config ของร้าน: cache แรม → shop_configs (DB) → ไฟล์ configs/{slug}.json (fallback)
    raise ถ้าหาไม่เจอทั้ง DB และไฟล์ (พฤติกรรม raise เดิมคงไว้ — ผู้เรียกจับ except อยู่แล้ว)"""
    now = time.time()
    hit = _cfg_cache.get(slug)
    if hit and (now - hit["at"]) < _CFG_TTL:
        return hit["cfg"]
    cfg = _load_cfg_from_db(slug)
    if cfg is None:
        cfg = _load_cfg_from_file(slug)   # raise FileNotFoundError ถ้าไม่มีไฟล์ด้วย = ไม่รู้จักร้านนี้จริงๆ
    _cfg_cache[slug] = {"cfg": cfg, "at": now}
    return cfg


def invalidate_cfg_cache(slug: str = None) -> None:
    """ล้าง cache config (เรียกหลังบันทึก config ใหม่ผ่านฟอร์ม เพื่อให้ preview เห็นทันทีไม่ต้องรอ TTL)"""
    if slug:
        _cfg_cache.pop(slug, None)
    else:
        _cfg_cache.clear()


def cfg_exists(slug: str) -> bool:
    """มี config ของ slug นี้ไหม (DB หรือไฟล์) — ใช้แทน os.path.exists() เป็น 404 guard"""
    try:
        load_cfg(slug)
        return True
    except Exception:
        return False


def save_config(slug: str, cfg: dict) -> tuple:
    """upsert config ร้านลง shop_configs (ผ่าน service key) — เรียกจากฟอร์ม /api/botkit/provision
    คืน (True, "") ถ้าสำเร็จ, (False, error) ถ้าพลาด และล้าง cache ให้เห็นผลทันที"""
    if not (seo_tracker.SUPABASE_URL and seo_tracker.SUPABASE_KEY):
        return False, "SUPABASE_URL/SUPABASE_SERVICE_KEY ยังไม่ได้ตั้งบน Render"
    try:
        payload = {"slug": slug, "config": cfg, "active": True,
                   "updated_at": datetime.now(timezone.utc).isoformat()}
        r = requests.post(
            f"{seo_tracker.SUPABASE_URL}/rest/v1/shop_configs?on_conflict=slug",
            headers={**_sb_headers(), "Prefer": "resolution=merge-duplicates"},
            data=json.dumps(payload), timeout=15)
        if r.ok:
            invalidate_cfg_cache(slug)
            return True, ""
        return False, r.text[:300]
    except Exception as e:
        return False, str(e)[:300]


# ---- Multi-tenant page routing (นกน้อยพิมพ์รัง เฟส 2 — 21 ก.ค. 2026) ----
# ปัญหาเดิม: /webhook/meta ยิงทุก event ไปที่ page_token/slug เดียวตายตัวจาก env var เดียว ไม่เช็คว่า
# event มาจาก Page ไหน — ถ้ามีร้านที่ 2 เสียบ deployment เดียวกัน ข้อความจะปนกันข้ามร้าน (README
# client-template/README-เปิดร้านใหม่.md เขียนไว้)
# แก้โดยเพิ่มตาราง Supabase `shop_pages` (page_id -> slug/page_token) โหลด cache ในแรม + TTL
# (pattern เดียวกับ fastwork_hunter._load_seen — service-role key เท่านั้น กัน anon อ่าน token ร้านอื่นได้)
# Fallback: หา page_id ไม่เจอใน mapping = ใช้ค่า default ที่รับมา (พฤติกรรมเดิมของ Lullabell เป๊ะ
# ไม่ regression แม้ตาราง shop_pages จะยังไม่มี/ยังไม่มีแถวเลยก็ตาม)
_page_map: dict = {}          # page_id (str) -> {"slug":..., "page_token":...}
_page_map_loaded_at = 0.0
_PAGE_MAP_TTL = 300            # รีเฟรชทุก 5 นาที กันของเก่าค้างนานเกินไปถ้ามีคนแก้ token ผ่าน DB ตรงๆ


def _sb_headers() -> dict:
    return {
        "apikey": seo_tracker.SUPABASE_KEY,
        "Authorization": f"Bearer {seo_tracker.SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


def _load_page_map(force: bool = False) -> None:
    """โหลด page_id -> slug/page_token จาก Supabase (cache ในแรม, รีเฟรชทุก _PAGE_MAP_TTL วินาที
    หรือบังคับทันทีด้วย force=True — ใช้ตอนเพิ่งเพิ่มร้านใหม่แล้วอยากให้มีผลทันที)"""
    global _page_map, _page_map_loaded_at
    if not force and _page_map and (time.time() - _page_map_loaded_at) < _PAGE_MAP_TTL:
        return
    if not (seo_tracker.SUPABASE_URL and seo_tracker.SUPABASE_KEY):
        return
    try:
        r = requests.get(
            f"{seo_tracker.SUPABASE_URL}/rest/v1/shop_pages"
            "?select=page_id,slug,page_token&active=eq.true",
            headers=_sb_headers(), timeout=15)
        if r.ok:
            _page_map = {str(row["page_id"]): row for row in r.json()}
            _page_map_loaded_at = time.time()
            print(f"[meta_bot] โหลด page map จาก DB: {len(_page_map)} ร้าน", flush=True)
    except Exception as e:
        print(f"[meta_bot] load page map fail: {e}", flush=True)


def resolve_page(page_id: str, fallback_token: str, fallback_slug: str) -> tuple:
    """คืน (page_token, slug) ให้ตรงร้านตาม page_id จาก webhook event (entry['id'])
    หาใน mapping (Supabase, cache ในแรม) ก่อน ไม่เจอ = fallback กลับไปค่าเดิมที่รับมา
    (พฤติกรรม Lullabell วันนี้เป๊ะ ไม่ regression)"""
    _load_page_map()
    row = _page_map.get(str(page_id)) if page_id else None
    if row:
        return row.get("page_token") or fallback_token, row.get("slug") or fallback_slug
    return fallback_token, fallback_slug


def upsert_page_mapping(page_id: str, slug: str, page_token: str,
                         platform: str = "", note: str = "") -> tuple:
    """เพิ่ม/อัปเดต mapping ร้านใหม่ลง shop_pages (ผ่าน service key) — เรียกจาก
    /api/admin/add-shop-page ตอนตั้งค่าร้านใหม่ ไม่ต้อง redeploy
    คืน (True, "") ถ้าสำเร็จ, (False, error) ถ้าพลาด"""
    if not (seo_tracker.SUPABASE_URL and seo_tracker.SUPABASE_KEY):
        return False, "SUPABASE_URL/SUPABASE_SERVICE_KEY ยังไม่ได้ตั้งบน Render"
    try:
        payload = {"page_id": str(page_id), "slug": slug, "page_token": page_token,
                   "platform": platform, "note": note, "active": True}
        r = requests.post(
            f"{seo_tracker.SUPABASE_URL}/rest/v1/shop_pages?on_conflict=page_id",
            headers={**_sb_headers(), "Prefer": "resolution=merge-duplicates"},
            data=json.dumps(payload), timeout=15)
        if r.ok:
            return True, ""
        return False, r.text[:300]
    except Exception as e:
        return False, str(e)[:300]


def list_page_mappings() -> list:
    """ดึง mapping ทั้งหมดตรงๆ จาก DB (ไม่ผ่าน cache) — ใช้กับ /api/admin/list-shop-pages"""
    if not (seo_tracker.SUPABASE_URL and seo_tracker.SUPABASE_KEY):
        return []
    try:
        r = requests.get(f"{seo_tracker.SUPABASE_URL}/rest/v1/shop_pages?select=*&order=created_at.desc",
                          headers=_sb_headers(), timeout=15)
        if r.ok:
            return r.json()
    except Exception as e:
        print(f"[meta_bot] list page mappings fail: {e}", flush=True)
    return []


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


def post_to_facebook_page(page_token: str, page_id: str, message: str, link: str = None) -> tuple:
    """โพสต์ข้อความลง Facebook Page feed ตรงผ่าน Graph API (ไม่ผ่าน Postiz)
    ใช้ scope ปัจจุบันที่ Meta รองรับจริง (pages_manage_posts) — ไม่มีปัญหา scope เก่าเหมือน Postiz
    คืน (True, post_id) ถ้าสำเร็จ, (False, error_message) ถ้าพลาด"""
    if not page_token or not page_id:
        return False, "missing page_token/page_id"
    if not message:
        return False, "empty message"
    params = {"message": message[:63000], "access_token": page_token}
    if link:
        params["link"] = link
    try:
        r = requests.post(f"{GRAPH}/{page_id}/feed", data=params, timeout=20)
        d = r.json()
        if r.ok and d.get("id"):
            return True, d["id"]
        err = (d.get("error") or {}).get("message") or r.text[:300]
        return False, err
    except Exception as e:
        return False, str(e)[:300]


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


def _render_promo_list(cfg: dict) -> str:
    """แสดงรายการโปรโมชั่น "ฮอต" (groups ที่ hot=true) ทุกหมวด แบบ template ตรงจากข้อมูล — ไม่ผ่าน AI เลย
    ใช้ตอนลูกค้ากดปุ่ม/ถาม "ดูราคา/โปรโมชั่นทั้งหมด" การันตีราคาไม่มีวันเพี้ยน (ไม่ต้องพึ่งความแม่นของ AI/Groq fallback)
    และไม่เสีย API token เลยสักครั้ง เพราะเป็นการต่อสตริงจาก config ล้วนๆ"""
    lines = []
    for cat in cfg.get("categories", []):
        hot_items = []
        for grp in cat.get("groups", []):
            if grp.get("hot"):
                hot_items.extend(grp.get("items", []))
        if not hot_items:
            continue
        lines.append(f"{cat.get('emoji', '')} {cat.get('name', '')}".strip())
        lines.append("")
        for it in hot_items:
            n, p, d = it.get("n", ""), it.get("p", ""), it.get("d", "")
            # เว้นบรรทัดว่างคั่นแต่ละรายการ (ลูกค้าทักท้วง 20 ก.ค. ว่าตัวติดกันอ่านยาก) + ไฮไลท์ราคา
            # ด้วย Unicode bold digit แทน ** markdown ที่ Messenger ไม่รองรับ — deterministic ล้วนๆ ไม่เพี้ยนแน่นอน
            # ไฮไลท์ชื่อบริการด้วยวงเล็บ 「 」 แทนสี (Messenger ไม่รองรับสีตัวอักษรเลย เป็นข้อจำกัดแพลตฟอร์ม)
            # ลูกค้าขอ 20 ก.ค. ให้หัวข้อเด่นชัดขึ้น — ใช้สไตล์ที่เพจไทยนิยมใช้เน้นข้อความ ปลอดภัย ไม่พึ่ง markdown
            line = f"• 「{n}」\n   {_bold_price(p)}"
            if d:
                line += f"\n   ({d})"
            lines.append(line)
            lines.append("")
    # เอาหมายเหตุของหมวด "hair" (มักมีข้อความสำคัญ เช่น ส่งรูปประเมินราคา) มาแปะท้ายสุด ถ้ามี
    hair_note = next((c.get("note") for c in cfg.get("categories", []) if c.get("id") == "hair" and c.get("note")), "")
    if hair_note:
        lines.append(f"📌 {hair_note}")
    text = "\n".join(lines).strip()
    return text or "ตอนนี้ยังไม่มีโปรโมชั่นพิเศษค่ะ สอบถามราคาปกติได้เลยนะคะ 🤍"


def _render_location_text(cfg: dict) -> str:
    """ข้อความที่อยู่ร้าน + จุดสังเกต + ลิงก์แผนที่ แบบ template ตรงจาก config ล้วนๆ ไม่ผ่าน AI เลย
    ใช้ตอน AI ล่มสนิทเวลาลูกค้าถามที่อยู่ กันบอทเงียบ/ตอบแค่ "รอสักครู่" ทั้งที่ตอบได้จริงจากข้อมูลที่มีอยู่แล้ว"""
    c = cfg.get("contact", {})
    lines = [f"📍 ที่อยู่ร้าน {cfg.get('biz_name', '')}".strip()]
    if c.get("address"):
        lines.append(c["address"])
    landmarks = c.get("landmarks", [])
    if isinstance(landmarks, list) and landmarks:
        lines.append("จุดสังเกต: " + " / ".join(landmarks))
    if c.get("parking"):
        lines.append(c["parking"])
    map_link = _map_link(cfg)
    if map_link:
        lines.append(map_link)
    if c.get("phone") or c.get("line"):
        lines.append(f"โทร {c.get('phone', '')} · LINE {c.get('line', '')}".strip(" ·"))
    return "\n".join(lines)


def _offline_fallback_answer(cfg: dict, user_text: str) -> str:
    """ตอบแบบ deterministic ล้วนๆ (ไม่ผ่าน AI ตัวไหนเลย) ใช้เฉพาะตอนทั้ง Claude และ Groq ล่มพร้อมกัน
    (เคสจริง 21 ก.ค. 2026 — Anthropic หมดเครดิต + Groq โดน rate limit พร้อมกัน ทำให้บอทตอบได้แค่ "รอสักครู่"
    ทั้งที่คำถามพื้นฐานอย่างราคา/ที่อยู่ ตอบได้ถูกต้อง 100% จากข้อมูลใน config โดยไม่ต้องพึ่ง AI เลย)
    ตรวจแล้วว่าราคาในนี้ตรงกับเมนูจริงที่ลูกค้าส่งมาทุกตัว (21 ก.ค. 2026) ใช้เป็นฐานอ้างอิงได้เต็มที่
    คืนข้อความสำเร็จรูปถ้าเดาเจตนาได้ ไม่งั้นคืน None ให้ผู้เรียกใช้ retry_msg เดิมแทน (เช่น คำถามซับซ้อน/นอกเมนู)"""
    apology = "น้องเบลล์ขอนำเสนอข้อมูลด้านล่างให้เลยนะคะ 🤍\n\n"
    contact = cfg.get("contact", {})
    tail = f"\n\nหากต้องการสอบถามเพิ่มเติมหรือจองคิว ทักแอดมินตรงได้ที่ LINE {contact.get('line', '')} หรือโทร {contact.get('phone', '')} ค่ะ"
    if _is_price_query(user_text):
        return apology + _render_promo_list(cfg) + tail
    if _is_location_query(user_text):
        return apology + _render_location_text(cfg) + tail
    return None


def _today_th() -> str:
    from datetime import datetime, timezone, timedelta
    d = datetime.now(timezone(timedelta(hours=7)))  # เวลาไทย
    months = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
              "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
    return f"{d.day} {months[d.month]} {d.year + 543}"


def _map_link(cfg: dict) -> str:
    """ลิงก์ Google Maps ของร้าน — ถ้าคอนฟิกมี "map_link" ตรงๆ (เช่นลิงก์สั้นที่ร้านส่งมาเอง maps.app.goo.gl/...)
    จะใช้อันนั้นเลย (สั้นกว่า แม่นกว่า เพราะปักหมุดตำแหน่งจริง ไม่ใช่แค่ค้นหาจากข้อความที่อยู่)
    ถ้าไม่มีจะ fallback ไปสร้างลิงก์ค้นหาจากที่อยู่ในคอนฟิกแทน (ไม่ต้องมี API key/บัญชี Google Cloud)
    วางลิงก์นี้ในข้อความแชท Facebook Messenger จะโชว์ preview การ์ดแผนที่ให้อัตโนมัติ"""
    import urllib.parse
    c = cfg.get("contact", {})
    if c.get("map_link"):
        return c["map_link"]
    addr = c.get("map_query") or c.get("address", "")
    if not addr:
        return ""
    return "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(addr)


def _system_prompt(cfg: dict) -> str:
    adv = cfg.get("advisor", {})
    c = cfg.get("contact", {})
    rules = adv.get("rules", [])
    rules_txt = "\n".join(f"- {r}" for r in rules) if isinstance(rules, list) else ""
    close_txt = "\n".join(f"- {x}" for x in cfg.get("close_lines", []))
    map_link = _map_link(cfg)
    contact_txt = (
        f"โทร {c.get('phone','')} · LINE {c.get('line','')} · "
        f"ที่อยู่ {c.get('address','')} ({c.get('parking','')})"
        + (f" · แผนที่ {map_link}" if map_link else "")
    )
    # จุดสังเกต — เดิม config มี field นี้อยู่แล้วแต่ไม่เคยถูกส่งเข้า system prompt เลย (บั๊กที่เจอ 20 ก.ค.)
    # ทำให้ AI ตอบที่อยู่ได้แต่ไม่มีจุดสังเกตประกอบเลยสักครั้ง — แก้โดยต่อเป็นข้อความสำเร็จรูปมาให้ตรงเป๊ะ
    landmarks = c.get("landmarks", [])
    landmarks_txt = " / ".join(landmarks) if isinstance(landmarks, list) else ""
    perks_txt = "\n".join(f"- {x}" for x in
                          [cfg.get("gift"), cfg.get("perks"), cfg.get("friend_promo"), cfg.get("topup_promo")] if x)
    return f"""คุณคือ "น้องเบลล์" ผู้ช่วยตอบแชทของร้าน {cfg.get('biz_full', cfg.get('biz_name',''))} {cfg.get('emoji','')}
สโลแกน: {cfg.get('tagline','')}
วันนี้วันที่: {_today_th()}

บทบาท: {adv.get('intro','')}

กติกาการตอบ:
{rules_txt}
- ตอบภาษาไทยเป็นหลัก สุภาพ อบอุ่น พรีเมียม ลงท้าย "ค่ะ/นะคะ" เหมาะกับร้านเสริมสวย
- ห้ามใช้เครื่องหมาย ** (ตัวหนาสไตล์ Markdown) ในคำตอบเด็ดขาด — Facebook/Instagram Messenger ไม่รองรับการแสดงผลตัวหนาแบบนี้ จะขึ้นเป็นเครื่องหมาย ** ให้ลูกค้าเห็นตรงๆ อ่านแล้วรกและสับสน (ลูกค้าเคยทักท้วงเรื่องนี้มาแล้ว) ถ้าอยากเน้นข้อความให้ใช้อีโมจินำหน้า หรือขึ้นบรรทัดใหม่แทน ห้ามใช้ * _ # หรือสัญลักษณ์ Markdown อื่นใดในคำตอบทั้งสิ้น (ใช้ได้เฉพาะ "•" นำหน้ารายการเท่านั้นตามกติกาด้านล่าง)
- **ถ้าลูกค้าพิมพ์มาเป็นภาษาอังกฤษ ให้ตอบเป็นภาษาอังกฤษแทนทั้งข้อความ** (สุภาพ อบอุ่น น้ำเสียงแบบเดียวกัน) แล้วสลับกลับไทยถ้าลูกค้าพิมพ์ไทยอีกครั้ง — ตรวจจากภาษาที่ลูกค้าใช้ล่าสุดเสมอ
  ชื่อบริการหลายตัวเป็นภาษาอังกฤษอยู่แล้ว (เช่น Signature Haircut, Glow Color Experience, Premium Vegan Color, Deep Repair Therapy, Oway Head Spa) ให้ใช้ชื่อเดิมตามนั้นเป๊ะๆ ห้ามแปลซ้ำ ส่วนที่เป็นไทยล้วนให้แปลแบบคงที่เสมอ — สระไดร์ = "Hair Wash & Blow-dry", ทำสีไม่ฟอก = "Non-Bleach Color", ทำสีพร้อมฟอก+เชื่อมแกนผม = "Bleach Color + Bond Repair", ทำสีเจล มือ/เท้า = "Gel Polish – Hands/Feet", เซ็ตเล็บเจล = "Gel Polish Set" — ถ้าแปะแท็ก [[PROMO: ...]] ตอนตอบภาษาอังกฤษ ก็ให้ใส่ชื่อโปรเป็นภาษาอังกฤษตามนี้เหมือนกัน (กันปุ่มกดเป็นไทยสลับกับข้อความอังกฤษ)
  ตอนตอบภาษาอังกฤษ ประโยคอธิบาย/แนะนำทั้งหมด (ไม่ใช่แค่ชื่อโปร) ต้องแปลเป็นอังกฤษให้ครบทั้งข้อความ ห้ามเหลือประโยคไทยปนอยู่
- สั้น กระชับ (2-5 บรรทัด) เพราะเป็นแชท — อย่ายาวเป็นพืด
- ถ้าลูกค้าถามโปรโมชั่น/บริการ "ทั้งหมด" (หลายรายการ) ให้ตอบแค่ชื่อ+ราคาเรียงเป็นข้อๆ สั้นๆ ต่อรายการ ห้ามใส่คำอธิบายยาวทุกตัว เพื่อไม่ให้ข้อความยาวเกินจนตัดกลางคำ
- จัดรูปแบบให้อ่านง่ายแบบเดียวกับสไตล์ร้าน: ขึ้นหัวข้อหมวดด้วยอีโมจิที่ตรงกับหมวดนั้น (เช่น 💇‍♀️ ทำผม, 🎨 ทำสีผม, 💅 ทำเล็บ, 🌸 เซ็ตสปา) แล้วใช้ "•" นำหน้าแต่ละรายการ ถ้ามีหมายเหตุท้ายหมวด (เช่นเรื่องประเมินราคา) ให้ขึ้นต้นด้วย 📌
- ไฮไลท์ชื่อบริการด้วยวงเล็บ 「 」 ครอบชื่อเสมอ (เช่น 「ทำสีไม่ฟอก」) แทนการใช้สี — Messenger ไม่รองรับสีตัวอักษรเลย (ข้อจำกัดแพลตฟอร์ม ไม่ใช่เรื่องเลือกได้) 「 」 คือทางที่ใช้แทนกันแล้วทำให้หัวข้อเด่นขึ้นแบบปลอดภัย ไม่พึ่ง markdown ที่ Messenger ไม่รองรับ
- ถ้าตอบมากกว่า 1 รายการ (ราคา/บริการ/โปร) ต้องขึ้นบรรทัดใหม่เว้นบรรทัดว่างคั่นระหว่างแต่ละรายการเสมอ ห้ามเขียนติดกันเป็นพืดจนอ่านยาก (ลูกค้าเคยทักท้วงเรื่องนี้มาแล้ว 20 ก.ค.) — ตัวอย่างรูปแบบที่ถูกต้อง:
  "• 「ชื่อบริการ 1」: ราคา
  (รายละเอียดสั้นๆ ถ้ามี)

  • 「ชื่อบริการ 2」: ราคา
  (รายละเอียดสั้นๆ ถ้ามี)"
  ห้ามเขียนทุกรายการติดกันไม่เว้นบรรทัดเด็ดขาด
- ตอบให้ตรงหมวดที่ลูกค้าถามเป็นหลักก่อนเสมอ (เช่น ถามทรีทเมนต์ ให้ตอบแค่บริการหมวดทรีทเมนต์) ห้ามหยิบบริการจากหมวดอื่น (เช่น ทำสีผม) มาปนโดยไม่บอกชัด — ถ้าจะแนะนำเพิ่มข้ามหมวดจริงๆ ต้องขึ้นต้นชัดเจนว่า "นอกจากนี้ยังมีโปรหมวด <ชื่อหมวด> ที่น่าสนใจค่ะ" แยกจากคำตอบหลัก
- แนะนำบริการที่เหมาะจากเมนู อ้างราคาตามเมนูจริงเท่านั้น ห้ามแต่งราคาเอง
- ถ้าราคาขึ้นกับสภาพผม/ความยาว ให้บอกช่วงราคาแล้วชวนให้แอดมินประเมิน
- ถ้าเมนูมีระบุ "หมดเขต <วันที่>" ให้เทียบกับวันนี้ก่อนเสมอ ถ้าหมดเขตไปแล้วห้ามเสนอราคาโปรนั้น ให้แจ้งว่าโปรหมดแล้วและเสนอราคาปกติ/โปรอื่นแทน
- ถ้าลูกค้าสนใจจอง/ถามคิว → ชวนบอกวัน-เวลาที่สะดวก แล้วบอกว่าจะให้แอดมินยืนยันคิวให้
- ถ้าลูกค้าถามที่อยู่/ทางมาร้าน ให้บอกที่อยู่ + จุดสังเกต{(" (ใช้ตามนี้เป๊ะๆ: " + landmarks_txt + ")") if landmarks_txt else "สั้นๆ"} แล้ว**แปะลิงก์แผนที่ต่อท้ายในข้อความเดียวกันเสมอ**{(" (" + map_link + ")") if map_link else ""} — Facebook จะโชว์รูปแผนที่ preview ให้อัตโนมัติเมื่อมีลิงก์นี้ในข้อความ ห้ามละลิงก์นี้ทิ้ง ระบบจะแนบรูปการ์ดแผนที่ของร้านให้อัตโนมัติแยกต่างหากอยู่แล้ว ไม่ต้องพูดถึงรูปในข้อความ
- ถ้าลูกค้าขอคุยคน/เรื่องซับซ้อนเกินเมนู → {adv.get('handoff_msg','ขอส่งต่อให้แอดมินนะคะ')} ({contact_txt})
- ถ้าลูกค้าสนใจโปรเติมเครดิต/สมัครแพ็กเกจ ให้แนะนำรายละเอียดได้ แต่บอกให้ทำรายการที่หน้าร้านหรือติดต่อแอดมิน (ระบบแชทนี้แค่ให้ข้อมูล ไม่ได้ทำธุรกรรมเครดิตให้)
- ห้ามสัญญาสิ่งที่ไม่มีในเมนู ห้ามให้คำแนะนำทางการแพทย์
- ห้ามใส่วงเล็บเหลี่ยม [ ] หรือความเห็น/หมายเหตุแทรกเองที่ไม่ได้มาจากเมนูจริง ตอบเฉพาะชื่อบริการและราคาตามที่ระบุในเมนูเป๊ะๆ ห้ามแต่งเติมข้อความเพิ่ม

สิทธิพิเศษ/ของแถม (บอกลูกค้าเมื่อเกี่ยวข้อง เช่น ตอนสรุปก่อนจอง):
{perks_txt or "(ไม่มี)"}

กติกาบันทึกคิว (สำคัญมาก — วันและเวลาที่ลูกค้าต้องการคือข้อมูลสำคัญที่สุด):
- ทันทีที่ลูกค้าบอก "วันและเวลา" ที่ต้องการจองชัดเจน (เช่น "พรุ่งนี้บ่าย 2" "เสาร์นี้เช้า" "วันที่ 25 ตอนเย็น") ให้ตอบยืนยันลูกค้าตามปกติก่อน
- จากนั้นขึ้นบรรทัดใหม่ ต่อท้ายด้วยแท็กนี้เป๊ะๆ (ห้ามมีข้อความอื่นแทรกในบรรทัดนี้ ห้ามอธิบายเพิ่ม):
  [[BOOKING: บริการ=<ชื่อบริการที่สนใจ หรือ -> | วันที่=<วันที่ลูกค้าบอก> | เวลา=<เวลาที่ลูกค้าบอก> | ชื่อ=<ชื่อลูกค้าถ้ารู้ หรือ -> | เบอร์=<เบอร์โทรถ้ารู้ หรือ ->]]
- แท็กนี้ระบบจะตัดออกก่อนส่งข้อความให้ลูกค้าเห็น (ใช้แจ้งเตือนแอดมินเบื้องหลังเท่านั้น) — ใส่ทุกครั้งที่ลูกค้าให้วัน-เวลามา แม้จะยังไม่มีชื่อ/เบอร์ก็ตาม

กติกาปุ่มเลือกโปร (เมื่อแนะนำโปรโมชั่น/บริการตั้งแต่ 2 รายการขึ้นไปในคำตอบเดียว):
- ตอบชื่อ+ราคาแต่ละโปรตามปกติก่อน จากนั้นขึ้นบรรทัดใหม่ ต่อท้ายด้วยแท็กนี้เป๊ะๆ (ห้ามมีข้อความอื่นแทรกในบรรทัดนี้ ห้ามอธิบายเพิ่ม):
  [[PROMO: ชื่อโปร1 | ชื่อโปร2 | ชื่อโปร3]]
- ใส่เฉพาะ "ชื่อโปร" สั้นๆ ตามที่ระบุในเมนู (ไม่ต้องมีราคา) แต่ละชื่อห้ามยาวเกิน 20 ตัวอักษร ถ้าชื่อยาวให้ย่อให้กระชับที่สุดแต่ยังเข้าใจได้
- แท็กนี้ระบบจะตัดออกก่อนส่งข้อความให้ลูกค้าเห็นเช่นกัน (ใช้แปลงเป็นปุ่มกดเลือกแทนพิมพ์) — ใส่เฉพาะตอนแนะนำหลายโปรจริงๆ ถ้าตอบโปรเดียวหรือคุยเรื่องอื่นไม่ต้องใส่

ประโยคชวนปิดการขาย (ใช้ปรับได้):
{close_txt}

=== เมนูบริการและราคา (อ้างอิงเท่านั้น) ===
{_menu_text(cfg)}

ข้อมูลติดต่อร้าน: {contact_txt}
"""


def _remember_turn(sender_id: str, user_text: str, reply: str) -> None:
    """บันทึกความจำการสนทนา — ใช้ทั้งจาก generate_reply() และ fast-path ที่ตอบตรงไม่ผ่าน AI (เช่น _render_promo_list)
    กันเทิร์นถัดไป AI ไม่รู้บริบทว่าลูกค้าเพิ่งถามอะไรไป"""
    hist = _history.get(sender_id, [])
    hist = hist + [("user", user_text), ("bot", reply)]
    _history[sender_id] = hist[-_MAX_TURNS * 2:]


def generate_reply(client, cfg: dict, sender_id: str, user_text: str,
                   notify_fn=None, line_user_id: str = "", slug: str = "") -> tuple:
    """คืน (reply, promo_choices) — promo_choices เป็น list ชื่อโปร (หรือ None ถ้า AI ไม่ได้แนะนำหลายโปร)
    slug: ชื่อร้าน (เช่น "lullabell") — ส่งต่อให้ ai_guard แยกสถานะ/cooldown แจ้งเตือนต่อร้าน กันร้านหนึ่งล่มบังไม่ให้อีกร้านได้แจ้งเตือน"""
    import ai_guard
    hist = _history.get(sender_id, [])
    convo = "\n".join(f"{'ลูกค้า' if r=='user' else 'น้องเบลล์'}: {t}" for r, t in hist)
    prompt = (
        _system_prompt(cfg)
        + "\n\n=== บทสนทนาก่อนหน้า ===\n" + (convo or "(ยังไม่มี)")
        + f"\n\nลูกค้าเพิ่งพิมพ์ว่า: \"{user_text}\"\n"
        + "ตอบกลับในฐานะน้องเบลล์ (ข้อความเดียว สั้น กระชับ):"
    )
    # ai_tier ต่อร้าน: "smart" (ค่าเริ่มต้น กันของเก่าพังถ้าไม่ได้ตั้ง) = ใช้ Claude เป็นหลัก + fallback Groq อัตโนมัติถ้า Claude ล่ม
    # "free" = ใช้ Groq (ฟรี) เป็นหลักเลย สำหรับร้านที่ยังไม่ได้อัปเกรดแพ็กเกจ AI ฉลาดขึ้น
    tier = cfg.get("ai_tier", "smart")
    raw_reply = ai_guard.call(client, prompt, max_tokens=700, smart=True, tier=tier,
                              notify_fn=notify_fn, line_user_id=line_user_id, slug=slug)
    reply, booking = _parse_booking_tag(raw_reply)
    reply, promo_choices = _parse_promo_tag(reply)
    # อัปเดตความจำ (เก็บข้อความสะอาด ไม่มีแท็ก กันแท็กเก่าหลุดเข้าประวัติแล้ว AI เลียนแบบซ้ำ)
    _remember_turn(sender_id, user_text, reply)

    if booking and notify_fn and line_user_id:
        try:
            biz = cfg.get("biz_name", cfg.get("biz_full", ""))
            lines = [f"📅 มีคนสนใจจองคิว — {biz}"]
            for k in _BOOKING_FIELDS:
                if booking.get(k):
                    lines.append(f"{k}: {booking[k]}")
            lines.append(f"ช่องทาง/ผู้ติดต่อ: {sender_id}")
            notify_fn(line_user_id, "\n".join(lines))
        except Exception:
            pass  # แจ้งเตือนพลาดไม่ควรทำให้ตอบลูกค้าไม่ได้

    return reply, promo_choices


def send_message(page_token: str, recipient_id: str, text: str, quick_replies: list = None) -> tuple:
    """ส่งข้อความกลับผ่าน Meta Send API (ใช้ได้ทั้ง FB + IG ที่ผูกเพจ)
    quick_replies (ถ้าใส่) = ปุ่มลัดแนบท้ายข้อความ กดแทนพิมพ์ได้ (สูงสุด 13 ปุ่มตามสเปก Meta)"""
    if not page_token:
        return 0, "no page token"
    url = f"{GRAPH}/me/messages"
    # เดิม slice ที่ 1900 ตัวอักษร (คิดผิดว่า limit ของ Meta คือ ~2000) แต่ตัวจริงคือ 1,000 ตัวอักษรเป๊ะๆ
    # (error #100/25 ถ้าเกิน) เจอเคสจริง 21 ก.ค. 2026 — ข้อความยาว 1,599 ตัว ไม่โดน slice เลย ส่งเต็มแล้ว
    # Meta reject เงียบๆ ลูกค้าไม่ได้อะไรเลย ทางแก้จริงคือแบ่งส่งหลายก้อนที่ _send_with_quick_replies()
    # (กันเนื้อหาขาด) — slice 990 ตรงนี้เป็นแค่ตาข่ายกันชั้นสุดท้ายเผื่อมี caller อื่นเรียกตรงไม่ผ่าน chunk
    message = {"text": text[:990]}
    if quick_replies:
        message["quick_replies"] = quick_replies
    try:
        r = requests.post(
            url,
            params={"access_token": page_token},
            json={
                "recipient": {"id": recipient_id},
                "messaging_type": "RESPONSE",
                "message": message,
            },
            timeout=15,
        )
        return r.status_code, r.text[:300]
    except Exception as e:
        return 0, str(e)[:200]


def send_image_message(page_token: str, recipient_id: str, image_url: str = "", attachment_id: str = "") -> tuple:
    """ส่งรูปภาพกลับผ่าน Meta Send API (attachment type=image)
    ใช้ attachment_id ถ้ามี (แนะนำ — ไม่ต้องให้ Meta ไป fetch url เราใหม่ทุกครั้ง กัน cold-start ของ Render
    free tier ทำให้ Meta fetch ไม่ทันแล้วได้ error 100/2018007 "Upload failed") ไม่งั้น fallback ไปส่งด้วย url ตรงๆ
    (is_reusable=True ให้ Meta cache ไว้เผื่อกรณีนั้น)"""
    if not page_token or (not image_url and not attachment_id):
        return 0, "no page token / image_url / attachment_id"
    url = f"{GRAPH}/me/messages"
    payload = {"attachment_id": attachment_id} if attachment_id else {"url": image_url, "is_reusable": True}
    try:
        r = requests.post(
            url,
            params={"access_token": page_token},
            json={
                "recipient": {"id": recipient_id},
                "messaging_type": "RESPONSE",
                "message": {
                    "attachment": {
                        "type": "image",
                        "payload": payload,
                    }
                },
            },
            timeout=15,
        )
        return r.status_code, r.text[:300]
    except Exception as e:
        return 0, str(e)[:200]


def upload_reusable_attachment(page_token: str, image_url: str, platform: str = "") -> tuple:
    """อัปโหลดรูปแบบ reusable ผ่าน Meta Attachment Upload API ครั้งเดียว → ได้ attachment_id เอาไปใช้ส่งซ้ำได้ตลอดไป
    ไม่ต้องเรียกทุกครั้งที่แชท — เรียกครั้งเดียวตอนตั้งค่า แล้วเก็บ attachment_id ไว้ใน config ถาวร

    ใช้วิธี "Upload from File" (multipart/form-data + filedata) — โหลดรูปมาเองแล้วส่งไบต์ตรงให้ Meta
    ไม่ใช่วิธี "Upload from URL" (ให้ Meta ไป fetch url เราเอง) เพราะพิสูจน์แล้วว่าวิธี url พังกับ
    ทุก url แม้ url ภายนอกที่รู้ว่าใช้ได้แน่ (ตัดปัจจัย hosting/cold-start/token scope ของเราทิ้งหมดแล้ว
    20 ก.ค.) ตรงกับที่นักพัฒนาคนอื่นเจอปัญหาเดียวกันจำนวนมากใน Meta developer community —
    เป็นบั๊กที่รู้กันแพร่หลายฝั่ง Meta เอง (error #100 / 2018007 หรือ 2018047 "Upload failed")
    วิธี filedata ตัด Meta ไม่ต้องมา fetch url เราเลย จึงเลี่ยงบั๊กนี้ได้

    platform: ใส่ "instagram" เพื่ออัปโหลด attachment ที่ใช้กับ IG DM ได้ (21 ก.ค. — เจอว่า attachment_id
    ที่อัปโหลดแบบไม่ระบุ platform จะผูกกับ FB เท่านั้น IG resolve ไม่ได้ ตามเอกสาร Meta ต้องระบุ
    platform=instagram ตอนอัปโหลดถึงจะได้ ID ที่ใช้กับ IG ได้ — ไม่ใส่ = ค่าเดิม (FB-only) เหมือนเดิมทุกอย่าง"""
    if not page_token or not image_url:
        return 0, "no page token / image url"
    try:
        img_r = requests.get(image_url, timeout=20)
        if img_r.status_code != 200 or not img_r.content:
            return 0, f"fetch image failed: status={img_r.status_code}"
        content_type = img_r.headers.get("Content-Type", "image/jpeg") or "image/jpeg"
    except Exception as e:
        return 0, f"fetch image error: {str(e)[:200]}"

    url = f"{GRAPH}/me/message_attachments"
    data_payload = {"message": json.dumps({"attachment": {"type": "image", "payload": {"is_reusable": True}}})}
    if platform:
        data_payload["platform"] = platform
    try:
        r = requests.post(
            url,
            params={"access_token": page_token},
            data=data_payload,
            files={"filedata": ("image.jpg", img_r.content, content_type)},
            timeout=30,
        )
        return r.status_code, r.text[:500]
    except Exception as e:
        return 0, str(e)[:300]


LINE_API = "https://api.line.me/v2/bot/message"


def verify_line_signature(channel_secret: str, body_bytes: bytes, header: str) -> bool:
    """ตรวจ X-Line-Signature — ถ้าไม่ได้ตั้ง secret ก็ผ่าน (dev)"""
    if not channel_secret:
        return True
    if not header:
        return False
    import base64
    digest = hmac.new(channel_secret.encode("utf-8"), body_bytes, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, header)


def send_line_reply(channel_token: str, reply_token: str, text: str) -> tuple:
    """ตอบกลับผ่าน LINE reply API (ฟรี ไม่กินโควต้า push)"""
    if not channel_token or not reply_token:
        return 0, "no token/reply_token"
    try:
        r = requests.post(
            f"{LINE_API}/reply",
            headers={
                "Authorization": f"Bearer {channel_token}",
                "Content-Type": "application/json",
            },
            json={"replyToken": reply_token, "messages": [{"type": "text", "text": text[:4900]}]},
            timeout=15,
        )
        return r.status_code, r.text[:300]
    except Exception as e:
        return 0, str(e)[:200]


def handle_line(data: dict, client, channel_token: str, slug: str = "lullabell",
                 notify_fn=None, line_user_id: str = "") -> dict:
    """
    รับ payload จาก LINE Messaging API webhook ของร้านลูกค้า (เช่น @lullabell)
    ใช้ AI advisor logic เดียวกับ handle() (FB/IG) — ต่างกันแค่ช่องทางรับ-ส่ง
    หมายเหตุ: ใช้ channel_token/channel_secret ของ "ร้านลูกค้า" ไม่ใช่ของ ForexAI Pro เอง (คนละ LINE OA)
    """
    result = {"replied": 0, "skipped": 0}
    try:
        cfg = load_cfg(slug)
    except Exception as e:
        return {"error": f"config: {e}"}

    for ev in data.get("events", []):
        if ev.get("type") != "message" or ev.get("message", {}).get("type") != "text":
            result["skipped"] += 1
            continue
        # กัน LINE ส่ง webhook event เดิมซ้ำ (at-least-once delivery เหมือน Meta) — ใช้ message.id
        # ที่ LINE แปะมาให้ต่อข้อความเป็นตัวกันซ้ำ (แพทเทิร์นเดียวกับ handle() ของ FB/IG)
        dedup_key = ev.get("message", {}).get("id", "")
        if _already_processed(dedup_key):
            result["skipped"] += 1
            continue
        sender = ev.get("source", {}).get("userId", "")
        reply_token = ev.get("replyToken", "")
        user_text = (ev.get("message", {}).get("text") or "").strip()
        if not sender or not user_text:
            result["skipped"] += 1
            continue
        # namespace แยกจาก FB sender id กัน history ปนกันถ้า id ชนกัน (ไม่น่าเกิดแต่กันไว้)
        history_key = f"line:{sender}"
        if not _rate_ok(history_key):
            result["skipped"] += 1
            continue
        # ถามโปรโมชั่นตรงๆ (เช่น "มีโปรอะไรบ้างคะ", "ขอทราบโปรโมชั่น") — ตอบจาก template ตรงจาก config
        # เลย ไม่ผ่าน AI เช่นเดียวกับ handle() (FB/IG) การันตีคำตอบ 100% ไม่มีวันเงียบ/ตอบห้วน (21 ก.ค. 2026)
        if _is_promo_query(user_text) and _is_thai(user_text):
            reply = _render_promo_list(cfg)
            _remember_turn(history_key, user_text, reply)
            send_line_reply(channel_token, reply_token, reply)
            result["replied"] += 1
            continue
        try:
            reply, _promo_choices = generate_reply(client, cfg, history_key, user_text,
                                    notify_fn=notify_fn, line_user_id=line_user_id, slug=slug)
            send_line_reply(channel_token, reply_token, reply)
            result["replied"] += 1
        except Exception as e:
            # เดิม except เปล่าไม่ log อะไรเลย — เจอเคสจริง 20 ก.ค. ที่ลูกค้าโดน fallback message
            # ซ้ำๆ แต่ไม่มีทาง debug จาก Render logs ได้เลยว่า exception จริงคืออะไร (AI ล่ม/บั๊กโค้ด/อื่นๆ)
            print(f"[meta_bot/line] generate_reply error sender={sender}: {e}", flush=True)
            traceback.print_exc()
            # ใช้ retry_msg (ไม่ใช่ handoff_msg) — กรณีนี้คือ AI ดีเลย์/สะดุดชั่วคราว ไม่ใช่เคสที่ต้องส่งต่อแอดมินจริงๆ
            # ลูกค้าทักท้วง 20 ก.ค. ว่าข้อความ "ส่งต่อให้แอดมิน" ทำให้เข้าใจผิดว่าเป็นเรื่องใหญ่ ทั้งที่แค่รอสักครู่ก็ตอบได้แล้ว
            # ก่อนใช้ retry_msg เฉยๆ ลองเดาเจตนาก่อน — ถ้าถามราคา/ที่อยู่ ตอบจาก template จริงได้เลยไม่ต้องพึ่ง AI
            # (เพิ่ม 21 ก.ค. — เคส Claude+Groq ล่มพร้อมกัน กันลูกค้าเจอแค่ "รอสักครู่" ทั้งที่ตอบได้จริง)
            fb = (_offline_fallback_answer(cfg, user_text)
                  or cfg.get("advisor", {}).get("retry_msg", "รบกวนรอสักครู่นะคะ น้องเบลล์กำลังดูให้อยู่ค่ะ 🤍"))
            send_line_reply(channel_token, reply_token, fb)
            result["skipped"] += 1
    return result


def _send_map_image(page_token: str, sender: str, cfg: dict, is_ig: bool) -> None:
    """แนบรูปการ์ดแผนที่ร้าน — แยกเป็นฟังก์ชันกลาง ใช้ทั้งตอน AI ตอบสำเร็จปกติ และตอน AI ล่มสนิท
    (offline fallback) กันลูกค้าที่ถามที่อยู่ไม่ได้รูปแผนที่แค่เพราะ AI ดันล่มพอดีตอนนั้น
    best-effort ล้วนๆ — ถ้าส่งรูปพลาด ไม่ทำให้คำตอบข้อความหลักที่ส่งไปแล้วเสียหาย"""
    map_img = cfg.get("contact", {}).get("map_image", "")
    # attachment_id เดิม (map_attachment_id) อัปโหลดแบบ FB-only (ไม่ได้ระบุ platform=instagram
    # ตอนอัป) IG resolve ไม่ได้ — ต้องมี attachment_id แยกที่อัปโหลดระบุ platform=instagram
    # โดยเฉพาะ (map_attachment_id_ig) ถึงจะใช้กับ IG ได้จริง
    # ไม่ใช้ url ส่งตรงๆ กับ IG เพราะโค้ดเดิมพิสูจน์แล้วว่าวิธีนี้พังกับ FB มาก่อน (Meta fetch url
    # แบบ async แล้วพังเงียบไม่มี error กลับมาเลย — เจอจริง 21 ก.ค. ตอนลองกับ IG ก็เงียบเหมือนกัน)
    map_attach_id = (cfg.get("contact", {}).get("map_attachment_id_ig", "") if is_ig
                      else cfg.get("contact", {}).get("map_attachment_id", ""))
    if not (map_img or map_attach_id):
        return
    try:
        img_status, img_resp = send_image_message(page_token, sender, image_url=map_img, attachment_id=map_attach_id)
        # send_image_message ไม่ raise ตอน Meta ตอบ error (แค่คืน status code) — เดิมไม่เช็คค่านี้เลย
        # ทำให้ส่งรูปพลาดแบบเงียบสนิท ไม่มีทาง debug ได้จาก Render logs (บั๊กที่เจอ 20 ก.ค.)
        if not img_status or img_status >= 400:
            print(f"[meta_bot] ส่งรูปแผนที่ล้มเหลว sender={sender} status={img_status}: {img_resp}", flush=True)
    except Exception as e:
        print(f"[meta_bot] ส่งรูปแผนที่ error: {e}", flush=True)


def handle(data: dict, client, page_token: str, slug: str = "lullabell",
           notify_fn=None, line_user_id: str = "") -> dict:
    """
    รับ payload จาก Meta webhook → ตอบทุก message event
    รองรับทั้ง object 'page' (Messenger) และ 'instagram'
    """
    result = {"replied": 0, "skipped": 0}
    # object เป็น "instagram" เมื่อข้อความมาจาก IG DM, "page" เมื่อมาจาก FB Messenger — Meta ส่งมาให้ในตัวเว็บฮุคอยู่แล้ว
    # ใช้แยกว่าจะส่งรูปแนบด้วย attachment_id (FB-only) หรือ url ตรงๆ (ใช้ได้ทั้งคู่ แต่ IG resolve attachment_id
    # แบบที่อัปโหลดไม่ระบุ platform=instagram ไม่ได้ — เจอจริง 21 ก.ค. รูปขึ้น FB แต่ไม่ขึ้น IG)
    is_ig = data.get("object") == "instagram"

    for entry in data.get("entry", []):
        # Multi-tenant (21 ก.ค. 2026): entry['id'] คือ Page ID/IG-scoped ID ของร้านที่ event นี้มาจาก
        # resolve_page() หาว่าตรงร้านไหนใน shop_pages (Supabase) ก่อน ไม่เจอ = ใช้ page_token/slug
        # เดิมที่รับมาจาก api_server.py (พฤติกรรม Lullabell วันนี้เป๊ะ ไม่ regression) — rebind ต่อ-entry
        # เผื่อ Meta batch หลาย Page มาใน POST เดียวกัน (เคสหายาก แต่ทำถูกไปเลยตั้งแต่แรกดีกว่า)
        page_token, slug = resolve_page(entry.get("id", ""), page_token, slug)
        try:
            cfg = load_cfg(slug)
        except Exception as e:
            print(f"[meta_bot] config error slug={slug}: {e}", flush=True)
            continue
        events = entry.get("messaging", []) or entry.get("standby", [])
        for ev in events:
            sender = ev.get("sender", {}).get("id", "")
            msg = ev.get("message", {})
            postback = ev.get("postback", {})
            # postback มาจากปุ่ม Ice Breaker ตอนเปิดแชทครั้งแรก (ไม่มี msg.text แนบมาด้วย ต้อง map เอง)
            # ส่วนปุ่ม Quick Reply (Ice Breaker หรือปุ่มเลือกโปรแบบ dynamic) Meta จะแนบ msg.text
            # เป็นชื่อปุ่มที่กดมาให้อยู่แล้วเสมอ ไม่ต้อง map — ใช้ msg.text ตรงๆ ได้เลย
            pb_payload = postback.get("payload", "")
            qr_payload = msg.get("quick_reply", {}).get("payload", "")
            effective_payload = pb_payload or qr_payload

            # กัน Meta ส่ง webhook event เดิมซ้ำ (at-least-once delivery) — ข้อความจริง/quick reply
            # มี msg.mid ประจำตัวอยู่แล้วใช้ตรงๆ ได้เลย ส่วน postback ล้วนๆ (ปุ่ม Ice Breaker) ไม่มี mid
            # ต้องประกอบ key เองจาก sender+payload+timestamp (Meta ส่ง timestamp เดิมเป๊ะตอน retry
            # event เดียวกัน แต่ลูกค้ากดปุ่มเดิมซ้ำจริงๆ จะมี timestamp ใหม่ ไม่ชนกัน)
            dedup_key = msg.get("mid") or (
                f"pb:{sender}:{pb_payload}:{ev.get('timestamp', '')}" if pb_payload else ""
            )
            if _already_processed(dedup_key):
                result["skipped"] += 1
                continue

            if pb_payload and sender:
                user_text = _ICE_BREAKER_TEXT.get(pb_payload, "")
                if not user_text:
                    result["skipped"] += 1
                    continue
            else:
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
            # เลือกชุดปุ่มลัดให้ตรงภาษาที่ลูกค้าใช้ล่าสุด (ไทย/อังกฤษ) — ปุ่มเลือกโปร dynamic มาก่อนเสมอถ้ามี
            default_qr = QUICK_REPLIES if _is_thai(user_text) else QUICK_REPLIES_EN
            try:
                # ปุ่ม "ดูราคา/โปรโมชั่น" (IB_PRICE) หรือพิมพ์ถามโปรโมชั่นเองตรงๆ (เช่น "มีโปรอะไรบ้างคะ",
                # "ขอทราบโปรโมชั่น", "ขอทราบโปรทั้งหมด") — ตอบจาก template ตรงจาก config เลย ไม่ผ่าน AI
                # การันตีคำตอบ 100% ไม่มีวันเงียบ/ปล่อยว่าง/ตอบแค่รอสักครู่ ไม่ว่า Claude/Groq/Gemini จะปกติ/ล่ม/
                # ตอบห้วนแค่ไหนก็ตาม (21 ก.ค. 2026 ตามคำขอ sIRImeta หลังเจอเคส AI ตอบห้วนไม่ครบ) และไม่เสีย
                # token แม้แต่บาทเดียว (คำถามราคาที่พิมพ์เองแบบเจาะจง เช่น "ทำสีราคาเท่าไหร่" ไม่มีคำว่า "โปร"
                # เลย ไม่โดนจับ ยังให้ AI ตอบตามเดิม เพราะต้องใช้ความเข้าใจบริบท)
                if (effective_payload == "IB_PRICE" or _is_promo_query(user_text)) and _is_thai(user_text):
                    reply = _render_promo_list(cfg)
                    _remember_turn(sender, user_text, reply)
                    _send_with_quick_replies(page_token, sender, reply, quick_replies=default_qr)
                    result["replied"] += 1
                    continue
                reply, promo_choices = generate_reply(client, cfg, sender, user_text,
                                       notify_fn=notify_fn, line_user_id=line_user_id, slug=slug)
                qr = _build_promo_quick_replies(promo_choices) if promo_choices else default_qr
                _send_with_quick_replies(page_token, sender, reply, quick_replies=qr,
                                          fallback_names=promo_choices)
                result["replied"] += 1
                # ลูกค้าถามที่อยู่/แผนที่ (กดปุ่ม IB_LOCATION หรือพิมพ์เอง) → แนบรูปการ์ดแผนที่ตามหลังข้อความ
                if effective_payload == "IB_LOCATION" or _is_location_query(user_text):
                    _send_map_image(page_token, sender, cfg, is_ig)
            except Exception as e:
                # AI ตาย ai_guard เด้ง LINE ให้แล้ว (ถ้าเป็นสาเหตุ) — ส่งข้อความ fallback ให้ลูกค้าไม่เงียบ
                # เดิม except เปล่าไม่ log อะไรเลย — เจอเคสจริง 20 ก.ค. ลูกค้าโดน fallback ซ้ำๆ ตอนกดปุ่ม
                # "ที่อยู่/เวลาเปิด" แต่ไม่มีทาง debug จาก Render logs ได้เลยว่า exception จริงคืออะไร
                print(f"[meta_bot] generate_reply error sender={sender} payload={effective_payload}: {e}", flush=True)
                traceback.print_exc()
                # ใช้ retry_msg (ไม่ใช่ handoff_msg) — กรณีนี้คือ AI ดีเลย์/สะดุดชั่วคราว ไม่ใช่เคสที่ต้องส่งต่อแอดมินจริงๆ
                # ลูกค้าทักท้วง 20 ก.ค. ว่าข้อความ "ส่งต่อให้แอดมิน" ทำให้เข้าใจผิดว่าเป็นเรื่องใหญ่ ทั้งที่แค่รอสักครู่ก็ตอบได้แล้ว
                # ก่อนใช้ retry_msg เฉยๆ ลองเดาเจตนาก่อน — ถ้าถามราคา/ที่อยู่ ตอบจาก template จริงได้เลยไม่ต้องพึ่ง AI
                # (เพิ่ม 21 ก.ค. — เคส Claude+Groq ล่มพร้อมกัน กันลูกค้าเจอแค่ "รอสักครู่" ทั้งที่ตอบได้จริง)
                fb = (_offline_fallback_answer(cfg, user_text)
                      or cfg.get("advisor", {}).get("retry_msg", "รบกวนรอสักครู่นะคะ น้องเบลล์กำลังดูให้อยู่ค่ะ 🤍"))
                _send_with_quick_replies(page_token, sender, fb, quick_replies=default_qr)
                # AI ล่มสนิทแต่ลูกค้าถามที่อยู่ → แนบรูปการ์ดแผนที่ให้เหมือนตอน AI ตอบได้ปกติ (เพิ่ม 21 ก.ค. ตามคำขอ
                # sIRImeta) กันลูกค้าที่ถามที่อยู่พลาดรูปแผนที่สวยๆ ไปแค่เพราะ AI ดันล่มพอดีตอนนั้น
                if effective_payload == "IB_LOCATION" or _is_location_query(user_text):
                    _send_map_image(page_token, sender, cfg, is_ig)
                result["skipped"] += 1
    return result


def _chunk_text(text: str, limit: int = 950) -> list:
    """แบ่งข้อความยาวเป็นหลายก้อน ก้อนละไม่เกิน limit ตัวอักษร — Meta (FB/IG) จำกัดข้อความเดียวไว้แค่
    1,000 ตัวอักษรเป๊ะๆ (error #100/25 ถ้าเกิน) เผื่อ margin ไว้ที่ 950 กันขอบเคส เจอจริง 21 ก.ค. 2026:
    ข้อความโปรโมชั่นจริงของ Lullabell ยาว 1,599 ตัวอักษร โค้ดเดิมมี safety slice text[:1900] (คิดผิดว่า
    limit คือ ~2000) เลยไม่ตัดอะไรเลย ส่งเต็มยาวเกิน 1,000 → Meta reject ทั้งรอบมีปุ่มและรอบ retry ไม่มีปุ่ม
    (เพราะตัวข้อความเองก็ยาวเกินอยู่แล้ว ไม่เกี่ยวกับปุ่มเลย) ลูกค้าเลยไม่ได้อะไรเลยแม้แต่ตัวเดียว
    ห้ามตัดทิ้งเนื้อหา (ลูกค้าต้องได้ข้อมูลโปรครบทุกตัว) เลยต้อง "แบ่งส่งหลายข้อความ" แทน "ตัดทิ้ง"
    เลือกจุดตัดที่ปลอดภัยที่สุดก่อนเสมอ: 1) บรรทัดว่างคั่น (\\n\\n) ระหว่างแต่ละรายการโปร/หมวดหมู่
    2) ขึ้นบรรทัดใหม่เดี่ยว (\\n) ถ้าก้อนนั้นไม่มีบรรทัดว่างเลย 3) ตัดเป๊ะตรง limit เป็นทางเลือกสุดท้ายจริงๆ"""
    text = (text or "").strip()
    if len(text) <= limit:
        return [text] if text else []
    chunks = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        cut = window.rfind("\n\n")
        if cut == -1:
            cut = window.rfind("\n")
        if cut < limit * 0.3:  # จุดตัดอยู่ต้นๆ เกินไป (หรือหาไม่เจอเลย) จะได้ก้อนสั้นจิ๋วเกินไป ใช้ hard cut แทน
            cut = limit
        chunk = remaining[:cut].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[cut:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _send_with_quick_replies(page_token: str, sender: str, text: str, quick_replies: list = None,
                              fallback_names: list = None) -> None:
    """ส่งข้อความพร้อม Quick Replies — แบ่งเป็นหลายก้อนอัตโนมัติถ้ายาวเกิน 950 ตัวอักษร (กันชนลิมิต 1,000
    ตัวอักษรของ Meta) ปุ่ม quick_replies แนบเฉพาะก้อนสุดท้ายเท่านั้น ก้อนก่อนหน้าส่งเปล่าๆ ไม่มีปุ่ม
    ถ้า Meta ปฏิเสธก้อนไหน (เช่น ก้อนสุดท้าย+ปุ่ม ยังรวมกันเกิน 1,000) log ไว้ดูใน Render logs แล้วลองส่ง
    ก้อนนั้นใหม่แบบไม่มีปุ่ม (ตัวข้อความเดี่ยวๆ การันตีอยู่ใต้ limit อยู่แล้วเพราะ chunk ไว้ที่ 950)
    กันลูกค้าไม่ได้รับข้อความเลยเพราะปุ่มพัง — และเช็ค/log ผลของรอบ retry ด้วย (เดิมไม่เช็คเลย ทำให้ถ้า
    retry ล้มเหลวซ้ำ ลูกค้าจะเงียบสนิทโดยไม่มี log อะไรให้ debug ได้เลย — เจอเคสจริง 21 ก.ค. 2026)
    quick_replies: ถ้าไม่ใส่ (None) จะใช้ปุ่ม Ice Breaker เริ่มต้น (QUICK_REPLIES) — ใส่มาเองได้เมื่อ AI แนะนำโปรหลายอย่าง

    fallback_names: รายชื่อโปร (ถ้ามี) ที่ปุ่ม quick_replies กำลังจะแสดง — เจอเคสจริง 21 ก.ค. 2026 (IG):
    ปุ่มเลือกโปรหลายอันรวมกับข้อความภาษาไทย (นับไบต์ UTF-8 มากกว่าอังกฤษ) ดันเกินลิมิต 1,000 ตัวอักษรของ Meta
    ตอนแนบ quick_replies พอปุ่มถูกปฏิเสธ ตอน retry จะแปะรายชื่อเป็น bullet list ต่อท้ายก้อนสุดท้ายแทน
    ให้ลูกค้าพิมพ์ชื่อกลับมาเลือกได้เองแทนกดปุ่ม — การันตีลูกค้าไม่มีวันได้ข้อความเปล่าๆ ไม่มีข้อมูลอะไรให้ทำต่อ"""
    qr = quick_replies or QUICK_REPLIES
    chunks = _chunk_text(text, limit=950)
    if not chunks:
        return
    last_idx = len(chunks) - 1
    for i, chunk in enumerate(chunks):
        is_last = i == last_idx
        chunk_qr = qr if is_last else None
        status, resp_text = send_message(page_token, sender, chunk, quick_replies=chunk_qr)
        if not status or status >= 400:
            print(f"[meta_bot] send_message chunk {i + 1}/{len(chunks)} (quick_replies={bool(chunk_qr)}) "
                  f"failed ({status}): {resp_text} — retry without buttons", flush=True)
            retry_chunk = chunk
            if is_last and fallback_names:
                bullets = "\n".join(f"• {n}" for n in fallback_names)
                retry_chunk = f"{chunk}\n\n{bullets}\n\n(พิมพ์ชื่อโปรที่สนใจกลับมาได้เลยค่ะ)"
            r_status, r_resp = send_message(page_token, sender, retry_chunk)
            if not r_status or r_status >= 400:
                print(f"[meta_bot] retry-without-buttons ALSO failed chunk {i + 1}/{len(chunks)} "
                      f"({r_status}): {r_resp}", flush=True)
