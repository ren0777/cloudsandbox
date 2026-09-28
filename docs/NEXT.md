# Next: Authoring excellence (phase 9)

Hand-off for the next working session. Read `CLAUDE.md` and `docs/PLAN.md` first.
State: **v0.2.0 is released** (`main` = merge `61770d8`, tag `v0.2.0`). Phase 8 (Instructor Lab Builder,
milestones 36–39) is complete and fully regressed; decisions D29–D38 are in `docs/STATUS.md`.

## Owner's direction (2026-09-27)
The roadmap is deliberately **not** "more services". Order of value:

1. Make instructor authoring excellent (the Lab Builder is the product).
2. Make labs richer (break-fix, multi-service) and add templates that teach real scenarios.
3. Deploy on a real server, test with actual students, collect feedback.
4. Only then expand AWS coverage (VPC first, then SQS/SNS) — where it unlocks richer labs.

The question for phase 9 is: **is the builder usable enough for a teacher who has never touched YAML?**
Focus: the visual authoring UX; safe starting-state builders for break-fix labs; preview/test/publish
clarity; templates (S3 basics, IAM least privilege, EC2 web server, Lambda + DynamoDB); and a validated
"create and assign a lab without developer help" journey.

## Milestones
### 40 Templates and a guided start ☑ (done, see STATUS 40 and D39)
- `GET /api/instructor/builder/templates`: curated templates resolved against the latest **built-in**
  version of their source lab (`available: false` when the pack is not installed).
- `POST /api/instructor/builder/drafts {source: "template", template_id, title?}`: a fresh draft owned by
  the author — id `<title-slug>-<short id>`, version `1.0.0`, the author's title, all files carried
  (a break-fix `public/setup.sh` stays read-only). Audited with `template_id`.
- Six templates from the built-in missions: S3 basics, DynamoDB basics, IAM least privilege, EC2 web
  server, Lambda serverless, IAM break-fix.
- UI: **New lab** is a gallery (Start from scratch + template cards with services/difficulty); dialogs
  scroll on small viewports.
- Tests: 2 API tests (`tests/test_lab_builder.py`), 1 E2E (`e2e/lab-builder.spec.ts`).
- Still open: a combined **"Lambda + DynamoDB"** template (needs a new lab pack and a labtest pass on
  MiniStack) — milestone 44.

### 41 Break-fix starting-state builders ☑ (option A, done — see STATUS 41 and D40)
The owner chose **A only** (2026-09-27): typed break actions, a deterministic compiler, baseline validation
and Reset reproducibility; **no raw setup script editor** in the instructor UI.
- `lab.yaml` `break_actions` (typed) + `baseline.expected_score`; compiled by `app/breakfix/` into the setup
  the runner executes; validated against engine capabilities at import.
- Lab Builder **Starting state** tab: forms generated from each action's Pydantic schema, Broken State
  Summary, kind toggle, baseline input. Legacy packs keep their read-only setup script.
- labtest runs a `reset` scenario for break-fix packs: setup → baseline → Reset → baseline must match.
- Verification: a real compiled pack scored baseline 0 and 40 → solution 100 → Reset reproduced the
  baseline, on moto and floci.
- **Remaining (M41b):** an interactive **preview sandbox** — launch the broken environment and inspect it in
  the console/terminal before running the publish gate. It needs a session-like sandbox access path and is
  deliberately separate from the test/publish flow.

### 42a Stackora brand + public landing page ☑ (done, see STATUS 42a and D42)
Public product name is **Stackora**; a premium marketing page at `/` (hero, services, features, screenshots,
Apache-2.0, CTAs). The authenticated app stays behind `/login`; internal identifiers keep the `cloudlabs`
codename.

### 42 Preview, test and publish clarity ☑ (done — see STATUS 42 and D43)
- Interactive **preview sandbox**: launch the authored starting state and inspect it in the console and
  terminal, with Reset reconstructing it. Never creates an attempt, grade, XP, badge or leaderboard event.
