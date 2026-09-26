# CloudLabs — implementation status (Vertical Slice 1)

Legend: ☐ todo · ◐ in progress · ☑ done + verified (evidence noted)

| # | Milestone | State | Verification evidence |
|---|---|---|---|
| 0 | Docs: PLAN / STATUS / CLAUDE.md | ☑ | files created |
| 1 | Compose + DB models/migrations + auth | ☑ | migration 0001 (20 tables, append-only triggers + grants); `tests/test_auth_and_policy.py` 13 passed |
| 2 | Sandbox images (emulator, terminal) | ☑ | non-root, read-only rootfs, no egress verified (`services/runner/tests`) |
| 3 | Runner agent + DockerDriver + HMAC; session API + state machine + reconciler/janitor | ☑ | runner 9 passed (real Docker); `test_sessions.py` 17 + `test_state_recovery.py` 105 passed |
| 4 | WebSocket terminal (tickets, proxy) | ☑ | `test_integration_docker.py::test_terminal_ticket_rules` (origin, single-use, expiry, max 2, reset close) |
| 5 | Lab loader/schema/capabilities + grader + evidence + `s3-basics` | ☑ | `test_labs_and_grader.py` 23 passed; Moto contract test passed |
| 6 | labtest CLI (0 / partial / 100) | ☑ | `python -m app.labtest /labs/s3-basics` → 0.00 / 50.00 / 100.00 PASS on real runner |
| 7 | S3 console API + UI (AWS-style, D7) | ☑ | `test_sessions.py` console + create-bucket-form tests; E2E |
| 8 | Lab player page | ☑ | E2E journey (checklist, progressive hints, timer, submit) |
| 9 | Instructor results + evidence + reopen/regrade | ☑ | `test_state_recovery.py` + E2E instructor test |
| 10 | E2E (Playwright): GUI + CLI journey, cleanup verified | ☑ | `apps/web/e2e/journey.spec.ts` 3/3 (docker ps cleanup check) |
| 11 | Demo mode + DEMO.md | ☑ | `scripts/demo-reset.*` → RESULT: READY; E2E uses it |
| 12 | Runtime status view | ☑ | `/admin/status`; E2E admin test |
| 13 | Remaining docs (ARCHITECTURE, SECURITY, LAB-AUTHORING, TESTING, SCALING) | ☑ | docs/ |

