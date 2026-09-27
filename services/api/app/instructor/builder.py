"""Instructor Lab Builder API (phase 8, docs/NEXT.md milestone 36): check-type catalogue for the form
builder, lab drafts (blank / clone / import), YAML round-trip, row-level validation and student preview.

Drafts hold private files (reference solutions), so every draft route answers 404 to anyone but the draft's
owner or an admin (PLAN §9, §7b). Milestone 37 adds the publish gate: a test run in real sandboxes (untouched
sandbox 0, partial optional, reference solution full marks) must pass on the current content before
`publish` imports it as an immutable lab version."""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit, labtest
from ..auth.policy import Action, Authz, load_draft_for, load_lab_version_visible
from ..config import get_settings
from ..db import get_db, sessionmaker
from ..errors import ApiError
from ..grader import registry
from ..grader.checks import load_all
from ..labs import drafts as dr
from ..labs.importer import get_bundle, import_package
from ..labs.package import LabPackage
from ..labs.render import compute_variables, student_lab_view
from ..labs.schema import LabValidationError
from ..labs.schema.v1 import SLUG, CheckSpec, Service
from ..models import Lab, LabDraft, LabVersion, Role, User
from ..obs.logging import log
from ..runtime import emulators
from ..runtime.runner_client import RunnerError, get_runner
from ..tasks import background
from . import templates as tpl

router = APIRouter(prefix="/api/instructor/builder", tags=["lab-builder"])

LOCKED = ("testing", "published")


def _now() -> datetime:
    return datetime.now(UTC)


def _invalid(e: LabValidationError, lab: dict[str, Any] | None = None) -> ApiError:
    return ApiError("lab_invalid", "the lab pack is not valid", 422,
                    extra={"errors": [dr.row_error(m, lab or {}) for m in e.errors]})


# ------------------------------------------------------------------------------ check catalogue
@router.get("/check-types")
async def check_types(user: User = Depends(Authz(Action.lab_manage))):
    """Every grader check with its parameter JSON Schema (generated from the check's Pydantic model), the
    emulator operations it reads and, per engine, whether those operations are usable there."""
    load_all()
    out = []
    for t, c in sorted(registry.REGISTRY.items()):
        engines = {}
        for name in emulators.ALL_ENGINES:
            bad = emulators.get(name).capabilities.unusable(list(c.reads))
            engines[name] = {"usable": c.supported and not bad, "unusable_ops": bad}
        out.append({"type": t, "service": t.split(".")[0], "params_schema": c.params_model.model_json_schema(),
                    "reads": list(c.reads), "supported": c.supported,
                    "unsupported_reason": c.unsupported_reason or None, "engines": engines})
    common = CheckSpec.model_json_schema()
    common["properties"] = {k: v for k, v in common["properties"].items() if k != "type"}
    return {"check_types": out, "common_fields": common, "services": list(Service.__args__),
            "engines": {"primary": list(emulators.ENGINES), "specialised": list(emulators.SPECIALISED)},
            "editable_files": list(dr.EDITABLE_FILES)}


# -------------------------------------------------------------------------------------- templates
@router.get("/templates")
async def list_templates(user: User = Depends(Authz(Action.lab_manage)), db: AsyncSession = Depends(get_db)):
    """Curated starting points for the New-lab gallery, resolved against the latest built-in version of
    each source lab. `available: false` means the built-in pack is not installed on this deployment."""
    out = []
    for t in tpl.TEMPLATES:
        lv = await _builtin_latest(db, t.source_lab_id)
        out.append({"id": t.id, "title": t.title, "summary": t.summary, "services": list(t.services),
                    "difficulty": t.difficulty, "highlights": list(t.highlights),
                    "source_lab_id": t.source_lab_id, "available": lv is not None,
                    "latest_version": lv.version if lv else None})
    return {"templates": out}


# --------------------------------------------------------------------------------------- helpers
def _denorm(d: LabDraft) -> None:
    lab = d.content.get("lab", {})
    d.slug = str(lab.get("id") or "")[:80]
    d.title = str(lab.get("title") or "Untitled lab")[:200]


