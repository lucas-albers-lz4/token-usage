# token-usage

Daily snapshots of LLM provider credits & spend on one static page — for the
providers this account actually uses: **OpenRouter**, **DeepSeek**,
**Cursor**, and **OpenCode** (via the local opencode ledger).

Modeled on the happycow pipeline: scheduled collectors write generated JSON,
the JSON is committed, and GitHub Pages redeploys on every commit. The page is
plain HTML + one JS file; nothing runs client-side against any API.

## What each provider reports

| Provider | What's tracked | How | Authority |
|---|---|---|---|
| OpenRouter | credits remaining / used / total, per-key cap | `GET /api/v1/auth/key` (official) | GH Action, daily cron |
| DeepSeek | balance (total / granted / topped-up, CNY) | `GET /user/balance` (official) | GH Action, daily cron |
| Cursor | usage per model (requests used/limit), billing period | undocumented `GET /api/usage?user=` via session token read from local Cursor state | local cron on a Cursor machine |
| OpenCode | calls, in/out/reasoning/cache tokens, cost, per provider+model | `~/.local/share/opencode/opencode.db` (message ledger) | local cron on the opencode machine |

API keys live only in GitHub Actions secrets or in local env — **never** in the
repo. The committed data files contain numbers only.

## Pipeline

```
GitHub Actions (daily 03:17 UTC + manual)          Local machines (daily cron)
┌──────────────────────────────────────┐           ┌──────────────────────────────────────┐
│ scripts/collect_usage.py             │           │ scripts/collect_cursor.py            │
│   → OpenRouter /auth/key             │           │   → token from Cursor state.vscdb    │
│   → DeepSeek /user/balance           │           │   → GET cursor.com/api/usage         │
│ scripts/validate_data.py (gate)      │           │ scripts/collect_opencode.py          │
│ commit data/usage.json → push        │           │   → incremental read of opencode.db  │
└──────────────────────────────────────┘           │ commit data/cursor.json /            │
                                                   │        data/opencode.json → push     │
                                                   └──────────────────────────────────────┘
        both push to main → GitHub Pages redeploys → index.html fetches the 3 JSON files
```

`scripts/push_data.sh <cursor|opencode>` collects **and** commits **and** pushes
from the machine that owns the local data — that's the "post it back" step.

## Layout

```
.github/workflows/collect.yml   scheduled collector (OpenRouter + DeepSeek)
scripts/collect_usage.py        GH-Action collector (stdlib only)
scripts/validate_data.py        schema gate for data/usage.json (CI)
scripts/collect_cursor.py       Cursor snapshot (run on a Cursor machine)
scripts/collect_opencode.py     opencode DB snapshot (run on the opencode machine)
scripts/push_data.sh            collect + commit + push, per local data source
data/usage.json                 committed output (OpenRouter + DeepSeek)
data/cursor.json                committed output (Cursor)
data/opencode.json              committed output (OpenCode)
index.html + assets/            static page, renders the three files
```

## Setup (one time)

1. **Create the repo** from this tree and push it:
   ```bash
   git init && git add -A && git commit -m "init"
   gh repo create token-usage --public --source . --push
   ```
2. **Add secrets** — repo Settings → Secrets and variables → Actions:
   `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`.
3. **Enable Pages** — Settings → Pages → Source: *Deploy from a branch* →
   `main` / `/ (root)` → Save.
4. **Seed** — Actions → *Collect usage* → Run workflow (first run fails until
   the secrets exist — expected).
5. Open `https://<owner>.github.io/token-usage/`.

## Cursor machine (the "post it back" side)

On either machine that runs Cursor: clone the repo, then run daily:

```bash
./scripts/push_data.sh cursor
```

The script reads the session token from Cursor's local `state.vscdb`
(`~/.config/Cursor/...` on Linux, `~/Library/Application Support/Cursor/...`
on macOS, `%APPDATA%\Cursor\...` on Windows), calls Cursor's undocumented
usage endpoint, commits `data/cursor.json`, and pushes.

Push auth: a **fine-grained PAT** (Contents: read/write on this repo) as
`CURSOR_GITHUB_TOKEN` in the environment (or `CURSOR_REPO_REMOTE` to point at
a fork). Without a token it pushes to the existing `origin`.

Cron examples (adjust paths):

```bash
# Linux/macOS — every day at 07:00
7 7 * * * cd /path/to/token-usage && CURSOR_GITHUB_TOKEN=ghp_... ./scripts/push_data.sh cursor
# Windows Task Scheduler: schtasks /create /tn cursor-usage /tr "cmd /c cd /d C:\path\token-usage && set CURSOR_GITHUB_TOKEN=ghp_...&& scripts\push_data.sh cursor" /sc daily /st 07:00
```

Notes: the token comes straight from the local Cursor install, so it stays
fresh as long as Cursor is logged in on that machine; the endpoint is
undocumented and can drift — the snapshot records the error instead of dying.

## OpenCode machine (this box)

OpenCode runs only on this machine via Hermes, so:

```bash
./scripts/push_data.sh opencode
```

reads `~/.local/share/opencode/opencode.db` (the per-call message ledger),
aggregates new assistant calls incrementally (resume marker stored in
`data/opencode.json`), and pushes `data/opencode.json`. Needs
`OPENCODE_GITHUB_TOKEN` (same fine-grained PAT recipe as Cursor).

## Local testing (no keys needed)

Both API collectors accept base-URL overrides, so point them at a mock:

```bash
python3 - <<'EOF' &   # tiny mock server
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = (b'{"data":{"label":"mock","usage":{"total_credits":10,"total_usage":3.25,"remaining":6.75}}}'
                if self.path.startswith("/api/v1/auth/key") else
                b'{"is_available":true,"balance_infos":[{"currency":"CNY","total_balance":"23.45","granted_balance":"0.00","topped_up_balance":"23.45"}]}')
        self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass
HTTPServer(("127.0.0.1", 8099), H).serve_forever()
EOF
OPENROUTER_API_URL=http://127.0.0.1:8099 DEEPSEEK_API_URL=http://127.0.0.1:8099 \
  OPENROUTER_API_KEY=x DEEPSEEK_API_KEY=x python3 scripts/collect_usage.py
python3 scripts/validate_data.py
```

For Cursor: `CURSOR_TOKEN=user_mock%3A%3Aabc CURSOR_API_URL=http://127.0.0.1:8099 python3 scripts/collect_cursor.py`
(the mock above doesn't serve `/usage` — add it). For opencode:
`OPENCODE_DB=/path/to/any/opencode.db python3 scripts/collect_opencode.py`.

## Extending

New provider = a collector that appends `{date, ...}` snapshots to its own
JSON file + one `render*()` card in `assets/js/app.js` + a `push_data.sh`
case if the data is local-only. `data/usage.json` stays the CI-gated file
(the Action validates it before committing); local files are written by
trusted local scripts.

## Troubleshooting

- **First workflow run fails** — expected until the two secrets exist.
- **Cursor shows an error snapshot** — endpoint drift or expired session;
  re-login to Cursor on that machine so `state.vscdb` refreshes the token.
- **opencode totals stop growing after a DB migration** — opencode changed its
  storage; delete `data/opencode.json` once to re-seed from the new ledger.
- **`git push` from the Action fails with non-fast-forward** — the workflow
  pulls with `--rebase` first; re-run and it resolves itself.

## License

MIT © 2026 Lucas Albers
