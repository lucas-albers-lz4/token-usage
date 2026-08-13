#!/usr/bin/env python3
"""Collect daily credit/usage snapshots from OpenRouter and DeepSeek.

Appends one snapshot per UTC date to data/usage.json (idempotent per day:
re-running on the same date replaces that day's snapshot).

Exit codes:
  0  collected (a provider error is recorded as an ok:false error snapshot)
  1  misconfiguration: no API keys set (the workflow should fail loudly)

Base URLs are overridable via env for testing or mirrors:
  OPENROUTER_API_URL   (default https://openrouter.ai)
  DEEPSEEK_API_URL     (default https://api.deepseek.com)
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(ROOT, "data", "usage.json")
DEFAULT_OPENROUTER_URL = "https://openrouter.ai"
DEFAULT_DEEPSEEK_URL = "https://api.deepseek.com"
TIMEOUT = 25


def fetch_json(url, headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def short_error(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code} {exc.reason}"
    if isinstance(exc, urllib.error.URLError):
        return f"network: {exc.reason}"
    return f"{type(exc).__name__}: {exc}"


def collect_openrouter(api_key, base_url):
    data = fetch_json(
        f"{base_url}/api/v1/auth/key",
        {"Authorization": f"Bearer {api_key}"},
    )
    key_data = data.get("data") or {}
    usage = key_data.get("usage") or {}
    snap = {"ok": True, "key_label": key_data.get("label")}
    # Account/credit usage lives in data.usage; the per-key spending cap may
    # sit at the same level as "usage". Prefer data.usage, fall back.
    for field in ("total_credits", "total_usage", "remaining"):
        if field in usage and usage[field] is not None:
            snap[field] = float(usage[field])
    for field in ("limit", "limit_remaining"):
        if field in usage and usage[field] is not None:
            snap[field] = float(usage[field])
        elif field in key_data and key_data[field] is not None:
            snap[field] = float(key_data[field])
    if "remaining" not in snap and "total_credits" in snap and "total_usage" in snap:
        snap["remaining"] = round(snap["total_credits"] - snap["total_usage"], 6)
    return snap


def collect_deepseek(api_key, base_url):
    data = fetch_json(
        f"{base_url}/user/balance",
        {"Authorization": f"Bearer {api_key}"},
    )
    snap = {"ok": bool(data.get("is_available", False)), "balances": []}
    for bal in data.get("balance_infos") or []:
        snap["balances"].append(
            {
                "currency": bal.get("currency"),
                "total_balance": bal.get("total_balance"),
                "granted_balance": bal.get("granted_balance"),
                "topped_up_balance": bal.get("topped_up_balance"),
            }
        )
    return snap


def load_snapshots():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, encoding="utf-8") as fh:
        data = json.load(fh)
    return data.get("snapshots", [])


def main():
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not openrouter_key and not deepseek_key:
        print(
            "ERROR: neither OPENROUTER_API_KEY nor DEEPSEEK_API_KEY is set. "
            "Add them as GitHub Actions secrets (or env vars locally).",
            file=sys.stderr,
        )
        return 1

    openrouter_url = os.environ.get("OPENROUTER_API_URL", DEFAULT_OPENROUTER_URL).rstrip("/")
    deepseek_url = os.environ.get("DEEPSEEK_API_URL", DEFAULT_DEEPSEEK_URL).rstrip("/")

    providers = {}
    if openrouter_key:
        try:
            providers["openrouter"] = collect_openrouter(openrouter_key, openrouter_url)
            print(f"openrouter: ok (remaining={providers['openrouter'].get('remaining')})")
        except Exception as exc:  # noqa: BLE001 - record any provider failure
            providers["openrouter"] = {"ok": False, "error": short_error(exc)}
            print(f"openrouter: ERROR {providers['openrouter']['error']}")
    if deepseek_key:
        try:
            providers["deepseek"] = collect_deepseek(deepseek_key, deepseek_url)
            total = sum(
                float(b["total_balance"] or 0)
                for b in providers["deepseek"]["balances"]
                if b.get("total_balance")
            )
            print(f"deepseek: ok (total={total})")
        except Exception as exc:  # noqa: BLE001
            providers["deepseek"] = {"ok": False, "error": short_error(exc)}
            print(f"deepseek: ERROR {providers['deepseek']['error']}")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    snapshots = [s for s in load_snapshots() if s.get("date") != today]
    snapshots.append({"date": today, **providers})
    snapshots.sort(key=lambda s: s["date"])

    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as fh:
        json.dump({"snapshots": snapshots}, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"data/usage.json: {len(snapshots)} snapshot(s), latest {today}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
