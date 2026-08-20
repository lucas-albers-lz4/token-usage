#!/usr/bin/env python3
"""Collect a Cursor usage snapshot on a machine where Cursor is logged in.

Cursor has no public personal usage API. This script reads the session JWT from
Cursor's local state.vscdb and calls the undocumented dashboard endpoints
(same ones the website uses). Prefer GET /api/usage-summary; fall back to
GET /api/usage?user= if summary is missing.

The token is never written to disk — only usage numbers land in the repo.

Env:
  CURSOR_TOKEN       session JWT; skips local DB read
  CURSOR_API_URL     default https://cursor.com/api
  CURSOR_STATE_DB    explicit path to state.vscdb
  CURSOR_USAGE_FILE  default data/cursor.json

Exit codes: 0 ok (or recorded error snapshot); 1 no token; 2 --doctor failed.
"""

import argparse
import base64
import json
import os
import platform
import re
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USAGE_FILE = os.environ.get("CURSOR_USAGE_FILE") or os.path.join(ROOT, "data", "cursor.json")
API_BASE = (os.environ.get("CURSOR_API_URL") or "https://cursor.com/api").rstrip("/")
TIMEOUT = 25
USER_ID_RE = re.compile(r"user_[A-Za-z0-9]+")
TOKEN_KEYS = (
    "cursorAuth/accessToken",
    "cursorAuth/workosSessionToken",
    "cursorAuth/sessionToken",
)
STATE_DB_CANDIDATES = {
    "Windows": [os.path.join(os.environ.get("APPDATA", ""), "Cursor", "User", "globalStorage", "state.vscdb")],
    "Darwin": [os.path.expanduser("~/Library/Application Support/Cursor/User/globalStorage/state.vscdb")],
    "Linux": [os.path.expanduser("~/.config/Cursor/User/globalStorage/state.vscdb")],
}


def find_state_db():
    env_db = os.environ.get("CURSOR_STATE_DB")
    if env_db:
        return env_db if os.path.exists(env_db) else None
    for path in STATE_DB_CANDIDATES.get(platform.system(), []):
        if path and os.path.exists(path):
            return path
    return None


def token_from_sqlite(db_path):
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
        cur = con.cursor()
        found = None
        for key in TOKEN_KEYS:
            row = cur.execute("SELECT value FROM ItemTable WHERE key = ?", (key,)).fetchone()
            if row and row[0]:
                found = row[0]
                break
        con.close()
        if isinstance(found, bytes):
            found = found.decode("utf-8", "replace")
        return found
    except Exception:
        return None


def find_token():
    token = os.environ.get("CURSOR_TOKEN", "").strip()
    if token:
        return token, "CURSOR_TOKEN"
    db_path = find_state_db()
    if not db_path:
        return None, None
    token = token_from_sqlite(db_path)
    if token:
        return token, db_path
    return None, db_path


def extract_user_id(token):
    decoded = urllib.parse.unquote(token)
    if "::" in decoded:
        return decoded.split("::", 1)[0]
    parts = decoded.split(".")
    if len(parts) != 3:
        return None
    try:
        b64 = parts[1].replace("-", "+").replace("_", "/")
        b64 += "=" * (-len(b64) % 4)
        payload = json.loads(base64.b64decode(b64))
        m = USER_ID_RE.search(str(payload.get("sub", "")))
        return m.group(0) if m else None
    except Exception:
        return None


def jwt_exp_days(token):
    decoded = urllib.parse.unquote(token)
    jwt = decoded.split("::")[-1]
    parts = jwt.split(".")
    if len(parts) != 3:
        return None
    try:
        b64 = parts[1].replace("-", "+").replace("_", "/")
        b64 += "=" * (-len(b64) % 4)
        payload = json.loads(base64.b64decode(b64))
        exp = payload.get("exp")
        if not exp:
            return None
        return (exp - datetime.now(timezone.utc).timestamp()) / 86400
    except Exception:
        return None


def build_cookie(token, user_id):
    value = token
    if "::" not in value and "%3A%3A" not in value:
        value = f"{user_id}%3A%3A{value}" if user_id else urllib.parse.quote(value)
    elif "::" in value and "%3A%3A" not in value:
        value = value.replace("::", "%3A%3A")
    return value


def short_error(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code} {exc.reason}"
    if isinstance(exc, urllib.error.URLError):
        return f"network: {exc.reason}"
    return f"{type(exc).__name__}: {exc}"


def http_json(method, url, token, user_id, body=None):
    headers = {
        "Cookie": f"WorkosCursorSessionToken={build_cookie(token, user_id)}",
        "Origin": "https://cursor.com",
    }
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def compact_plan(block):
    if not isinstance(block, dict):
        return None
    out = {}
    for key in ("enabled", "used", "limit", "remaining", "autoPercentUsed", "apiPercentUsed", "totalPercentUsed"):
        if key in block:
            out[key] = block[key]
    return out or None


def compact_summary(summary):
    plan = compact_plan((summary.get("individualUsage") or {}).get("plan"))
    on_demand = compact_plan((summary.get("individualUsage") or {}).get("onDemand"))
    return {
        "ok": True,
        "membershipType": summary.get("membershipType"),
        "limitType": summary.get("limitType"),
        "billingCycleStart": summary.get("billingCycleStart"),
        "billingCycleEnd": summary.get("billingCycleEnd"),
        "plan": plan,
        "onDemand": on_demand,
    }


