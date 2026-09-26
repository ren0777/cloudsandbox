# CloudLabs v0.1.0 (2026-09-26)

First complete prototype of a college cloud lab platform: students do hands-on AWS labs in isolated, cost-free
simulated clouds and are graded automatically on what they actually built.

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
- The repository has no project licence yet.
