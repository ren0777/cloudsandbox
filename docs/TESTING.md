# Testing CloudLabs

| Suite | Where | Runs against | Command |
|---|---|---|---|
| Runner unit + Docker integration | `services/runner/tests` | real Docker | see below |
| API unit/integration (FakeRunner = real Moto subprocess per sandbox) | `services/api/tests/test_*.py` | Postgres `cloudlabs_test` | `scripts/test-api.sh` |
| API real-runtime integration (`-m docker`) | `services/api/tests/test_integration_docker.py` | real runner + Docker | included in `scripts/test-api.sh` |
| Lab packs | `python -m app.labtest /labs/<id>` | real runner | see LAB-AUTHORING.md |
| End-to-end (Playwright) | `apps/web/e2e` | full compose stack in a browser | `cd apps/web && npx playwright test` |

```bash
# runner (needs the Docker socket)
MSYS_NO_PATHCONV=1 docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  -e RUNNER_SECRET=x cloudlabs/runner:dev python -m pytest -q

# API (starts postgres + runner + the api-test container labelled for env "test")
./scripts/test-api.sh                  # everything
./scripts/test-api.sh -m "not docker"  # fast subset

# E2E (the stack must be up: scripts/up.sh). It resets demo data itself.
cd apps/web && npx playwright install chromium && npx playwright test
```

## Engines
Real-runtime tests are parametrized over every emulator engine (`floci`, the default, and `moto`, the
regression backend): runner hardening and isolation, S3 and DynamoDB contract tests, labtest, the GUI+CLI
journey with the session freeze, and terminal ticket rules. Run the browser E2E on a specific engine with
`CL_DEFAULT_EMULATOR=moto scripts/up.sh` before `npx playwright test`.

## What is covered (PLAN "Slice 1 is done when")
- **Schema / loader / capabilities:** unknown schema version, extra keys, unknown/stub checks, unsupported
  operations, bad params, template errors, missing setup script, deterministic bundles.
- **Grading:** every S3 check, 0 / partial / 100, weights, proportional scoring, determinism, and the
  student view hiding expected/actual and hidden checks.
- **Auth/authz:** cookies, refresh rotation + reuse detection, CSRF, rate limit, demo accounts refused
  outside demo mode, the role matrix, 404-not-403, and **route coverage** (every route has `Authz`).
- **Architecture:** the API never imports Docker; the HMAC known-answer vector matches the runner.
- **Sessions:** 20 parallel Starts → 1 session; configurable active limit; capacity full → 503 and nothing
  created; runtime unavailable; provisioning failure frees the slot; console; progress rate limit;
  ownership 404s.
- **Submit:** parallel submits → 1 attempt; Idempotency-Key replay / reuse / required; console frozen while
  submitting; attempts exhausted; closed window; reset (new baseline, no attempt); stop.
- **State machine:** all 81 (from, to) pairs; CAS loses cleanly on a race.
- **Immutability:** UPDATE/DELETE rejected on append-only tables for the app role and (by trigger) the
  owner; regrade adds a row and the original stays.
- **Expiry:** TTL with no change → `counts=false`; idle with changes → counts; non-READY never touched.
- **Reconciler:** every row of the PLAN §3 table, including orphans, leftovers, other environments left
  alone, and a reset racing the lost-sandbox check.
- **Real runtime:** the GUI+CLI journey over the real WebSocket terminal; terminal ticket rules (origin,
  single use, expiry, max 2, close reasons); no private files in the sandbox; no egress; cleanup;
  labtest; Moto contract for every declared supported operation.
- **Phase 5 (instructor/admin):** `test_courses_roster.py` (row-level CSV validation, preview token,
  all-or-nothing commit, forced password change, course scoping, append-only audit), `test_assignments_manage.py`,
  `test_gradebook.py` (statuses, best/latest, regrades, extensions, CSV fields, formula neutralisation),
  `test_live.py` (stored progress, extend caps, terminate grade/discard), `test_admin_manage.py` (users, staff,
  sessions, audit paging and scoping). E2E `instructor-roster.spec.ts` and `instructor-ops.spec.ts`.
- **Phase 6:** `test_diagram.py`, `test_breakfix.py` (break-fix grading, negative checks, labtest on both
  default engines, setup/Reset/baseline through a real session), `test_cost.py`, `test_gamification.py`. E2E
  `architecture.spec.ts` and `breakfix-fun.spec.ts`.
- **Phase 7:** `test_fleet.py` (heartbeats, registration, scheduler: spreading, drain, stale heartbeats, engine
  compatibility, 12 concurrent Starts with heartbeats; no migration; runner lost; CLI audit; plus a **real
  two-runner test** with runner2 in gateway mode covering console, grading, terminal WebSocket, token rejection and
  cleanup). Runner tests cover capacity/stats scoping and the reattach/destroy race. The class-scale load test is
  `python -m app.loadtest` (docs/LOADTEST.md); it isn't part of CI because it needs minutes and a quiet machine.
- **Phase 8 (Lab Builder):** `test_lab_builder.py` (draft CRUD + ownership 404s, row-level errors, YAML
  round-trip, clone keeps private files, redacted preview, export/import + unsafe tar refusals, visibility and
  sharing, assignment refusal for invisible labs, demo reset) and `test_lab_builder_publish.py` (test run +
  publish gate on the FakeRunner, interrupted runs and the test cap, reconciler keeps in-flight test
  sandboxes, immutability, plus a docker-marked real-sandbox clone of Mission 1). E2E `lab-builder.spec.ts`.
- **Phase 9 (authoring):** `test_lab_builder.py` also covers the template catalogue (availability against the
  installed built-in packs) and starting a draft from a template (fresh id/version/title, files carried,
  break-fix setup read-only, audit, 404/403). E2E `lab-builder.spec.ts` has a template-gallery test.
- **Phase 9 (break actions, M41):** `test_breakfix_actions.py` covers the typed registry, compiler
  determinism and shell quoting, the schema rules (`break_actions` XOR setup, baseline below full marks),
  import-time validation (unknown type, parameters, service, engine capabilities), the compiled setup bundle
  and the baseline/expected-score contract. `test_lab_builder.py` covers the break-action catalogue endpoint,
  saving a break-fix draft and the Broken State Summary. `labtest` adds a `reset` scenario for break-fix
  packs; the real-runtime check (baseline 0 and 40 → solution 100 → Reset reproduces the baseline) is verified
  on moto and floci. E2E `lab-builder.spec.ts` has a Starting-state test.
- **E2E:** the DEMO.md flow in Chromium, including `docker ps` cleanup checks. It writes screenshots to
  `docs/screenshots/`.

Logging runs in strict mode during tests: any event name outside the fixed set fails the test.
