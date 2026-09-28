# Next: authoring excellence (phase 9) → quality + teaching value (phase 10)

Hand-off for the next working session. Read `CLAUDE.md` and `docs/PLAN.md` first.
State: **v0.2.0 is released** (`main` = merge `61770d8`, tag `v0.2.0`). Phase 8 (Instructor Lab Builder,
milestones 36–39) is complete and fully regressed; decisions D29–D38 are in `docs/STATUS.md`.
Phase 9 milestones 40–44a are done; **phase 10 (milestones 45–49) is the batch described below.**

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

### 44 New teaching templates (richer labs)
- **Lambda + DynamoDB** combined pack ☑ (Mission 7, done — see STATUS 44a and D45): table + function that
  saves and totals an order; MiniStack declares the 12 DynamoDB contract ops; labtest 0/55/100 on MiniStack;
  template `lambda-dynamodb`.
- **VPC** next: console, checks, capabilities on the primary engines, a lab pack and labtest. VPC unlocks
  richer real-world labs (public/private subnets, routing, security groups) than another isolated service.
- **SQS/SNS** after that, in the same shape.
- Each new lab must pass `app.labtest` (empty 0 / partial / solution 100) on every engine it may run on
  before it appears in the gallery.

## Phase 10: quality + teaching value (the current batch)

**Scope rule (owner, 2026-09-27):** no new AWS service coverage in this phase — no VPC, SQS, SNS, Redis,
dark mode, command palette, i18n, audit proxy, LTI, SSO or notifications. The **audit proxy / `audit.*`
checks are the next major architecture milestone after this batch.** Preserve the architecture, grading
semantics, sandbox isolation, emulator abstraction, immutable evidence, audit guarantees and multi-runner
behaviour throughout.

Build in this order; each sub-milestone must be green before starting the next.

### 45 Authorization coverage guard ☑ (done — see STATUS 45 and D46)
- `services/api/tests/test_authz_coverage.py` restored as the file `app/main.py` and `app/auth/policy.py`
  already referred to (it lived inside `test_auth_and_policy.py` before).
- Guards: every route carries `Authz(action)` or is on a **reviewed allowlist held in the test**; no
  resource-scoped path may be public; every `Authz` action has a `MATRIX` row (else 500 instead of 403);
  no route is both public and protected; a **non-vacuity self-test** proves the checker flags a new
  unprotected route; every protected route answers **401** to an anonymous caller (141 routes); cross-resource
  access stays **404, wrong role 403**.

### 46 Lab Builder autosave + undo/redo ☑ (done — see STATUS 46 and D48)
- Debounced autosave of dirty drafts with `Saving… / Saved / Save failed` states, save-on-leave, and no
  silent loss when switching tabs or routes.
- Optimistic concurrency: a save carries the content revision (`drafts.rev`) it was based on and **does
  not** overwrite newer server state (409 `stale_revision`).
- Undo/redo for meaningful edits (coalesced keystrokes), keyboard shortcuts, YAML ⇄ form stay consistent.
- Published immutable versions untouched. Tests: autosave, failed save, undo, redo, stale revision.

### 47 Single-check live runner ☑ (done — see STATUS 47 and D49)
- From the Lab Builder, run **one** check against the preview sandbox and see type, expected, actual,
  pass/fail, marks possible, the normal grader message and a clear capability/unsupported reason.
- Same deterministic check code as final grading; **never** an attempt, grade, XP, badge, leaderboard event
  or immutable evidence; ownership, freeze and capability rules respected; nothing calls an emulator
  directly from the browser; serialised and rate-limited. Backend + browser tests.

### 48 Attempt diff ("since your last attempt") ☑ (done — see STATUS 48 and D51)
- Student- and instructor-facing comparison of two attempts from **stored** grade results only (never a
  live sandbox): fixed / regressed / unchanged / added / removed, first attempt handled gracefully,
  regraded attempts correct. Students never see `expected`/`actual`. Original evidence and grades untouched.

### 49 Instructor course analytics ☑ (done — see STATUS 49 and D52)
- Per course: average score, submission rate, average attempts, average completion time, most-failed
  tasks, most-missed checks, late count, and infrastructure interruptions counted **separately**.
- Staff only see their own courses (admins see all); no live-sandbox queries; a fixed query count (no N+1);
  empty states. CSV export left for later.

## After phase 10
Deploy on a real server (docs/DEPLOYMENT.md) → run it with actual students → collect feedback → the audit
proxy (`audit.*`) → expand AWS coverage in the order the feedback justifies (VPC first, then SQS/SNS).

## Verification
- API: `tests/test_lab_builder.py` (templates catalogue/create/errors, drafts, publish gate) — fast suite
  must stay green; `scripts/test-api.sh` for the full suite before a release.
- Phase 10: `tests/test_authz_coverage.py` (route coverage + the 401 sweep),
  `tests/test_lab_builder_autosave.py`, `tests/test_preview_check.py`, `tests/test_attempt_diff.py`,
  `tests/test_course_analytics.py` — all inside `scripts/test-api.sh -m "not docker"`.
- E2E: `apps/web/e2e/lab-builder.spec.ts` on the compose stack (template gallery + the full clone/test/
  publish/assign journey), plus `lab-builder-autosave.spec.ts`, `lab-builder-check-run.spec.ts` and
  `instructor-analytics.spec.ts`. `instructor-first-run.spec.ts` is the M43 acceptance journey.
- Docs: LAB-AUTHORING (builder section), STATUS (milestones and decisions), DEMO (optional walkthrough).

## How to run
See `README.md`. API tests: `scripts/test-api.sh` (fast: `-m "not docker"`). The stack must be up for E2E:
`docker compose -f infra/docker-compose.yml --profile multi up -d --build`, then `cd apps/web && npx
playwright test`. Commit or push only when the owner asks.
