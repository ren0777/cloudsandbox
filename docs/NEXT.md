# Next: Instructor Lab Builder (phase 8)

Hand-off for the next working session (for example Claude Code on the web). Read `CLAUDE.md` and `docs/PLAN.md` first.
State at hand-off: v0.1.0 is complete and verified on `main` (API 267, runner 16, E2E 13). On this branch
(`feat/lab-builder`), the `package.py` refactor is verified and **milestone 36 (backend) is done**. Next up is
**milestone 37**.

## Goal
Instructors create, test and publish their own labs in the browser, without editing files on the server.

## Decisions already made by the owner
- **Editor:** a form builder whose check parameter forms are generated from the grader's Pydantic models, with a
  synchronised YAML view and an "edit as YAML" escape hatch.
- **Publish gate:** schema/capability validation **and** a sandbox test run (untouched sandbox scores 0,
  reference solution scores 100, partial optional). Nothing reaches students otherwise.
- **Sharing:** a published lab is private to its author (and admins) by default. The author can mark it
  *shared* so every instructor can assign or clone it. Built-in missions are visible to all.
- **v1 scope:** author from scratch, **clone** an existing lab, **student preview**, **export/import** lab packs.
  **Not in v1:** authoring break-fix setup scripts. A setup script in a cloned or imported pack is kept unchanged
  and shown read-only.

## Already done on this branch
- **Refactor verified (2026-09-26):** `pack_from_files(files)`, `load_pack(dir)` (delegates to it), `pack_files(...)`
  (inverse) and `check_files(files)` (shared path/size/count limits) are in `services/api/app/labs/package.py`. The
  fast API suite is unchanged (239/239). All 6 lab packs have byte-identical bundle hashes before and after, so
  built-ins won't re-import as new versions.
- **Milestone 36 done** (see STATUS 36, D29–D34). Main pieces:
  - `alembic/versions/0006_lab_builder.py`
  - `app/labs/drafts.py`: pure helpers (YAML, validation rows, scenario rules, tar.gz)
  - `app/instructor/builder.py`: `/api/instructor/builder/...`
  - visibility helpers in `app/auth/policy.py`: `lab_visible`, `load_lab_version_visible`, `load_own_lab`,
    `load_draft_for`
  - in `app/instructor/routes.py`: the `lab-versions` list with owner/shared/builtin/mine, export, share, and
    visibility checks on create/update assignment
  - `import_package(owner_id=…)`
  - `tests/test_lab_builder.py` (14 tests). Fast suite: 253 passed.
- **Not yet re-run on this branch:** the docker-marked tests (28) and `python -m app.labtest`. In the cloud
  session that did milestone 36, image builds couldn't reach PyPI through the sandbox's TLS proxy, so the tests
  ran on the host (Python 3.12 venv) against the compose Postgres. Run both first on a machine with a working
  `docker compose build`.

### API added in milestone 36 (for milestone 38's UI)
| Route | Notes |
|---|---|
| `GET builder/check-types` | `check_types[]` (`type`, `service`, `params_schema`, `reads`, `supported`, `engines{usable, unusable_ops}`), `common_fields`, `services`, `engines`, `editable_files` |
| `GET/POST builder/drafts` | POST body `{source: blank\|clone, lab_version_id?, title?, slug?}` |
| `POST builder/drafts/import` | multipart `file` |
| `GET/PUT/DELETE builder/drafts/{id}` | PUT body `{lab?, files?}`; the response always carries `validation {ok, errors[{message, loc, task, check, field}], content_sha256}` |
| `GET/PUT builder/drafts/{id}/yaml` | |
| `POST builder/drafts/{id}/validate` | |
| `GET builder/drafts/{id}/preview` | |
| `GET lab-versions` | |
| `GET lab-versions/{id}/export` | |
| `POST labs/{lab_id}/share {shared}` | |

All routes are under `/api/instructor/`.

## Milestones
### 36 Backend ☑ (done, see above)
- **Migration `0006`:**
  - `labs.owner_id` (NULL = built-in) and `labs.shared` (bool)
  - table `lab_drafts` with columns: `id`, `owner_id`, `slug`, `title`, `content`, `base_lab_version_id`, `status`
    (draft|testing|passed|failed|published), `last_validation`, `last_test`, `tested_sha256`,
    `published_version_id`, timestamps
  - `content` JSON = `{lab: <schema-v1 dict>, files: {"private/solution.sh", "private/partial.sh",
    "private/expected.yaml", "private/notes.md", "public/…" (read-only)}}`
