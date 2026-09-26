# CloudLabs

Hands-on AWS labs for college courses, with automatic grading. Each student gets an **isolated
simulated AWS cloud** (Moto in Docker, no AWS account, no internet), works through a **simplified
AWS-style console** or the **real AWS CLI** in a browser terminal, and is graded on the **actual state**
of what they built. Grading uses immutable, explainable evidence that instructors can inspect.

**Status:** vertical slice 1 (S3) complete and verified. See [docs/STATUS.md](docs/STATUS.md).

## Quick start (Windows, Docker Desktop with WSL2)
```powershell
scripts\up.ps1           # build images + start the stack  → http://localhost:3000
scripts\demo-reset.ps1   # seed demo accounts and the S3 lab (password: cloudlabs-demo)
```
Sign in as `demo-student1@cloudlabs.demo`, `demo-instructor@cloudlabs.demo` or `demo-admin@cloudlabs.demo`.
The walkthrough is in [docs/DEMO.md](docs/DEMO.md).

## Documentation
| Doc | Contents |
|---|---|
| [docs/PLAN.md](docs/PLAN.md) | Scope, architecture, hardening decisions, acceptance criteria (source of truth) |
| [docs/STATUS.md](docs/STATUS.md) | Milestones with verification evidence and implementation decisions |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, sandbox, state machine, grading, data |
| [docs/SECURITY.md](docs/SECURITY.md) | Trust boundaries, sandbox hardening, grade integrity |
| [docs/LAB-AUTHORING.md](docs/LAB-AUTHORING.md) | Writing and testing lab packs |
| [docs/TESTING.md](docs/TESTING.md) | Test suites and how to run them |
| [docs/SCALING.md](docs/SCALING.md) | From one laptop to several college servers |
| [docs/DEMO.md](docs/DEMO.md) | Reproducible teacher demonstration |

## Repository
```
apps/web          Next.js UI (student player, console, terminal, instructor, admin)
services/api      FastAPI control plane (auth, sessions, grading, proxies) + Alembic
services/runner   Runner Agent — the only component that talks to Docker
images/           emulator (Moto) and terminal (AWS CLI v2 + ttyd) sandbox images
labs/             lab packs (lab.yaml + public/ + private/)
infra/            docker-compose, nginx gateway, Postgres roles
scripts/          up, demo-reset, test helpers
```
