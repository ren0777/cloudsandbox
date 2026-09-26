# CloudLabs architecture (vertical slice 1)

Source of truth for decisions: [PLAN.md](PLAN.md). Changes made during implementation: [STATUS.md](STATUS.md) (D1–D9).

## Components

```
Browser ──http://localhost:3000──▶ gateway (nginx)
                                     ├─ /        → web  (Next.js, standalone)
                                     ├─ /api/*   → api  (FastAPI control plane)
                                     └─ /ws/*    → api  (terminal WebSocket proxy)
api ──HMAC-signed HTTP──▶ runner (FastAPI + Docker SDK; the ONLY component with the Docker socket)
api ──SQL (app role)──▶ postgres (owner role for migrations / maintenance)
api ──boto3 / WebSocket over the sandbox network──▶ emulator (Floci | Moto) / terminal (ttyd)
```

| Component | Path | Responsibility |
|---|---|---|
| Web | `apps/web` | Student dashboard, lab player (mission checklist, S3 console, xterm.js terminal), results, instructor results/evidence, admin runtime status |
| API | `services/api/app` | Auth, authorization, session state machine, grading, console proxy, terminal proxy, reconciler, janitor |
| Runner | `services/runner/app` | Typed sandbox operations over the `SandboxDriver` protocol (`DockerDriver`) |
| Emulator engines | `images/emulator-floci` (**default**), `images/emulator` (Moto, regression backend), `images/emulator-ministack` (specialised: labs that execute Lambda code) | Floci 2.1.0 / Moto 5.2.3 / MiniStack 1.5.16, non-root, read-only rootfs, no Docker socket |
| Terminal image | `images/terminal` | AWS CLI v2 + ttyd, non-root; also used for one-off *job containers* (setup, labtest) |
| Lab packs | `labs/<id>` | `lab.yaml` (schema v1) + `public/` + `private/` |

## Emulator abstraction (PLAN emulator strategy)
- **Runner:** an `EmulatorSpec` table (`image`, `port`, `tmpfs`, `env`, `endpoint_by_ip`) per engine. The sandbox's engine is
  recorded as the `cloudlabs.engine` label, so reset and jobs reuse it.
- **API:** `app/runtime/emulators.py` `EmulatorAdapter` (capabilities + boto3 client factory).
  `lab_sessions.engine` is resolved at Start (`runtime.emulator: default` → `CL_DEFAULT_EMULATOR`, currently
  `floci`). Grader checks, evidence format, console endpoints and the UI are engine-agnostic.
