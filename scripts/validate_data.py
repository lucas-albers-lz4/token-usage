#!/usr/bin/env python3
"""Validate data/usage.json against the schema contract. CI gate: exit 1 on violation."""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(ROOT, "data", "usage.json")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def main():
    errors = []
    try:
        with open(DATA_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        print(f"FAIL: {DATA_FILE} missing")
        return 1
    except json.JSONDecodeError as exc:
        print(f"FAIL: {DATA_FILE} is not valid JSON: {exc}")
        return 1

    if not isinstance(data, dict) or "snapshots" not in data:
        errors.append("top level must be an object with a 'snapshots' list")
    elif not isinstance(data["snapshots"], list):
        errors.append("'snapshots' must be a list")
    else:
        seen = set()
        prev_date = ""
        for i, snap in enumerate(data["snapshots"]):
            tag = f"snapshots[{i}]"
            if not isinstance(snap, dict) or "date" not in snap:
                errors.append(f"{tag}: missing 'date'")
                continue
            date_s = snap["date"]
            if not DATE_RE.match(date_s):
                errors.append(f"{tag}: bad date {date_s!r}")
                continue
            try:
                d = datetime.strptime(date_s, "%Y-%m-%d").date()
            except ValueError:
                errors.append(f"{tag}: unparseable date {date_s!r}")
                continue
            if d > datetime.now(timezone.utc).date() + timedelta(days=1):
                errors.append(f"{tag}: date {date_s} is in the future")
            if date_s in seen:
                errors.append(f"{tag}: duplicate date {date_s}")
            seen.add(date_s)
            if prev_date and date_s < prev_date:
                errors.append(f"{tag}: dates out of order ({date_s} < {prev_date})")
            prev_date = date_s

            for prov in ("openrouter", "deepseek"):
                block = snap.get(prov)
                if not isinstance(block, dict):
                    continue  # provider not configured — fine
                if "ok" not in block or not isinstance(block["ok"], bool):
                    errors.append(f"{tag}.{prov}: missing boolean 'ok'")
                    continue
                if block["ok"]:
                    if prov == "openrouter":
                        for field in ("total_credits", "total_usage", "remaining"):
                            if field not in block or not is_number(block[field]):
                                errors.append(
                                    f"{tag}.{prov}: ok=true but missing/non-numeric '{field}'"
                                )
                    else:  # deepseek
                        balances = block.get("balances")
                        if not isinstance(balances, list) or not balances:
                            errors.append(f"{tag}.{prov}: ok=true but 'balances' is empty/missing")
                        else:
                            for b in balances:
                                if not isinstance(b, dict) or not b.get("currency"):
                                    errors.append(f"{tag}.{prov}: balance entry missing 'currency'")
                                if not b.get("total_balance"):
                                    errors.append(
                                        f"{tag}.{prov}: balance entry missing 'total_balance'"
                                    )
                elif "error" not in block or not isinstance(block["error"], str):
                    errors.append(f"{tag}.{prov}: ok=false but no string 'error'")

    if errors:
        print("VALIDATION FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    n = len(data.get("snapshots", []))
    print(f"data/usage.json OK: {n} snapshot(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
