# CloudLabs

Hands-on AWS labs for college courses, with automatic grading. Each student gets an **isolated simulated AWS
cloud** in Docker (no AWS account, no cost, no internet). They work in an **AWS-style console** or with the
**real AWS CLI** in a browser terminal, and are graded on the **actual state** of what they built, using immutable,
explainable evidence that instructors can inspect.

**Version 0.1.0.** S3, DynamoDB, IAM, EC2 and Lambda; guided and break-fix labs; instructor and admin tools;
multi-runner deployment. What's in the release: [RELEASE_NOTES.md](RELEASE_NOTES.md). Verified status:
[docs/STATUS.md](docs/STATUS.md).

## v0.2.0 (unreleased)
- **Instructor Lab Builder** (`/instructor/labs`, in progress): create, **clone** or **import** a lab, edit
  it in the browser (a form builder with a synchronised **YAML** view and a redacted **student preview**),
  **validate** it, **test** it in real sandboxes (untouched `0`, optional partial, reference solution full
  marks) and **publish** it as an immutable version. Authored labs are private to their author (and admins)
  until **shared** with all instructors; packs export/import as deterministic `.tar.gz`. See
  [docs/LAB-AUTHORING.md](docs/LAB-AUTHORING.md#instructor-lab-builder-browser) and, for the security
  boundary, [docs/SECURITY.md](docs/SECURITY.md). Optional walkthrough: [docs/DEMO.md](docs/DEMO.md).

## Prerequisites
- Docker Desktop (Windows with the WSL2 backend, or macOS) or Docker Engine 24+ with Compose v2 (Linux).
  Give Docker at least 4 CPUs and 6 GB RAM.
- About 6 GB of free disk for images. Internet access for the first build only.
- For the end-to-end tests only: Node.js 20+.

## Quick start
Windows (PowerShell):
```powershell
scripts\up.ps1           # builds the sandbox images and the stack, starts it  → http://localhost:3000
scripts\demo-reset.ps1   # seeds demo accounts, a course and six labs
```
Linux / macOS:
```bash
scripts/up.sh
scripts/demo-reset.sh
```
The first build takes several minutes. Then sign in at http://localhost:3000 with password `cloudlabs-demo` as
`demo-student1@cloudlabs.demo` (students 1–3), `demo-instructor@cloudlabs.demo` or `demo-admin@cloudlabs.demo`.
Demo accounts exist only while `CL_DEMO_MODE=true` (the laptop default). The teacher walkthrough is in
[docs/DEMO.md](docs/DEMO.md).

Stop with `docker compose -f infra/docker-compose.yml down` (add `-v` to also delete the database).

## Tests
```bash
scripts/test-api.sh                                        # API suite incl. real-Docker tests (about 40 min)
scripts/test-api.sh -m "not docker"                        # fast subset (no sandboxes)
docker compose -f infra/docker-compose.yml exec runner python -m pytest -q   # runner (real Docker)
cd apps/web && npm ci && npx playwright install chromium && npx playwright test   # browser E2E (stack must be up)
```
Lab packs: `docker compose -f infra/docker-compose.yml exec api python -m app.labtest /labs/<id>`.
Load test: [docs/LOADTEST.md](docs/LOADTEST.md).

## Documentation
| Doc | Contents |
|---|---|
| [docs/PLAN.md](docs/PLAN.md) | Scope, architecture, hardening decisions, acceptance criteria (source of truth) |
| [docs/STATUS.md](docs/STATUS.md) | Milestones with verification evidence and implementation decisions |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, sandbox, state machine, grading, fleet, data |
| [docs/SECURITY.md](docs/SECURITY.md) | Trust boundaries, sandbox hardening, grade integrity, staff actions, runner fleet |
| [docs/LAB-AUTHORING.md](docs/LAB-AUTHORING.md) | Writing and testing lab packs (including break-fix labs) |
| [docs/TESTING.md](docs/TESTING.md) | Test suites and what they cover |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | One-server and multi-runner deployment, TLS, secrets, backups, upgrades, rollback |
| [docs/SCALING.md](docs/SCALING.md) | Runner fleet, scheduler, sizing, next steps |
| [docs/LOADTEST.md](docs/LOADTEST.md) | Class-scale load test and results |
| [docs/EMULATOR-EVALUATION.md](docs/EMULATOR-EVALUATION.md) | Why Floci (default), Moto (regression) and MiniStack (Lambda code) |
| [docs/DEMO.md](docs/DEMO.md) | Reproducible teacher demonstration |

## Repository
```
apps/web          Next.js UI (student player, consoles, terminal, instructor, admin)
services/api      FastAPI control plane (auth, sessions, scheduler, grading, proxies) + Alembic migrations
services/runner   Runner agent: the only component that talks to Docker (optional sandbox gateway)
images/           sandbox images: emulators (Floci, Moto, MiniStack) and terminal (AWS CLI v2 + ttyd)
labs/             lab packs (lab.yaml + public/ + private/)
infra/            docker-compose (laptop), production/ and runner-host/ overrides, nginx, Postgres roles
scripts/          up, demo-reset, test helpers
tools/            emulator bake-off probes
```

## License
CloudLabs is licensed under the [Apache License 2.0](LICENSE). Copyright 2026 ren0777.
Third-party software and its licences: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
