# CloudLabs — a college hands-on AWS lab platform with auto-grading

## Context
The college wants something like AWS Academy / Skill Builder labs (which run on Vocareum): students do cloud labs in the browser, and the platform **checks the real state of what they built** and gives marks. Real AWS accounts are expensive and risky, so every student gets an **isolated simulated AWS cloud running in Docker**. Students can work through a **simplified, AWS-style web console (GUI)** or the **real AWS CLI in a browser terminal**. Both change the same backend state, so the grader doesn't care which one was used.

Other platforms we researched: AWS Academy/Vocareum (auto-grading with scripts and API checks, LMS sync over LTI), Killercoda/KodeKloud (a `verify.sh` for each step that inspects real state, not marker files), Instruqt (challenges plus check scripts).

Constraints: build a prototype on a Windows laptop (Docker Desktop + WSL2) first. The lab runtime has to be isolated and able to move to several college servers **without rewriting the app**. Supported services for now: **S3, EC2, IAM, Lambda, DynamoDB** only. It should be fun, not a pixel copy of the AWS console.

Note: the LocalStack Community Edition was archived in March 2026. We will use **Moto in server mode** (Apache-2.0, mature, supports all five services) behind an adapter, so we can later swap to MiniStack or LocalEmu if needed.

---

# ▶ EXECUTION MODE (binding)
- **Step 0 of implementation:** copy this plan into the repo as `docs/PLAN.md` (the source of truth for scope, architecture, phases and acceptance criteria). Also create `docs/STATUS.md` (a milestone checklist with verification evidence) and `CLAUDE.md` (conventions + these execution rules + "re-read docs/PLAN.md before architectural decisions").
- Work autonomously through the approved slice-1 build order: implement → run tests → fix → re-run until green → update `docs/STATUS.md` → next milestone. **No "should I continue?" check-ins.**
- **Stop and ask only for:** a product decision that is genuinely missing and can't be inferred; a destructive or irreversible action outside the project; credentials, paid services or permissions; the repo state materially conflicting with the plan; or a major architectural flaw.
- **No scope expansion.** IAM/EC2/Lambda/DynamoDB, advanced gamification and multi-server scheduling stay stubbed in slice 1.
- **"Done" means verified**: unit + integration + E2E tests pass, including the full student journey through **both GUI and CLI**, and the cleanup has been checked.

# ▶ CURRENT SCOPE: Vertical Slice 1 (build and fully test this first)

**Flow:** sign in → start the S3 lab → isolated sandbox (Moto + terminal) → do tasks in the **browser terminal** or the **S3 console GUI** → check progress / submit → **deterministic grader** → result **stored in Postgres** → sandbox **cleaned up**.

**In scope:** auth (email/password, roles student/instructor), one lab pack (`s3-basics`), `SandboxDriver` + `DockerDriver`, emulator and terminal images, WebSocket terminal proxy, S3 console (list/create/delete buckets, versioning toggle, upload/list/delete objects), grader with `s3.*` checks, attempts + task results in the database, a TTL/idle cleanup loop, and an orphan janitor on startup. The instructor gets a minimal results table for that one lab.

**Stubbed but interface-compatible (not built now):**
| Area | Stub in slice 1 | Future swap |
|---|---|---|
| Runner | **A separate Runner Agent process** (`services/runner`, FastAPI, the only thing holding the Docker socket). The API talks to it only through `RunnerClient` → `HttpRunnerClient` (HMAC + timestamp over localhost/internal network in slice 1; mTLS is added on top later, see §10). The API **never** imports the Docker SDK, and a test enforces this. | more runners + mTLS + scheduler |
| Redis / queues | none; grading is synchronous, cleanup is an asyncio loop in the API (`app/tasks/janitor.py`) | arq worker + Redis |
| Audit | `AuditSource` protocol → `NullAuditSource`; `audit.*` checks are registered but raise `NotSupportedInSlice` | proxy-backed audit source |
| Other services | check registry namespaces `iam/ec2/lambda/dynamodb` exist and are empty; the console nav shows them as "Coming soon" | fill in the modules |
| Gamification, multi-server, LTI, analytics | not built | roadmap phases below |

**Slice 1 files:**
```
infra/docker-compose.yml            postgres, api, runner, web
services/runner/app/                main.py (typed ops, HMAC auth), driver.py (SandboxDriver), docker_driver.py
images/emulator/Dockerfile          moto[server] pinned, runs `moto_server -H 0.0.0.0 -p 5000`
images/terminal/Dockerfile          aws-cli v2 + ttyd, non-root "student", AWS_ENDPOINT_URL set at run time
services/api/app/
  main.py, config.py, db.py, models.py (User, Lab, LabSession, Attempt, TaskResult), alembic/
  auth/            register/login, JWT cookie, role dependency
  runtime/         runner_client.py (RunnerClient protocol + HttpRunnerClient with HMAC signing), capabilities/
  sessions/        start/get/stop/reset endpoints; default one active sandbox per student across all labs (MAX_ACTIVE_SESSIONS_PER_STUDENT)
  terminal/        WS proxy: browser ⇄ API ⇄ ttyd in the student's container (authorised by session owner)
  console/s3.py    boto3 client built from the session's emulator endpoint; tag source=console
  labs/            loader.py (YAML + Jinja variables, Pydantic schema), packs read from /labs
  grader/          registry.py, engine.py, checks/s3.py, stubs for other namespaces
  tasks/janitor.py TTL/idle expiry + orphan removal by container label `cloudlabs.session=<id>`
labs/s3-basics/lab.yaml, solution.sh, partial.sh
apps/web/
  app/(auth)/login, app/labs, app/labs/[id]/play (split: task panel | tabs [Console | Terminal]),
  app/instructor/results, components/console/s3/*, components/terminal (xterm.js + attach addon)
```