async def _ownership_errors(db: AsyncSession, d: LabDraft, slug: str, version: str) -> list[str]:
    """Publishing adds a version to the lab with this id, so the id must be free or the author's own lab,
    and the version new (lab versions are immutable, PLAN §7)."""
    lab = await db.scalar(select(Lab).where(Lab.slug == slug))
    if lab is None:
        return []
    if lab.owner_id != d.owner_id:
        return [f"id: {slug!r} is already used by another lab; choose a different id"]
    if await db.scalar(select(LabVersion.id).where(LabVersion.lab_id == lab.id, LabVersion.version == version)):
        return [f"version: {version} of {slug} is already published; bump the version"]
    return []


async def _validate(db: AsyncSession, d: LabDraft) -> dict[str, Any]:
    pkg, errors = dr.build(d.content)
    if pkg is not None:
        errors += await _ownership_errors(db, d, pkg.definition.id, pkg.definition.version)
    result = {"ok": not errors, "errors": [dr.row_error(m, d.content.get("lab", {})) for m in errors],
              "content_sha256": pkg.content_sha256 if pkg else None, "validated_at": _now().isoformat()}
    d.last_validation = result
    return result


def _files_info(content: dict[str, Any]) -> dict[str, Any]:
    names = sorted(content.get("files", {}))
    return {"editable_files": list(dr.EDITABLE_FILES),
            "read_only_files": [n for n in names if n not in dr.EDITABLE_FILES]}


async def _out(db: AsyncSession, d: LabDraft, full: bool = True) -> dict[str, Any]:
    owner = await db.get(User, d.owner_id)
    o = {"id": str(d.id), "slug": d.slug, "title": d.title, "status": d.status,
         "owner": {"id": str(d.owner_id), "name": owner.name if owner else None},
         "base_lab_version_id": str(d.base_lab_version_id) if d.base_lab_version_id else None,
         "published_version_id": str(d.published_version_id) if d.published_version_id else None,
         "validation": d.last_validation, "tested_sha256": d.tested_sha256,
         "created_at": d.created_at, "updated_at": d.updated_at}
    if full:
        o.update(content=d.content, last_test=d.last_test, **_files_info(d.content))
    return o


async def _unique_slug(db: AsyncSession, base: str) -> str:
    base = base[:70].strip("-") or "lab"
    taken = set((await db.scalars(select(Lab.slug).where(Lab.slug.startswith(base)))).all()) | \
        set((await db.scalars(select(LabDraft.slug).where(LabDraft.slug.startswith(base)))).all())
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    return slug


def _slug_from_title(title: str, short_id: str) -> str:
    """A lab id from a teacher's title: lower-case words joined by dashes, suffixed with the author's short
    id so two teachers naming a lab the same way can never collide (and the SLUG pattern still holds)."""
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:70].strip("-") or "lab"
    return f"{base}-{short_id}"


async def _builtin_latest(db: AsyncSession, lab_slug: str) -> LabVersion | None:
    """The newest version of a built-in lab (owner_id NULL = imported from labs/ on disk)."""
    return await db.scalar(
        select(LabVersion).join(Lab, Lab.id == LabVersion.lab_id)
        .where(Lab.slug == lab_slug, Lab.owner_id.is_(None))
        .order_by(LabVersion.id.desc()).limit(1))


def _semver(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))  # lab versions match SEMVER (schema v1)


async def _create(db: AsyncSession, user: User, content: dict[str, Any], source: str,
                  base: LabVersion | None = None, template_id: str | None = None) -> LabDraft:
    d = LabDraft(owner_id=user.id, content=content, status="draft",
                 base_lab_version_id=base.id if base else None, slug="", title="")
    _denorm(d)
    db.add(d)
    await db.flush()
    await _validate(db, d)
    audit.record(db, user, "lab.draft_created", draft_id=d.id, source=source, slug=d.slug,
                 lab_version_id=base.id if base else None, template_id=template_id)
    await db.commit()
    await db.refresh(d)
    return d


