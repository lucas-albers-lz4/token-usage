# token-usage

Daily credit/spend snapshots. Keys never go in the repo. Collectors write
`data/*.json`; GitHub Pages serves `index.html`.

## Entry point

`./scripts/token_usage.sh` (doctor / collect / push / install / status /
uninstall / test). Do not invent a second wrapper. `push_data.sh` is the git
half; call it via `token_usage.sh push`. Host CI gate:
`python3 scripts/validate_data.py` (`--also cursor` when needed).

## Hazards

- Stdlib Python 3 only. No pip deps, no Node build, no CDN in `index.html`.
- Never print, log, or commit session JWTs, API keys, or
  `~/.config/token-usage/env` (`chmod 600`, not git).
- Cursor token: `ItemTable.cursorAuth/accessToken` in Cursor `state.vscdb`.
  Primary API: `GET https://cursor.com/api/usage-summary`. `/api/usage?user=`
  is vestigial — fallback only.
- Snapshot: compact `plan` / `onDemand` only — never dump the raw dashboard
  payload, never write the JWT or `userId`. Dashboard card reads `plan`, not
  `usage.gpt-4`.
- Push uses SSH `origin`. Optional PAT via `GIT_ASKPASS`, never
  `https://token@...`.
- Launchd label `com.lucasalbers.token-usage.cursor` — plist under
  `~/Library/LaunchAgents/`, logs `~/Library/Logs/token-usage-cursor.log`
  (not in this repo). After `install`, first publish still needs
  `./scripts/token_usage.sh push cursor`.
- Provider HTTP failure → `ok: false`. Exit 1 only when there is no token /
  no keys.
- `data/cursor.json` commits are the pipeline, not leftover debug.

## PR merge gates

Before merging **code** PRs (not data-only snapshot commits): Luna, Bugbot,
security review. Fix or document false positives. Do not merge with an
unresolved blocker.