- **Student cloud operations** always go Next.js → FastAPI service endpoint (`/console/s3`,
  `/console/dynamodb`, `/console/iam`, `/console/ec2`, `/console/lambda`) → ownership + session-state (freeze)
  checks → **capability check** (`console/common.py::aws_call` rejects any operation the session's engine
  doesn't declare supported/simulated with `409 not_in_simulator`) → adapter → emulator.
- **Engines:** `ENGINES` (floci, moto) must each run every `default` lab; `SPECIALISED` (ministack) is used
  only by labs that pin it. A console service shows in the nav only if every operation its page needs is usable.

## A sandbox
One per session: a Docker bridge network `cl-sbx-<session>` with `internal: true` (no egress). It holds:
- `…-emulator`: the session's engine (Floci on :4566 by default, Moto on :5000), alias `emulator`
- `…-terminal`: ttyd on :7681 (alias `terminal`), `aws` preconfigured with `endpoint_url=http://emulator:<port>`
- short-lived `…-job-*` containers for setup scripts / labtest

The runner connects control-plane containers (`cloudlabs.role=control-plane`, same `cloudlabs.env`) to
the network (decision D1), so the API reaches the emulator and ttyd by container IP. Sandboxes can't
reach each other or the internet (tested in `services/runner/tests/test_docker_driver.py`).

## Session lifecycle
`app/sessions/state.py` is the only writer of `lab_sessions.state`. Every transition is a row-locked
compare-and-set on (state, version) that appends to `session_events` and logs `session.transition`.

```
REQUESTED → PROVISIONING → READY ⇄ RESETTING
                 │            ├─ submit / ttl / idle / close → SUBMITTING → SUBMITTED → TERMINATING → TERMINATED
                 ▼            ├─ stop / admin kill ───────────────────────────────→ TERMINATING
               FAILED ◀───────┴─ sandbox lost / OOM / provisioning / reset / grading infra error
```

- **Start** (`service.start_session`): an advisory lock per student and a configurable active-session
  limit, with a partial unique index as a backstop. Runner capacity is reserved under `SELECT … FOR
  UPDATE`. Provisioning runs as a background task and captures a **baseline** evidence snapshot
  before READY.
- **Submit** (`service.submit`): CAS READY→SUBMITTING first (terminals close, console answers 409
  `session_frozen`, reset/expiry/cleanup can't act). Then evidence capture → pure `grade()` → one
  transaction inserting the attempt, final evidence, task results, the initial grade, and →SUBMITTED.
  Teardown follows.
- **Expiry** (`tasks/janitor.expire_once`): auto-submit from READY only. It uses up an attempt only if the
  normalized graded state differs from the latest baseline.
- **Reconciler** (`sessions/reconciler.py`): the PLAN §3 table, run at startup and every 30 s.

## Grading
`grade(definition, variables, evidence)` is pure (no I/O). Collectors (`grader/evidence.py`) read
stable fields only (no timestamps), so baseline comparisons and regrades are deterministic. Evidence is
canonical JSON with a sha256 and a normalized sha256. Checks live in `grader/checks/` (s3, dynamodb, iam, ec2, lambda). A check may declare a *probe* (e.g. a
Lambda invocation) that the collector runs first during capture, so its result is evidence too. IAM decisions use the CloudLabs evaluator
(`grader/iam_eval.py`, support level `simulated`), which also powers the console's Policy simulator. The `audit` namespace exists as
a stub that is rejected at import.

## Data
PostgreSQL 16, Alembic migrations `0001` (schema), `0002` (`lab_sessions.engine`) and `0003` (phase 5:
`audit_events`, `users.must_change_password`, `lab_sessions.last_progress`). Append-only tables (`attempts`, `task_results`,
`grading_evidence`, `grades`, `session_events`, `student_overrides`, `lab_versions`,
`lab_version_bundles`, `audit_events`) are protected by triggers and by missing UPDATE/DELETE/TRUNCATE grants for the
app role.

## Instructor and admin (phase 5)
| Module | Routes | Notes |
|---|---|---|
| `instructor/courses.py` | courses, roster, roster preview/import, enrolments | CSV preview → token → all-or-nothing commit |
| `instructor/routes.py` | results, attempt evidence, regrade, overrides, assignments CRUD | lab version fixed once started |
| `instructor/gradebook.py` | course gradebook, course/assignment CSV | bulk queries; same final-score rule as the student view |
| `instructor/live.py` | live sessions, terminate (grade/discard), extend | reads stored progress summaries only |
| `admin/manage.py` | users, course staff, all sessions, audit log (+ course audit for instructors) | |
| `audit.py` | `record()` | fixed action set, same transaction as the action |

## Learning layer (phase 6)
| Module | What | Source of truth |
|---|---|---|
| `diagram.py` | architecture graph | collector evidence: a live read-only snapshot (`service.inventory`, no probes, cached 5 s) or stored final evidence |
| `cost/` | simulated cost estimate | collector evidence + versioned price table `cost/pricing/<version>.yaml` |
| `insights.py` | graph + cost for the Architecture tab, result pages, instructor attempt view | the two above |
| `gamification.py` | XP (derived), levels, badges (append-only `user_badges`) | counted attempts, latest grade, final evidence |
| `fun.py` | `/me/progress`, course leaderboard, course settings (audited) | `courses.leaderboard` (off/anonymous/named) |

Migration `0004`: `user_badges` (append-only), `courses.leaderboard`.

## Runner fleet (phase 7)
| Module | What |
|---|---|
| `runtime/fleet.py` | seed/register runners (signed probe, encrypted per-runner secret), pull heartbeats, `runner_lost`, CLI `python -m app.runtime.fleet list/register/drain/resume` |
| `runtime/scheduler.py` | `pick_runner()`: healthy, not draining, engine-compatible, free seat, least loaded; advisory lock |
| `runtime/runner_client.py` | `client_for(runner)` / `client_for_id(id)`: one signed client per runner; sessions always use their own runner |
| `sessions/reconciler.py` | the PLAN §3 table per runner, plus the runner-lost rules |
| `admin/runners.py` | list, register, drain/resume, retire (audited) |
| runner `gateway.py` | `RUNNER_ACCESS_MODE=gateway`: per-sandbox emulator HTTP and terminal WebSocket forwarding for runners on other servers |
| `loadtest.py` | end-to-end class simulation over the real API (`docs/LOADTEST.md`) |

Migration `0005`: runner registry columns (secret, drain, engines, host stats, reachability) and an index on
`lab_sessions(runner_id, state)`.

## Observability
structlog JSON with correlation IDs (`request_id`, `user_id`, `assignment_id`, `session_id`,
`sandbox_id`, `attempt_id`, `runner_id`). Event names come from a fixed set (`app/obs/events.py`),
and tests fail on unknown names. Prometheus `/metrics` is internal only (the gateway doesn't route it). `/healthz` is
exposed. The admin *Runtime status* page reads `runners`, `lab_sessions` and `session_events`.