- **New router `app/instructor/builder.py`:** `Action.lab_manage`; drafts visible only to their owner or an admin,
  **404** for anyone else.
  - `GET /api/instructor/builder/check-types`: every registry check with `params_model.model_json_schema()`, its
    service, the operations it reads, and whether each engine supports it.
  - Drafts: list; create (blank / clone from a *visible* lab version / import an uploaded pack); get; update;
    delete.
  - `GET` and `PUT drafts/{id}/yaml` (YAML ⇄ JSON round-trip, validated).
  - `POST drafts/{id}/validate` returns row-level errors from `pack_from_files` / `validate_definition`.
  - `GET drafts/{id}/preview` returns `student_lab_view` with sample variables (never private files).
- **Visibility:**
  - `GET /api/instructor/lab-versions` lists built-in, own and shared labs (admins see all).
  - `create_assignment` refuses invisible versions.
  - `POST /api/instructor/labs/{id}/share` is audited.
  - `GET lab-versions/{id}/export` returns a tar.gz pack (instructors/admins only).
- **Audit actions:** add `lab.draft_created`, `lab.published` and `lab.shared` to `app/audit.py`.
- **Reuse:**
  - `pack_from_files` / `pack_files` (`app/labs/package.py`)
  - `parse_definition`
  - `import_package`, `definition_of` and `get_bundle` (`app/labs/importer.py`)
  - `student_lab_view` and `compute_variables` (`app/labs/render.py`)
  - `audit.record`

### 37 Test run and publish gate
Hooks that are already in place:
- `drafts.expectations(files, definition)` gives the scenarios to run.
- `drafts.package(content)` gives the `LabPackage`, and `last_validation.content_sha256` is the hash to store as
  `tested_sha256`.
- Publish should call `import_package(db, pkg, owner_id=draft.owner_id)`.
- Refactor `app/labtest.py` so `check_pack` accepts a `LabPackage` as well as a path.
- `POST drafts/{id}/test` runs the empty, partial and solution scenarios in real sandboxes (background task), and
  stores the per-check results together with the content sha256 that was tested.
- `POST drafts/{id}/publish` is allowed only if the last test passed on the **current** content sha256. It then:
  - calls `import_package` (immutable; the version must be new)
  - sets `labs.owner_id`
  - records `lab.published`
  - sets the draft to `published`
  Editing a published lab means a new draft with a new version.

### 38 UI (apps/web)
- `/instructor/labs`: my drafts / my labs / shared labs / built-in missions, with **New**, **Clone** and
  **Import**.
- `/instructor/labs/drafts/[id]` tabs:
  - Overview: title, summary, story, services, engine, duration, attempts, variables
  - Tasks: tasks with hints and marks; checks as generated forms (string, number, bool, enum, key-value maps,
    lists, and JSON for free-form values)
  - Scripts: solution and partial scripts, expected partial score, notes
  - YAML
  - Preview (as a student)
  - Test & publish (run test, per-check results, publish, share)
  A validation panel is always visible.
- Playwright spec `e2e/lab-builder.spec.ts`: clone Mission 1 → change a task → test (0 and 100) → publish →
  assign to the demo course → start it as a student.

### 39 Docs and regression
- LAB-AUTHORING (builder section), SECURITY (who can see private files), STATUS (milestones 36–39, decisions D29+),
  DEMO (optional section).
- Full regression: API, runner and E2E must all be green, including the existing 267 / 16 / 13.
- Then merge `feat/lab-builder` into `main`.

## Verification
- API tests:
  - drafts CRUD and ownership (404 for others)
  - validation errors
  - YAML round-trip
  - clone and import/export (private files never in student responses)
  - visibility and sharing, assignment refusal for invisible labs
  - publish refused until a passing test on the current content
  - publish immutability (same version refused)
- Docker-marked test: a cloned Mission 1 test run gives 0 / partial / 100 in real sandboxes.
- Playwright spec above, then the full suite.

## How to run
See `README.md` (Quick start, Tests). API tests: `scripts/test-api.sh` (fast: `-m "not docker"`).
Commit or push only when the owner asks.