| R1 | **Regression after console-fidelity changes (Moto baseline)** | ☑ | runner 9/9 · API 163/163 (incl. docker) · labtest 0/50/100 · E2E 3/3, 2026-09-25 |
| 14 | Emulator abstraction + Floci (capabilities, contract, labtest, E2E, isolation/freeze) | ☑ | runner 12/12 · API 174/174 · docker suite 8/8 on both engines · E2E 3/3 on Floci |
| 15 | Floci promotion gate + decision in EMULATOR-EVALUATION.md | ☑ | Floci is the default (2026-09-25); Moto is the regression backend |
| 15a | Known flake: `test_append_only...[attempts]` failed once in a full run | ◐ | watch; not reproduced in 8 runs |
| 15b | Load-sensitive: Moto `DescribeImages` read timeout (20 s) once in a 55-min run under heavy host load | ☑ | passes in isolation 2/2; EC2 client read timeout raised to 60 s |
| 16 | DynamoDB service (console adapted from Floci UI, checks, lab pack) | ☑ | contract 12 ops + labtest 0/50/100 on Floci **and** Moto; console API tests; E2E `dynamodb.spec.ts`; full regression API 183/183, runner 12/12, E2E 4/4 (2026-09-25) |
| 17 | IAM service (users, groups, roles, policies; CloudLabs policy evaluator for grading) | ☑ | contract 41 ops + labtest 0/70/100 on Floci and Moto; console + simulator tests; E2E 5/5; full regression API 192/192, runner 12/12 |
| 18 | EC2 service (instances, security groups, key pairs; Launch instance wizard) | ☑ | contract 19 ops + labtest 0/30/100 on Floci and Moto; console tests; E2E 6/6; regression API 200/200, runner 12/12 |
| 19 | Lambda service (evaluate MiniStack only if Floci can't execute code safely) | ☑ | Floci/Moto can't invoke without Docker → MiniStack specialised engine (D14); runner 14/14; Lambda contract on floci/moto/ministack; labtest 0/45/100 on MiniStack; console tests; E2E 7/7; full regression API 209/209, runner 14/14 |

**Phase 5 — instructor/admin** (order set by the user, 2026-09-25)

| # | Milestone | State | Verification evidence |
|---|---|---|---|
| 20 | Audit trail + classes + roster CSV import (preview → commit) + enrolments + first-sign-in password change | ☑ | migration 0003; `test_courses_roster.py` 9; E2E `instructor-roster.spec.ts` |
| 21 | Assignments: create/edit/delete (lab version fixed once started), audited | ☑ | `test_assignments_manage.py` 3; E2E (roster spec creates an assignment) |
| 22 | Gradebook + CSV export + evidence drill-down | ☑ | `test_gradebook.py` 3 (statuses, best-attempt policy, regrades, extensions, CSV fields, formula neutralisation, task order); E2E `instructor-ops.spec.ts` |
| 23 | Live student progress + terminate/extend sessions (audited) | ☑ | `test_live.py` 5; E2E `instructor-ops.spec.ts` (extend, end-with-grading, student lands on result) |
| 24 | Runner/admin dashboard (users, sessions, audit log) | ☑ | `test_admin_manage.py` 4; E2E (audit log, users, engine images) |
| R2 | **Phase 5 regression** | ☑ | API 233/233 (incl. docker), runner 14/14, E2E 9/9 (2026-09-25). Found and fixed: attempt evidence listed tasks in storage order (now lab order) |

**Phase 6: learning-first fun layer** (order set by the user, 2026-09-25)

| # | Milestone | State | Verification evidence |
|---|---|---|---|
| 25 | Live architecture diagram (from sandbox/evidence state only) | ☑ | `test_diagram.py` 4; E2E `architecture.spec.ts` (CLI change appears without reload; result page shows what was built); regression API 237/237 |
| 26 | Break-fix labs (versioned lab packs + setup + deterministic grader) + `iam-breakfix` (Mission 6) | ☑ | `test_breakfix.py` 8, including labtest 0/45/100 on Floci **and** Moto and the real-session setup/Reset/baseline test |
| 27 | Simulated cost meter (versioned educational price table) | ☑ | `test_cost.py` 4; E2E (labelled simulated, on the live tab and the result page) |
| 28 | XP / levels / badges from verified results | ☑ | `test_gamification.py` (rules, idempotency, uncounted attempts, regrades, append-only); E2E badges on result + progress card |
| 29 | Instructor-configurable leaderboard (off / anonymous / named, per course) | ☑ | `test_gamification.py` leaderboard test (default off, aliases, staff names, audit, scoping); E2E `breakfix-fun.spec.ts` |
| R3 | **Phase 6 regression** | ☑ | API 255/255 (incl. docker: break-fix labtest on Floci and Moto, setup/Reset session test), runner 14/14, E2E 11/11 (2026-09-25). Found and fixed in review: same-lane diagram arcs clipped at the left edge; the IAM-only cost meter now explains that IAM is free |

**Phase 7: multi-server readiness** (order set by the user, 2026-09-25)

| # | Milestone | State | Verification evidence |
|---|---|---|---|
| 30 | Runner registration + heartbeats (per-runner secret, engines, host stats, CLI + admin API, audited) | ☑ | migration 0005; `test_fleet.py` heartbeat/registration/CLI tests; real registration of a 2nd runner (signed probe, wrong secret refused) |
| 30a | Cross-host sandbox gateway (`RUNNER_ACCESS_MODE=gateway`) | ☑ | real test through runner2 in gateway mode: console, grading, **terminal WebSocket**, wrong token → 404, cleanup |
| 31 | Scheduler (health, drain, engine/images, capacity, least load; concurrency-safe) | ☑ | `test_fleet.py` spreading, drain, stale heartbeat, engine compatibility, 12 concurrent Starts + heartbeats → exactly 2 + 2; real 2-runner placement |
| 32 | Drain / maintenance / retire | ☑ | admin + CLI tests (audited, *safe to stop* at 0, retire only when drained and empty); real drained runner takes no new lab |
| 33 | Failure reconciliation (runner lost; never migrate) | ☑ | `test_fleet.py`: unreachable ≠ lost, lost → `runner_lost` (no attempt), graded → closed, other runner untouched, leftovers destroyed on return; reset on a dead runner fails honestly |
| 34 | Load testing (`python -m app.loadtest`) | ☑ | `docs/LOADTEST.md`: 24 students / 8 seats and 32 / 16 seats PASS (0 failures, cleanup 100%). Found and fixed 4 real defects (deadlock, blocking password hashing, heartbeat flapping, reattach/destroy race) |
| 35 | Deployment docs (one-server, multi-runner, TLS, secrets, backup/restore, firewall, upgrades, rollback) | ☑ | `docs/DEPLOYMENT.md` + `infra/production/*`, `infra/runner-host/*` (validated with `docker compose config`); backup → restore verified: identical row counts, triggers and grants intact |
| R4 | **Phase 7 regression** | ☑ | API 267/267 (incl. docker + real two-runner gateway test), runner 16/16, E2E 13/13 incl. `fleet.spec.ts` (with runner2 registered, so labs also ran through the gateway) (2026-09-26). Postgres backup → restore verified: identical migration, row counts, append-only triggers and grants |

**Release v0.1.0: final verification** (2026-09-26)

| # | Check | State | Evidence |
|---|---|---|---|
| R5 | Clean start from README (`docker compose down -v`, `scripts/up.sh`, `scripts/demo-reset.sh`) | ☑ | healthy in 3 min; demo reset READY, 6 lab packs imported |
| R5 | Full regression | ☑ | **API 267/267** (incl. real-Docker and two-runner gateway tests, 0 skipped), **runner 16/16**, **browser E2E 13/13** (12 on the default single-runner stack, `fleet.spec` with runner2 registered) |
| R5 | DEMO.md walkthrough | ☑ | every section automated in `apps/web/e2e/` and passing on the fresh stack; stale wording fixed |
| R5 | Load-test smoke | ☑ | 6 students on 4 seats: 0 failures, 6/6 cleanup, provisioning p50 7.5 s, grading p50 1.0 s |
| R5 | Repository hygiene | ☑ | no keys/tokens/private keys tracked (only documented dev defaults); `.env`, `production.env`, `runner.env`, backups, certificates and build/test output ignored; `tsconfig.tsbuildinfo` untracked |
| R5 | Licences | ☑ | THIRD_PARTY_NOTICES.md lists every bundled/adapted component with MIT copyright notices and the full Apache-2.0 text; CloudLabs itself is Apache-2.0 (`LICENSE`, added after the release commit) |

**Phase 8: Instructor Lab Builder** (branch `feat/lab-builder`, plan in `docs/NEXT.md`)

| # | Milestone | State | Verification evidence |
|---|---|---|---|
| 36a | `pack_from_files` / `pack_files` refactor of `labs/package.py` | ☑ | API 239/239 fast suite unchanged; all 6 lab packs give byte-identical public/private bundle hashes before and after, and `pack_files → pack_from_files` round-trips losslessly (2026-09-26) |
| 36 | Backend: migration 0006, drafts API, validation, YAML, preview, clone/import/export, visibility + sharing | ☑ | `tests/test_lab_builder.py` 14 passed (ownership 404s, row-level errors, YAML round-trip, clone keeps private files, redacted preview, export/import round-trip + unsafe tar refusals, private-until-shared, assign/clone/export refused for invisible labs, demo reset); fast suite 253/253; 0006 downgrade → upgrade clean. Docker-marked tests and labtest not re-run in this session (see NEXT.md) |
| 37 | Test run and publish gate | ☑ | `tests/test_lab_builder_publish.py` 10 passed on the FakeRunner (job hook applies scripts with boto3): pass → publish owned private version + audit, publish refused until a passing test of the current content (any edit, even notes.md), wrong/failed solution blocks, partial scenario, runtime failure unlocks, interrupted run + test cap, reconciler keeps in-flight test sandboxes, immutability + clone → 1.1.0, 404/403; fast suite 263/263. Docker-marked real-sandbox test (clone Mission 1 → 0/50/100 → publish) **passes on the compose stack** (2026-09-26) |
| 38 | UI (`apps/web`) + `e2e/lab-builder.spec.ts` | ☑ | `tsc --noEmit` and `next build` clean. `e2e/lab-builder.spec.ts` passed in a smoke stack in this session (API in-process with the FakeRunner emulating Mission 1's scripts via boto3, `next dev`, system Chromium): clone → edit task → preview/YAML → test 0/50/100 on moto+floci → publish → assign → student starts and ends. **Runs on the real compose stack** (real sandboxes) in the full E2E below (2026-09-26) |
| 39 | Docs and full regression; merged to `main` | ☑ | **Full regression green, 2026-09-26:** API **292 passed, 1 skipped** (the skip is the two-runner gateway test when `runner2` is not registered; re-run with `runner2` up: **1/1 passed**), runner **16/16** (real Docker), `python -m app.labtest` on all six lab packs **0/partial/100 PASS on every engine**, browser E2E **14/14** including `e2e/lab-builder.spec.ts` and `e2e/fleet.spec.ts` (runner-local-2 registered, gateway). Found and fixed **D37** (reconciler reaped in-flight `labtest` sandboxes). Phase-8 docs added to LAB-AUTHORING / SECURITY / ARCHITECTURE / TESTING / DEMO (2026-09-27); fast-forward merged into `main` |
| R6 | **Phase 8 regression (Lab Builder)** | ☑ | **API 292 passed, 1 skipped** (the skip is the two-runner gateway test when `runner2` is not registered; **1/1** with it up), runner **16/16** (real Docker), `python -m app.labtest` on six lab packs **0/partial/100 PASS on every engine**, browser E2E **14/14** incl. `e2e/lab-builder.spec.ts` and `e2e/fleet.spec.ts` (2026-09-26). Follow-up review of D37 (2026-09-27, **D38**) closed a clock-skew hole: a future/non-finite `created_at` no longer grants the orphan grace window. Fast suite `-m "not docker"`: **265 passed, 29 deselected**; reconciler tests **12 passed** |

## Implementation decisions log
- **D1 — Sandbox networking.** Docker can't publish ports from `internal: true` networks. The runner
  therefore connects all containers labelled `cloudlabs.role=control-plane` (with the matching
  `cloudlabs.env`) to each sandbox network, and returns container IPs as endpoints. The API still never
  calls Docker. PLAN.md "Key decisions" and §11.3 have been amended to match.
- **D2 — Setup and lab-test scripts** run in a short-lived *job container* (the terminal image, created
  by the runner's typed `run_job` op) on the sandbox network. This is never an exec into the student's
  terminal container. `run_job` gets bundle bytes + sha256 from the API and verifies the hash.
- **D3 — Log event names added to the fixed set** (PLAN §14 amended): `assignment.override.granted`
  (audited instructor reopen), `http.request.failed` (unhandled error), `background.task.failed`
  (periodic loop error). The runner uses `runner.reattach_failed`. Tests run with strict name
  enforcement, so any other name fails the test run.
- **D4 — WebSocket rejections** accept and then immediately close with an application code
  (4401 invalid_ticket, 4403 origin_not_allowed, 4409 session_not_ready, 4429 too_many_terminals), so
  the browser can show why. No data is ever sent on a rejected socket.
- **D5 — Demo account email domain** is `@cloudlabs.demo` (`.local` is rejected by the email validator).
- **D6 — S3 re-create semantics:** in us-east-1, Moto (like AWS) returns success when you re-create a
  bucket you already own, and deleting an object in a versioned bucket leaves a delete marker. The
  contract tests assert the AWS-faithful behaviour.
- **D7 — Student console fidelity:** the student console follows AWS terminology, hierarchy and workflows
  (PLAN "Student console fidelity principle"). Lab pack s3-basics v1.1.0 uses progressive hints.
- **D8 — Emulator abstraction.** Runner: `EmulatorSpec` table (`image`, `port`, `tmpfs`, `env`) with the
  engine recorded as the `cloudlabs.engine` label, so reset/jobs keep it. API: `app/runtime/emulators.py`
  `EmulatorAdapter` (capabilities + client factory). `lab_sessions.engine` (migration 0002) is resolved at
  Start from `runtime.emulator` (`default` → `CL_DEFAULT_EMULATOR`). A `default` lab must be valid on
  **every** engine at import. Engine names never appear in student-facing responses (tested).
- **D9 — Floci image.** `images/emulator-floci` pins `floci/floci:2.1.0`, runs as UID 10001 with
  `FLOCI_STORAGE_MODE=memory`, tmpfs `/app/data`, the image's bash healthcheck, and bypasses the
  root/Docker-socket entrypoint. No Docker socket, so Floci Lambda invoke / real EC2 are unavailable by
  design.
- **D10 — Shared console plumbing.** `app/console/common.py` (`console_session`, `aws_call`) is the only path
  from a service console endpoint to an emulator: ownership, READY check and the grading freeze
  (`409 session_frozen`) apply identically to S3 and DynamoDB. Web: `CloudConsole` shell + `console-kit`.
- **D11 — Floci UI adaptation.** DynamoDB console patterns adapted from Floci UI (MIT) with attribution in
  file headers and `THIRD_PARTY_NOTICES.md`. Floci UI is not embedded and its generic proxy isn't used.
- **D12 — IAM.** Neither engine enforces IAM or implements the policy simulator. CloudLabs grades IAM with its own
  evaluator (identity policies, explicit deny wins, conditions reported but not evaluated) and exposes it as
  the console's *Policy simulator* (`SimulatePrincipalPolicy: simulated`). Moto runs with
  `MOTO_IAM_LOAD_MANAGED_POLICIES=true` (engine spec only), so AWS managed policies exist on both engines.
- **D13 — EC2.** Instances are simulated records on both engines (no Docker, so no real machines). Evidence and
  checks never use AMI IDs (they differ per engine). `ec2.running_instance_count` has a `min` bound so an
  empty sandbox can't earn cost-control marks (found by the empty-scenario test). Real instance shells stay in
  the fun-layer phase as a runner-managed feature.
- **D14 — Lambda.** Floci and Moto manage functions but can only execute them through Docker, which sandboxes
  never get. MiniStack executes Lambda code in-process, so it is a *specialised* engine used only by labs that
  pin `runtime.emulator: ministack` (docs/EMULATOR-EVALUATION.md). Capability enforcement moved into
  `console/common.py::aws_call`: every console operation is checked against the session engine's capability
  file (`409 not_in_simulator`). `lambda.invoke_returns` is graded from a probe run during evidence capture.
  The console nav now shows `unavailable` services as "Not in this lab" (all five consoles exist).
- **D15 — Audit trail (phase 5).** `audit_events` is append-only (trigger + grants, like evidence) with no foreign
  keys, so it can't block or be removed by changes to what it describes. `app/audit.py::record()` adds the row to
  the same transaction as the action (both commit or neither) from a fixed action set: course/roster/enrolment,
  assignment create/update/delete, deadline extensions, extra attempts, regrades, session terminate/extend, user
  role/deactivate/password reset. Log event `audit.recorded` added to the fixed set.
- **D16 — Roster import.** Two steps: `preview` validates every row (email syntax, duplicates in the file,
  missing name for new accounts, non-student or deactivated accounts, surplus values) and returns a token bound
  to (course, exact CSV text); `import` requires that token, re-validates, and commits all-or-nothing. Unknown
  emails become student accounts with a one-time readable temporary password, shown once (downloadable CSV);
  `users.must_change_password` makes every API except `/auth/me` and `/auth/change-password` answer
  `403 password_change_required` until it is changed. Removing an enrolment is refused while the student has a
  lab running in that course; attempts are kept. Courses and roster accounts created by demo users are demo
  rows, so demo reset removes them.
- **D17 — Assignment edits.** Any field can change, but the pinned lab version only until the first session
  starts, and delete only while nobody has started it and no extensions exist (results must stay reproducible).
  Each change is one audit row with `changes: {field: [old, new]}`.
- **D18 — Live progress and staff session controls.** The live view reads a small progress summary stored when
  the *student* runs *Check progress* (`lab_sessions.last_progress`, not evidence). Staff never read or poll
  sandboxes, so monitoring can't change graded state or load the runner. *End lab* has two modes, both through
  the state machine: **grade** = `submit(trigger="staff")` (counts only if graded state differs from the baseline,
  like other automatic submits) and **discard** = `stop` (no attempt). *Extend* adds 5–60 minutes to a READY
  session's `expires_at` (a compare-and-set on the old value) and restarts the idle timer. It is capped by
  `cap_extended_ttl_minutes` (240) and the student's effective close. Admin *kill* is audited as
  `session.terminated` (mode discard).
- **D19 — Admin dashboard.** Runtime status also shows each runner's engine images (live `capacity()` call,
  3 s timeout, optional) and all running labs with +15 min / End. Users can be created (staff accounts with a
  temporary password), searched, have their role changed, be deactivated/reactivated, or have their password
  reset. Admins can't change themselves, and demo accounts keep their role and password. Course staff can be
  added or removed. The global audit log is paged by id (`before`), and instructors get their course's log.
- **D20 — Architecture diagram.** `app/diagram.py::build_graph` is a pure function of collector evidence. The live
  view (`GET /sessions/{id}/architecture`, owner only, READY only) takes a read-only snapshot using the lab's own
  grading collectors (so only capability-checked read operations) **without probes** (no Lambda invocations).
  It is cached 5 s per session, and is neither evidence nor activity. The web polls every 6 s while the tab is
  visible. Result pages draw the same graph from the stored final evidence. Node flags are generic console
  warnings only (SSH/RDP open to the internet, AdministratorAccess attached), never lab-specific checks.
- **D21 — Break-fix labs.** New optional `kind: break_fix` in schema v1 (requires `setup`). Setup scripts now
  receive the session variables through a generated wrapper in the public bundle (same convention as labtest
  scripts). Because the baseline is captured after setup, an untouched auto-submit compares against the
  *broken* state and doesn't count. Reset re-runs setup. Negative IAM checks were added with safe defaults:
  `iam.user_in_group` / `iam.policy_attached` take `expect: absent`, and `iam.policy_allows` takes opt-in
  `absent_ok` (a deleted principal has no access). The opt-in keeps existing labs at 0 in an empty sandbox.
- **D22 — Simulated cost.** `app/cost/pricing/<version>.yaml` is an immutable, versioned educational price table
  (`edu-2026.1`: simplified us-east-1 list prices, no free tier). `estimate()` is pure over collector evidence.
  Running instances are charged compute, every non-terminated instance its root volume (stopped too), S3 by
  object size, DynamoDB provisioned capacity per hour, and on-demand and Lambda nothing while idle. Every
  response carries `simulated: true`, the table version and a "not AWS billing" disclaimer, and the UI labels
  it *Simulated · educational*.
- **D23 — XP, badges, leaderboard.** XP is derived on read: per assignment, the best counted score as a
  percentage (latest grade, so regrades apply), plus badge bonuses, so no client action can create it. Badges
  are append-only `user_badges` rows awarded by pure rules over verified attempt facts (counted attempts, latest
  grade, lab kind/services, final-evidence instance types) after the grade commits. This is idempotent, a
  failure can't affect grading, and `python -m app.gamification backfill` exists. Regrades can award badges but
  never revoke them. Leaderboards are per course, `off` by default, `anonymous` (stable per-course aliases) or
  `named`; changes are audited as `course.settings_changed`. Students see the top 10 and their own rank; staff
  see real names.
- **D24 — Runner fleet.** Heartbeats are pulled by the control plane (runners never call the API). Each runner has its
  own HMAC secret (encrypted with `CL_SECRET_KEY`; NULL = the platform runner's `CL_RUNNER_SECRET`). Registration
  succeeds only if a signed capacity call answers with the same id. Statuses: healthy / unhealthy (Docker down) /
  unreachable / misconfigured (answers with another id) / retired. One missed beat keeps the runner schedulable
  until its last good heartbeat is older than `runner_unhealthy_after_s` (a load-test finding). An engine is
  "present" only when its emulator image and the terminal image both exist.
- **D25 — Scheduler.** Least-loaded (`in_use/max`, then free host memory, then id) among healthy, non-draining,
  engine-compatible runners with a free seat. Serialised by one transaction advisory lock, and runner rows are only
  read (row locks `FOR UPDATE` deadlocked with heartbeat updates in the load test). `capacity_full` only when every
  eligible runner is full; `runtime_unavailable` when none is eligible. Sessions keep their runner for life.
- **D26 — Runner lost.** Unreachable for `runner_lost_after_s` (300 s): active and ungraded sessions → FAILED
  `runner_lost` without contacting the runner (no attempt used; `fail(destroy=False)`), graded ones → TERMINATED
  (`runner_lost`). The reconciler runs per runner, so orphans and leftovers are scoped to that runner, and a returning
  runner's leftovers are destroyed. Nothing is ever recreated on another runner.
- **D27 — Sandbox gateway.** For runners on other servers, `RUNNER_ACCESS_MODE=gateway` + `RUNNER_PUBLIC_URL`:
  the runner attaches itself to each sandbox network and forwards only that sandbox's emulator (HTTP) and ttyd
  (WebSocket) at `/gw/<sandbox>/<token>/…`. The token is 24 random bytes, stored as a network label, returned only
  in the signed create/reset answer, and checked in constant time. The upstream is resolved by the runner (no
  host/port from the client). `/gw/` is exempt from HMAC (boto3/WebSocket clients can't sign), so the runner port
  must stay private. The API treats endpoints as opaque URLs (Lambda code download keeps the path prefix).
- **D28 — Load-test fixes.** argon2id OWASP profile (19 MiB, t=2, p=1) in bounded worker threads (CPUs − 2), with
  rehash at next sign-in. The runner's reattach loop takes the per-sandbox lock and skips half-destroyed sandboxes.
  Destroy retries network removal, and an empty network Docker refuses to remove (stale endpoint) is recorded as
  leaked (no seat, surfaced on Runtime). Line endings normalised to LF with `.gitattributes`, because Windows tooling
  had introduced CRLF, which would break shell scripts in Linux containers.
- **D29 — Lab ownership.** `labs.owner_id` NULL = built-in mission (imported from `labs/` on disk), visible to all.
  An authored lab is visible to its author and admins, or to every instructor once `shared`. Anything invisible
  answers 404 (list, assign, re-pin an assignment, clone, export, share). `import_package(owner_id=…)` refuses a
  lab id that belongs to a different owner (`lab_owner_conflict`, 409), so neither the CLI nor a publish can add a
  version to someone else's lab or to a built-in mission. Sharing is audited (`lab.shared`) and only changes future
  visibility: existing assignments keep working.
- **D30 — Drafts.** A draft stores `{lab: <schema-v1 dict>, files: {path: text}}` as JSON, so YAML comments are not
  kept, and YAML-only values such as unquoted dates are refused. YAML aliases are also refused, in lab.yaml and
  expected.yaml, because a few KB of nested aliases would expand exponentially when serialised. Drafts save even when invalid (work in progress).
  Every save re-validates and stores `last_validation`, with errors turned into rows (`task`, 1-based `check`,
  `field`, or a schema/file `loc`). Only `private/{solution.sh,partial.sh,expected.yaml,notes.md}` are editable.
  Other files from a clone or import (for example break-fix setup scripts) are carried unchanged and refused if
  changed. Saving changed content moves a `passed`/`failed` draft back to `draft`. `testing` and `published` drafts
  are read-only.
- **D31 — Clone semantics.** Cloning your own lab prepares its next version (same id, next minor). Cloning anyone
  else's lab or a built-in mission starts a new lab `<id>-<your short id>[-n]` at 1.0.0, titled "… (copy)", so a
  clone can never collide with the original. Validation already flags an id owned by another lab, or a version
  that is already published, before any test run.
- **D32 — Scenario rules in validation.** `private/solution.sh` is required, `expected.yaml` defaults to
  `{empty: 0, solution: <max score>}`, and it must keep empty at 0 and solution at full marks (owner's publish
  gate). A partial scenario needs both `partial.sh` and a score strictly between 0 and full marks.
- **D33 — Pack upload/export.** Export is a deterministic `.tar.gz` (`<id>-<version>/…`, mtime 0) for staff who can
  see the lab. It includes the private bundle and is never offered to students. Import accepts `.tar`/`.tar.gz`
  up to 2 MB with lab.yaml at the top or in one folder. Only regular UTF-8 files within the pack limits are
  accepted (no links, devices, traversal or other top-level folders); a schema-invalid pack still becomes a draft.
- **D34 — Demo reset** also deletes demo authors' drafts and published labs. Draft links to lab versions are
  `ON DELETE SET NULL`, so a real instructor's clone of a demo lab survives the reset.
- **D35 — Test run and publish gate.** `POST drafts/{id}/test` validates, locks the draft (`testing`) and answers
  202; a background task runs `labtest.check_pack(LabPackage)` on the platform runner: empty, partial (if any) and
  solution, each in a fresh sandbox, one at a time, on every engine the lab may run on. Per-scenario results with
  per-check detail are written into `last_test` as they land, and only while that run id is still current. The
  run ends `passed` (every scenario matched) or `failed` and stores `tested_sha256` = the tested content hash (it
  covers private files too, so editing even notes.md needs a new test). Runner errors and crashes end as `failed`
  with `last_test.status = error`. A run still `testing` after `builder_test_timeout_s` (900 s, e.g. the API
  restarted) is reported interrupted on the next read, so a draft can't stay locked. At most
  `builder_max_concurrent_tests` (2) runs at once (`429 test_capacity_full`). Sandbox ids are uuid5(run id,
  scenario) and listed in `last_test.sandbox_ids`; the reconciler counts those of `testing` drafts as known, so
  only leftovers of finished runs are removed as orphans. `POST drafts/{id}/publish` needs `passed` and
  `tested_sha256` = current hash (`409 test_required`), re-validates, then `import_package(owner_id=author)`
  must create a new version (`409 lab_version_conflict` otherwise), updates the lab title, records `lab.published`
  and makes the draft `published` (read-only). The published lab is private to its author until shared.
- **D36 — Lab Builder UI.** `/instructor/labs` (nav "Labs"): drafts, my labs (share toggle, *New version*), shared / other
  authors' labs, built-in missions, each with Clone and Export; New (blank) and Import (.tar.gz). The editor
  `/instructor/labs/drafts/[id]` keeps local edits with an explicit Save (plus a leave-page warning); the YAML, Preview and
  Test tabs save first because they show the saved draft. Check parameter forms are generated from each check's JSON
  Schema (`components/schema-form.tsx`): string, number, bool, enum, key-value maps, lists, and JSON for anything
  else. Engine warnings only name engines the lab can run on. The validation panel is always visible and each row jumps
  to its tab/task. Testing and published drafts are shown read-only (`<fieldset disabled>`); a running test is polled
  every 2.5 s. Publishing needs a passing test of the saved content, then offers Share, Assign and *Prepare next version*.
- **D37 — In-flight `labtest` sandboxes.** `python -m app.labtest` creates sandboxes with no session or draft row, so
  the reconciler's orphan sweep destroyed them mid-run (the first regression run on this branch hit exactly that: a
  `sandbox not found` from `run_job`). The runner now stamps each sandbox's creation time (`cloudlabs.created_at`
  network label, surfaced as `SandboxStatus.created_at`), and the reconciler keeps a rowless sandbox younger than
  `orphan_grace_s` (300 s) as `orphan_young`. Older rowless sandboxes and rowless sandboxes whose runner reports no
  creation time (the test FakeRunner) are still destroyed as orphans, so session/draft cleanup and existing tests are
  unchanged.
- **D38 — Orphan grace needs a plausible clock.** D37's grace window used `now - created < grace`, so a
  `created_at` in the future (a runner clock ahead of the control plane) or a non-finite label gave a negative age
  and kept the sandbox alive forever. The reconciler now grants the window only when `0 <= age < orphan_grace_s`;
  a missing, future, `inf`/`nan` or older-than-grace value is reaped as an orphan. A rowless sandbox can therefore
  never outlive the grace window, and live sessions / running draft tests are still kept as `known`. Regression:
  `test_state_recovery.py::test_reconcile_reaps_rowless_sandboxes_with_an_implausible_age`.
