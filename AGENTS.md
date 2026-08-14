# token-usage

Daily credit/spend snapshots. Keys never go in the repo. Collectors write
`data/*.json`; GitHub Pages serves `index.html`.

## Commands

```bash
./scripts/token_usage.sh doctor cursor     # token, JWT expiry, usage-summary, git remote
./scripts/token_usage.sh collect cursor    # write data/cursor.json only
./scripts/token_usage.sh push cursor       # collect + validate + commit + git push
./scripts/token_usage.sh install cursor    # macOS LaunchAgent, daily 07:00 local
./scripts/token_usage.sh status cursor
./scripts/token_usage.sh uninstall cursor
./scripts/token_usage.sh test              # stdlib unittest for cookie/summary helpers
python3 scripts/validate_data.py           # CI gate: data/usage.json
python3 scripts/validate_data.py --also cursor
```

Do not invent a second entry point. `token_usage.sh` wraps collect / validate /
launchd. `push_data.sh` is the git half; call it via `token_usage.sh push`.

## Cursor collector (this Mac)

- Cursor must stay logged in. Token is `ItemTable.cursorAuth/accessToken` in
  `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb`.
- Primary API: `GET https://cursor.com/api/usage-summary` (undocumented).
  `/api/usage?user=` is vestigial (often empty `gpt-4` counters) — fallback only.
- Snapshot: `{date, ok, userId, membershipType, billingCycleStart,
  billingCycleEnd, plan, onDemand}`. Compact `plan`/`onDemand` only — never dump
  the raw dashboard payload, never write the JWT.
- Push uses SSH `origin` on this clone. PAT is optional:
  `~/.config/token-usage/env` with `CURSOR_GITHUB_TOKEN` (`chmod 600`, not git).
- Launchd label: `com.lucasalbers.token-usage.cursor`. Plist lives under
  `~/Library/LaunchAgents/` (not in this repo). Logs:
  `~/Library/Logs/token-usage-cursor.log`.
- After `install`, daily push is automatic. First publish still needs
  `./scripts/token_usage.sh push cursor`.

## Rules

- Stdlib Python 3 only. No pip deps, no Node build, no CDN in `index.html`.
- Never print, log, or commit session JWTs, API keys, or the env file.
- Provider HTTP failure → `ok: false` snapshot. Exit 1 only when there is no
  token / no keys.
- Dashboard: `index.html` + `assets/js/app.js` only. Cursor card reads `plan`,
  not `usage.gpt-4`.
- `data/cursor.json` is generated output; committing numbers is the pipeline.
  Do not treat those commits as leftover debug.

## PR merge gates

Before merging code PRs (not data-only snapshot commits):

1. Luna (`gpt-5.6-luna-medium`) — contract / drift review
2. Bugbot — bugs in the diff
3. Security review — secrets, token handling, public Pages data

Fix or document false positives. Do not merge with an unresolved blocker.
Do not re-run Bugbot in a loop unless the user asks after a substantive fix.
