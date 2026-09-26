#!/usr/bin/env bash
# Build sandbox images + the stack, start it, wait for health.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose -f infra/docker-compose.yml --profile images build emulator-image emulator-floci-image emulator-ministack-image terminal-image
docker compose -f infra/docker-compose.yml up -d --build
echo "waiting for http://localhost:3000/healthz ..."
for i in $(seq 1 90); do
  if curl -fsS http://localhost:3000/healthz >/dev/null 2>&1; then echo "CloudLabs is up: http://localhost:3000"; exit 0; fi
  sleep 2
done
echo "stack did not become healthy; see: docker compose -f infra/docker-compose.yml logs api runner" >&2
exit 1