# ---------------------------------------------------------------------------------------- drafts
@router.get("/drafts")
async def list_drafts(user: User = Depends(Authz(Action.lab_manage)), db: AsyncSession = Depends(get_db)):
    """The user's drafts (an admin sees every author's)."""
    q = select(LabDraft).order_by(LabDraft.updated_at.desc())
    if user.role != Role.admin:
        q = q.where(LabDraft.owner_id == user.id)
    return {"drafts": [await _out(db, d, full=False) for d in (await db.scalars(q)).all()]}


class DraftIn(BaseModel):
    source: str = Field("blank", pattern=r"^(blank|clone|template)$")
    lab_version_id: uuid.UUID | None = None  # clone: a lab version the user can see
    template_id: str | None = Field(None, max_length=60)  # template: a curated starting point
    title: str | None = Field(None, min_length=1, max_length=200)
    slug: str | None = Field(None, pattern=SLUG)


@router.post("/drafts", status_code=201)
async def create_draft(body: DraftIn, user: User = Depends(Authz(Action.lab_manage)),
                       db: AsyncSession = Depends(get_db)):
    """Blank draft, a clone of a visible lab version, or a fresh lab from a curated template. Cloning your
    own lab prepares its next version (same id, next minor version); cloning anyone else's lab (or a
    built-in mission) starts a new lab with a new id, so it can never overwrite the original."""
    if body.source == "blank":
        slug = await _unique_slug(db, body.slug or f"new-lab-{user.short_id}")
        return await _out(db, await _create(db, user, dr.blank_content(slug, body.title or "Untitled lab"), "blank"))
    if body.source == "template":
        if not body.template_id:
            raise ApiError("validation_error", "template_id is required to start from a template", 400)
        t = tpl.BY_ID.get(body.template_id)
        if t is None:
            raise ApiError("template_not_found", "no such lab template", 404)
        lv = await _builtin_latest(db, t.source_lab_id)
        if lv is None:
            raise ApiError("template_unavailable", "this template's built-in lab is not installed", 409)
        lv, _lab = await load_lab_version_visible(db, user, lv.id)
        pub, priv = await get_bundle(db, lv.id, "public"), await get_bundle(db, lv.id, "private")
        try:
            content = dr.content_from_bundles(pub.data, priv.data)
        except LabValidationError as e:
            raise _invalid(e) from e
        lab_def = content["lab"]
        title = (body.title or t.title)[:200]
        lab_def["id"] = await _unique_slug(db, body.slug or _slug_from_title(title, user.short_id))
        lab_def["version"] = "1.0.0"
        lab_def["title"] = title
        return await _out(db, await _create(db, user, content, "template", base=lv, template_id=t.id))
    if body.lab_version_id is None:
        raise ApiError("validation_error", "lab_version_id is required to clone", 400)
    lv, lab = await load_lab_version_visible(db, user, body.lab_version_id)
    pub, priv = await get_bundle(db, lv.id, "public"), await get_bundle(db, lv.id, "private")
    try:
        content = dr.content_from_bundles(pub.data, priv.data)
    except LabValidationError as e:
        raise _invalid(e) from e
    lab_def = content["lab"]
    if lab.owner_id == user.id:
        versions = (await db.scalars(select(LabVersion.version).where(LabVersion.lab_id == lab.id))).all()
        major, minor, *_ = max((_semver(v) for v in versions), default=(1, 0, 0))
        lab_def["version"] = f"{major}.{minor + 1}.0"
    else:
        lab_def["id"] = await _unique_slug(db, body.slug or f"{lab.slug}-{user.short_id}")
        lab_def["version"] = "1.0.0"
        lab_def["title"] = f"{lab_def.get('title', lab.title)} (copy)"[:200]
    if body.title:
        lab_def["title"] = body.title
    return await _out(db, await _create(db, user, content, "clone", base=lv))


@router.post("/drafts/import", status_code=201)
async def import_draft(file: UploadFile, user: User = Depends(Authz(Action.lab_manage)),
                       db: AsyncSession = Depends(get_db)):
    """A draft from an uploaded lab pack (.tar.gz, as exported). The pack's paths, sizes and encodings must
    be valid; schema problems are reported by the draft's validation so the author can fix them."""
    data = await file.read(dr.MAX_UPLOAD_BYTES + 1)
    try:
        content = dr.content_from_files(dr.from_targz(data))
    except LabValidationError as e:
        raise _invalid(e) from e
    return await _out(db, await _create(db, user, content, "import"))