**Key decisions:**
- **Driver:** each session gets its own Docker bridge network (`internal=true`, no egress) holding the emulator and terminal. Labels identify containers for cleanup. Limits: memory 256–512m, cpus 0.5, pids 256.
- **Laptop networking (amended during implementation, see STATUS.md decision D1):** Docker cannot publish ports from `internal: true` networks, so the "127.0.0.1 published port" idea is replaced by the planned *Dockerised API on shared network* mode: the API runs in a container labelled `cloudlabs.role=control-plane`; when the runner creates a sandbox it connects every control-plane container with the same `cloudlabs.env` to that sandbox's internal network and returns container IPs as endpoints. The API still never talks to Docker, and sandboxes still have no egress and can't reach each other.
- **Grader is deterministic:** it reads only the sandbox state through boto3, with variables fixed per attempt (`student_short_id`). The same state always gives the same score. Results are stored per task with check messages.
- **Submit** closes the attempt, stores the score, then tears down the sandbox. **Check progress** grades without storing a final result.

## Student console fidelity principle (added after slice-1 review, STATUS D7)
- The CloudLabs dashboard, lab briefing, checklist/score/timer, grading, instructor and admin UIs keep
  **our own design**.
- The **student cloud console** prioritises **AWS conceptual fidelity**: AWS terminology, resource
  hierarchy, navigation patterns and the major configuration workflows (e.g. S3 → Buckets → Create bucket
  with Region / Object Ownership / Block Public Access / Bucket Versioning / Tags; bucket tabs Objects |
  Properties | Permissions | Management | Metrics). Not a pixel clone, no AWS branding.
- The AWS CLI stays **standard AWS CLI syntax**; the terminal states that the endpoint is redirected to the
  student's isolated training cloud.
- Unsupported simulator features are **visibly labelled** ("Not available in CloudLabs simulator"), never
  silently omitted.
- Lab hints are **progressive** (where to look first, the CLI help command later), not copy-paste answers.
- Later: an "Interface mode: Guided / AWS-style" switch (not in slice 1).

## Emulator strategy (binding, added after the emulator evaluation — see EMULATOR-EVALUATION.md)
1. The S3 slice stays on **Moto** until the full regression suite (runner, API, labtest, contract, E2E) is green
   after the console-fidelity changes.
2. **Floci** is then added through the existing emulator abstraction: a runner-side emulator table plus an
   API-side `EmulatorAdapter` registry. Moto and Floci satisfy the same CloudLabs emulator interface.
   Emulator-specific behaviour must not leak into the grader, lab definitions (beyond `runtime.emulator`),
   FastAPI service contracts or the student UI.
3. Floci needs `capabilities/floci.yaml`, Floci contract tests, labtest, the S3 E2E flow, and isolation +
   session-freeze tests. It is **promoted to default only if all of these pass**. Moto stays a supported
   fallback/regression backend.
4. **Lambda:** evaluate MiniStack through the same abstraction, and use it only if Floci cannot safely run
   the required Lambda lab behaviour without giving the student sandbox Docker access. Never adopt it just
   for having more features.
5. **Floci UI** (MIT): adapt useful code and patterns into our Next.js console (DynamoDB, IAM, EC2, Lambda),
   keeping license notices (`THIRD_PARTY_NOTICES.md`). Never embed it as the student console and never
   expose its generic cloud proxy.
6. **Boundary:** no frontend component talks to an emulator or to Floci UI's proxy. Every student cloud operation
   goes Next.js → FastAPI service-specific endpoint → authz / session state / capability checks →
   `EmulatorAdapter` → the selected emulator. CloudLabs owns auth, isolation, ownership, grading freeze,
   capability filtering, AWS-style UI, deterministic grading, evidence, attempts and lifecycle.
7. After promotion: DynamoDB next, then the remaining roadmap in order, following the execution-mode loop.

## Architecture hardening decisions (these apply to slice 1)

### 1. Lab session state machine
```
REQUESTED → PROVISIONING → READY ⇄ RESETTING
                 │            │
                 ▼            ├──(submit | ttl/idle/close expiry)──▶ SUBMITTING → SUBMITTED → TERMINATING → TERMINATED
               FAILED ◀───────┴──(sandbox lost / provisioning error / grading infra error)       ▲
                 └─────────────────────────────────────────────────────────────▶ TERMINATING ─┘
```
- The allowed transitions are one table in `sessions/state.py`. All changes go through `transition(session_id, from_states, to_state, reason, actor)`, which runs `UPDATE lab_sessions SET state=:to, version=version+1 WHERE id=:id AND state IN :from AND version=:v`. If 0 rows change, the result is `409 invalid_state`. There are no other writes to `state`.
- Every transition appends a row to `session_events` (from, to, reason, actor, request_id, ts). The table is append-only.
- Long Docker work never runs inside a database transaction. The transient state (`PROVISIONING`, `RESETTING`, `SUBMITTING`, `TERMINATING`) is the lock, and it has a `state_deadline_at` for recovery.

