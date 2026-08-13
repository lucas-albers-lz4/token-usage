#!/usr/bin/env python3
"""Collect a Cursor usage snapshot on a machine where Cursor is installed.

Cursor has no public usage API. Community tools (e.g. lixwen/cursor-usage-monitor)
read the session token from Cursor's local state and call the undocumented
endpoint `GET https://cursor.com/api/usage?user=<userId>` with the token in a
Cookie header. This script does the same and appends one snapshot per UTC date
to data/cursor.json (idempotent per day: re-running replaces that day).

The token is never written to disk by this script — only usage numbers land
in the repo.

Env overrides (testing / non-standard installs):
  CURSOR_TOKEN       session token (user_XXXX::JWT or JWT); skips local DB read
  CURSOR_API_URL     default https://cursor.com/api
  CURSOR_STATE_DB    explicit path to Cursor's state.vscdb
  CURSOR_USAGE_FILE  default data/cursor.json

Exit codes: 0 ok (or recorded error snapshot); 1 no token found anywhere.
"""

import base64
import json
import os
import platform
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

# (platform, state.vscdb path) — keyed how lixwen/cursor-usage-monitor does it
STATE_DB_CANDIDATES = {
    "Windows": [os.path.join(os.environ.get("APPDATA", ""), "Cursor", "User", "globalStorage", "state.vscdb")],
    "Darwin": [os.path.expanduser("~/Library/Application Support/Cursor/User/globalStorage/state.vscdb")],
    "Linux": [os.path.expanduser("~/.config/Cursor/User/globalStorage/state.vscdb")],
}
CONFIG_CANDIDATES = [
    os.path.expanduser("~/.cursor/config.json"),
    os.path.expanduser("~/.cursor/config"),
    os.path.expanduser("~/.config/cursor/config.json"),
]
TOKEN_KEYS = (
    "cursorAuth/accessToken",
    "cursorAuth/workosSessionToken",
    "cursorAuth/sessionToken",
)


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
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cur = con.cursor()
        cols = [c[1] for c in cur.execute("PRAGMA table_info(ItemTable)")]
        if "key" not in cols or "value" not in cols:
            return None
        found = None
        for key in TOKEN_KEYS:
            row = cur.execute("SELECT value FROM ItemTable WHERE key = ?", (key,)).fetchone()
            if row and row[0]:
                found = row[0]
                break
        if not found:
            for row in cur.execute(
                "SELECT key, value FROM ItemTable WHERE key LIKE '%workos%' OR key LIKE '%sessionToken%' OR key LIKE '%accessToken%'"
            ):
                if row[1]:
                    found = row[1]
                    break
        con.close()
        return found
    except Exception:
        return None


def token_from_configs():
    import re

    pattern = re.compile(r"WorkosCursorSessionToken[=:][\"']?([^\"'\s;]+)")
    for path in CONFIG_CANDIDATES:
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                content = fh.read()
            try:
                config = json.loads(content)
                for k, v in config.items():
                    if "token" in k.lower() and isinstance(v, str) and v:
                        return v
            except json.JSONDecodeError:
                m = pattern.search(content)
                if m:
                    return m.group(1)
        except OSError:
            continue
    return None


def find_token():
    token = os.environ.get("CURSOR_TOKEN", "").strip()
    if token:
        return token
    db_path = find_state_db()
    if db_path:
        token = token_from_sqlite(db_path)
        if token:
            print(f"token: read from {db_path}")
            return token
        print(f"token: no token row in {db_path}")
    token = token_from_configs()
    if token:
        print("token: read from config file")
        return token
    return None


def extract_user_id(token):
    decoded = token
    try:
        decoded = urllib.parse.unquote(token)
    except Exception:
        pass
    if "::" in decoded:
        return decoded.split("::")[0]
    parts = decoded.split(".")
    if len(parts) == 3:
        try:
            b64 = parts[1].replace("-", "+").replace("_", "/")
            b64 += "=" * (-len(b64) % 4)
            payload = json.loads(base64.b64decode(b64))
            m = __import__("re").search(r"user_[A-Za-z0-9]+", str(payload.get("sub", "")))
            if m:
                return m.group(0)
        except Exception:
            pass
    return None


def build_cookie(token, user_id):
    value = token
    if "::" not in value and "%3A%3A" not in value:
        if user_id:
            value = f"{user_id}%3A%3A{value}"
        else:
            value = urllib.parse.quote(value)
    elif "::" in value and "%3A%3A" not in value:
        value = value.replace("::", "%3A%3A")
    return value


def short_error(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code} {exc.reason}"
    if isinstance(exc, urllib.error.URLError):
        return f"network: {exc.reason}"
    return f"{type(exc).__name__}: {exc}"


def fetch_usage(token):
    user_id = extract_user_id(token)
    if not user_id:
        raise ValueError("could not extract userId from token")
    url = f"{API_BASE}/usage?user={user_id}"
    req = urllib.request.Request(
        url,
        headers={"Cookie": f"WorkosCursorSessionToken={build_cookie(token, user_id)}"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8")), user_id


def load_snapshots():
    if not os.path.exists(USAGE_FILE):
        return []
    with open(USAGE_FILE, encoding="utf-8") as fh:
        return json.load(fh).get("snapshots", [])


def main():
    token = find_token()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not token:
        print(
            "ERROR: no Cursor session token found. Run this on a machine with Cursor "
            "installed, or set CURSOR_TOKEN (cookie WorkosCursorSessionToken).",
            file=sys.stderr,
        )
        return 1

    snap = {"date": today, "machine": platform.node() or platform.system()}
    try:
        usage, user_id = fetch_usage(token)
        snap["ok"] = True
        snap["userId"] = user_id
        snap["startOfMonth"] = usage.get("startOfMonth")
        snap["usage"] = usage
        print(f"cursor: ok (user={user_id}, startOfMonth={usage.get('startOfMonth')})")
    except Exception as exc:  # noqa: BLE001 - record any provider failure
        snap["ok"] = False
        snap["error"] = short_error(exc)
        print(f"cursor: ERROR {snap['error']}")

    snapshots = [s for s in load_snapshots() if s.get("date") != today]
    snapshots.append(snap)
    snapshots.sort(key=lambda s: s["date"])

    os.makedirs(os.path.dirname(USAGE_FILE), exist_ok=True)
    with open(USAGE_FILE, "w", encoding="utf-8") as fh:
        json.dump({"snapshots": snapshots}, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"{USAGE_FILE}: {len(snapshots)} snapshot(s), latest {today}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
