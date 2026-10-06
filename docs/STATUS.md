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
| 15a | Known flake: `test_append_only...[attempts]` failed once in a full run | ☑ | Not reproducible: 8 runs, then 20 stress rounds (all five tables + owner trigger, 120 executions) on 2026-10-06, 0 failures. The guard cannot depend on data (see D60); closed |
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
| R6 | **Phase 8 regression (Lab Builder)** | ☑ | **Fresh full regression from `46d4ed2`, 2026-09-27:** API **294 passed, 0 skipped** (incl. real-Docker and the two-runner gateway test with runner-local-2 registered), runner **16/16** (real Docker), `python -m app.labtest` on all six lab packs **0/partial/100 PASS on every engine** (lambda on MiniStack; the rest on moto and floci), browser E2E **14/14** incl. `e2e/lab-builder.spec.ts` and `e2e/fleet.spec.ts`. D38 review closed a clock-skew hole in D37 (a future/non-finite `created_at` no longer grants the orphan grace window). Fast suite `-m "not docker"`: 265 passed, 29 deselected; reconciler tests 12 passed. Web `npm run typecheck` clean. Supersedes the 2026-09-26 run (API 292 + 1 skip, before the D38 test) |


**Phase 9: Authoring excellence** (branch `feat/authoring-excellence`, plan in `docs/NEXT.md`)

