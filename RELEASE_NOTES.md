# CloudLabs v0.2.0 (unreleased)

**Instructor Lab Builder.** Instructors create, test and publish their own labs from the browser, without
editing files on the server.

## Lab Builder
- `/instructor/labs`: **New** (blank), **Clone** any lab version you can see (a built-in mission or another
  author's lab becomes a new id; cloning your own prepares its next minor version) or **Import** a `.tar.gz`
  pack.
- Form editor (Overview, Tasks, Scripts) whose check parameter forms are generated from the grader's Pydantic
  models, a synchronised **YAML** view (aliases refused), and a **Preview** of the redacted student view.
- Always-on **validation** with row-level errors; drafts save while invalid.
- **Test & publish gate**: a run in real sandboxes on every engine the lab may run on — an untouched sandbox
  must score `0`, an optional partial must hit its expected score, the reference solution full marks — and it
  must pass on the **current** content hash before publishing.
- Published versions are **immutable**. An authored lab is **private to its author (and admins)** until it is
  marked *shared* with all instructors. Export/import round-trips a deterministic `.tar.gz`; private files
  never reach students.
- Audited: `lab.draft_created`, `lab.published`, `lab.shared`.

## Verification
- Fresh full regression from `46d4ed2` (2026-09-27): API **294 passed / 0 skipped** (including the real-Docker
  tests and the two-runner gateway test with `runner-local-2` registered), runner **16/16**, `python -m
  app.labtest` on all six lab packs **0/partial/100 PASS on every engine**, browser E2E **14/14** including
  `lab-builder.spec.ts`. Web `npm run typecheck` clean.
- Found and fixed D37: the reconciler could reap in-flight `labtest` sandboxes that have no database row;
  D38 then closed a clock-skew hole (a future/non-finite `created_at` no longer grants the orphan grace
  window).
- Lint: the repo defines no Python linter dependency (no `pyproject.toml`, `ruff` absent from
  `requirements-dev.txt`) and no ESLint/Prettier config; the declared TypeScript gate `tsc --noEmit` passes.
  `ruff check --isolated --select F,E9` is a working convention in `CLAUDE.md`, not a repo dependency, so it
  was not installed for the release.

---

# CloudLabs v0.1.0 (2026-09-26)

First complete prototype of a college cloud lab platform: students do hands-on AWS labs in isolated, cost-free
simulated clouds and are graded automatically on what they actually built.

CloudLabs is licensed under the Apache License 2.0 (see `LICENSE`). Third-party components keep their own licences
(`THIRD_PARTY_NOTICES.md`).

## Core platform
- One isolated sandbox per student (emulator + terminal on a private network, no internet, resource limits).
- AWS-style web console **and** the real AWS CLI in a browser terminal, both acting on the same sandbox.
- S3, DynamoDB, IAM, EC2 and Lambda.
- Emulator abstraction with capability checks: Floci (default), Moto (regression backend), MiniStack (Lambda code).
- Deterministic grading from stored, immutable evidence; hidden checks; regrades; attempts and deadlines.
- Versioned YAML lab packs with a tester (`labtest`): six CloudCafé missions included.

## Teaching
- Guided and break-fix labs.
- Live architecture diagram and simulated (educational) cost meter.
- XP, badges and an optional, instructor-controlled leaderboard.
- Courses, CSV roster import with preview, assignments, gradebook and CSV export, live progress,
  extend/end sessions.

## Operations
- Admin dashboard: users, course staff, runners, running labs, audit log of every staff action.
- Multi-runner scheduler, drain/maintenance mode, runner-lost handling (labs are never moved between servers).
- Gateway mode for runners on other servers.
- Deployment guide: one-server and multi-runner, TLS, secrets, firewall, tested Postgres backup/restore,
  upgrades and rollback.

## Verification
- API 267/267, runner 16/16, browser E2E 13/13.
- Load test: 32 students on 16 seats, 0 failures, 100% sandbox cleanup (docs/LOADTEST.md).
- Clean start from the README verified.

## Known limitations
- One control-plane instance (API replicas need Redis-backed shared state).
- Runner channel: HMAC + per-sandbox tokens on a private network. Native mTLS is not implemented; use a VPN
  tunnel across untrusted networks.
- Lambda code execution needs the MiniStack engine; EC2 instances are simulated records (no real VM shell).
