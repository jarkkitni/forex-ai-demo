"""
Dialysis API — ต่อ Supabase จริง
- คนไข้ใหม่: พิมพ์ชื่อ+HN ครั้งเดียว → บันทึกลง patients
- รอบต่อไป: ดึงรายชื่อมาเป็นปุ่มให้กด (ไม่ต้องพิมพ์อีก)
- บันทึกรอบฟอก → visits (พร้อม audit fields)

ต้องมี env:
  SUPABASE_URL       = https://tghgpnveusfulczxcnbo.supabase.co
  SUPABASE_SERVICE_KEY = service_role key (bypass RLS — ห้ามหลุดออกฝั่ง client)
"""
import os
import requests
from datetime import datetime, date, timedelta

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

# รหัสเข้าใช้งานของศูนย์ (ตั้งใน Render: DIALYSIS_PIN)
CENTER_PIN = os.environ.get("DIALYSIS_PIN", "")

# ค่าคงที่จากศูนย์ (ต้องตรงกับใน demo_dialysis.html)
FILTERS = {"F7": 96, "F60": 82, "F80": 110, "F100": 132}
CUTOFF_PCT = 80
MAX_REUSE = 20

SCHEDULE_MAP = {"จ-พ-ศ": [0, 2, 4], "อ-พฤ-ส": [1, 3, 5]}  # Mon=0


def is_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)


def _h(extra: dict | None = None) -> dict:
    h = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def _url(path: str) -> str:
    return f"{SUPABASE_URL}/rest/v1/{path}"


# ---------------- คนไข้ ----------------

def list_patients() -> list:
    """รายชื่อคนไข้ที่ยัง active + ข้อมูลตัวกรองจากรอบล่าสุด"""
    r = requests.get(
        _url("patients"),
        headers=_h(),
        params={
            "select": "id,name,hn,schedule,status,init_filter_type,dry_weight",
            "status": "eq.active",
            "order": "name.asc",
        },
        timeout=15,
    )
    r.raise_for_status()
    patients = r.json()
    if not patients:
        return []

    # ดึงรอบล่าสุดของแต่ละคน (ครั้งเดียว ไม่วน query)
    ids = ",".join(f'"{p["id"]}"' for p in patients)
    rv = requests.get(
        _url("visits"),
        headers=_h(),
        params={
            "select": "patient_id,date,filter_type,filter_use,filter_base,filter_pct,next_appointment",
            "patient_id": f"in.({ids})",
            "order": "date.desc",
        },
        timeout=15,
    )
    rv.raise_for_status()
    latest: dict = {}
    for v in rv.json():
        latest.setdefault(v["patient_id"], v)  # ตัวแรก = ล่าสุด (เรียง date desc)

    out = []
    for p in patients:
        lv = latest.get(p["id"], {})
        ftype = lv.get("filter_type") or p.get("init_filter_type")
        out.append({
            "id": p["id"],
            "name": p["name"],
            "hn": p.get("hn") or "",
            "schedule": p.get("schedule") or "จ-พ-ศ",
            "filter": ftype,
            "base": lv.get("filter_base") or FILTERS.get(ftype),
            "uses": lv.get("filter_use") or 0,
            "last_visit": lv.get("date"),
            "next_appointment": lv.get("next_appointment"),
        })
    return out