@router.get("/drafts/{draft_id}")
async def get_draft(draft_id: uuid.UUID, user: User = Depends(Authz(Action.lab_manage)),
                    db: AsyncSession = Depends(get_db)):
    return await _out(db, await _load(db, user, draft_id))


def _ensure_editable(d: LabDraft) -> None:
    if d.status == "published":
        raise ApiError("draft_published", "this draft is published and read-only; clone the published version "
                       "to prepare a new one", 409)
    if d.status == "testing":
        raise ApiError("draft_testing", "a test run is in progress; wait for it to finish", 409)


async def _save(db: AsyncSession, d: LabDraft, content: dict[str, Any]) -> dict[str, Any]:
    if content != d.content:
        d.content = content
        _denorm(d)
        if d.status in ("passed", "failed"):
            d.status = "draft"  # the last test no longer describes this content
    await _validate(db, d)
    await db.commit()
    await db.refresh(d)
    return await _out(db, d)


class DraftUpdate(BaseModel):
    lab: dict[str, Any] | None = None
    files: dict[str, str] | None = None


@router.put("/drafts/{draft_id}")
async def update_draft(draft_id: uuid.UUID, body: DraftUpdate, user: User = Depends(Authz(Action.lab_manage)),
                       db: AsyncSession = Depends(get_db)):
    """Save the form builder's lab and/or editable files. Invalid content is saved too (a draft is work in
    progress); the response carries the validation result for the always-visible validation panel."""
    d = await _load(db, user, draft_id, for_update=True)
    _ensure_editable(d)
    try:
        content = dr.apply_edit(d.content, body.lab, body.files)
    except LabValidationError as e:
        raise _invalid(e, d.content.get("lab")) from e
    return await _save(db, d, content)


@router.delete("/drafts/{draft_id}", status_code=204)
async def delete_draft(draft_id: uuid.UUID, user: User = Depends(Authz(Action.lab_manage)),
                       db: AsyncSession = Depends(get_db)):
    """Deleting a draft never touches published lab versions."""
    d = await _load(db, user, draft_id, for_update=True)
    if d.status == "testing":
        raise ApiError("draft_testing", "a test run is in progress; wait for it to finish", 409)
    await db.delete(d)
    await db.commit()


class YamlIn(BaseModel):
    yaml: str = Field(max_length=dr.MAX_LAB_JSON_BYTES)


@router.get("/drafts/{draft_id}/yaml")
async def get_yaml(draft_id: uuid.UUID, user: User = Depends(Authz(Action.lab_manage)),
                   db: AsyncSession = Depends(get_db)):
    d = await load_draft_for(db, user, draft_id)
    return {"yaml": dr.lab_to_yaml(d.content["lab"])}


@router.put("/drafts/{draft_id}/yaml")
async def put_yaml(draft_id: uuid.UUID, body: YamlIn, user: User = Depends(Authz(Action.lab_manage)),
                   db: AsyncSession = Depends(get_db)):
    """"Edit as YAML": the text must be a YAML mapping (else 422, nothing saved); it then replaces the lab
    exactly like a form save. YAML comments are not kept: the draft stores the lab as JSON."""
    d = await _load(db, user, draft_id, for_update=True)
    _ensure_editable(d)
    try:
        lab = dr.yaml_to_lab(body.yaml)
        content = dr.apply_edit(d.content, lab, None)
    except LabValidationError as e:
        raise _invalid(e) from e
    out = await _save(db, d, content)
    out["yaml"] = dr.lab_to_yaml(d.content["lab"])
    return out


@router.post("/drafts/{draft_id}/validate")
async def validate_draft(draft_id: uuid.UUID, user: User = Depends(Authz(Action.lab_manage)),
                         db: AsyncSession = Depends(get_db)):
    """Row-level errors from the pack, schema, check-parameter, capability and scenario checks, plus the
    id/version rules publishing will enforce."""
    d = await load_draft_for(db, user, draft_id, for_update=True)
    result = await _validate(db, d)
    await db.commit()
    return result


