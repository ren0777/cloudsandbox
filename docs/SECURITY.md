# CloudLabs security model (slice 1)

## Trust boundaries
| Boundary | Control |
|---|---|
| Browser → API | httpOnly `cl_access` JWT (15 min) + rotating refresh token (7 days, stored hashed, reuse revokes the family); CSRF double-submit (`cl_csrf` cookie ↔ `X-CSRF-Token`) on every mutation; argon2id passwords; login rate limit (10/min per IP+email) |
| Authorization | `auth/policy.py`: `Authz(action)` on every route (role matrix, PLAN §9). A test fails if any route lacks it. Other people's resources answer **404**. Session IDs are UUIDv4 |
| Browser → terminal | 256-bit **single-use** ticket, 30 s TTL, stored hashed, bound to (session, user). Origin allowlist. Session must be READY. At most 2 terminals. Frame limit 64 KiB. Closed on any state change |
| API → runner | HMAC-SHA256 over `METHOD\|PATH\|SHA256(BODY)\|TS`, ±30 s window, internal network only. **No generic exec endpoint** (typed ops only). The runner acts only on objects labelled with its own id. mTLS + certificate pinning are specified for the college deployment (PLAN §10) |
| API → ttyd | per-session random basic-auth credential, Fernet-encrypted at rest, never sent to the browser |
| Runner → Docker | only the runner mounts the Docker socket. The API never imports the Docker SDK (test-enforced) |

## Sandbox hardening (PLAN §12)
Per container: `cap_drop: ALL`, `no-new-privileges`, non-root UID, read-only rootfs + size-limited tmpfs,
memory limit without swap, CPU quota, PID limit. The network is `internal: true` (no egress). No
volumes. Labs may override resources only within admin caps (≤1 CPU, ≤1 GiB, TTL ≤120 min, idle
10–30 min). The runner clamps again independently. Verified by `services/runner/tests/test_docker_driver.py`
and `services/api/tests/test_integration_docker.py` (no egress, no reaching another sandbox).

## Lab confidentiality (PLAN §7b)
Lab versions are stored as a **public** bundle (lab.yaml + `public/`) and a **private** bundle
(`private/`: solutions, expected scores, notes). Only the public bundle is ever sent to the runner for
setup. Private scripts run only in labtest job containers, never in student sandboxes. Student APIs
return a redacted lab view (no checks, no expected values). Hidden checks show a generic message.
Integration tests search the student terminal's filesystem for private files.

The **Lab Builder** (phase 8) keeps the same boundary. A draft holds private files (reference solutions,
expected scores, notes) and is visible only to its owner or an admin — every draft route answers **404** to
anyone else (`auth/policy.py::load_draft_for`). The **preview** endpoint returns the same redacted
`student_lab_view` as the student API, never checks or private files. **Export** (which includes the private
bundle) is staff-only, and an authored lab is visible to its author and admins until it is *shared* with all
instructors. Publishing is gated on a passing real-sandbox test of the exact content hash and imports an
immutable version owned by the author; `import_package(owner_id=…)` refuses an id that belongs to another
owner, so a draft can never add a version to a built-in mission or someone else's lab. Draft creation,
publishing and sharing are audited (`lab.draft_created`, `lab.published`, `lab.shared`).

## Staff actions and accounts (phase 5)
- **Role matrix additions:** `course.manage` (courses, roster, enrolments), `session.manage` (live view,
  terminate/extend), `audit.view` for instructors and admins; `admin` for users, course staff, all sessions and
  the global audit log. Instructors act only on courses they teach (`load_course_for_staff`,
  `load_session_for_staff`); anything else answers **404**.
- **Audit trail:** every instructor/admin mutation writes an append-only `audit_events` row in the same
  transaction (actor, role, course, assignment, student, session, details, request id). No foreign keys, so
  the trail can't be removed by deleting what it describes. Instructors can read their own course's trail.
- **Staff never touch sandboxes directly.** Live progress shows the student's own last *Check progress*
  result. Terminating goes through the session state machine (`submit`/`stop`), and extending changes only
  the expiry of a READY session, capped by the maximum session lifetime (240 min) and the student's closing time.
- **Temporary passwords** (roster imports, admin-created accounts, resets) are random and readable, shown once
  and never stored in clear. `must_change_password` blocks every API except `/auth/me` and
  `/auth/change-password` until it is replaced. Resets and deactivation revoke refresh tokens. Role changes and
  deactivation apply immediately (users are re-read on every request). Admins can't change their own role or
  deactivate themselves.
- **CSV:** roster import is validated server-side (size ≤256 KB, ≤1,000 rows, every row checked) and commits
  only with a preview token bound to the exact file. Exports neutralise spreadsheet formulas (`=`, `+`, `-`,
  `@` prefixed with `'`).

## Learning layer (phase 6)
- The architecture/cost snapshot is available only to the session owner while READY. It uses only the
  lab's grading collectors (capability-checked read operations), never runs probes, and is cached per session,
  so polling can't load or change a sandbox. It is not stored as evidence.
- XP is computed from graded, counted attempts and badges are awarded server-side after the grade commits.
  No client request can grant either, and `user_badges` is append-only.
- Leaderboards are off by default. Anonymous mode shows students stable aliases; real names are shown only in
  named mode or to course staff. Settings changes are audited.

## Runner fleet (phase 7)
- Every runner has its **own** HMAC secret, stored encrypted and verified at registration (a signed call must
  answer with the same runner id). A runner acts only on objects labelled with its id, so one runner can't list,
  touch or count another's sandboxes (tested with two runners on one Docker host).
- **Gateway mode** exposes `/gw/<sandbox>/<token>/emulator|terminal` without HMAC (boto3 and WebSocket clients can't
  sign). Each sandbox has a 192-bit random token, returned only inside the signed create/reset answer and checked in
  constant time; a wrong token or sandbox answers 404. The upstream is always that sandbox's own emulator or
  terminal, resolved by the runner, so there is no open proxy. The runner port must be reachable from the API servers
  only (DEPLOYMENT.md §6).
- A lost runner's sessions are failed without pretending they survived, and never recreated elsewhere.
- Password hashing: argon2id (OWASP profile) in bounded worker threads, so a sign-in burst can't stall the API.

## Integrity of grades
Evidence, attempts, task results, grades, session events, overrides and audit events are append-only (triggers plus
missing grants). A regrade adds a new `grades` row computed from the **stored** evidence, and the
original stays. Owner-role maintenance (`app/maintenance.py`) can bypass the triggers explicitly: for
test isolation, and for demo reset only when `CL_DEMO_MODE=true`.

## Known limitations / before a college deployment
- Replace `CL_SECRET_KEY` and `CL_RUNNER_SECRET` (the compose defaults are for development only). Set
  `CL_DEMO_MODE=false` (demo accounts are then refused at login).
- Serve over HTTPS (cookies are `Secure`; browsers only treat `localhost` as secure without TLS).
- Rate limits and the terminal/progress throttles are per-process (Redis in a later phase).
- IAM is **not enforced** inside sandboxes (any training credential works). IAM tasks are graded by the
  CloudLabs evaluator (`grader/iam_eval.py`), which covers identity-based policies only.
- The audit proxy isn't built (`audit.*` checks are rejected at import).
- Consider gVisor (`runsc`) as the container runtime for defence in depth.