def create_patient(name: str, hn: str, schedule: str, note: str = "") -> dict:
    """สร้างคนไข้ใหม่ — พิมพ์ชื่อครั้งเดียว รอบต่อไปกดปุ่มเอา"""
    name = (name or "").strip()
    hn = (hn or "").strip()
    if not name:
        raise ValueError("ต้องระบุชื่อคนไข้")
    if schedule not in SCHEDULE_MAP:
        raise ValueError("รอบฟอกไม่ถูกต้อง")

    # id: ใช้ HN ถ้ามี (กันซ้ำ) ไม่มีก็ generate
    pid = f"HN{hn}" if hn else f"P{datetime.now().strftime('%y%m%d%H%M%S')}"

    # กันซ้ำ
    chk = requests.get(_url("patients"), headers=_h(),
                       params={"select": "id", "id": f"eq.{pid}"}, timeout=15)
    if chk.ok and chk.json():
        raise ValueError(f"มีคนไข้ HN {hn} อยู่แล้วในระบบ")

    r = requests.post(
        _url("patients"),
        headers=_h({"Prefer": "return=representation"}),
        json={
            "id": pid, "name": name, "hn": hn or None,
            "schedule": schedule, "status": "active",
            "start_date": date.today().isoformat(),
            "notes": note or None,
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()[0]


# ---------------- รอบฟอก ----------------

def next_appointment(schedule: str, from_date: date | None = None) -> str:
    days = SCHEDULE_MAP.get(schedule, [0, 2, 4])
    d0 = from_date or date.today()
    for i in range(1, 8):
        d = d0 + timedelta(days=i)
        if d.weekday() in days:
            return d.isoformat()
    return (d0 + timedelta(days=2)).isoformat()


def save_visit(v: dict) -> dict:
    """
    บันทึกรอบฟอก + audit fields
    v = {patient_id, schedule, filter, base, uses, tcv, pct,
         wPre, wPost, uf, bpPre, bpPost,
         wPreSkipReason, wPostSkipReason, bpPreSkipped, bpPostSkipped,
         filterSource, filterNote, override, recordedBy}
    """
    pid = v.get("patient_id")
    if not pid:
        raise ValueError("ไม่มี patient_id")

    nxt = next_appointment(v.get("schedule") or "จ-พ-ศ")
    row = {
        "patient_id":  pid,
        "date":        date.today().isoformat(),
        "filter_type": v.get("filter"),
        "filter_base": v.get("base"),
        "filter_new":  bool(v.get("tcv") is None),
        "filter_vol":  v.get("tcv"),
        "filter_pct":  v.get("pct"),
        "filter_use":  v.get("uses"),
        "filter_source": v.get("filterSource") or "auto",
        "filter_note": v.get("filterNote") or None,
        "filter_override": bool(v.get("override")),
        "weight_pre":  v.get("wPre"),
        "weight_post": v.get("wPost"),
        "uf":          v.get("uf"),
        "bp_pre":      v.get("bpPre"),
        "bp_post":     v.get("bpPost"),
        "w_pre_skip_reason":  v.get("wPreSkipReason") or None,
        "w_post_skip_reason": v.get("wPostSkipReason") or None,
        "bp_pre_skipped":  bool(v.get("bpPreSkipped")),
        "bp_post_skipped": bool(v.get("bpPostSkipped")),
        "next_appointment": nxt,
        "recorded_by": v.get("recordedBy") or "ไม่ระบุ",
        "source": "web",
    }
    r = requests.post(_url("visits"), headers=_h({"Prefer": "return=representation"}),
                      json=row, timeout=15)
    r.raise_for_status()
    saved = r.json()[0]

    # อัปเดตตัวกรองเริ่มต้นของคนไข้ ถ้าเป็นตัวกรองใหม่
    if v.get("tcv") is None and v.get("filter"):
        try:
            requests.patch(_url("patients"), headers=_h(),
                           params={"id": f"eq.{pid}"},
                           json={"init_filter_type": v.get("filter")}, timeout=10)
        except Exception:
            pass

    saved["next_appointment_th"] = _thai_date(nxt)
    return saved


def recent_visits(limit: int = 10) -> list:
    r = requests.get(
        _url("visits"),
        headers=_h(),
        params={
            "select": "*,patients(name,hn)",
            "order": "created_at.desc",
            "limit": str(limit),
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def tomorrow_list() -> list:
    """พรุ่งนี้ใครมาบ้าง"""
    tm = (date.today() + timedelta(days=1)).isoformat()
    r = requests.get(
        _url("visits"),
        headers=_h(),
        params={
            "select": "patient_id,next_appointment,patients(name,hn,schedule)",
            "next_appointment": f"eq.{tm}",
            "order": "created_at.desc",
        },
        timeout=15,
    )
    r.raise_for_status()
    seen, out = set(), []
    for v in r.json():
        if v["patient_id"] in seen:
            continue
        seen.add(v["patient_id"])
        p = v.get("patients") or {}
        out.append({"name": p.get("name"), "hn": p.get("hn"), "date": tm})
    return out


_TH_DAYS = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]


def _thai_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{_TH_DAYS[d.weekday()]} {d.day}/{d.month}"
