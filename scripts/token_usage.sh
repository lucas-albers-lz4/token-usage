#!/usr/bin/env bash
# One entry point for local collectors (Cursor today; opencode later).
#
#   ./scripts/token_usage.sh doctor [cursor]
#   ./scripts/token_usage.sh collect [cursor]   # write JSON, no git
#   ./scripts/token_usage.sh push [cursor]      # collect + commit + push
#   ./scripts/token_usage.sh install [cursor]   # macOS launchd, daily 07:00 local
#   ./scripts/token_usage.sh uninstall [cursor]
#   ./scripts/token_usage.sh status [cursor]
#   ./scripts/token_usage.sh test
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ENV_FILE="${TOKEN_USAGE_ENV:-$HOME/.config/token-usage/env}"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
  mode="$(stat -f '%Lp' "$ENV_FILE" 2>/dev/null || stat -c '%a' "$ENV_FILE" 2>/dev/null || echo "")"
  case "$mode" in
    600|400) ;;
    *) echo "warning: $ENV_FILE mode is ${mode:-unknown}; chmod 600 recommended" >&2 ;;
  esac
fi

cmd="${1:-}"
target="${2:-cursor}"
case "$target" in
  cursor|opencode) ;;
  *)
    echo "unknown target: $target (use cursor|opencode)" >&2
    exit 2
    ;;
esac
label="com.lucasalbers.token-usage.${target}"
plist="$HOME/Library/LaunchAgents/${label}.plist"
log_out="$HOME/Library/Logs/token-usage-${target}.log"
log_err="$HOME/Library/Logs/token-usage-${target}.err.log"

usage() {
  sed -n '2,12p' "$0" | sed 's/^# \?//'
  exit 2
}

need_macos() {
  if [ "$(uname -s)" != "Darwin" ]; then
    echo "install/uninstall/status use launchd and only run on macOS" >&2
    exit 2
  fi
}

write_plist() {
  mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
  cat >"$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${label}</string>
  <key>WorkingDirectory</key>
  <string>${ROOT}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${ROOT}/scripts/token_usage.sh</string>
    <string>push</string>
    <string>${target}</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>7</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${log_out}</string>
  <key>StandardErrorPath</key>
  <string>${log_err}</string>
  <key>Nice</key>
  <integer>10</integer>
</dict>
</plist>
EOF
}

uid="$(id -u)"

case "$cmd" in
  doctor)
    if [ "$target" != cursor ]; then
      echo "doctor is implemented for cursor only" >&2
      exit 2
    fi
    python3 "$ROOT/scripts/collect_${target}.py" --doctor
    echo "git remote: $(git remote get-url origin 2>/dev/null || echo none)"
    echo "env file: $([ -f "$ENV_FILE" ] && echo "$ENV_FILE" || echo "none (SSH origin is enough on this machine)")"
    ;;
  collect)
    python3 "$ROOT/scripts/collect_${target}.py"
    python3 "$ROOT/scripts/validate_data.py" --also "${target}"
    ;;
  push)
    exec "$ROOT/scripts/push_data.sh" "$target"
    ;;
  install)
    need_macos
    write_plist
    launchctl bootout "gui/${uid}/${label}" 2>/dev/null || true
    launchctl bootstrap "gui/${uid}" "$plist"
    launchctl enable "gui/${uid}/${label}"
    echo "installed ${label} (daily 07:00 local)"
    echo "plist: $plist"
    echo "logs:  $log_out"
    echo "run now: ./scripts/token_usage.sh push ${target}"
    ;;
  uninstall)
    need_macos
    launchctl bootout "gui/${uid}/${label}" 2>/dev/null || true
    rm -f "$plist"
    echo "removed ${label}"
    ;;
  status)
    need_macos
    if [ -f "$plist" ]; then
      echo "plist: $plist"
      launchctl print "gui/${uid}/${label}" 2>/dev/null | grep -E 'state =|pid =|runs =|last exit code' || echo "loaded: no (run install)"
    else
      echo "not installed (no $plist)"
    fi
    if [ -f "$log_out" ]; then
      echo "--- last log ---"
      tail -n 20 "$log_out"
    fi
    if [ -f "$log_err" ] && [ -s "$log_err" ]; then
      echo "--- last err ---"
      tail -n 20 "$log_err"
    fi
    ;;
  test)
    python3 -m unittest discover -s "$ROOT/scripts" -p 'test_*.py' -v
    ;;
  *)
    usage
    ;;
esac
