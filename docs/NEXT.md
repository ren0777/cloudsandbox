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

### 41 Break-fix starting-state builders (needs the owner's model decision)
Today a break-fix `setup.sh` is carried read-only; v1 never authors it. To let teachers create break-fix
labs, pick one:
- **(A) Curated typed break actions (recommended).** A catalogue of safe, reversible operations per service
  (IAM: attach `AdministratorAccess` / remove a policy from a group; S3: delete a bucket policy; EC2:
  remove an ingress rule / stop an instance; Lambda: clear an env var), each with a parameter form
  generated from a Pydantic model, composed into a deterministic `setup.sh`. Reset re-runs setup, and the
  builder previews the broken state in a sandbox before testing.
- **(B) Sandboxed raw `setup.sh` editing.** Full power, but the teacher writes shell; a live preview run is
  the only safety net. More support burden, less "no YAML" friendly.
- **(C) Both:** typed actions for common cases, raw script as an escape hatch.
Acceptance for whichever is chosen: the broken baseline scores 0, the reference solution 100; validation
refuses a setup that leaves the lab already solved.

### 42 Preview, test and publish clarity
- A **publish-readiness checklist** (valid? tested on the *current* content? version free? title?) as the
  first thing on the Test tab, with one next action.
- Test results: per-scenario summary that says what to fix, with the failing task/check linked to its row.
- Preview: choose the sample variables / student identity, and show "what the student sees" next to "what
  is graded" (without leaking hidden checks).

### 43 Instructor validation (no developer help)
- A Playwright "new instructor" journey: sign in → start from a template → edit a task → test → publish →
  assign → a student starts it, with no developer intervention.
- A quickstart doc ("Your first lab in 15 minutes") and, if useful, short screen recordings/screenshots.
- Success test: hand it to a teacher who has never seen the repo; they complete the journey unaided.

### 44 New teaching templates (richer labs)
- **Lambda + DynamoDB** combined pack (function writes/reads a table), then VPC and SQS/SNS when their
  consoles are added. Each new template must pass `app.labtest` (empty 0 / partial / solution 100) on every
  engine it may run on before it appears in the gallery.

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