- **Publish-readiness checklist** (validation, capabilities, baseline, solution, reset, current content) as
  the first thing on the Test tab, with row-level errors; the Publish button waits for all of it.
- Test results: per-scenario summary that says what to fix, with the failing task/check linked to its row.
- Preview: choose the sample variables / student identity, and show "what the student sees" next to "what
  is graded" (without leaking hidden checks).

### 43 Instructor validation (no developer help) ☑ (done — see STATUS 43)
- `e2e/instructor-first-run.spec.ts`: create course → roster → lab from a template → edit tasks/checks →
  starting state → preview → readiness → publish → assign → student completion → instructor evidence, with
  **no YAML, shell, database or developer tooling**. Passed with no blockers.
- `docs/INSTRUCTOR-QUICKSTART.md` + an in-app first-run card and quickstart links.

### 44p Services preparation: VPC / SQS / SNS ☑ (done — see STATUS 44p and docs/M44-SERVICES-EVALUATION.md)
- Evaluated on Moto 5.2.3, Floci 2.1.0 and MiniStack 1.5.16 under production sandbox hardening: VPC
  32/32, SQS 20/20, SNS 16/16 probe checks on every engine (`tools/emulator-bakeoff/m44_bakeoff.sh`).
- Contract tests `tests/test_vpc.py`, `test_sqs.py`, `test_sns.py` run per engine through the runner;
  capability declarations added behind the adapter (`SERVICE_CLIENT`), `CONSOLE_OPS` untouched.
- Proposals (grader checks, FastAPI routes, console IA) and the per-service default recommendation
  (**Floci**; no switch made) are in `docs/M44-SERVICES-EVALUATION.md`. Nothing reaches students yet.

### 44 New teaching templates (richer labs)
- **Lambda + DynamoDB** combined pack ☑ (Mission 7, done — see STATUS 44a and D45): table + function that
  saves and totals an order; MiniStack declares the 12 DynamoDB contract ops; labtest 0/55/100 on MiniStack;
  template `lambda-dynamodb`.
- **VPC** ☑ (Missions 8/9, done — see STATUS 44v): console page, six checks, `vpc-basics` guided lab and
  `vpc-breakfix` built from typed `vpc.*` break actions; labtest 0/50/100 and baseline 25/65/100 + Reset
  on moto and floci; E2E builds and repairs a network in the VPC console.
- **SQS** ☑ (Missions 10/11, done — see STATUS 44q): console page, four checks including a non-destructive
  message probe, `sqs-basics` guided lab and `sqs-breakfix` (queue attributes incident); labtest
  0/35/100 and baseline 20/70/100 + Reset on moto and floci; E2E creates a queue and unsticks one.
- **SNS** next, in the same shape (capability declarations and contract tests already exist). SNS adds
  fan-out: publish to a topic and subscribe an in-sandbox SQS queue.
- Each new lab must pass `app.labtest` (empty 0 / partial / solution 100) on every engine it may run on
  before it appears in the gallery.

## After phase 9
Deploy on a real server (docs/DEPLOYMENT.md) → run it with actual students → collect feedback → expand AWS
coverage in the order the feedback justifies (VPC first, then SQS/SNS).

## Verification
- API: `tests/test_lab_builder.py` (templates catalogue/create/errors, drafts, publish gate) — fast suite
  must stay green; `scripts/test-api.sh` for the full suite before a release.
- E2E: `apps/web/e2e/lab-builder.spec.ts` on the compose stack (template gallery + the full clone/test/
  publish/assign journey).
- Docs: LAB-AUTHORING (builder section), STATUS (milestones and decisions), DEMO (optional walkthrough).

## How to run
See `README.md`. API tests: `scripts/test-api.sh` (fast: `-m "not docker"`). The stack must be up for E2E:
`docker compose -f infra/docker-compose.yml --profile multi up -d --build`, then `cd apps/web && npx
playwright test`. Commit or push only when the owner asks.