| # | Milestone | State | Verification evidence |
|---|---|---|---|
| 40 | Template gallery and guided New-lab start | ☑ | `GET builder/templates` (curated, resolved against the latest built-in version, `available: false` when the pack is not installed) and `POST builder/drafts {source: "template", template_id, title?}` → a fresh draft: id `<title-slug>-<short id>`, version `1.0.0`, the author's title, all files carried (a break-fix `public/setup.sh` stays read-only), audited with `template_id`. Six templates from the built-in missions. UI: New-lab gallery (Start from scratch + cards with services/difficulty), dialogs scroll. `tests/test_lab_builder.py` **16 passed** (2 new); fast suite **267 passed, 29 deselected**; `tsc --noEmit` clean; `e2e/lab-builder.spec.ts` **2/2** (new template test on the real stack) (2026-09-27) |
| 40a | Demo one-click sign-in on the login page | ☑ | Public `GET /api/auth/demo-accounts` returns the seeded demo accounts and the shared password only while `CL_DEMO_MODE=true` **and** only accounts that exist in the DB (a fresh, unseeded stack shows nothing). The login page renders the password and role buttons that sign in directly. `tests/test_auth_and_policy.py` **15 passed**; `e2e/login.spec.ts` **1/1** (2026-09-27) |
| 42a | **Stackora** public brand + landing page | ☑ | Public product renamed to **Stackora** ("Launch it. Break it. Fix it." / "Hands-on cloud labs with real CLI workflows and instant grading.") on user-facing surfaces: page titles/metadata, app shell, login, console/simulator labels, cost disclaimer, demo CLI output, API/Runner docs titles and the terminal welcome banner. Packages, Docker images, DB identifiers, env vars, migrations and API contracts keep the `cloudlabs` codename. New public marketing page at `/` (hero + CTAs, AWS services, 9 platform features, console/CLI workflow, E2E screenshots, Apache-2.0, final CTA, footer); the auth guard exempts `/`, `/login` remains the authentication page and the authenticated app is unchanged. README intro, DEMO and RELEASE_NOTES updated; all E2E screenshots regenerated with the new brand. `e2e/landing.spec.ts` **2/2**; full browser E2E **19/19**; `tsc --noEmit` clean (2026-09-27) |
| 41 | Typed break actions (declarative starting states) | ☑ | `app/breakfix/` registry + pure compiler; schema `break_actions` + `baseline.expected_score` (below full marks, `empty` must match); import validation (unknown type, params, service, engine capabilities); `setup_job` compiles actions into the public setup bundle; `GET builder/break-actions` + `POST builder/break-actions/summary`; Starting state tab (typed forms from each action's Pydantic schema, Broken State Summary, kind toggle); labtest adds a **reset** scenario for break-fix packs. `tests/test_breakfix_actions.py` 13 passed; `tests/test_lab_builder.py` 17 passed; real compiled pack on moto+floci: **baseline 0 and 40 → solution 100 → Reset reproduces the baseline**; `e2e/lab-builder.spec.ts` 3/3; fast suite **281 passed, 29 deselected**. Interactive preview sandbox landed in milestone 42 |
| 42 | Preview sandbox + publish readiness | ☑ | Migration 0007 (`lab_drafts.last_preview`, `terminal_tickets.draft_id`); `POST/GET/DELETE builder/drafts/{id}/preview-sandbox` + `POST .../reset` launch a **real runner sandbox** with the compiled declared setup (same isolation/limits/env as a student lab), owner/admin only (404 to anyone else). Console and terminal reuse the student routes (`AuthzAny(session.use, lab.manage)` + resource check); the reconciler treats a running preview as known and destroys it after `preview_ttl_s` idle. **Never a session/attempt/grade/XP/badge/leaderboard row.** `GET builder/drafts/{id}/readiness` is the publish gate as a checklist (validation, capabilities, baseline vs `baseline.expected_score`, reference solution full marks, Reset reproducibility, passing test on the current content, row-level errors); the Publish button is enabled only when every row passes. Tests: `test_lab_preview.py` **3 fast + 1 docker** (real runner: baseline 0 → Reset → 0, console, terminal, no student work), readiness tests in `test_lab_builder_publish.py`; fast suite **287 passed, 30 deselected**; **full API suite incl. Docker 317 passed, 0 skipped**; full browser E2E **20/20** incl. the preview walkthrough and the landing/login specs (2026-09-27) |
| 42b | Landing page recognizes a signed-in visitor | ☑ | `/` renders session-aware CTAs (`components/landing-cta.tsx`, client fragments — the page stays a server component): a signed-in visitor sees **name · role** and a role-aware app link ("Go to my labs/courses/runtime") in the header, and the hero/final "Try the demo" + "For instructors" collapse to that one link; anonymous visitors keep the marketing CTAs, and the page remains static. The app-shell brand links to `homeFor(me)` instead of `/`, so clicking **Stackora** from inside the app stays in the app. `e2e/landing.spec.ts` **3/3** (new signed-in test: brand click from `/instructor` stays there; direct `/` shows the account and no `cta-try`/`cta-primary`/`cta-instructor`), `tsc --noEmit` and `next build` clean; `web` image rebuilt and spot-checked on the compose stack (2026-09-27) |
| 43 | Instructor first-run journey + quickstart | ☑ | `e2e/instructor-first-run.spec.ts` walks the whole product with **no YAML, shell, database or developer tooling**: create course → import roster (new + existing student) → New lab from the S3 template → rename a task and **add a check** with the generated form → configure the starting state with a typed break action → **launch the preview sandbox** (console visible, Reset, Stop) → readiness → **test run in real sandboxes** (0 / 50 / 100 + reset on moto and floci) → publish → assign → the new student changes their temporary password and completes the lab **in the console only** (bucket, versioning, upload, tags) → submits → instructor sees the result and drills into the evidence. **Passed (3.4 min) with no blockers found**; screenshots 25–29. `docs/INSTRUCTOR-QUICKSTART.md` (step-by-step with screenshots, troubleshooting, "what you never need"); in-app first-run card on the instructor home and a quickstart link on the Labs page; README doc table. `tsc --noEmit` clean (2026-09-27) |
| 44a | Lambda + DynamoDB combined lab (Mission 7) + template | ☑ | New pack `labs/lambda-dynamodb` (pins `runtime.emulator: ministack`, the only engine that runs Lambda code): create an orders table, a Lambda function with `TABLE_NAME`, and a task where the function **saves the order and returns the total** — the invoke probe runs before the other collectors, so a hidden `dynamodb.item` check proves the row the function wrote. MiniStack now declares all **12 DynamoDB contract ops as supported** (verified by `test_dynamodb.py` on all three engines), which also makes the DynamoDB console available in MiniStack labs. Template `lambda-dynamodb` in the gallery; `demo-reset` imports and assigns Mission 7 (`RESULT: READY`). labtest on the real runner: **0 / 55 / 100 PASS on MiniStack**; docker tests: dynamodb contract ×3 engines, lambda contract ×3, `test_lambda_dynamodb_labtest_on_ministack` (2026-09-27) |

**M44 preparation: VPC / SQS / SNS evaluation** (branch `feat/m44-services-eval`, based on `034fd07`; not merged)

| # | Milestone | State | Verification evidence |
|---|---|---|---|
| 44p | VPC / SQS / SNS evaluated on every engine + contract tests (preparation only) | ☑ | 68 semantic probe checks per engine under the production sandbox hardening (`tools/emulator-bakeoff/m44_bakeoff.sh` + `m44_probe.py`; raw logs `m44-results/{moto,floci,ministack}.txt`): Moto 5.2.3 **32/32 VPC, 20/20 SQS, 16/16 SNS** (192 MiB), Floci 2.1.0 **32/32, 20/20, 16/16** (40 MiB), MiniStack 1.5.16 **32/32, 20/20, 16/16** (59 MiB); SNS delivery verified SNS→SQS in-sandbox (enveloped, raw, batch). Capability files declare `vpc` (28 supported), `sqs` (16) and `sns` (12) identically on all three engines; `SERVICE_CLIENT = {"vpc": "ec2"}` keeps the mapping in the adapter; `service_status()` only announces services that have a console page, so the student catalogue is unchanged (and capability notes stay engine-neutral). New contract tests `tests/test_vpc.py` / `test_sqs.py` / `test_sns.py` **13 passed** (4 fast parity/mapping + 9 real-sandbox through the runner); full fast suite **291 passed, 39 deselected**. Findings: deleting a VPC cascades to subnets on Floci (Moto refuses like AWS — do not grade dependency errors), SNS tag writes fail on Floci, MiniStack ignores `CreateTopic` tags. Grader-check, FastAPI-route and console-IA proposals plus the per-service default recommendation (**Floci**, no switch made) in `docs/M44-SERVICES-EVALUATION.md`. No UI, lab pack, endpoint or default changed (2026-09-27) |
| 44v | **VPC service end to end** (console, checks, labs, console UI, E2E) | ☑ | Implemented from the 44p evaluation: `app/console/vpc.py` **17 endpoints** (overview, VPCs, subnets, route tables/routes/associations, internet gateways, security groups with rule editing) addressed by `Name` tags and capability-filtered through the adapter (`SERVICE_CLIENT` maps `vpc` → boto3 `ec2`); `CONSOLE_OPS["vpc"]` lists exactly the operations the page calls, so the page is capability-gated and never half-working. Grading: `vpc` evidence collector + six checks (`vpc.exists`, `vpc.subnet`, `vpc.route`, `vpc.subnet_route_table`, `vpc.internet_gateway_attached`, `vpc.security_group_rule`) — no ids, ARNs or AZs; `vpc` added to the lab `Service` list, the Lab Builder catalogue and the architecture diagram's network lane (VPC stays free in the cost meter). Labs: `vpc-basics` guided (labtest **0/50/100**) and `vpc-breakfix` built from **10 typed `vpc.*` break actions** (**baseline 25 / partial 65 / solution 100**, Reset reproduces 25) — both on **moto and floci**, both seeded by the demo reset and offered as two Lab Builder templates. UI: `components/vpc-console.tsx` (Your VPCs, Subnets, Route tables, Internet gateways, Security groups) behind the capability nav. E2E `e2e/vpc.spec.ts` **2/2** on the compose stack (Mission 8 built in the console and scores 100; Mission 9 repaired in the console). Timeout chain raised for CLI-heavy break-action setups (a VPC network is ~20–30 AWS CLI calls): compiled setup cap 60 → **180 s**, `runner_timeout_s` 150 → **240 s**, gateway `proxy_read_timeout` 180 → **300 s**. Console ordering puts named (lab) resources before the unnamed engine defaults, and rule editing maps null ports to −1. `tests/test_vpc_console.py` + labtest tests in `tests/test_vpc.py`; full fast suite **299 passed, 45 deselected**; `tsc --noEmit` and `next build` clean; docs: LAB-AUTHORING (checks table, break actions, setup cap), M44 evaluation implementation status. Branch `feat/m44-services-eval` (2026-09-28) |
| 44q | **SQS service end to end** (console, checks, labs, console UI, E2E) | ☑ | `app/console/sqs.py`: queue list/detail, attributes, tags, send, poll, delete message, purge and delete queue; FIFO-aware creation (`.fifo` rule enforced). The console **poll** receives with `VisibilityTimeout=0`, so inspecting messages never hides them from other consumers or from grading. Grading: `sqs` evidence collector with an **`sqs_peek` probe** (`ReceiveMessage` visibility 0, up to 10 bodies — non-destructive) and four checks (`sqs.queue_exists`, `sqs.queue_attribute`, `sqs.queue_tag`, `sqs.message_present`); the architecture diagram gained queue nodes. Labs: `sqs-basics` guided (labtest **0/35/100**) and `sqs-breakfix` built from typed `sqs.*` break actions (**baseline 20 / partial 70 / solution 100**, Reset reproduces 20) — both on **moto and floci**, seeded by the demo reset and offered as two templates. UI `components/sqs-console.tsx` behind the capability nav; E2E `e2e/sqs.spec.ts` **2/2** (Mission 10 creates a queue, sends an order and polls it; Mission 11 restores visibility/delay). `tests/test_sqs_console.py` + labtest tests in `tests/test_sqs.py`; full fast suite **305 passed, 49 deselected**; `tsc --noEmit` and `next build` clean; docs: LAB-AUTHORING, M44 evaluation status (2026-09-28) |
| 44n | **SNS service end to end** (console, checks, labs, console UI, E2E) | ☑ | `app/console/sns.py`: topics with display names, subscriptions (in-sandbox SQS queues only — there is no egress), unsubscribe and publish; the subscribe form lists the sandbox's queues. Grading: `sns` evidence collector (topics with protocol/queue/raw-delivery subscriptions) and two checks (`sns.topic_exists`, `sns.subscription`); **delivery is graded through the non-destructive `sqs.message_present` probe** (the peek now waits up to ~5 s so an asynchronous SNS delivery is not flaky), and the diagram shows topics with `delivers to` edges. Labs: `sns-basics` guided (labtest **0/45/100**) and `sns-breakfix` built from typed `sns.*` break actions (**baseline 20 / partial 70 / solution 100**, Reset reproduces 20) — both on **moto and floci**, seeded by the demo reset and offered as two templates. UI `components/sns-console.tsx` behind the capability nav; E2E `e2e/sns.spec.ts` **2/2** (Mission 12 builds fan-out and proves delivery; Mission 13 restores the deleted subscription and proves it again). Found and fixed: AWS CLI v2 spells the SNS Subscribe endpoint `--notification-endpoint` (`--endpoint` is the global `--endpoint-url`); the compiler and lab scripts use the correct flag. Tests: `tests/test_sns_console.py` + labtest in `tests/test_sns.py`; full fast suite **311 passed, 53 deselected**; `tsc --noEmit` and `next build` clean; docs: LAB-AUTHORING, M44 evaluation status (2026-09-28) |

**Phase 10: Quality + teaching value** (branch `feat/m45-quality`, plan in `docs/NEXT.md`)

| # | Milestone | State | Verification evidence |
|---|---|---|---|
| 45 | Authorization coverage guard | ☑ | `tests/test_authz_coverage.py` — the file `app/main.py:131` and `app/auth/policy.py:2` already named but which did not exist (the check had been living inside `test_auth_and_policy.py`). Moved and strengthened: route coverage; a **public allowlist held in the test** so opening a route to anonymous callers is a reviewable diff; no resource-scoped path public; `Authz` action ↔ `MATRIX` consistency; a **non-vacuity self-test**; an anonymous sweep asserting **401 on all 141 protected routes** (181 after the M44 merge — see R7); and the 404-not-403 contract. Found and fixed a stale `PUBLIC_ROUTES` entry: FastAPI registers the Swagger OAuth2 redirect at `/docs/oauth2-redirect`, not `/api/docs/oauth2-redirect`. Fast suite green (2026-09-27) |
| 46 | Lab Builder autosave + undo/redo | ☑ | **Server:** `drafts.rev` (sha256 of the content — not `updated_at`, which validation and status changes also bump), sent back as `base_rev` on `PUT .../drafts/{id}` and `PUT .../yaml`; a stale save gets **409 `stale_revision`** with the current `rev` instead of overwriting. Tests: `tests/test_lab_builder_autosave.py` **8 passed** (rev round-trip across an autosave run, stale refused and newer content kept, no `base_rev` still allowed, a validation run never invalidates a save, unchanged content keeps the rev, invalid partial content saves *and* stays protected, YAML guarded too), builder suites **37 passed**. **Client:** debounced autosave (800 ms) with `Saving… / Saved / Save failed`, save-on-tab-switch and unmount flush, no retry loop on failure, a stale banner with Reload; undo/redo over a 100-step history with keystroke coalescing (900 ms), Ctrl/Cmd+Z ⇄ Shift/Ctrl+Y outside text fields, form remount on step so no tab keeps discarded state. `tsc --noEmit` clean; **`e2e/lab-builder-autosave.spec.ts` 4/4** (autosave survives tab switch + reload, undo/redo, one failed PUT → "Save failed" with **exactly one** request then a manual retry, stale → banner, no overwrite, reload recovers) |
| 47 | Single-check live runner | ☑ | `POST .../drafts/{id}/preview-sandbox/check {task, check}` runs **one** check against the running preview sandbox: same `registry.get(...).fn` and the same `ev.capture` the real grader uses, one collector, probes first. Returns type, index, hidden, scoring, **marks possible** (the same `Fraction` share `grade()` computes), rendered params, expected, actual, pass/fail and the **normal grader message** (author feedback when set); or `status: "blocked"` with a reason code for `not_in_simulator` / `check_unsupported` / `emulator_error`. Owner/admin only (404), preview must be running (409), serialised by a lock and spaced by `CL_PREVIEW_CHECK_MIN_INTERVAL_S` (429 + `Retry-After`). **Never** an attempt, grade, evidence row or badge — asserted directly. Tests: `tests/test_preview_check.py` **8 passed** including exact parity with `grade()` on `passed/expected/actual/message/marks_possible`, and `e2e/lab-builder-check-run.spec.ts` (browser) |
| 48 | Attempt diff ("since your last attempt") | ☑ | New `app/diff.py`: `compare()` walks two **stored** `grades.result` rows and classifies every check as `fixed / regressed / unchanged / added / removed`; `diff_for()` pairs an attempt with the previous attempt that **counted** (a `counts=False` auto-submit is stepped over). Reads the **newest** grade per attempt — the same row the results page uses — so a regrade is reflected without touching `task_results`. Student route `GET /api/attempts/{id}/diff` is redacted (`public=True`: no `expected`, `actual` or params, hidden checks keep their generic message, per PLAN §7b); `GET /api/instructor/attempts/{id}/diff` adds them. First attempt → `first_attempt: true` and an empty `tasks` list, not a wall of "added". UI: `components/attempt-diff.tsx` on the student results page and the instructor attempt view. Tests: `tests/test_attempt_diff.py` **10 passed** (all five classifications, redaction, first attempt, `counts=False` skip, ownership 403/404, regrade-follows-newest, determinism after sandboxes are gone) |
| 49 | Instructor course analytics | ☑ | `GET /api/instructor/courses/{id}/analytics` (`app/analytics.py`, `Authz(results_view)` + `load_course_for_staff`): per assignment — submission rate, average score under the assignment's grade policy, average attempts used, average completion time (`ready_at`→submit), late submissions — plus course totals, **most-failed tasks** and **most-missed checks** (top 10, counted attempts only) and **interruptions** broken down by `failure_reason` and always reported apart from student results. Fixed query count (enrolments, lab definitions, attempts, sessions, task results) aggregated in memory — no sandbox, no regrade, no query per student. Empty states for a course with no labs and for a course with no submissions. UI `/instructor/courses/[id]/analytics` (five stat cards + three tables), linked from the course page. Tests: `tests/test_course_analytics.py` **5 passed** including a **query-count assertion** (`q2 == q1` after doubling the data); browser `e2e/instructor-analytics.spec.ts`. CSV export left for later (nothing in the implementation made it free) |
| R7 | **Integration regression: M43 + M44a + M44 (VPC/SQS/SNS) + M45–M49 on `feat/authoring-excellence`** | ☑ | Release-gate audit of the merged branch (`1966557`) on an isolated project, then fixes and a full re-run on the default project (2026-09-29). **Found:** (a) M45's `lab-builder-autosave.spec.ts` / `lab-builder-check-run.spec.ts` still filtered `hasText: "Mission 1"`, which after M44's Missions 10–13 matched five rows (strict-mode violation, 5 E2E failures) — now the full title, as M44 already did in the other specs; (b) M49 course totals divided submitted (student, assignment) pairs by the student count only (the demo course showed **133%**) — `submission_rate` is now over students × assignments, the card reads "of expected submissions", and `test_course_submission_rate_counts_every_student_assignment_pair` (two assignments; fails on the old formula with 1.0 ≠ 0.5) guards it; (c) `vpc.spec.ts` screenshotted on the save banner, before the list reloaded — it now waits for the security group row to report 1 inbound rule. Screenshot `30-course-analytics` renumbered to **`36-course-analytics`** (M44 owns 30–35). The authz sweep now covers **181 protected routes** (192 total, 11 public). **Gate:** API **404 passed, 0 failed, 0 skipped** (incl. Docker and the two-runner gateway test); fast suite **351 passed, 53 deselected**; runner **16/16**; `app.labtest` on all **13 packs: 80/80 scenarios PASS** (Reset reproduces every break-fix baseline on moto and floci; Lambda packs on MiniStack); browser E2E **35/35, 0 skipped** (runner-local-2 registered); `tsc --noEmit` and `next build` clean; all 40 `docs/screenshots` regenerated on the default project. Docs brought in line: README, NEXT, ARCHITECTURE, TESTING, landing page service list |

**Maintenance** (branch `fix/maintenance` from `feat/authoring-excellence`; owner request 2026-10-05)

| # | Item | State | Verification evidence |
|---|---|---|---|
| M1 | API image split: Dockerfile `test` stage (requirements-dev) vs `runtime` stage (production); compose + `scripts/test-api.sh` use the test stage | ☑ | `docker compose build api api-test` clean. `cloudlabs/api:dev` runtime `pip list`: **no pytest/moto** (also enforced at build time by `! python -c "import pytest"` / `"import moto"`), `cloudlabs/api-test:dev` has pytest 8.4.2, pytest-asyncio 1.2.0, moto 5.2.3. Fast API suite on the rebuilt test stage: **351 passed, 53 deselected** (819 s, 2026-10-05) |
| M2 | Refuse insecure secrets at startup: API (`secret_key`, `runner_secret`) when `CL_DEMO_MODE=false`; runner (`RUNNER_SECRET`) always; known dev defaults / `change-me` / < 32 chars | ☑ | New `tests/test_config.py` in both services; API **12 passed**, full fast suite **363 passed, 53 deselected** (779 s); runner image rebuilt → `python -m pytest -q` **31 passed** (incl. Docker, 238 s). Dev/test secrets in compose raised to valid values; `production.env.example` / `runner.env.example` now document `openssl rand -hex 32` (2026-10-05) |
| M3 | Web dependencies: `next` 15.5.27 (latest 15.x), npm audit highs fixed (`postcss` 8.5.29, `sharp` 0.35.5 overrides), `npm install` fallback removed from the web Dockerfile; Next 16.x evaluated (report in D56) | ☑ | `npm audit` **0 vulnerabilities**; `npm run typecheck` clean; `next build` clean; `npm ci`-only web image built; full Playwright **35/35 passed** (14.3 min, runner-local-2 registered; first run was 34/35 on a one-off `runtime_unavailable` "no healthy runner" immediately after `fleet.spec`'s drain/resume — not reproduced, logged for M8 investigation); screenshots regenerated by the suite were reverted (dynamic content, unrelated to this item) (2026-10-05) |
| M4 | Python deps: `pip-audit` on both requirement sets, fix every advisory (only what's needed) plus patch releases | ☑ | Before: pyjwt 2.10.1 (20), cryptography 46.0.1 (13), python-multipart 0.0.20 (12), starlette 0.48.0 (12, both services). After: **pip-audit reports no known vulnerabilities** on `services/api/requirements.txt` and `services/runner/requirements.txt`. Bumps: fastapi 0.142.2 (lifts the starlette `<1.0` cap; starlette resolves to 1.7.0), pyjwt 2.15.1, cryptography 50.0.2, python-multipart 0.0.32, plus patch releases sqlalchemy 2.0.54, pydantic 2.11.10, boto3 1.40.76, pyyaml 6.0.3. Fallout found and fixed: FastAPI 0.142 stores included routers as `_IncludedRouter`, so the flat `app.routes` walks in `test_authz_coverage.py` (which then silently passed **vacuously** — only the allowlist test failed) and `test_signing.py::test_no_exec_endpoint` missed most routes; both now use the public `iter_route_contexts`, and an OpenAPI-surface guard pins the walk so it can't go vacuous again. Full API suite incl. Docker: **415 passed, 1 failed** (the walk test; scored as an M4 fix, re-run green `test_authz_coverage.py` **10 passed**); runner suite **31 passed** (real Docker). Final combined full-suite re-run recorded under M6 (2026-10-05) |
| M6 | CI + lint + architecture guard: `.github/workflows/ci.yml` (ruff, architecture test, fast API suite on Postgres, runner unit tests, web typecheck + build), `ruff.toml` (E4/E7/E9/F), `tests/test_architecture.py` (the file CLAUDE.md named did not exist) | ☑ | `ruff check services` (0.16.10) **all checks passed** after removing unused imports/variables (no behaviour change; `I` → `INS` in the role matrix for E741). `tests/test_architecture.py` in the API container **3 passed, 1 skipped** (runner half skipped there, runs in CI). Full fast suite with the lint edits **367 passed, 1 skipped, 53 deselected** (722 s); runner `-m "not docker"` **20 passed**. First GitHub run (`37367075073`): **Web typecheck + build** and **Runner unit tests** green; API and Ruff were cancelled before starting (*job was not acquired by Runner of type hosted* — a GitHub capacity issue). Jobs pinned to `ubuntu-24.04` (`ubuntu-latest` moves to Ubuntu 26 on 2026-10-19). CI fix: the architecture step ran before Postgres started (the autouse `clean_db` fixture needs the DB) — reordered. **GitHub run `37428993495`: Ruff, API, Runner, Web all green** (2026-10-06) |
| M5 | Terminal image: AWS CLI pinned (2.37.1, the version the suites were green on) and ttyd 1.7.7, both **sha256-verified**; amd64 + arm64 via `TARGETARCH`; versions as image labels | ☑ | amd64 build: `aws-cli/2.37.1`, `ttyd 1.7.7`, uid 10002; a wrong ttyd hash **fails the build**; arm64 (`buildx --platform linux/arm64`) builds and runs (`aarch64`, same versions). `cloudlabs/terminal:dev` rebuilt from it → docker-marked API suite **53 passed** (46 min: real terminal WebSocket, job containers, sandbox grading). With the fast run: **420 passed, 1 skipped** in total. Browser E2E on this image: see M9 (35/35) |
| M7 | Per-checkout Compose overrides moved to `infra/dev-isolation/` (+ README) and repaired | ☑ | Two regressions from M1/M2 found while moving: runner secrets of 21–29 chars (refused since M2) lengthened to ≥ 38; `api` and `api-test` shared one image tag per override although they build `runtime` and `test` — `api-test` now has its own tag. `docker compose config` resolves all three with unchanged build contexts and distinct images |
| M8 | Analytics CSV export (deferred in D52): `GET /api/instructor/courses/{id}/analytics.csv` + *Export CSV* on the analytics page | ☑ | One row per assignment plus an *All labs* totals row, same computation as the JSON, same formula neutralisation as the gradebook (`safe()` now shared), same access rule. `tests/test_course_analytics.py` new CSV test + scope assertions (404 other instructor, 403 student, 200 admin); with gradebook + authz coverage **20 passed**; ruff clean; `tsc --noEmit` clean; E2E `instructor-analytics.spec.ts` (downloads and checks header, row count and totals row) + `instructor-ops.spec.ts` **3 passed** on rebuilt images |
| M9 | Gateway re-resolves `api`/`web` (dev `infra/gateway/nginx.conf` + production `nginx-tls.conf`) | ☑ | Found by a full E2E run that failed **30/35 at the login page (502)**: `api`/`web` were recreated after the gateway started and nginx kept their old IPs. Now `resolver 127.0.0.11 valid=10s` + variables in `proxy_pass`. `nginx -t` on both configs; with `web` forced from 172.21.0.7 to .8 the untouched gateway still serves `/login` 200. **Full browser E2E 35/35 passed** (12.9 min, runner-local-2 registered) on the stack with every maintenance change (M1–M9) — 2026-10-06 |
| M10 | **Next 16** (branch `feat/next16`): next 16.3.8 (Turbopack builder), react/react-dom 19.3.0, @types/react(-dom) 19.3.0; the postcss/sharp `overrides` from M3 removed | ☑ | `npm audit --omit=dev` **0** without overrides (next 16 ships postcss 8.5.23, past the ≤ 8.5.22 range; sharp 0.35.5). `tsc --noEmit` clean, also with no `.next/` (CI runs typecheck before build); Next rewrote `tsconfig.json` (`jsx: react-jsx`, dev types) and `next-env.d.ts` itself. Turbopack `next build` clean, no warnings; standalone image serves (`Next.js 16.3.8`). **Full browser E2E 35/35** (13.0 min, runner-local-2 registered) — 2026-10-06. PR #3 CI: all four jobs green after one re-run — the first web build failed in Turbopack's `next/font/google` step (Google Fonts fetch on the runner; passed unchanged on re-run). **Known risk:** web builds download fonts at build time; self-hosting them with `next/font/local` would remove the network dependency |

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
- **D39 — Lab templates.** The New-lab flow offers curated templates instead of only a blank S3 skeleton
  (phase 9, milestone 40). A template is a built-in lab version resolved at request time
  (`app/instructor/templates.py::TEMPLATES`), so a teacher always starts from the installed,
  labtest-verified content; creating a draft copies the pack under a new id (`<title-slug>-<short id>`) and the
  teacher's title at `1.0.0`. Unlike Clone, it is not a "copy" of a mission — it is the teacher's own new lab.
  `available: false` hides a template whose built-in pack is not installed. Break-fix setup scripts are carried
  read-only, keeping the v1 scope (no setup authoring) until milestone 41.
- **D40 — Typed break actions (owner decision: option A only).** A break-fix starting state is declarative
  data, never instructor-written shell: `lab.yaml`'s `break_actions` (typed, validated by `app/breakfix/`) are
  compiled by a pure, order-preserving function into the setup script `setup_job` runs, so the same lab always
  produces the same broken state and Reset reproduces it. `baseline.expected_score` (default 0, must be below
  full marks) replaces the hard-coded "empty = 0"; `private/expected.yaml`'s `empty` must match it, so a lab
  may intentionally start partly correct. Import validation refuses unknown action types, bad parameters, a
  service not listed in `services`, and actions an engine cannot perform; a lab uses `break_actions` or a
  legacy setup script, never both. The Lab Builder's Starting state tab generates forms from each action's
  Pydantic schema, shows the Broken State Summary, and never exposes a raw setup editor. labtest adds a
  `reset` scenario for break-fix packs (setup → baseline → Reset → baseline, which must match). The
  interactive preview sandbox (M41b) is not built yet.
- **D41 — Demo one-click sign-in.** The login page lists the seeded demo accounts and their shared password,
  so a demo starts with one click instead of typing. The data comes from a public `GET /api/auth/demo-accounts`
  that is empty unless `CL_DEMO_MODE=true`, and it only lists accounts that actually exist (the endpoint reads
  the DB), so a fresh stack or a real deployment never advertises credentials or dead buttons.
- **D42 — Public brand: Stackora.** The public product name is **Stackora** ("Launch it. Break it. Fix it.").
  Only user-facing surfaces and public docs changed; Python/Node packages, Docker images, database
  identifiers, environment variables, migration history, API contracts and the repository codename stay
  `cloudlabs` for compatibility. `/` is the public marketing site (no auth; the global auth guard exempts
  it), `/login` is the only authentication page, and the authenticated application is unchanged.
- **D43 — Preview sandboxes.** An authored lab can be inspected before testing: `POST .../preview-sandbox`
  creates a real runner sandbox with the compiled declared setup (same isolation, limits and env as a student
  lab) and stores it in `lab_drafts.last_preview` (sandbox id, engine, endpoints, encrypted ttyd credential).
  It is **not** a session: no attempt, grade, XP, badge or leaderboard row is ever created and there is no
  submit path. The console and terminal routes serve both a student session and a preview:
  `AuthzAny(session.use, lab.manage)` lets the role matrix through, and the resource check (session
  ownership, or draft ownership/admin for a preview) decides — anyone else gets 404. The reconciler treats a
  running preview as known and destroys it after `preview_ttl_s` (1800 s) idle. New log events
  `preview.started/reset/stopped/destroy.failed` were added to the fixed set (PLAN §14). The
  publish-readiness checklist is computed from the same validation and test data the publish gate uses, so
  the UI can never show "ready" while `publish` would refuse.
- **D44 — Instructor first-run journey.** The product proves itself with an end-to-end journey
  (`e2e/instructor-first-run.spec.ts`) that starts from an empty account and reaches a graded student result
  using only the browser: create a course, import a roster, create a lab from a template, edit tasks/checks
  with the generated forms, configure the starting state with typed actions, launch the preview sandbox,
  clear the readiness checklist, run the test in real sandboxes, publish, assign, complete the lab in the
  console only, and drill into the instructor's evidence. It is the M43 acceptance test.
  `docs/INSTRUCTOR-QUICKSTART.md` documents the journey with screenshots; the instructor home shows a
  first-run card when the account has no courses, and the Labs page links the guide. No product blockers
  were found: the journey passed unchanged apart from test-side fixes.
- **D45 — Lambda + DynamoDB combined lab (M44).** Mission 7 pins `runtime.emulator: ministack` because only
  MiniStack executes Lambda code. MiniStack's DynamoDB support was verified operation by operation (the same
  12 contract ops as moto/floci are now declared `supported` in `ministack.yaml`, and the contract test runs
  on all three engines), so the lab can grade both services and the DynamoDB console becomes available in
  MiniStack labs. The combined task is proven by the probe order: the invocation runs before the other
  collectors, so a hidden `dynamodb.item` check sees the row the function wrote. Partial = 55 (table +
  function, no save), solution = 100. New template `lambda-dynamodb`.
- **D46 — `create_user` retries only real `short_id` collisions (M45).** The old guard was
  `if "short_id" not in str(e): raise`, but `str(IntegrityError)` also contains the whole `INSERT`
  statement — which lists every column of `users`. **Any** integrity failure on that table (a duplicate
  email above all) therefore looked like a short-id collision, was retried ten times with a fresh argon2
  hash each, and surfaced as the misleading `RuntimeError: could not allocate short_id`. `_violated_column()`
  now reads the **constraint name** from the server message (text before `[SQL:`), falling back to the
  driver's `constraint_name`, so a duplicate email raises immediately and a genuine collision still
  retries. This was found while debugging a test failure that the old message pointed away from.
- **D47 — Tests must not hardcode the runner id.** Two tests pinned `runner-local-1`
  (`test_state_recovery._mk_session` writing `lab_sessions.runner_id`, and `test_fleet`'s `A`), which is
  only correct when `CL_RUNNER_ID` happens to have its default; under any other runner id they fail on a
  foreign key (`lab_sessions_runner_id_fkey`) or on capacity/scheduler assertions. Both now read
  `get_settings().runner_id`. Combined with `infra/docker-compose.m45.yml`, this lets a second and third
  checkout run their own project (own project name, ports, runner ids, sandbox env and app image tags)
  so containers, networks, volumes, runners and test databases are never shared — the interference this
  milestone first ran into was a concurrent suite truncating the same test database.
- **D48 — The draft's save revision is a content hash, not `updated_at`.** Autosave has to know whether
  the content it edited is still the content on the server. `updated_at` looked tempting but moves on
  every row write — a validate run, a test run, a status change — which would tell a teacher their own
  in-flight save was "changed somewhere else". `drafts.rev` is instead a sha256 over canonical JSON of the
  draft content (`dr.fingerprint`), deliberately independent of the lab being *valid*, because a draft is
  allowed to hold half-finished work. It is exposed on both the full and list responses, echoed back as
  `base_rev`, and a mismatch is 409 `stale_revision` carrying the server's `rev` so the client can tell the
  user precisely what happened. Omitting `base_rev` keeps working for callers that just re-read the draft.
- **D49 — The single-check runner lives on the preview router and stores nothing.**
  `POST .../preview-sandbox/check` was placed with the preview lifecycle so it inherits exactly the same
  access rule (owner/admin, else 404) and the same "is a sandbox running?" gate, rather than growing a
  second ownership path. It calls `registry.get(type).fn` on `ev.capture(...)` output — the identical code
  `grade()` uses — with only that check's collector, and never writes a row: no attempt, grade, evidence,
  badge or leaderboard event (asserted by `test_single_check_runs_...` and `nothing_graded()`). It is
  serialised by a module lock and spaced per draft by `CL_PREVIEW_CHECK_MIN_INTERVAL_S` (429 +
  `Retry-After`) so a double-click can't flood the emulator with captures. Capability and unsupported-type
  problems are checked before any capture; in practice the pack validator rejects those first (the run then
  answers 422 with the same row-level errors the validation panel shows), so the pre-check is defence in
  depth and is unit-tested directly.
- **D50 — Stale test sandboxes starve the E2E runner (found during M46 regression).** `scripts/test-api.sh`
  runs with `CL_BACKGROUND_LOOPS=false`, so the reconciler and janitor never run inside a test process;
  sandboxes left behind by a docker-marked run are only reaped by the *next* run's reconciler. Six orphans
  from `env=test` had accumulated against `RUNNER_MAX_SANDBOXES=4`, and the Lab Builder E2E failed with
  `preview_unavailable: runner is at capacity` — a capacity failure wearing a product-looking face. Two
  take-aways recorded here: check `docker ps -a --filter label=cloudlabs.runner=<id>` before blaming a
  regression for a capacity error, and cleaning a checkout's own sandboxes between suites is legitimate
  housekeeping. Two other leftovers belonged to the other checkouts' projects (`runner-authoring`,
  `runner-m44`) and were correctly left alone.
- **D51 — The attempt diff compares stored grades, not task results.** `task_results` is written once per
  attempt, but a regrade only appends a `grades` row — so diffing `task_results` would show a student a
  per-check story that contradicts the score their results page is showing. The diff therefore reads the
  **newest** `grades.result` for each attempt (exactly what `_attempt_result` already renders), which makes
  a regrade follow automatically and keeps the comparison reproducible from immutable rows. "Your previous
  attempt" is the previous attempt with `counts=True`: an auto-submit that changed nothing was never the
  student's work, and comparing against it would report a wall of regressions they never caused. Students
  get `public=True` (no `expected`/`actual`/params, hidden checks keep their generic message — PLAN §7b);
  instructors get the same rows plus those fields, so one code path serves both.
- **D52 — Analytics is five queries and keeps interruptions out of the averages.** The report reads
  enrolments, the pinned lab definitions (for titles and a truthful `max_score` even when nobody started),
  attempts, sessions and task results, then aggregates in memory — no query inside a loop, asserted by
  `test_analytics_issues_a_fixed_number_of_queries`, which doubles the data and requires the statement count
  to stay identical. A `FAILED` session is counted under **interruptions** with its `failure_reason` and is
  never folded into a submission, an attempt or an average: a lost sandbox is the platform's failure, not
  the student's. Failure rates use counted attempts only. CSV export was **left for later** — nothing about
  the in-memory aggregation made it fall out for free, and a second format is a second thing to keep correct.
- **D53 — Two ways an isolated checkout silently loses its sandbox network (found while getting the M47
  browser test green).** (a) `DockerDriver._count_active()` counts this runner's `component=network`
  labels, so a **network whose containers are gone still holds a seat**. Force-removing containers by hand
  (the fix for D50) left six networks behind, and because control-plane containers stay connected to them
  (PLAN/D1) they could not be deleted — the runner then answered `runner is at capacity` for over an hour
  while `docker ps` showed nothing. Recovery is `docker network disconnect -f <network> <container>` (note
  the order: **network first**) then `docker network rm`. Normally the reconciler reaps rowless sandboxes
  through `list_sandboxes(env)`, which is why this only bites outside a running API process.
  (b) The `api` service's `cloudlabs.env` **label** is built from `${CL_ENV:-demo}` — the *shell* variable —
  while the container's own `CL_ENV` comes from `environment:`. Overriding only the environment (as an
  isolation file does) leaves the API labelled `demo` while its sandboxes are `m45`, so the runner never
  attaches the control plane and every console/terminal/grading call dies with `ConnectTimeoutError`. The
  override now sets the label explicitly; anyone adding an isolation file must do the same. Related: all
  three checkouts run `api-test` as `cloudlabs.env=test`, so their control planes attach to each other's
  test sandboxes — harmless for assertions, but another reason D47's per-project ids matter.
  Test side: `e2e/journey.spec.ts` no longer hardcodes `runner-local-1` (reads `CLOUDLABS_RUNNER_ID`),
  the same rule `fleet.spec.ts` already followed for runner2. (c) An isolation file must also **keep**
  `http://localhost:3000` in `CL_ALLOWED_ORIGINS`: `test_integration_docker.py` sends that as the
  WebSocket Origin for the terminal ticket rules, so trimming the list to the checkout's own port failed
  five Docker-marked tests with `terminal.ticket.rejected / origin_not_allowed`. All five pass with the
  list restored.
- **D54 — The API image has a `test` stage and a `runtime` stage (maintenance M1).** `services/api/Dockerfile`
  is now `base` (python 3.12-slim, the `api` user, requirements files) → `test` (adds
  `requirements-dev.txt`: pytest, moto) and `runtime` (`requirements.txt` only). The `runtime` stage is
  declared **last**, so any plain `docker build` (e.g. someone building the context directly, or the
  production compose overrides) produces the production image; it also fails the build if `pytest` or
  `moto` can be imported, so a future dependency change can't silently reintroduce them.
  `infra/docker-compose.yml` builds `api` with `target: runtime` (`cloudlabs/api:dev`) and `api-test`
  with `target: test` (`cloudlabs/api-test:dev`), and `scripts/test-api.sh` now builds `api-test` before
  `up`, so test runs can never reuse a stale image. Isolation override files keep their own image tags
  but must repeat the target (M7 moves them under `infra/dev-isolation/`).
- **D55 — Insecure secrets are refused at boot (maintenance M2).** With `CL_DEMO_MODE=false`, the API
  refuses `CL_SECRET_KEY` / `CL_RUNNER_SECRET` if the value is a known dev default (the ones previously
  shipped in `config.py` / compose / the isolation overrides), contains `change-me`, or is shorter than
  32 characters; the error names the variable and suggests `openssl rand -hex 32`. Demo mode stays the
  documented dev/presentation escape (a fresh checkout boots with known credentials on purpose). The
  runner has no demo mode and can destroy sandboxes, so it applies the same check to `RUNNER_SECRET`
  **always**. Consequences: the dev compose runner/runner2 secrets become long values (the API's
  `api-test` runs with `CL_DEMO_MODE=false` and the HMAC secret must match the runner service, so both
  read the same `${CL_RUNNER_SECRET:-…}`), `api-test` gets its own test `CL_SECRET_KEY` (the dev one is
  refused outside demo mode), and `test_fleet`'s runner2 default + `docs/TESTING.md`'s runner command
  were aligned. `production.env.example` and `runner.env.example` now say to generate each secret with
  `openssl rand -hex 32`.
- **D56 — Next stays on 15.x for now; 16.x is a separate upgrade (maintenance M3).** `next` was bumped
  15.5.26 → **15.5.27** (the current 15.x backport, and the highest stable 15.x on npm). The two audit
  highs were transitive pins that next 15.x's own ranges already allow: an `overrides` block pins
  `postcss` 8.5.29 (next pins 8.4.31, vulnerable ≤ 8.5.22) and `sharp` 0.35.5 (next allows
  `^0.34.3 || ^0.35.4`; 0.34.5 was vulnerable). `npm audit` is now 0. The web Dockerfile no longer falls
  back to `npm install` if `npm ci` fails: the committed lockfile is the only dependency source, so a
  broken lock fails the build instead of silently resolving new versions. **Next 16.3.8 evaluation:**
  checked against the official 15→16 guide and this codebase — no `middleware`/`proxy`, no `next/image`,
  no `searchParams`, no `cookies()`/`headers()` in server code (all dynamic pages are client components
  using `useParams`), no `serverRuntimeConfig`, no parallel routes, no custom webpack config, no
  `next lint` script; Node 22 satisfies the new 20.9+ floor. The remaining risk is the switch to
  **Turbopack as the default builder** and the React 19.2 canary runtime, which need a dedicated
  verification pass (typecheck + Turbopack build + full E2E) rather than riding along with a security
  patch. Recommendation: schedule Next 16 as its own change after this maintenance batch; the 15.x
  backport channel keeps receiving security fixes meanwhile. *Done as maintenance M10 (Next 16.3.8, E2E 35/35).*
- **D57 — The Python bump is vulnerability-driven; FastAPI 0.142 needed a route-walk fix (maintenance
  M4).** `python-multipart` (0.0.20 → 0.0.32), `pyjwt` (2.10.1 → 2.15.1) and `cryptography` (46.0.1 →
  50.0.2) are self-contained security bumps; our uses (multipart uploads, HS256 encode/decode, Fernet
  for terminal credentials/secrets) are unchanged APIs. Starlette's advisories are only fixed in 1.x,
  and FastAPI capped starlette below 1.0 until **0.133.0**, so the minimal fix was to move FastAPI to
  the current 0.142.2 (its only new hard dependency is `opentelemetry-api`). FastAPI 0.142 registers
  included routers as `_IncludedRouter` objects instead of flattening them into `app.routes`; the flat
  walks in `test_authz_coverage.py` and `test_signing.py` therefore saw almost no routes — the authz
  coverage tests would have passed **vacuously** (the authz sweep silently shrank from 181 protected
  routes to a handful; only the public-allowlist test failed). Both tests now enumerate the effective
  routes through the public `fastapi.routing.iter_route_contexts`, and
  `test_route_walk_sees_the_openapi_surface` pins the walk to `app.openapi()["paths"]` so a future
  representation change fails loudly instead of hiding a route without `Authz`. Remaining patch-level
  bumps: sqlalchemy 2.0.54, pydantic 2.11.10, boto3 1.40.76, pyyaml 6.0.3 (no other same-minor patch
  existed for the pins). `pip-audit` is clean on both requirement files.
- **D58 — CI runs the fast gates only (maintenance M6).** GitHub Actions runs ruff, the architecture
  invariant, the API suite without Docker markers (against the repo's own Postgres service and roles),
  the runner unit tests and the web typecheck/build. The Docker-marked API tests, `app.labtest` and the
  Playwright E2E need sandbox images and stay a local / pre-release gate (`scripts/test-api.sh`,
  `apps/web/e2e`). `tests/test_architecture.py` scans imports by AST (no false positives from comments or
  strings), proves non-vacuity on a synthetic violation, guards against an empty scan root, and checks
  the runner side when its sources are present.
- **D59 — Terminal downloads are pinned and checksummed (maintenance M5).** The AWS CLI was "latest" and
  ttyd had no integrity check, so a rebuild could change student tooling silently or ship a tampered
  binary. Both are now pinned with per-architecture sha256 values (ttyd from the release's SHA256SUMS; AWS
  publishes PGP signatures but no checksums, so the hashes were taken from the pinned zips). Bumping a
  version means updating its hash. The emulator engines (Floci, MiniStack) are upstream images and keep
  their own architecture support.
- **D60 — Flake 15a is closed as not reproducible.** For the app role the append-only check cannot depend on data: UPDATE/DELETE are
  revoked, so both statements fail with *permission denied* even on an empty table. A failure of
  `test_append_only...[attempts]` can only come from its setup (`_submitted`: the submit must answer 200)
  or from another suite truncating the same test database (D47). Not reproduced in 8 runs, 20 stress rounds
  (120 executions) and an independent 10-round check (50 executions).
- **D61 — The gateway resolves services per request (maintenance M9).** nginx resolves a literal
  `proxy_pass` host once at startup, so a recreated `api` or `web` container (any upgrade, or
  `docker compose up --build` after the gateway is running) left the gateway pointing at a dead IP and
  every route answered 502 until the gateway restarted. Both nginx configs use Docker's embedded DNS
  (`resolver 127.0.0.11 valid=10s ipv6=off`) and `proxy_pass $api_upstream` / `$web_upstream`; with no URI
  part in the variable, the request URI is passed unchanged, exactly as before.
