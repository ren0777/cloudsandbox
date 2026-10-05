#!/usr/bin/env bash
# Run the API test suite inside the api-test container (attached to test sandboxes by the runner).
#
# Isolation from another checkout on the same machine (own project, ports, runners and test DB):
#   CL_COMPOSE_PROJECT=cloudlabs-authoring \
#   CL_COMPOSE_EXTRA_FILE=infra/docker-compose.authoring.yml scripts/test-api.sh
set -euo pipefail
cd "$(dirname "$0")/.."
COMPOSE=(docker compose)
[ -n "${CL_COMPOSE_PROJECT:-}" ] && COMPOSE+=(-p "$CL_COMPOSE_PROJECT")
COMPOSE+=(-f infra/docker-compose.yml)
[ -n "${CL_COMPOSE_EXTRA_FILE:-}" ] && COMPOSE+=(-f "$CL_COMPOSE_EXTRA_FILE")
"${COMPOSE[@]}" --profile test build api-test   # Dockerfile `test` stage: requirements-dev included
"${COMPOSE[@]}" --profile test up -d postgres runner api-test
MSYS_NO_PATHCONV=1 "${COMPOSE[@]}" exec -T api-test python -m app.migrate
MSYS_NO_PATHCONV=1 "${COMPOSE[@]}" exec -T api-test python -m pytest -q "$@"