@router.get("/drafts/{draft_id}/preview")
async def preview_draft(draft_id: uuid.UUID, user: User = Depends(Authz(Action.lab_manage)),
                        db: AsyncSession = Depends(get_db)):
    """The draft exactly as a student would see it (the same redacted view as the student API), rendered
    with the viewer's own short id. Never includes check definitions or private files."""
    d = await load_draft_for(db, user, draft_id)
    try:
        pkg = dr.package(d.content)
    except LabValidationError as e:
        raise _invalid(e, d.content.get("lab")) from e
    variables = compute_variables(pkg.definition, user.short_id)
    return {"lab": student_lab_view(pkg.definition, variables), "variables": variables}


# ------------------------------------------------------------------------ test run + publish gate
def _stale(d: LabDraft) -> bool:
    if d.status != "testing":
        return False
    started = (d.last_test or {}).get("started_at")
    since = datetime.fromisoformat(started) if started else d.updated_at
    return since < _now() - timedelta(seconds=get_settings().builder_test_timeout_s)


async def _load(db: AsyncSession, user: User, draft_id: uuid.UUID, for_update: bool = False) -> LabDraft:
    """load_draft_for, and a run still "testing" past `builder_test_timeout_s` (the API restarted mid-run) is
    reported as interrupted, so a draft can never stay locked."""
    d = await load_draft_for(db, user, draft_id, for_update=for_update)
    if _stale(d):
        if not for_update:
            d = await load_draft_for(db, user, draft_id, for_update=True)
        if _stale(d):
            d.last_test = {**(d.last_test or {}), "status": "error", "finished_at": _now().isoformat(),
                           "error": "the test run was interrupted (timeout or restart); run it again"}
            d.status = "failed"
            await db.commit()
            await db.refresh(d)
    return d


def _scenario_out(r: labtest.ScenarioResult) -> dict[str, Any]:
    eng, _, scenario = r.name.partition("/")
    return {"name": r.name, "engine": eng, "scenario": scenario, "expected": str(r.expected),
            "actual": None if r.actual is None else str(r.actual), "ok": r.ok, "detail": r.detail,
            "tasks": (r.result or {}).get("tasks", [])}


async def _run_test(draft_id: uuid.UUID, run_id: str, pkg: LabPackage, expected: dict[str, Decimal],
                    sandbox_ids: dict[str, str]) -> None:
    """Background task: each scenario in a fresh sandbox on the platform runner, one at a time (labtest).
    Results are written as they land; a write only applies while this run is still the draft's current one."""

    async def write(fn: Callable[[LabDraft, dict[str, Any]], None]) -> None:
        async with sessionmaker()() as db:
            d = await db.scalar(select(LabDraft).where(LabDraft.id == draft_id).with_for_update())
            if d is None or d.status != "testing" or (d.last_test or {}).get("id") != run_id:
                return
            lt = dict(d.last_test)
            fn(d, lt)
            d.last_test = lt
            await db.commit()

    async def on_result(r: labtest.ScenarioResult) -> None:
        await write(lambda _d, lt: lt.update(scenarios=[*lt.get("scenarios", []), _scenario_out(r)]))

    error: str | None = None
    results: list[labtest.ScenarioResult] = []
    try:
        results = await asyncio.wait_for(
            labtest.check_pack(pkg, get_runner(), expected=expected, sandbox_id_for=sandbox_ids.__getitem__,
                               on_result=on_result),
            timeout=get_settings().builder_test_timeout_s)
    except TimeoutError:
        error = "the test run took too long and was stopped"
    except RunnerError as e:
        error = f"the lab runtime refused the test run: {e.message}"
    except Exception as e:  # a crashed run must still unlock the draft
        log.error("background.task.failed", task="lab_builder_test", draft_id=str(draft_id), error=repr(e))
        error = "the test run failed unexpectedly; see the server log"
    passed = error is None and bool(results) and all(r.ok for r in results)

    def finish(d: LabDraft, lt: dict[str, Any]) -> None:
        lt.update(status="passed" if passed else ("error" if error else "failed"), error=error,
                  finished_at=_now().isoformat())
        d.status = "passed" if passed else "failed"
        d.tested_sha256 = lt["content_sha256"]
    await write(finish)