### 2. Idempotent Start / Reset / Submit + concurrency
- **Active-session limit**: by default **one active sandbox per student across all labs**, set by `MAX_ACTIVE_SESSIONS_PER_STUDENT` (default 1). This was chosen for laptop capacity. In the Start transaction, `pg_advisory_xact_lock(user_id)` is taken and active sessions are counted before insert. A partial unique index `lab_sessions(user_id, assignment_id) WHERE state IN (active states)` always guarantees at most one active session per student per assignment. Raising the limit means changing the config only.
- **Start** `POST /assignments/{id}/sessions`: if an active session exists for the same assignment, return it (`200`). If it is for another assignment, return `409 other_session_active` with a link to it. Otherwise insert `REQUESTED`. A unique-violation race is caught and the winner's row is returned. When the session reaches FAILED or TERMINATED, a new Start creates a new session.
- **Reset** and **Submit** need an `Idempotency-Key` header (a UUID from the client). The `idempotency_keys(user_id, key, endpoint, response_hash, response_body, created_at)` table replays the stored response. The same key with a different body gives `422`. Keys expire after 24h.
- Reset: `READY→RESETTING` (CAS), destroy the containers but keep the network, recreate, rerun `setup`, then `→READY`. It doesn't use up an attempt. Terminals are disconnected with the close reason `reset`.
- Double-clicking Submit or submitting from two tabs gives one CAS winner. The loser gets `409` with `attempt_id` pointing at the winner's result. The UI shows that result.
- **Cleanup and expiry never race grading or reset.** The janitor and TTL expiry act only through CAS from `READY`. A session in `SUBMITTING` or `RESETTING` is skipped until its operation finishes or its deadline passes, and then the reconciler handles it. Reset and Submit both CAS from `READY`, so only one can win.
- Runner capacity is reserved in the Start transaction with `SELECT … FOR UPDATE` on the `runners` row (active count < max), so parallel Starts can't provision past the limit.

### 3. Crash recovery and DB↔Runner reconciliation
A `reconciler` loop runs at API startup and every 30s:
| DB state | Runner has sandbox? | Action |
|---|---|---|
| PROVISIONING past deadline (3 min) | any | destroy by label → FAILED(`provision_timeout`) |
| READY / RESETTING | no | FAILED(`sandbox_lost`); the attempt is not used up |
| RESETTING past deadline | yes | destroy → FAILED(`reset_timeout`) |
| SUBMITTING past deadline | evidence stored | finish: → SUBMITTED → TERMINATING |
| SUBMITTING past deadline | no evidence, sandbox alive | retry capture + grade (at most 2 times), then FAILED(`grading_failed`) with the attempt not used up |
| TERMINATING / TERMINATED / FAILED | yes | destroy (idempotent) → TERMINATED if it was TERMINATING |
| no row | yes (label `cloudlabs.session`) | orphan → destroy |

