#!/usr/bin/env python3
"""hunter_doctor.py - probe live Render service, report what is actually broken."""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

JOBBOARD = "https://jobboard-api.fastwork.co/api/jobs"

# platform.claude.com/docs/en/about-claude/model-deprecations (2026-08-25)
CLAUDE_RETIREMENT = {
    "claude-sonnet-4-5": "2026-09-29",
    "claude-sonnet-4-5-20250929": "2026-09-29",
    "claude-haiku-4-5-20251001": "2026-10-15",
    "claude-haiku-4-5": "2026-10-15",
    "claude-sonnet-4-6": "2027-02-17",
    "claude-sonnet-5": "2027-06-30",
    "claude-opus-5": "2027-07-24",
}

OK, WARN, BAD = "  ok  ", " WARN ", " FAIL "


def get(url: str, timeout: int = 120):
    """Render free tier boots in 30-60s, so timeout must be long (cron-job.org used 30s).
    Must send a real User-Agent: urllib's default 'Python-urllib/x' gets 403 from
    Fastwork's edge, while the hunter's `requests` client is fine. Without this the
    doctor reports a job-source outage that does not exist."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "hunter-doctor/1.0",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(body)
            except json.JSONDecodeError:
                return r.status, body[:400]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, body[:400]
    except Exception as e:
        return 0, str(e)


def main(base: str) -> int:
    base = base.rstrip("/")
    problems = 0

    print("\n=== waking " + base + " (free tier: up to 60s) ===")
    t0 = time.time()
    code, _ = get(base + "/api/health")
    mark = OK if code == 200 else BAD
    print("%s service HTTP %s in %.1fs" % (mark, code, time.time() - t0))
    if code != 200:
        print("        -> service down / deploy failed. Check Render logs first.")
        return 1

    print("\n=== hunter kill switch ===")
    code, body = get(base + "/api/hunter/status")
    enabled = body.get("enabled") if isinstance(body, dict) else None
    if enabled is True:
        print(OK + " HUNTERS_ENABLED = on")
    else:
        problems += 1
        print(BAD + " HUNTERS_ENABLED is OFF -> /api/hunter/check returns 503 every time")
        print("        -> Render > forex-ai-demo > Environment > HUNTERS_ENABLED = 1 > Save")

    print("\n=== AI the hunter actually uses (tier=free: Gemini -> Groq) ===")
    code, ai = get(base + "/api/ai-health")
    if not isinstance(ai, dict):
        problems += 1
        print(BAD + " /api/ai-health returned %s: %s" % (code, ai))
    else:
        if ai.get("gemini_configured"):
            print(OK + " GEMINI_API_KEY is set")
        else:
            problems += 1
            print(BAD + " no GEMINI_API_KEY = hunter cannot analyse at all")
        if ai.get("groq_configured"):
            print(OK + " GROQ_API_KEY present (fallback when Gemini dies)")
        else:
            problems += 1
            print(BAD + " no GROQ_API_KEY -> Gemini dead = straight to offline scoring")
            print("        -> free signup at console.groq.com, then set it on Render")

        for label, key in (("smart", "model_smart"), ("cheap", "model_cheap")):
            m = ai.get(key)
            if not m:
                continue
            ret = CLAUDE_RETIREMENT.get(m)
            if ret is None:
                problems += 1
                print(BAD + " %s model '%s' unknown - check model-deprecations" % (label, m))
            elif ret < "2026-11-01":
                print(WARN + " %s model '%s' retires as soon as %s (hits tier=smart bots)" % (label, m, ret))
            else:
                print(OK + " %s model '%s' safe until %s" % (label, m, ret))

    print("\n=== alert channel (LINE Messaging API) ===")
    code, h = get(base + "/api/health")
    if isinstance(h, dict) and h.get("line_token"):
        print(OK + " LINE_TOKEN is set")
    else:
        problems += 1
        print(BAD + " no LINE_TOKEN -> /api/hunter/check returns 500 before doing any work")

    print("\n=== job source (Fastwork public JSON API) ===")
    code, jb = get(JOBBOARD, timeout=30)
    if code == 200:
        n = len(jb.get("data", jb)) if isinstance(jb, (dict, list)) else "?"
        print(OK + " jobboard 200 (%s jobs) - public API, not scraping, no ban risk" % n)
    else:
        problems += 1
        print(BAD + " jobboard returned %s - Fastwork may have changed the endpoint" % code)

    print("\n" + "=" * 50)
    print("RESULT: " + ("all checks passed" if not problems else "%d problem(s) to fix" % problems))
    return 1 if problems else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
