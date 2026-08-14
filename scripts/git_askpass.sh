#!/usr/bin/env bash
# GIT_ASKPASS helper: username/password from env, never from argv/URL.
# Git calls this with a prompt; we only print credentials to stdout.
set -euo pipefail
case "${1:-}" in
  *Username*|*username*) printf '%s\n' "x-access-token" ;;
  *) printf '%s\n' "${TOKEN_USAGE_GIT_PASSWORD:-}" ;;
esac