def plan_is_usable(snap):
    plan = (snap or {}).get("plan") or {}
    used, limit = plan.get("used"), plan.get("limit")
    return (
        isinstance(used, (int, float))
        and isinstance(limit, (int, float))
        and not isinstance(used, bool)
        and not isinstance(limit, bool)
    )


def compact_legacy_usage(usage):
    models = {}
    if not isinstance(usage, dict):
        return models
    for key, block in usage.items():
        if key == "startOfMonth" or not isinstance(block, dict):
            continue
        row = {}
        for field in ("numRequests", "numRequestsTotal", "numTokens", "maxRequestUsage"):
            if field in block:
                row[field] = block[field]
        if row:
            models[key] = row
    return models


def fetch_snapshot(token):
    user_id = extract_user_id(token)
    if not user_id:
        raise ValueError("could not extract userId from token")
    summary_err = "usage-summary missing plan used/limit"
    try:
        summary = http_json("GET", f"{API_BASE}/usage-summary", token, user_id)
        if isinstance(summary, dict):
            snap = compact_summary(summary)
            if plan_is_usable(snap):
                return snap
    except Exception as exc:
        summary_err = short_error(exc)
    usage = http_json("GET", f"{API_BASE}/usage?user={user_id}", token, user_id)
    snap = {
        "ok": True,
        "billingCycleStart": usage.get("startOfMonth") if isinstance(usage, dict) else None,
        "startOfMonth": usage.get("startOfMonth") if isinstance(usage, dict) else None,
        "legacyModels": compact_legacy_usage(usage),
        "warning": f"fell back to /usage ({summary_err})",
    }
    if not plan_is_usable(snap) and not snap["legacyModels"]:
        raise ValueError(f"no plan in usage-summary and empty /usage ({summary_err})")
    return snap


def load_snapshots():
    if not os.path.exists(USAGE_FILE):
        return []
    with open(USAGE_FILE, encoding="utf-8") as fh:
        return json.load(fh).get("snapshots", [])


def write_snapshot(snap):
    today = snap["date"]
    snapshots = [s for s in load_snapshots() if s.get("date") != today]
    snapshots.append(snap)
    snapshots.sort(key=lambda s: s["date"])
    os.makedirs(os.path.dirname(USAGE_FILE), exist_ok=True)
    with open(USAGE_FILE, "w", encoding="utf-8") as fh:
        json.dump({"snapshots": snapshots}, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return snapshots


def doctor():
    failed = False
    db = find_state_db()
    print(f"python: {sys.version.split()[0]}")
    print(f"state.vscdb: {db or 'NOT FOUND'}")
    if db:
        print(f"  size_mb: {os.path.getsize(db) / 1e6:.1f}")
    else:
        failed = True
    token, source = find_token()
    print(f"token: {'found' if token else 'MISSING'} ({source or 'nowhere'})")
    if not token:
        failed = True
        print("doctor: FAIL")
        return 2
    days = jwt_exp_days(token)
    if days is not None:
        print(f"token_exp_days: {days:.1f}")
        if days < 3:
            print("  warning: session JWT expires soon — stay logged into Cursor")
    user_id = extract_user_id(token)
    print(f"userId: {user_id or 'MISSING'}")
    if not user_id:
        failed = True
    try:
        snap = fetch_snapshot(token)
        plan = snap.get("plan") or {}
        used = plan.get("used")
        limit = plan.get("limit")
        plan_text = (
            f"{used}/{limit}"
            if plan_is_usable(snap)
            else "unavailable (legacy usage)"
        )
        print(
            f"api: ok plan={plan_text}"
            + (" membership=ok" if snap.get("membershipType") else "")
        )
        if snap.get("warning"):
            print(f"  warning: {snap['warning']}")
    except Exception as exc:
        print(f"api: FAIL {short_error(exc)}")
        failed = True
    print(f"write_target: {USAGE_FILE}")
    print("doctor: " + ("FAIL" if failed else "OK"))
    return 2 if failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Collect Cursor usage into data/cursor.json")
    parser.add_argument("--doctor", action="store_true", help="check token + API; do not write")
    args = parser.parse_args(argv)
    if args.doctor:
        return doctor()

    token, source = find_token()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not token:
        print(
            "ERROR: no Cursor session token found. Stay logged into Cursor on this "
            "machine, or set CURSOR_TOKEN. Run: python3 scripts/collect_cursor.py --doctor",
            file=sys.stderr,
        )
        return 1

    print(f"token: read from {source}")
    snap = {"date": today}
    try:
        snap.update(fetch_snapshot(token))
        plan = snap.get("plan") or {}
        print(
            f"cursor: ok (plan={plan.get('used')}/{plan.get('limit')}, "
            f"membership={snap.get('membershipType')})"
        )
        if snap.get("warning"):
            print(f"cursor: {snap['warning']}")
    except Exception as exc:  # noqa: BLE001 - record any provider failure
        snap["ok"] = False
        snap["error"] = short_error(exc)
        print(f"cursor: ERROR {snap['error']}")

    snapshots = write_snapshot(snap)
    print(f"{USAGE_FILE}: {len(snapshots)} snapshot(s), latest {today}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