- `DockerDriver.destroy` is idempotent ("not found" counts as success). Containers and networks carry the labels `cloudlabs.session`, `cloudlabs.runner`, and `cloudlabs.env` (so dev and test don't reap each other).

### 4. Sandbox persistence policy
- **Ephemeral by design.** There are no volumes. Moto state lives only in memory. Closing the browser does **not** end the session, and reopening reattaches.
- **Idle timeout** is 20 min with no terminal input, console API call or heartbeat (the page sends a heartbeat every 60s while visible). A warning banner shows at 15 min.
- **Hard TTL** = `lab.duration_minutes` (the maximum is 120), and the timer is shown in the UI.
- **Expiry** (idle, TTL, or the assignment `close_at`) triggers an **auto-submit** (`trigger=idle|ttl|close`), so work is graded before it is lost. **Whether it uses up an attempt is decided from graded state, not from activity counters:** right after provisioning + `setup`, the runner reaches READY only after the API captures a **baseline evidence snapshot** (`grading_evidence.kind=baseline`). On automatic expiry, the final evidence is captured and the **normalized graded-resource state** (collector output with volatile fields such as timestamps and request IDs removed) is compared against the baseline. If it is unchanged, the attempt is stored with `counts=false` (visible to the instructor, but not using up the attempt). If it changed, `counts=true`. **An explicit Submit always uses up an attempt.**
- A runner or API restart that loses the sandbox → `FAILED(sandbox_lost)`. The student sees "Restart lab" and the attempt is not used up.
- Instructors see interrupted sessions (FAILED with a reason) on the results page and can **reopen**: grant +1 attempt or extend the student's `close_at`. This is logged as a `session_events`/`grades` action with the actor.
- Persistence across machine restarts (Moto state snapshots) is explicitly **out of scope** for now.

### 5. Exact Submit semantics
1. CAS `READY → SUBMITTING`. The terminal WebSockets are closed (`1000, "submitted"`) and console mutations return `409 session_frozen`.
2. **Capture evidence**: the collector for each check namespace takes a raw snapshot (for S3: every bucket, its versioning, its policy, and the object list with key/size/etag, capped at 1,000 objects). It is canonical JSON with a `sha256`.
3. **Grade** = a pure function `grade(lab_version, variables, evidence) → task results`. No live calls are made during scoring.
   Each check produces an explainable record, which is stored in `task_results.checks jsonb`:
   `{task:"t2", check:"s3.versioning", params:{bucket:"cafe-ab12-site"}, expected:"Enabled", actual:"Suspended", passed:false, marks_awarded:0, marks_possible:20, message:"Versioning is Suspended; expected Enabled"}`.
   Students see `message`, `passed` and marks. Instructors also see `expected`/`actual` and the raw evidence.
4. In one transaction: insert `grading_evidence`, `attempts(attempt_no, trigger, late, score, max_score, grader_version, lab_version_id, emulator_image_digest)` and `task_results`, then `→ SUBMITTED`.
5. Tear down asynchronously (`→ TERMINATING → TERMINATED`).
- **Attempts**: each Submit uses one attempt (up to `max_attempts`). After that, Start is refused with `attempts_exhausted`. The final grade uses the assignment's `grade_policy`: `best` (the default) or `latest`.
- **Windows**: before `open_at`, Start is refused. Between `due_at` and `close_at`, the attempt is marked `late=true` (only if `allow_late`). After `close_at`, Start and Submit are refused, and active sessions are auto-submitted.
- **Check progress** grades a live snapshot and does not store it (it goes to logs only). It is rate-limited to 1 per 10s per session and doesn't count as an attempt.
- If there is an infrastructure error during capture or grading, the attempt is not used up, the session goes to FAILED(`grading_failed`), and the UI explains this.

### 6. Immutable grading evidence
- `grading_evidence(id, attempt_id, sha256, payload jsonb, captured_at)` and `attempts` are append-only. A Postgres trigger rejects UPDATE/DELETE, and the app DB role has no UPDATE/DELETE grant on these tables.
- **Regrade** (instructor/admin) runs `grade()` on the **stored evidence** with the current or a chosen grader version. It inserts a new `grades` row (`attempt_id, grader_version, score, created_by, reason`) and never changes the original. The gradebook shows the newest grade row and links to the full history.

### 7. YAML schema versioning + immutable lab versions
- `lab.yaml` needs `schema_version: 1` and `version: <semver>`. `labs/schema/v1.py` is a Pydantic model with `extra=forbid`. The loader sends each schema version to its own model, and an unknown version is rejected.
- Import creates a `lab_versions` row (`lab_id, version, content_sha256, yaml_text, files tar blob, capabilities_required, created_at`), and the row is immutable. Importing the same version with a different hash is rejected.
- An **assignment pins `lab_version_id`**. Editing a lab means importing a new version, and existing assignments don't change. A version that assignments reference can't be deleted.
- Lab runtime: `runtime: { emulator: moto }` maps to the platform's pinned **image digest**, which is recorded on each session and attempt.

### 7b. Reference solutions never reach students
- A lab version is stored as two bundles: **`public`** (`lab.yaml` student view, `setup` assets) and **`private`** (`solution.sh`, `partial.sh`, hidden checks (`hidden: true`), answer notes, instructor-only files).
- `setup` runs in a **short-lived setup container** on the sandbox network, which is removed before READY. The terminal image holds nothing lab-specific, and the runner's `create_sandbox` gets only the public bundle.
- Student APIs return a **redacted lab view** (story, task titles, hints, marks). They never include check definitions, expected values of hidden checks, or private files. For hidden checks, students get only a generic failure message.
- The private bundle is readable only by `labtest`/CI and the instructor/admin tooling.
- Tests: `docker exec` a find/grep over the terminal filesystem for solution content returns nothing, and every student endpoint's response is checked for private-bundle strings.

### 8. Moto capability declarations
- `services/api/app/runtime/capabilities/moto.yaml` lists the supported operations for each service (slice 1: `s3:CreateBucket, DeleteBucket, ListBuckets, Get/PutBucketVersioning, Put/Get/Delete/ListObject(s)V2, HeadObject, Get/PutBucketPolicy, Get/PutBucketTagging`), plus the **known limitations** shown to authors:
  - IAM is not enforced (any credentials work).
  - The S3 static-website endpoint is not served.
  - Presigned URLs are unreliable through the proxy.
  - State is only in memory.
  - Checksum/ACL behaviour is partial.
  - EC2 is metadata-only and Lambda needs Docker access (both out of scope for the slice).
- Every operation or feature has a **support level**: `supported` (Moto behaves like AWS for our purposes), `simulated` (CloudLabs implements it, e.g. our IAM policy evaluator later), or `unsupported`. Example: `s3:PutBucketWebsite: {level: unsupported, note: "config stored, endpoint not served"}`. The console hides or labels anything that isn't `supported`/`simulated`.
- A lab declares `requires: [s3:CreateBucket, …]`. Import fails if any operation is missing from the capability file. Checks declare the operations they read, and those are validated the same way.
- **Contract tests** (`tests/contract/test_moto_s3.py`) run every declared operation against the pinned image. If the image digest is bumped, those tests must pass in CI.

### 9. Backend authorization matrix
One policy module, `auth/policy.py`: `authorize(actor, action, resource)` is called on every route, and a test makes sure every route is covered.
| Action | Student | Instructor | Admin |
|---|---|---|---|
| List assignments / view lab | own enrolments | courses they teach | all |
| Start / Reset / Submit / Check progress | own sessions only | ✗ (they use preview mode later) | ✗ |
| Terminal WS / console API on a session | owner, only while READY | ✗ (read-only viewing is for later) | ✗ |
| View own attempts, results, feedback | ✓ | — | — |
| View class results / evidence / session events | ✗ | courses they teach | all |
| Regrade, extend deadline, add attempts | ✗ | courses they teach | all |
| Import lab version, create assignment | ✗ | ✓ (their courses) | ✓ |
| Kill session / manage runners / users | ✗ | ✗ | ✓ |
- Loading a resource that belongs to someone else returns **404** (not 403), so IDs can't be enumerated. Session IDs are UUIDv4.
- Auth: an httpOnly, Secure, SameSite=Lax cookie holding a JWT that lasts 15 min, plus a refresh token that lasts 7 days, rotates, and is stored hashed. Mutating routes need a CSRF double-submit token. Passwords use argon2id. Login is rate-limited.

### 10. Control Plane ↔ Runner authentication
- Slice 1: the runner is a separate process on `127.0.0.1` (or the internal compose network only). Every request carries `X-Runner-Timestamp` + `X-Runner-Signature = HMAC-SHA256(secret, method|path|body_sha256|ts)`, and a request outside the 30s window is rejected. Only the runner holds the Docker socket, and it is never mounted into sandboxes. The runner API offers only typed operations (`create_sandbox, destroy_sandbox, reset_sandbox, status, list_sandboxes, capacity`). **There is no generic exec endpoint.** The runner runs setup/solution scripts only from lab-pack content the API sends by `lab_version_id` + hash.
- **Built in slice 1:** HMAC + timestamp over the internal/localhost network only. Requests carry `X-Request-ID`. The runner acts only on containers carrying its own `cloudlabs.runner` label. Heartbeats (`capacity, active, version`) use the same signed channel.
- **College deployment (NOT built in slice 1):** mTLS **plus** the same HMAC, a private CA, a runner accepting only the control plane's client certificate, and the control plane pinning each runner's certificate by `runner_id`. Slice 1 only keeps `HttpRunnerClient` ready for this: TLS settings are config fields that are unused for now, and the request format and signing don't change.

### 11. Terminal / WebSocket authorization
1. `POST /sessions/{id}/terminal-ticket` (cookie + CSRF + owner + state READY) returns a random 256-bit ticket that is **single-use**, lasts **30s**, and is stored hashed with `(session_id, user_id)`.
2. `WS /ws/terminal?ticket=…`: the ticket is consumed atomically, the `Origin` is checked against an allowlist, and the ticket is redacted from logs.
3. The API reaches ttyd over the sandbox's internal network (decision D1; nothing is published on the host), using per-session random ttyd basic-auth credentials (`ttyd -c`). Those credentials are never sent to the browser.
4. A session can have at most 2 terminals open. The proxy watches for state changes and closes the socket with a reason code (`submitted|reset|expired|failed`). The frame size limit is 64 KiB. Input counts as activity for the idle timer.

### 12. Per-sandbox quotas (Docker `HostConfig`)
| | emulator (Moto) | terminal |
|---|---|---|
| CPU | `nano_cpus` 0.5 | 0.5 |
| RAM (hard, no swap) | 384 MiB | 256 MiB |
| PIDs | 128 | 128 |
| Disk | `read_only` rootfs + tmpfs `/tmp` 32 MiB | `read_only` + tmpfs `/home/student` 64 MiB, `/tmp` 32 MiB |
| Security | non-root, `cap_drop ALL`, `no-new-privileges` | same |
- These are platform defaults in `config.py`. A lab can set `resources:` overrides, and they are clamped to admin-set caps (≤1 CPU and ≤1 GiB for each container, TTL ≤120 min, idle between 10 and 30 min).
- The network is `internal: true` (no egress). S3 object data sits in Moto's memory, so it is capped by the RAM limit, and console uploads are capped at 5 MiB per object. The TTL comes from §4.
- If the emulator is OOM-killed, the session goes to FAILED(`sandbox_lost`), and the UI says "Your sandbox ran out of memory — restart lab."

### 13. Runner capacity / full behaviour
- `runners(id, max_sandboxes, active, mem_budget_mib, status, last_heartbeat)`. The laptop default is `max_sandboxes=4` (slice 1 has one runner row, seeded at startup).
- If Start happens when the runner is full, the response is **`503 capacity_full`** with `Retry-After: 60`, and no session is created. There is no queue in slice 1. The UI shows "All lab seats are in use (4/4). Retrying automatically…" and retries with **increasing delay: 3s → 5s → 8s → 12s (then every 12s), with ±20% jitter**. There is also a cancel button, and it never polls in a tight loop.
- If a runner is unhealthy (no heartbeat for 90s, or the Docker ping fails), it isn't scheduled, and Start returns `503 runtime_unavailable`.

### 14. Structured observability
- IDs: `request_id` (generated or taken from `X-Request-ID`, and echoed back), `user_id`, `session_id` (also used as the sandbox ID), `attempt_id`, `runner_id`, `lab_version_id`, `container_id`.
- **structlog** writes JSON logs with contextvars, so every log line in a request or background job carries these IDs. Secrets and tickets are redacted by a processor.
- Each state transition is written to `session_events` (the source of truth) and also logged. The Docker driver logs each call with its duration.
- Log events have fixed names: `session.created`, `session.transition`, `sandbox.create.started|succeeded|failed`, `sandbox.destroy.started|succeeded|failed`, `terminal.ticket.issued|rejected`, `terminal.connected|closed`, `grader.progress`, `grader.submit.started|finished|failed`, `evidence.stored`, `grade.regraded`, `reconciler.action`, `janitor.orphan_removed`, `runner.unavailable`, `capacity.rejected`, `authz.denied` — amended during implementation (STATUS D3) with `assignment.override.granted`, `http.request.failed`, `background.task.failed` and `runner.reattach_failed` (runner). Each carries `user_id, assignment_id, session_id, sandbox_id, attempt_id, runner_id` when they apply.
- `/metrics` (Prometheus): `sessions_active`, `provision_seconds`, `grading_seconds`, `session_failures_total{reason}`, `capacity_rejections_total`. `/healthz` checks the database and Docker.
- Every error response has the shape `{error: {code, message, request_id}}`, and the UI shows the request ID in failure dialogs.

### 15. Failure UX
| Situation | What the student sees | Action offered |
|---|---|---|
| Provisioning > 20s | progress steps (network → emulator → terminal) | wait |
| `capacity_full` | "All lab seats in use, retrying…" | auto-retry / cancel |
| `provision_timeout` / `runtime_unavailable` | "Couldn't start your lab (ref: req-id)" | Try again |
| Terminal disconnect | "Reconnecting…" (5 tries with backoff) | Reconnect button |
| `sandbox_lost` / out of memory | "Your sandbox stopped. Your attempts are unaffected." | Restart lab |
| Console call fails (Moto 4xx/5xx) | inline toast with the AWS error code + request ID | retry |
| Idle warning | banner with a countdown | "I'm here" |
| Auto-submitted on expiry | results page with a trigger badge | view results |
| `grading_failed` | "Grading failed; this attempt wasn't counted." | Restart lab |
| `attempts_exhausted` / closed | disabled Start with the reason | view best result |
| `409 session_frozen` during submit | the console is disabled with "Submitting…" | — |

### 16. Demo Mode (developer/presentation tooling, not student product scope)
- `DEMO_MODE=true` enables deterministic seed data: `demo-admin`, `demo-instructor`, `demo-student1..3` (fixed passwords, **refused when `DEMO_MODE` is off**), the course "Cloud Computing Demo", an open assignment of `s3-basics`, and fixed `student_short_id`s.
- **One command:** `scripts/demo-reset.ps1` / `scripts/demo-reset.sh` → `python -m app.demo reset`. It destroys all sandboxes labelled `cloudlabs.env=demo` through the runner, wipes and reseeds the demo rows, imports the lab pack, checks database + runner + emulator image health, and prints a pass/fail summary with the login details.

### 17. Runtime status view (after the core slice is green, must not delay it)
- An admin page `/admin/status` backed by `GET /admin/runtime-status`. It shows runner health + last heartbeat, active/max sandboxes, database health, p50/p95 provisioning latency (last 1h), and session failures by reason (last 24h). It reads the existing `session_events`, the `runners` table and the metrics, so no new telemetry is needed.

### 18. Documentation deliverables (`docs/`)
`PLAN.md`, `STATUS.md`, then as milestones land: `ARCHITECTURE.md`, `SECURITY.md`, `LAB-AUTHORING.md`, `TESTING.md`, `SCALING.md`, and **`DEMO.md`**. DEMO.md is a reproducible teacher script: demo-reset → student creates an S3 bucket in the **GUI** → proves it in the **CLI** (`aws s3 ls`) → changes it from the CLI (versioning + upload) → proves it in the GUI → **Check progress/submit fails deliberately** on a missing task → fix it → score 100 → log in as instructor and show the result + per-check evidence → show the sandbox containers/networks gone (`docker ps -a --filter label=cloudlabs.session`).

### Data model (slice 1)
`users, courses, enrolments, labs, lab_versions, assignments(lab_version_id, open_at, due_at, close_at, allow_late, max_attempts, grade_policy), runners, lab_sessions(state, version, state_deadline_at, runner_id, emulator_port, ttyd_port, ttyd_cred_enc, image_digest, variables jsonb, last_activity_at, expires_at), session_events, attempts(…, counts bool), task_results(checks jsonb), grading_evidence(kind baseline|final, …), lab_version_bundles(public|private), grades, idempotency_keys, terminal_tickets, refresh_tokens`.

**Slice 1 build order:** docs (PLAN/STATUS/CLAUDE.md) → compose + database + auth → images → DockerDriver + session API (+ janitor) → WS terminal → lab loader + grader + `s3-basics` → labtest CLI → S3 console UI → lab player page → instructor results → end-to-end tests → demo mode + DEMO.md → runtime status view → remaining docs.

**Additional slice-1 modules from the hardening pass:** `sessions/state.py` (transition table + CAS), `sessions/reconciler.py`, `idempotency.py`, `auth/policy.py`, `terminal/tickets.py`, `grader/evidence.py` (collectors), `grader/grade.py` (pure scoring), `labs/schema/v1.py`, `runtime/capabilities/moto.yaml`, `obs/logging.py`, `obs/metrics.py`, a migration adding the append-only triggers, and `tests/contract/`.

**Slice 1 is done when:**
1. `pytest` passes: loader schema, each `s3.*` check, grader scoring (0 / partial / 100), auth and ownership (student B can't touch A's session or terminal).
   - It also passes these: every allowed and every illegal state transition; 20 parallel Starts give 1 session; parallel Submits give 1 attempt; an Idempotency-Key replay returns the same body; the route-coverage test for the authorization matrix; an expired, reused or wrong-user ticket is rejected; UPDATE/DELETE on evidence fails; regrade adds a new grade row; the same evidence gives the same score; capacity full returns 503 and nothing is created; each reconciler table row is simulated (kill containers, stop the API mid-provision, stale states); a lab needing an undeclared capability is rejected at import; a Moto contract test covers each declared operation.
2. `python -m app.labtest labs/s3-basics` gives an empty sandbox → 0, `partial.sh` → the expected partial score, `solution.sh` → 100.
3. Integration: after TTL expiry or submit, `docker ps -a --filter label=cloudlabs.session` and `docker network ls` show nothing left. Restarting the API removes orphans. The terminal container can't reach the internet or another session's emulator.
4. Playwright E2E: create the bucket in the **GUI**, enable versioning and upload in the **terminal**, check progress shows both, submit → the score is stored → the instructor results page shows it.

---

# Full roadmap (reference; build after slice 1 is green)

## Refined project prompt (the brief to use from now on)
> Build **CloudLabs**, a web platform where college students do guided, hands-on AWS labs in a safe simulated cloud and get marked automatically.
> - Each lab session starts an **isolated sandbox** (Docker network + AWS emulator + terminal container) for that student, with a timer and automatic cleanup.
> - Students complete tasks through a **simplified AWS-style console** (S3, EC2, IAM, Lambda, DynamoDB) **or** a browser terminal with the preconfigured `aws` CLI. Both act on the same sandbox.
> - Labs are defined as **versioned YAML lab packs**: story, tasks, hints, starting resources, and **declarative checks with marks**.
> - A **grading engine** inspects the live sandbox state (and the API call log) to confirm each step was really done, gives partial marks per task, and stores results in a gradebook.
> - **Gamified**: mission storyline, live task checklist, XP, badges, class leaderboard, simulated "cloud bill", live architecture diagram, break-fix and challenge modes.
> - Roles: **student, instructor, admin**. Covers courses and classes, lab assignments with due dates, a gradebook and CSV export, analytics, and a lab authoring and test tool.
> - Architecture: **Next.js** frontend, **FastAPI** control plane, **PostgreSQL**, **Redis**, and a separate **Runner Agent** that manages containers. It runs on one laptop now and scales to several servers by adding runners.

---

## Architecture

```
Browser (Next.js)
  ├─ Console UI (S3/EC2/IAM/Lambda/DynamoDB)  ──HTTP──▶ FastAPI Control Plane ──boto3──▶ student's emulator
  ├─ Terminal (xterm.js)  ──WebSocket──▶ Control Plane (proxy) ──▶ terminal container (ttyd)
  └─ Task panel / Check / Submit ───────▶ Control Plane ──▶ Grader ──boto3──▶ student's emulator
Control Plane ──HTTP/gRPC──▶ Runner Agent(s) ──Docker API──▶ sandboxes
Postgres (users, labs, attempts, grades)   Redis (sessions, queues, pub/sub)   Worker (grading, cleanup)
```

**Per-student sandbox** (one Docker network per session, no internet access):
1. `emulator`: Moto server, with an **API-audit proxy** in front that logs every AWS call (service, action, params, source=cli|console, timestamp).
2. `terminal`: a small image with `aws` CLI v2, `jq`, `python3`, `zip`, and `~/.aws/config` set to point at the emulator endpoint, served over `ttyd`. Runs as a non-root user.
3. Optional **EC2 "real instance" containers**: when a student launches an EC2 instance, the runner also starts a tiny Alpine container, so "connect to instance" opens a real shell (the fun part). Moto holds the metadata; the runner syncs the container lifecycle with start/stop/terminate.

**The runtime abstraction is the key to scaling later.** The control plane never calls Docker directly. It calls a `RunnerClient` → the **Runner Agent** (small FastAPI service) → a `SandboxDriver` interface (`create/destroy/exec/status/endpoint`).
- Now: one runner on the laptop with `DockerDriver`.
- Later: one runner on each college server, with a scheduler that picks the least-loaded runner. Swarm or Kubernetes drivers can be added the same way. The app code doesn't change.

**Isolation and safety:** cgroup limits (CPU, memory, pids), no Docker socket in student containers, read-only root filesystem where possible, a per-sandbox network, egress blocked, idle timeout plus a hard TTL, and a janitor that removes orphans. gVisor (`runsc`) can be added later.

---

## Lab pack format (`labs/<lab-id>/lab.yaml`)
```yaml
id: s3-static-website
title: "Mission 1: Launch CloudCafé's website"
services: [s3]
duration_minutes: 45
max_attempts: 3
variables: { bucket: "cafe-{{student_short_id}}-site" }   # per-student names stop students copying each other
setup: setup.py            # optional starting resources (e.g. a broken policy for break-fix labs)
tasks:
  - id: t1
    title: Create bucket {{bucket}}
    hints: ["Use the S3 console or `aws s3 mb`"]
    marks: 20
    checks:
      - { type: s3.bucket_exists, bucket: "{{bucket}}" }
  - id: t2
    title: Enable versioning
    marks: 20
    checks: [{ type: s3.versioning, bucket: "{{bucket}}", status: Enabled }]
  - id: t3
    title: Upload index.html
    marks: 30
    checks:
      - { type: s3.object_exists, bucket: "{{bucket}}", key: index.html }
      - { type: audit.called, action: s3:PutObject }        # proves the step really happened
solution.sh: ...           # reference solution, used to test the lab automatically
```
- Built-in check library (Python, one function per check): `s3.*`, `ec2.instance(state, type, tags, sg_rule)`, `iam.user/role/policy_attached/policy_allows` (policy statements are evaluated by our own simulator, because Moto doesn't enforce IAM), `lambda.function(runtime, handler, env)`, `lambda.invoke_returns`, `dynamodb.table(keys, billing)`, `dynamodb.item`, `audit.called/order`. Custom `python:` checks are the fallback.
- **Check progress** (live, costs no marks) is separate from **Submit** (final, limited attempts). Tasks can give partial marks, and there is optional feedback text per failed check.

---

## Features

**Student**
- Dashboard with assigned labs, due dates, XP/level, badges, streak.
- Lab player: story brief, a task list that ticks green live, hints (can cost XP), a split view with the console and terminal, timer, reset lab.
- **Simplified console** for 5 services with the AWS feel (service menu, resource tables, create wizards), plus a **live architecture diagram** that draws the resources the student creates.
- **Simulated cost meter** ("your bill: $3.42/hr") to teach cost awareness.
- Results page: marks per task, what failed and why, the reference explanation after the due date.

**Fun / gamification:** mission storylines (the "CloudCafé" startup arc), XP and badges ("First Bucket", "Least Privilege Hero"), class leaderboard (can be turned off), **break-fix labs** (fix a broken setup), **challenge mode** (goal only, no steps), speed-run times, confetti when a lab is finished.

**Instructor:** classes and roster CSV import, assign labs with a window, due date and attempts; gradebook plus CSV export; progress in real time for each student (which task they're on); view a student's API audit log; regrade; extend deadlines; analytics (tasks with the most failures).

**Admin:** users and roles, runner health and capacity, active sandboxes (kill/extend), lab pack upload, and a **lab tester** (runs `solution.sh` → must score 100%; an empty sandbox → must score 0).

**Later:** Google/college SSO, LTI 1.3 (Moodle/Canvas grade passback), plagiarism signals (identical audit timelines), certificates, quizzes.

---

## Repo layout (monorepo in `e:\projects\CLOUD LABS`)
```
apps/web/                 Next.js (App Router, TypeScript, Tailwind, shadcn/ui, xterm.js, React Flow for the diagram)
services/api/             FastAPI control plane (SQLAlchemy + Alembic, Pydantic, JWT auth, WebSocket terminal proxy)
  app/console/            per-service console endpoints → boto3 against the student's emulator
  app/grader/             check registry, engine, IAM policy evaluator
  app/labs/               lab pack loader/validator (YAML + Jinja variables)
services/runner/          Runner Agent + SandboxDriver (DockerDriver first)
services/worker/          background jobs: grading, TTL cleanup, leaderboard (arq/Redis)
images/terminal/          Dockerfile: aws-cli v2 + ttyd, non-root
images/emulator/          Moto server + audit proxy (mitm-style reverse proxy logging to Redis)
images/ec2-instance/      tiny Alpine "instance" image
labs/                     lab packs (starter set below)
infra/docker-compose.yml  postgres, redis, api, worker, runner, web
docs/                     architecture, lab authoring guide
```

## Build phases (after slice 1; phases 1–3 partly done by the slice)
1. **Foundation**: compose stack, auth (email/password + roles), Postgres models (User, Course, Class, Lab, Assignment, Session, Attempt, TaskResult, AuditEvent, Badge).
2. **Sandbox runtime**: Runner Agent + DockerDriver, emulator + terminal images, session start/stop/TTL, WebSocket terminal in the browser. *Milestone: open a lab → a working `aws s3 ls` against your own sandbox.*
3. **Grader + lab packs**: YAML schema, check library for all 5 services, audit proxy, check progress/submit, lab tester CLI. *Milestone: S3 lab graded end to end from the CLI.*
4. **Console UI**: S3 → IAM → DynamoDB → EC2 → Lambda (code editor, zip upload, test invoke). Both GUI and CLI act on the same sandbox.
5. **Instructor/admin**: classes, assignments, gradebook, CSV export, live progress, runner dashboard.
6. **Fun layer**: XP, badges, leaderboard, cost meter, architecture diagram, break-fix/challenge labs, EC2 instance shells.
7. **Multi-server readiness**: runner registration + heartbeats, scheduler, load test (e.g. 50 sandboxes), hardening, deployment docs.

**Starter labs (8):** S3 static site · S3 versioning and lifecycle · IAM users, groups and a least-privilege policy · IAM break-fix (over-permissive policy) · EC2 launch with security group and tags · DynamoDB table + CRUD · Lambda hello-world + invoke · capstone: Lambda + DynamoDB + S3 "order processor".

---

## Verification
- **Each lab is tested automatically**: `python -m cloudlabs.labtest labs/<id>` spins up a sandbox, runs `solution.sh` → asserts 100%, then a fresh sandbox with no actions → asserts 0%, then a partial solution → asserts the expected partial marks. This runs in CI for every lab pack.
- Unit tests for each check type and for the IAM policy evaluator (pytest). API tests with httpx.
- Isolation tests: student A's terminal can't reach student B's emulator; no internet egress; containers are removed after the TTL.
- Playwright end-to-end: log in as a student → start the S3 lab → do step 1 in the GUI and step 2 in the terminal → check progress shows both → submit → the instructor gradebook shows the marks.
- Local run: `docker compose up` on Windows (Docker Desktop, WSL2 backend), then open `http://localhost:3000`.