@router.post("/drafts/{draft_id}/test", status_code=202)
async def test_draft(draft_id: uuid.UUID, user: User = Depends(Authz(Action.lab_manage)),
                     db: AsyncSession = Depends(get_db)):
    """Start a test run of the current content: the empty, partial (if any) and solution scenarios, each in
    a fresh real sandbox on every engine the lab may run on. Answers 202 at once; poll the draft for
    `last_test` (per-scenario, per-check results) and the final status `passed` or `failed`."""
    s = get_settings()
    d = await _load(db, user, draft_id, for_update=True)
    _ensure_editable(d)
    result = await _validate(db, d)
    if not result["ok"]:
        await db.commit()
        raise ApiError("lab_invalid", "fix the validation errors before testing", 422,
                       extra={"errors": result["errors"]})
    busy = await db.scalar(select(func.count()).select_from(LabDraft).where(
        LabDraft.status == "testing", LabDraft.updated_at > _now() - timedelta(seconds=s.builder_test_timeout_s)))
    if (busy or 0) >= s.builder_max_concurrent_tests:
        await db.commit()
        raise ApiError("test_capacity_full", "other lab tests are running; try again in a minute", 429,
                       headers={"Retry-After": "60"})
    pkg = dr.package(d.content)
    expected, _ = dr.expectations(dr.draft_files(d.content), pkg.definition)
    run_id = str(uuid.uuid4())
    plan = labtest.scenario_plan(pkg, expected)
    sandbox_ids = {f"{e}/{n}": str(uuid.uuid5(uuid.UUID(run_id), f"{e}/{n}")) for e, n in plan}
    d.status = "testing"
    d.tested_sha256 = None
    d.last_test = {"id": run_id, "status": "running", "content_sha256": pkg.content_sha256,
                   "started_at": _now().isoformat(), "finished_at": None, "started_by": str(user.id),
                   "expected": {k: str(v) for k, v in expected.items()},
                   "plan": list(sandbox_ids), "scenarios": [], "sandbox_ids": list(sandbox_ids.values()),
                   "error": None}
    await db.commit()
    await db.refresh(d)
    background.spawn(_run_test(d.id, run_id, pkg, expected, sandbox_ids), name=f"lab-test-{d.id}")
    return await _out(db, d)


@router.post("/drafts/{draft_id}/publish")
async def publish_draft(draft_id: uuid.UUID, user: User = Depends(Authz(Action.lab_manage)),
                        db: AsyncSession = Depends(get_db)):
    """Publish the draft as a new immutable lab version owned by the draft's author (private until shared).
    Allowed only after a passing test run of exactly the current content."""
    d = await _load(db, user, draft_id, for_update=True)
    _ensure_editable(d)
    result = await _validate(db, d)
    if not result["ok"]:
        await db.commit()
        raise ApiError("lab_invalid", "fix the validation errors before publishing", 422,
                       extra={"errors": result["errors"]})
    if d.status != "passed" or d.tested_sha256 != result["content_sha256"]:
        await db.commit()
        raise ApiError("test_required", "publishing needs a passing test run of the current content; "
                       "run the test", 409)
    pkg = dr.package(d.content)
    lv, created = await import_package(db, pkg, owner_id=d.owner_id)
    if not created:  # _validate already refuses a published version; this closes the race
        raise ApiError("lab_version_conflict", f"{pkg.definition.id}@{pkg.definition.version} is already "
                       "published; bump the version", 409)
    lab = await db.get(Lab, lv.lab_id)
    assert lab is not None
    lab.title = pkg.definition.title
    d.status = "published"
    d.published_version_id = lv.id
    audit.record(db, user, "lab.published", draft_id=d.id, lab_id=lab.id, lab_version_id=lv.id,
                 slug=lab.slug, version=lv.version, content_sha256=lv.content_sha256)
    await db.commit()
    await db.refresh(d)
    return {"draft": await _out(db, d),
            "lab_version": {"id": str(lv.id), "lab_id": str(lab.id), "slug": lab.slug, "version": lv.version,
                            "title": lab.title, "shared": lab.shared}}
