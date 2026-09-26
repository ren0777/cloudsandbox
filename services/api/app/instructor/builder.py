"""Instructor Lab Builder API (phase 8, docs/NEXT.md milestone 36): check-type catalogue for the form
builder, lab drafts (blank / clone / import), YAML round-trip, row-level validation and student preview.

Drafts hold private files (reference solutions), so every draft route answers 404 to anyone but the draft's
owner or an admin (PLAN §9, §7b). Testing and publishing a draft are milestone 37."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..auth.policy import Action, Authz, load_draft_for, load_lab_version_visible
from ..db import get_db
from ..errors import ApiError
from ..grader import registry
from ..grader.checks import load_all
from ..labs import drafts as dr
from ..labs.importer import get_bundle
from ..labs.render import compute_variables, student_lab_view
from ..labs.schema import LabValidationError
from ..labs.schema.v1 import SLUG, CheckSpec, Service
from ..models import Lab, LabDraft, LabVersion, Role, User
from ..runtime import emulators

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


def _semver(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))  # lab versions match SEMVER (schema v1)


async def _create(db: AsyncSession, user: User, content: dict[str, Any], source: str,
                  base: LabVersion | None = None) -> LabDraft:
    d = LabDraft(owner_id=user.id, content=content, status="draft",
                 base_lab_version_id=base.id if base else None, slug="", title="")
    _denorm(d)
    db.add(d)
    await db.flush()
    await _validate(db, d)
    audit.record(db, user, "lab.draft_created", draft_id=d.id, source=source, slug=d.slug,
                 lab_version_id=base.id if base else None)
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
    source: str = Field("blank", pattern=r"^(blank|clone)$")
    lab_version_id: uuid.UUID | None = None  # clone: a lab version the user can see
    title: str | None = Field(None, min_length=1, max_length=200)
    slug: str | None = Field(None, pattern=SLUG)


@router.post("/drafts", status_code=201)
async def create_draft(body: DraftIn, user: User = Depends(Authz(Action.lab_manage)),
                       db: AsyncSession = Depends(get_db)):
    """Blank draft, or a clone of a visible lab version. Cloning your own lab prepares its next version
    (same id, next minor version); cloning anyone else's lab (or a built-in mission) starts a new lab with a
    new id, so it can never overwrite the original."""
    if body.source == "blank":
        slug = await _unique_slug(db, body.slug or f"new-lab-{user.short_id}")
        return await _out(db, await _create(db, user, dr.blank_content(slug, body.title or "Untitled lab"), "blank"))
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
    return await _out(db, await load_draft_for(db, user, draft_id))


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
    d = await load_draft_for(db, user, draft_id, for_update=True)
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
    d = await load_draft_for(db, user, draft_id, for_update=True)
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
    d = await load_draft_for(db, user, draft_id, for_update=True)
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
