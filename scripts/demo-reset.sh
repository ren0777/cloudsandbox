#!/usr/bin/env bash
# One-command demo reset (PLAN §16). Requires the stack to be running (scripts/up.sh).
set -euo pipefail
cd "$(dirname "$0")/.."
MSYS_NO_PATHCONV=1 docker compose -f infra/docker-compose.yml exec -T api python -m app.demo reset
