"""Import a lab pack as an immutable lab_versions row (PLAN §7).

    python -m app.labs.importer /labs/s3-basics
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import ApiError
from ..models import Lab, LabVersion, LabVersionBundle
from .package import LabPackage, load_pack
from .schema import LabDefinition, parse_definition


async def import_package(db: AsyncSession, pkg: LabPackage) -> tuple[LabVersion, bool]:
    """Returns (version, created). Same id+version with identical content is a no-op; with different
    content it is rejected — a changed lab needs a new version number."""
    d = pkg.definition
    lab = await db.scalar(select(Lab).where(Lab.slug == d.id))
    if lab is None:
        lab = Lab(slug=d.id, title=d.title)
        db.add(lab)
        await db.flush()
    existing = await db.scalar(select(LabVersion).where(LabVersion.lab_id == lab.id,
                                                        LabVersion.version == d.version))
    if existing is not None:
        if existing.content_sha256 != pkg.content_sha256:
            raise ApiError("lab_version_conflict",
                           f"{d.id}@{d.version} already exists with different content; bump the version",
                           409)
        return existing, False
    from ..grader.registry import get as get_check
    reads = {op for t in d.tasks for c in t.checks for op in get_check(c.type).reads}
    lv = LabVersion(lab_id=lab.id, version=d.version, schema_version=d.schema_version,
                    content_sha256=pkg.content_sha256, yaml_text=pkg.yaml_text,
                    definition=d.model_dump(mode="json"),
                    capabilities_required=sorted(set(d.requires) | reads))
    db.add(lv)
    await db.flush()
    db.add(LabVersionBundle(lab_version_id=lv.id, kind="public", sha256=pkg.public_sha256,
                            data=pkg.public_bundle))
    db.add(LabVersionBundle(lab_version_id=lv.id, kind="private", sha256=pkg.private_sha256,
                            data=pkg.private_bundle))
    await db.flush()
    return lv, True


def definition_of(lv: LabVersion) -> LabDefinition:
    return parse_definition(lv.definition)


async def get_bundle(db: AsyncSession, lab_version_id, kind: str) -> LabVersionBundle:
    b = await db.scalar(select(LabVersionBundle).where(LabVersionBundle.lab_version_id == lab_version_id,
                                                       LabVersionBundle.kind == kind))
    if b is None:
        raise RuntimeError(f"missing {kind} bundle for lab version {lab_version_id}")
    return b


async def _main(paths: list[str]) -> int:
    from ..db import sessionmaker
    from .schema import LabValidationError
    rc = 0
    async with sessionmaker()() as db:
        for p in paths:
            try:
                lv, created = await import_package(db, load_pack(p))
                await db.commit()
                print(f"{'imported' if created else 'unchanged'}: {p} -> {lv.id}")
            except LabValidationError as e:
                rc = 1
                print(f"INVALID {p}:\n  - " + "\n  - ".join(e.errors))
            except ApiError as e:
                rc = 1
                await db.rollback()
                print(f"REJECTED {p}: {e.message}")
    return rc


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv[1:])))
