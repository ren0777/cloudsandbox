# Testing CloudLabs

| Suite | Where | Runs against | Command |
|---|---|---|---|
| Runner unit + Docker integration | `services/runner/tests` | real Docker | see below |
| API unit/integration (FakeRunner = real Moto subprocess per sandbox) | `services/api/tests/test_*.py` | Postgres `cloudlabs_test` | `scripts/test-api.sh` |
| API real-runtime integration (`-m docker`) | `services/api/tests/test_integration_docker.py` | real runner + Docker | included in `scripts/test-api.sh` |
| Lab packs | `python -m app.labtest /labs/<id>` | real runner | see LAB-AUTHORING.md |
| End-to-end (Playwright) | `apps/web/e2e` | full compose stack in a browser | `cd apps/web && npx playwright test` |

```bash
# runner (needs the Docker socket; RUNNER_SECRET must be >= 32 chars, see config validation)
MSYS_NO_PATHCONV=1 docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  -e RUNNER_SECRET=runner-pytest-secret-0123456789abcdef cloudlabs/runner:dev python -m pytest -q

# API (starts postgres + runner + the api-test container labelled for env "test")
./scripts/test-api.sh                  # everything
./scripts/test-api.sh -m "not docker"  # fast subset

# E2E (the stack must be up: scripts/up.sh). It resets demo data itself.
cd apps/web && npx playwright install chromium && npx playwright test

# A second (or third) checkout running beside the first one — its own project, ports, runner ids,
# sandbox env, images and test database, so two suites can never truncate each other's tables:
CL_COMPOSE_PROJECT=cloudlabs-m45 CL_COMPOSE_EXTRA_FILE=infra/dev-isolation/docker-compose.m45.yml ./scripts/test-api.sh

# …and the browser E2E for that checkout, which needs its runner id and URL (see STATUS D47/D53):
CLOUDLABS_URL=http://localhost:4444 CLOUDLABS_RUNNER_ID=runner-m45 \
  CL_COMPOSE_PROJECT=cloudlabs-m45 CL_COMPOSE_EXTRA_FILE=infra/dev-isolation/docker-compose.m45.yml \
  npx playwright test
```

(The gateway port lives in `infra/dev-isolation/docker-compose.m45.yml`. It is **4444** because Windows had excluded
3200 and 3900 from the dynamic range after a restart, and Docker could not bind them — "forbidden by its
access permissions". If a port refuses to bind, pick another and update this file and `CL_ALLOWED_ORIGINS`
in the override together.)

Keep `http://localhost:3000` in the override's `CL_ALLOWED_ORIGINS` even though this checkout serves on
another port: `tests/test_integration_docker.py` uses `http://localhost:3000` as the WebSocket **Origin**
for the terminal ticket rules, so dropping it fails the whole Docker-marked journey with
`terminal.ticket.rejected / origin_not_allowed` (STATUS **D53**).

If the E2E fails with `preview_unavailable: runner is at capacity` while `docker ps` shows no sandboxes,
check for orphan networks before believing it is a product bug: `docker network ls | grep cl-sbx`, then
`docker network disconnect -f <network> <container>` and `docker network rm` (STATUS **D53**).

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
  outside demo mode, the role matrix, 404-not-403, and **route coverage** in
  `tests/test_authz_coverage.py` (every route carries `Authz` or is on the reviewed public allowlist; every
  action is in the matrix; a non-vacuity self-test; every protected route answers 401 to an anonymous
  caller; cross-resource access stays 404). Run it alone with `./scripts/test-api.sh tests/test_authz_coverage.py`.
- **Lab Builder authoring (M46/M47):** `tests/test_lab_builder_autosave.py` covers the content revision a
  save is based on (stale refused, validation never invalidates it, unchanged content keeps it, invalid
  partial content saves and stays protected, YAML guarded); `tests/test_preview_check.py` runs one check
  against a real preview sandbox and asserts **parity with `grade()`** plus the absence of any attempt,
  grade, evidence or badge row. Browser: `e2e/lab-builder-autosave.spec.ts` (autosave, undo/redo, one failed
  PUT then a manual retry, stale reload) and `e2e/lab-builder-check-run.spec.ts` (run → fail → make it
  true in the console → run → pass).
- **Attempt diff and analytics (M48/M49):** `tests/test_attempt_diff.py` classifies every change (fixed,
  regressed, unchanged, added, removed), proves the student copy never carries `expected`/`actual`, steps
  over non-counting attempts and follows a regrade; `tests/test_course_analytics.py` covers the empty state,
  the metrics, interruptions kept apart from student results, ownership (404/403/200) and a **fixed query
  count** that must not grow with the data. Browser: `e2e/instructor-analytics.spec.ts` (metrics, assignment
  table, honest empty states, and a course with no labs).
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
- **Phase 9 (preview + readiness, M42):** `test_lab_preview.py` covers the preview lifecycle (start, console
  calls through the student routes, terminal ticket, reset, stop), ownership (404 for another instructor,
  404 for a student on console/terminal, 403 on `lab_manage` routes), the reconciler keeping a running
  preview and expiring an idle one, and — docker-marked — a real break-fix preview where the baseline scores
  0, Reset reproduces it, the console and terminal work, and no session/attempt/grade exists. Readiness tests
  in `test_lab_builder_publish.py` cover the checklist mirroring the gate, the guided-lab N/A reset row, and
  unsupported engines blocking test/publish. E2E `lab-builder.spec.ts` walks the preview and the checklist.
- **Phase 9 (M44, richer labs):** `test_lambda.py::test_lambda_dynamodb_labtest_on_ministack` runs Mission 7
  end to end (0 / 55 / 100) on a real MiniStack sandbox, where the probe invocation writes the DynamoDB row
  the hidden item check then reads. `test_dynamodb.py`'s contract test now runs on **all three engines**, so
  every DynamoDB operation declared for MiniStack is exercised for real.
- **Phase 9 (M44, VPC / SQS / SNS):** `test_vpc.py`, `test_sqs.py` and `test_sns.py` hold the per-engine
  contract tests (real sandboxes through the runner) and — docker-marked — the labtest of each pair of packs on
  moto and floci (`vpc-basics` 0/50/100 and `vpc-breakfix` 25/65/100; `sqs-basics` 0/35/100 and
  `sqs-breakfix` 20/70/100; `sns-basics` 0/45/100 and `sns-breakfix` 20/70/100; each break-fix pack also
  proves Reset reproduces its baseline). `test_vpc_console.py`, `test_sqs_console.py` and
  `test_sns_console.py` cover grading, the console journeys and the break-fix states. Browser:
  `e2e/vpc.spec.ts`, `e2e/sqs.spec.ts` and `e2e/sns.spec.ts` (Missions 8–13 built or repaired in the console).
- **E2E:** the DEMO.md flow in Chromium, including `docker ps` cleanup checks. It writes screenshots to
  `docs/screenshots/`.

Logging runs in strict mode during tests: any event name outside the fixed set fails the test.
