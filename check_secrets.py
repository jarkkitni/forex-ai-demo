#!/usr/bin/env python3
"""
check_secrets.py — เช็คลับก่อน push ทุกครั้ง

เกิดจากบทเรียน: TikTok CLIENT_SECRET เคยหลุดในโค้ดมาแล้ว (แก้ไปแล้ว 18 ก.ค. 2026)
สคริปต์นี้สแกนไฟล์ที่ git track อยู่ทั้งหมด หา pattern ที่ดูเหมือน API key/token/secret
ที่ hardcode ไว้ในโค้ด (ควรอยู่ใน env var เท่านั้น)

วิธีใช้ (ก่อน push ทุกครั้ง):
    python3 check_secrets.py

Exit code 0 = สะอาด push ได้ · Exit code 1 = เจอของน่าสงสัย ห้าม push จนกว่าจะเช็คให้ชัวร์
"""
import re
import subprocess
import sys

# ไฟล์/โฟลเดอร์ที่ไม่ต้องสแกน
SKIP_PATH_PARTS = (
    ".git/", "node_modules/", ".understand-anything/",
    "check_secrets.py",  # ไม่สแกนตัวเอง (มี pattern ในคอมเมนต์/ชื่อตัวแปร)
)
SKIP_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".woff", ".woff2", ".ttf", ".mp4",
)

# ค่าที่เป็น placeholder ปกติ ไม่ใช่ของจริง — กันเตือนเท็จ
SAFE_VALUE_HINTS = (
    "changeme", "your_", "xxx", "example", "placeholder", "todo", "<", "{{",
    "env.get", "environ.get", "process.env", "getenv",
)

# pattern ของ key/token จริงจากผู้ให้บริการที่รู้จัก — เฉพาะเจาะจง แทบไม่มี false positive
KNOWN_KEY_PATTERNS = [
    (r"sk-ant-[A-Za-z0-9\-_]{20,}", "Anthropic API key"),
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key ID"),
    (r"ghp_[A-Za-z0-9]{36}", "GitHub personal access token"),
    (r"xox[baprs]-[A-Za-z0-9\-]{10,}", "Slack token"),
    (r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----", "Private key block"),
]

# pattern ทั่วไป: ตัวแปรชื่อ secret/token/key/password = ค่ายาวๆ hardcode
GENERIC_PATTERN = re.compile(
    r'(?i)\b(secret|token|api[_-]?key|apikey|password|channel_secret|channel_token|access_token)\b'
    r'\s*[:=]\s*["\']([A-Za-z0-9_\-\.]{20,})["\']'
)


def tracked_files() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
        return [f for f in out.stdout.splitlines() if f.strip()]
    except Exception as e:
        print(f"[check_secrets] เรียก git ls-files ไม่ได้: {e}", file=sys.stderr)
        return []


def should_skip(path: str) -> bool:
    if any(part in path for part in SKIP_PATH_PARTS):
        return True
    if path.lower().endswith(SKIP_EXTENSIONS):
        return True
    return False


def scan_file(path: str) -> list[tuple[int, str, str]]:
    """คืน list ของ (line_no, kind, matched_snippet)"""
    findings = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception:
        return findings

    for i, line in enumerate(lines, start=1):
        for pattern, label in KNOWN_KEY_PATTERNS:
            m = re.search(pattern, line)
            if m:
                findings.append((i, label, m.group(0)[:40]))

        m = GENERIC_PATTERN.search(line)
        if m:
            value = m.group(2)
            low = line.lower()
            if any(hint in low for hint in SAFE_VALUE_HINTS):
                continue
            findings.append((i, f"hardcoded {m.group(1)}", value[:12] + "..."))

    return findings


def main() -> int:
    files = tracked_files()
    if not files:
        print("[check_secrets] ไม่มีไฟล์ให้สแกน (ไม่ใช่ git repo หรือยังไม่ track อะไรเลย)")
        return 0

    total_findings = 0
    for path in files:
        if should_skip(path):
            continue
        findings = scan_file(path)
        for line_no, kind, snippet in findings:
            total_findings += 1
            print(f"⚠️  {path}:{line_no}  [{kind}]  {snippet}")

    print("━━━━━━━━━━━━")
    if total_findings:
        print(f"❌ เจอของน่าสงสัย {total_findings} จุด — เช็คให้ชัวร์ก่อน push จริง")
        print("   (ถ้าเป็น false positive เช่น ค่า placeholder ให้แก้ SAFE_VALUE_HINTS เพิ่มได้)")
        return 1
    print(f"✅ สะอาด — สแกน {len(files)} ไฟล์ ไม่เจอ secret หลุด push ได้เลย")
    return 0


if __name__ == "__main__":
    sys.exit(main())
