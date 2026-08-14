#!/usr/bin/env bash
# Collect + commit + push one provider's snapshot from the machine that owns
# the local data (Cursor state, opencode DB). Run daily via cron / Task Scheduler.
#
# Usage:
#   ./scripts/push_data.sh cursor     # on a machine with Cursor installed
#   ./scripts/push_data.sh opencode   # on the machine that runs opencode
#
# Auth for the push: SSH `origin` by default. Optional PAT via
# CURSOR_GITHUB_TOKEN / OPENCODE_GITHUB_TOKEN is passed to Git through
# GIT_ASKPASS (scripts/git_askpass.sh), never embedded in the remote URL.
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
cd "$(dirname "$0")/.."

ENV_FILE="${TOKEN_USAGE_ENV:-$HOME/.config/token-usage/env}"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

name="${1:?usage: push_data.sh cursor|opencode}"
case "$name" in
  cursor)
    file="data/cursor.json"
    collect="python3 scripts/collect_cursor.py"
    token_var="CURSOR_GITHUB_TOKEN"
    remote_var="CURSOR_REPO_REMOTE"
    ;;
  opencode)
    file="data/opencode.json"
    collect="python3 scripts/collect_opencode.py"
    token_var="OPENCODE_GITHUB_TOKEN"
    remote_var="OPENCODE_REPO_REMOTE"
    ;;
  *)
    echo "unknown target: $name (use cursor|opencode)" >&2
    exit 2
    ;;
esac

branch="$(git symbolic-ref --short HEAD 2>/dev/null || echo main)"

if [ -n "${!token_var:-}" ]; then
  repo="${!remote_var:-lucas-albers-lz4/token-usage}"
  export GIT_ASKPASS="$(pwd)/scripts/git_askpass.sh"
  export GIT_TERMINAL_PROMPT=0
  export TOKEN_USAGE_GIT_PASSWORD="${!token_var}"
  push_url="https://github.com/${repo}.git"
else
  push_url="origin"
fi

$collect
python3 scripts/validate_data.py --also "$name"

git add "$file"
if git diff --cached --quiet; then
  echo "No $name change to commit"
  exit 0
fi

git config user.name "Lucas Albers"
git config user.email "lucas.b.albers@gmail.com"
git commit -m "data: $name snapshot $(date -u +%F)"
git pull --rebase --autostash "$push_url" "$branch"
git push "$push_url" HEAD:"$branch"
echo "Pushed $name snapshot"
