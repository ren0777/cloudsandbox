#!/usr/bin/env bash
# Run the API test suite inside the api-test container (attached to test sandboxes by the runner).
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose -f infra/docker-compose.yml --profile test up -d postgres runner api-test
MSYS_NO_PATHCONV=1 docker compose -f infra/docker-compose.yml exec -T api-test python -m app.migrate
MSYS_NO_PATHCONV=1 docker compose -f infra/docker-compose.yml exec -T api-test python -m pytest -q "$@"
