#!/usr/bin/env python3
"""Collect an OpenCode usage snapshot from the machine that runs opencode.

Reads the event-sourced ledger at ~/.local/share/opencode/opencode.db (message
table; per-call records in message.data JSON), aggregates assistant calls since
the last processed row (incremental, resumed via last_processed_id/time), and
appends one snapshot per UTC date to data/opencode.json (idempotent per day).

Env overrides:
  OPENCODE_DB          default ~/.local/share/opencode/opencode.db
  OPENCODE_USAGE_FILE  default data/opencode.json

Note: if the DB is migrated/recreated, delete data/opencode.json once so
totals re-seed from scratch (the resume marker points at the old ledger).
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USAGE_FILE = os.environ.get("OPENCODE_USAGE_FILE") or os.path.join(ROOT, "data", "opencode.json")
DB_PATH = os.environ.get("OPENCODE_DB") or os.path.expanduser("~/.local/share/opencode/opencode.db")
MS_PER_DAY = 24 * 3600 * 1000

EMPTY_TOTALS = {
    "n": 0,
    "input": 0,
    "output": 0,
    "reasoning": 0,
    "cache_read": 0,
    "cache_write": 0,
    "cost": 0.0,
}


def load_snapshots():
    if not os.path.exists(USAGE_FILE):
        return []
    with open(USAGE_FILE, encoding="utf-8") as fh:
        return json.load(fh).get("snapshots", [])


def main():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: opencode DB not found at {DB_PATH}. Run this on the opencode machine.", file=sys.stderr)
        return 1

    snapshots = load_snapshots()
    last = snapshots[-1] if snapshots else None
    last_id = (last or {}).get("last_processed_id", "")
    last_time = (last or {}).get("last_processed_time", 0)

    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    cur = con.cursor()
    rows = cur.execute(
        "SELECT id, time_created, data FROM message "
        "WHERE (time_created > ? OR (time_created = ? AND id > ?)) AND data LIKE '%modelID%' "
        "ORDER BY time_created, id",
        (last_time, last_time, last_id),
    ).fetchall()
    con.close()

    totals = dict(EMPTY_TOTALS)
    by_provider = {}
    delta = {"n": 0, "input": 0, "output": 0, "cost": 0.0}
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    window_start = now_ms - MS_PER_DAY
    first_ts = None
    last_ts = None
    new_last_id, new_last_time = last_id, last_time
    processed = 0
    skipped = 0

    for rid, ts, raw in rows:
        try:
            d = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            skipped += 1
            continue
        if d.get("role") != "assistant":
            continue
        prov = d.get("providerID")
        model = d.get("modelID")
        if not prov and not model:
            continue
        toks = d.get("tokens") or {}
        cache = toks.get("cache") or {}
        try:
            cost = float(d.get("cost") or 0.0)
        except (TypeError, ValueError):
            cost = 0.0
        totals["n"] += 1
        totals["input"] += toks.get("input") or 0
        totals["output"] += toks.get("output") or 0
        totals["reasoning"] += toks.get("reasoning") or 0
        totals["cache_read"] += cache.get("read") or 0
        totals["cache_write"] += cache.get("write") or 0
        totals["cost"] += cost
        p = by_provider.setdefault(prov or model, {"n": 0, "input": 0, "output": 0, "cost": 0.0})
        p["n"] += 1
        p["input"] += toks.get("input") or 0
        p["output"] += toks.get("output") or 0
        p["cost"] += cost
        if ts >= window_start:
            delta["n"] += 1
            delta["input"] += toks.get("input") or 0
            delta["output"] += toks.get("output") or 0
            delta["cost"] += cost
        if first_ts is None:
            first_ts = ts
        last_ts = ts
        new_last_id, new_last_time = rid, ts
        processed += 1

    totals["cost"] = round(totals["cost"], 6)
    delta["cost"] = round(delta["cost"], 6)
    for p in by_provider.values():
        p["cost"] = round(p["cost"], 6)
    by_provider = dict(sorted(by_provider.items(), key=lambda kv: -kv[1]["cost"]))

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if processed == 0:
        print(
            f"opencode: no new calls since last snapshot "
            f"(resume at {new_last_time}); nothing to record"
        )
        return 0
    snap = {
        "date": today,
        "processed": processed,
        "skipped": skipped,
        "since": first_ts,
        "until": last_ts,
        "last_processed_id": new_last_id,
        "last_processed_time": new_last_time,
        "totals": totals,
        "by_provider": by_provider,
        "delta24h": delta,
    }
    snapshots = [s for s in snapshots if s.get("date") != today]
    snapshots.append(snap)
    snapshots.sort(key=lambda s: s["date"])

    os.makedirs(os.path.dirname(USAGE_FILE), exist_ok=True)
    with open(USAGE_FILE, "w", encoding="utf-8") as fh:
        json.dump({"snapshots": snapshots}, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(
        f"opencode: {processed} new call(s) processed ({skipped} unparseable), "
        f"totals: {totals['n']} calls, {totals['cost']} USD, "
        f"24h: {delta['n']} calls, {delta['cost']} USD"
    )
    print(f"{USAGE_FILE}: {len(snapshots)} snapshot(s), latest {today}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
