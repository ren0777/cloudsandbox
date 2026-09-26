# CloudLabs — working rules

**Source of truth:** `docs/PLAN.md` (scope, architecture, hardening decisions §1–§18, acceptance criteria).
Re-read the relevant section of `docs/PLAN.md` before any architectural decision. Progress and
decisions taken during implementation are recorded in `docs/STATUS.md`.

## Execution mode
- Work autonomously through the slice-1 build order in `docs/PLAN.md`: implement → test → fix → re-run
  until green → update `docs/STATUS.md` → next milestone. No "should I continue?" check-ins.
- Stop and ask only for: a genuinely missing product decision, destructive/irreversible action outside
  the project, credentials/paid services/permissions, repo state conflicting with the plan, or a major
  architectural flaw.
- No scope expansion. IAM/EC2/Lambda/DynamoDB, advanced gamification, multi-server scheduling stay stubbed.
- "Done" = verified by tests (unit + integration + E2E), not "it compiles".

## Invariants that must never be broken
- The API (`services/api`) never imports the Docker SDK. Only `services/runner` talks to Docker.
  (`tests/test_architecture.py` enforces this.)
- Session `state` is written only through `app/sessions/state.py::transition` (CAS on state+version).
- `attempts`, `grading_evidence`, `session_events`, `task_results` are append-only (DB triggers).
- Grading is a pure function of `(lab_version, variables, evidence)`; no live calls while scoring.
- Private lab bundles (`solution.sh`, `partial.sh`, hidden checks, answers) never reach student
  sandboxes or student API responses.
- Log event names come only from the fixed set in `app/obs/events.py` (PLAN §14).

## Layout
- `services/api` — FastAPI control plane (Python 3.12, SQLAlchemy 2 async, Alembic, pytest)
- `services/runner` — Runner Agent (FastAPI + docker SDK), HMAC-authenticated typed ops only
- `images/emulator`, `images/terminal` — sandbox images
- `labs/<id>/` — lab packs (`lab.yaml` + `private/`)
- `apps/web` — Next.js frontend
- `infra/docker-compose.yml` — the whole stack; `scripts/` — dev/demo helpers

## Commands
- Stack: `docker compose -f infra/docker-compose.yml up -d --build`
- API tests: `scripts/test-api.sh` (runs pytest inside the test container on the Docker network)
- Lab test: `docker compose -f infra/docker-compose.yml exec api python -m app.labtest /labs/s3-basics`
- Demo reset: `scripts/demo-reset.sh` / `scripts/demo-reset.ps1`

## Conventions
- Python: type hints, `ruff` style, small modules, errors raised as `ApiError(code, message, status)`.
- Error body shape: `{"error": {"code", "message", "request_id"}}`.
- TypeScript: strict mode, fetch via `apps/web/lib/api.ts` only.
