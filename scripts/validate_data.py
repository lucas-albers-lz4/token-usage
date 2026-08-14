#!/usr/bin/env python3
"""Validate committed JSON snapshots. CI gate for data/usage.json; optional
local files via --also cursor|opencode."""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def check_dates(snapshots, errors, prefix):
    if not isinstance(snapshots, list):
        errors.append(f"{prefix}: 'snapshots' must be a list")
        return
    seen = set()
    prev_date = ""
    for i, snap in enumerate(snapshots):
        tag = f"{prefix}.snapshots[{i}]"
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


def check_usage(data, errors):
    if not isinstance(data, dict) or "snapshots" not in data:
        errors.append("usage: top level must be an object with a 'snapshots' list")
        return
    check_dates(data["snapshots"], errors, "usage")
    if not isinstance(data["snapshots"], list):
        return
    for i, snap in enumerate(data["snapshots"]):
        if not isinstance(snap, dict):
            continue
        tag = f"usage.snapshots[{i}]"
        for prov in ("openrouter", "deepseek"):
            block = snap.get(prov)
            if not isinstance(block, dict):
                continue
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
                else:
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


def check_cursor(data, errors):
    if not isinstance(data, dict) or "snapshots" not in data:
        errors.append("cursor: top level must be an object with a 'snapshots' list")
        return
    check_dates(data["snapshots"], errors, "cursor")
    if not isinstance(data["snapshots"], list):
        return
    for i, snap in enumerate(data["snapshots"]):
        if not isinstance(snap, dict):
            continue
        tag = f"cursor.snapshots[{i}]"
        if "ok" not in snap or not isinstance(snap["ok"], bool):
            errors.append(f"{tag}: missing boolean 'ok'")
            continue
        if not snap["ok"]:
            if "error" not in snap or not isinstance(snap["error"], str):
                errors.append(f"{tag}: ok=false but no string 'error'")
            continue
        plan = snap.get("plan")
        if isinstance(plan, dict):
            for field in ("used", "limit"):
                if field in plan and not is_number(plan[field]):
                    errors.append(f"{tag}.plan.{field} must be numeric")
            if not (is_number(plan.get("used")) and is_number(plan.get("limit"))):
                if not isinstance(snap.get("legacyModels"), dict):
                    errors.append(f"{tag}: ok=true but plan is missing used/limit")
        elif isinstance(snap.get("legacyModels"), dict) and snap["legacyModels"]:
            pass
        else:
            errors.append(f"{tag}: ok=true but neither plan nor legacyModels")
        blob = json.dumps(snap)
        if "eyJ" in blob or ("::" in blob and "user_" in blob):
            errors.append(f"{tag}: snapshot looks like it contains a session token")


def check_opencode(data, errors):
    if not isinstance(data, dict) or "snapshots" not in data:
        errors.append("opencode: top level must be an object with a 'snapshots' list")
        return
    check_dates(data["snapshots"], errors, "opencode")


def validate_file(path, checker, errors):
    try:
        data = load_json(path)
    except FileNotFoundError:
        errors.append(f"{path} missing")
        return
    except json.JSONDecodeError as exc:
        errors.append(f"{path} is not valid JSON: {exc}")
        return
    checker(data, errors)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--also",
        action="append",
        default=[],
        choices=("cursor", "opencode"),
        help="also validate a local collector file",
    )
    args = parser.parse_args(argv)
    errors = []
    validate_file(os.path.join(ROOT, "data", "usage.json"), check_usage, errors)
    extra = {
        "cursor": (os.path.join(ROOT, "data", "cursor.json"), check_cursor),
        "opencode": (os.path.join(ROOT, "data", "opencode.json"), check_opencode),
    }
    for name in args.also:
        path, checker = extra[name]
        validate_file(path, checker, errors)

    if errors:
        print("VALIDATION FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("data files OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
