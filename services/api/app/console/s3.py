"""Simplified S3 console API. Acts on the student's own emulator through boto3, exactly like the CLI,
so both paths change the same simulated AWS state. Only READY sessions accept calls; a session being
submitted answers 409 session_frozen (PLAN §5)."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.policy import Action, Authz
from ..config import get_settings
from ..db import get_db
from ..errors import ApiError
from .common import aws_call, console_session
from ..models import LabSession, SessionState as S, User

router = APIRouter(prefix="/api/sessions/{session_id}/console/s3", tags=["console"])
BUCKET_RE = r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$"


async def _session(session_id: uuid.UUID, user: User, db: AsyncSession) -> LabSession:
    return await console_session(session_id, user, db)


async def _call(sess: LabSession, fn_name: str, **kw: Any) -> dict:
    return await aws_call(sess, "s3", fn_name, **kw)


class TagIn(BaseModel):
    key: str = Field(min_length=1, max_length=128)
    value: str = Field("", max_length=256)


class CreateBucketIn(BaseModel):
    """Mirrors the AWS console 'Create bucket' form. Settings the simulator can't honour are rejected
    with a clear message instead of being silently ignored (PLAN console fidelity principle)."""
    name: str = Field(pattern=BUCKET_RE)
    region: str = "us-east-1"
    object_ownership: str = Field("BucketOwnerEnforced",
                                  pattern=r"^(BucketOwnerEnforced|ObjectWriter|BucketOwnerPreferred)$")
    block_public_access: bool = True
    versioning: str = Field("Disabled", pattern=r"^(Disabled|Enabled)$")
    tags: list[TagIn] = Field(default_factory=list, max_length=50)


class VersioningIn(BaseModel):
    status: str = Field(pattern=r"^(Enabled|Suspended)$")


class TagsIn(BaseModel):
    tags: dict[str, str] = Field(max_length=50)


class PublicAccessBlockIn(BaseModel):
    block_public_acls: bool = True
    ignore_public_acls: bool = True
    block_public_policy: bool = True
    restrict_public_buckets: bool = True


class PolicyIn(BaseModel):
    policy: str = Field(min_length=2, max_length=20_000)


SUPPORTED_REGIONS = ("us-east-1",)
ALL_ON = {"BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True,
          "RestrictPublicBuckets": True}


async def _optional(sess: LabSession, fn: str, missing: tuple[str, ...], **kw) -> dict | None:
    try:
        return await _call(sess, fn, **kw)
    except ApiError as e:
        if e.extra.get("aws_code") in missing:
            return None
        raise


async def _pab(sess: LabSession, bucket: str) -> dict:
    out = await _optional(sess, "get_public_access_block", ("NoSuchPublicAccessBlockConfiguration",),
                          Bucket=bucket)
    cfg = (out or {}).get("PublicAccessBlockConfiguration") or {}
    return {k: bool(cfg.get(k, False)) for k in ALL_ON}


async def _policy(sess: LabSession, bucket: str) -> str | None:
    out = await _optional(sess, "get_bucket_policy", ("NoSuchBucketPolicy",), Bucket=bucket)
    return out.get("Policy") if out else None


def _access(pab: dict, policy: str | None) -> str:
    if all(pab.values()):
        return "Bucket and objects not public"
    if policy and '"*"' in policy.replace(" ", "") and not pab["BlockPublicPolicy"]:
        return "Public"
    return "Objects can be public"


@router.get("/buckets")
async def list_buckets(session_id: uuid.UUID, user: User = Depends(Authz(Action.session_use)),
                       db: AsyncSession = Depends(get_db)):
    sess = await _session(session_id, user, db)
    out = await _call(sess, "list_buckets")
    rows = []
    for b in out.get("Buckets", []):
        rows.append({"name": b["Name"], "created_at": b.get("CreationDate"), "region": "us-east-1",
                     "access": _access(await _pab(sess, b["Name"]), await _policy(sess, b["Name"]))})
    return {"buckets": rows}


@router.post("/buckets", status_code=201)
async def create_bucket(session_id: uuid.UUID, body: CreateBucketIn,
                        user: User = Depends(Authz(Action.session_use)), db: AsyncSession = Depends(get_db)):
    sess = await _session(session_id, user, db)
    if body.region not in SUPPORTED_REGIONS:
        raise ApiError("not_in_simulator", "The Stackora simulator only provides the us-east-1 Region.", 400)
    if body.object_ownership != "BucketOwnerEnforced":
        raise ApiError("not_in_simulator", "ACLs are not available in the Stackora simulator. "
                       "Choose ACLs disabled (recommended).", 400)
    await _call(sess, "create_bucket", Bucket=body.name)
    if body.block_public_access:
        await _call(sess, "put_public_access_block", Bucket=body.name, PublicAccessBlockConfiguration=ALL_ON)
    if body.versioning == "Enabled":
        await _call(sess, "put_bucket_versioning", Bucket=body.name,
                    VersioningConfiguration={"Status": "Enabled"})
    tags = [t for t in body.tags if t.key.strip()]
    if tags:
        await _call(sess, "put_bucket_tagging", Bucket=body.name,
                    Tagging={"TagSet": [{"Key": t.key, "Value": t.value} for t in tags]})
    return {"name": body.name}


@router.delete("/buckets/{bucket}", status_code=204)
async def delete_bucket(session_id: uuid.UUID, bucket: str, user: User = Depends(Authz(Action.session_use)),
                        db: AsyncSession = Depends(get_db)):
    sess = await _session(session_id, user, db)
    await _call(sess, "delete_bucket", Bucket=bucket)


@router.get("/buckets/{bucket}")
async def bucket_details(session_id: uuid.UUID, bucket: str, user: User = Depends(Authz(Action.session_use)),
                         db: AsyncSession = Depends(get_db)):
    sess = await _session(session_id, user, db)
    v = await _call(sess, "get_bucket_versioning", Bucket=bucket)
    tags_out = await _optional(sess, "get_bucket_tagging", ("NoSuchTagSet", "NoSuchTagSetError"), Bucket=bucket)
    tags = {t["Key"]: t["Value"] for t in (tags_out or {}).get("TagSet", [])}
    loc = (await _call(sess, "get_bucket_location", Bucket=bucket)).get("LocationConstraint") or "us-east-1"
    pab = await _pab(sess, bucket)
    policy = await _policy(sess, bucket)
    return {"name": bucket, "region": loc, "arn": f"arn:aws:s3:::{bucket}",
            "versioning": v.get("Status") or "Disabled", "tags": tags,
            "object_ownership": "BucketOwnerEnforced", "public_access_block": pab, "policy": policy,
            "access": _access(pab, policy)}


@router.put("/buckets/{bucket}/versioning")
async def put_versioning(session_id: uuid.UUID, bucket: str, body: VersioningIn,
                         user: User = Depends(Authz(Action.session_use)), db: AsyncSession = Depends(get_db)):
    sess = await _session(session_id, user, db)
    await _call(sess, "put_bucket_versioning", Bucket=bucket, VersioningConfiguration={"Status": body.status})
    return {"versioning": body.status}


@router.put("/buckets/{bucket}/public-access-block")
async def put_public_access_block(session_id: uuid.UUID, bucket: str, body: PublicAccessBlockIn,
                                  user: User = Depends(Authz(Action.session_use)),
                                  db: AsyncSession = Depends(get_db)):
    sess = await _session(session_id, user, db)
    cfg = {"BlockPublicAcls": body.block_public_acls, "IgnorePublicAcls": body.ignore_public_acls,
           "BlockPublicPolicy": body.block_public_policy, "RestrictPublicBuckets": body.restrict_public_buckets}
    await _call(sess, "put_public_access_block", Bucket=bucket, PublicAccessBlockConfiguration=cfg)
    return {"public_access_block": cfg}


@router.put("/buckets/{bucket}/policy")
async def put_policy(session_id: uuid.UUID, bucket: str, body: PolicyIn,
                     user: User = Depends(Authz(Action.session_use)), db: AsyncSession = Depends(get_db)):
    sess = await _session(session_id, user, db)
    try:
        json.loads(body.policy)
    except ValueError:
        raise ApiError("invalid_policy", "The bucket policy must be valid JSON.", 400) from None
    await _call(sess, "put_bucket_policy", Bucket=bucket, Policy=body.policy)
    return {"policy": body.policy}


@router.delete("/buckets/{bucket}/policy", status_code=204)
async def delete_policy(session_id: uuid.UUID, bucket: str, user: User = Depends(Authz(Action.session_use)),
                        db: AsyncSession = Depends(get_db)):
    sess = await _session(session_id, user, db)
    await _call(sess, "delete_bucket_policy", Bucket=bucket)


@router.put("/buckets/{bucket}/tags")
async def put_tags(session_id: uuid.UUID, bucket: str, body: TagsIn,
                   user: User = Depends(Authz(Action.session_use)), db: AsyncSession = Depends(get_db)):
    sess = await _session(session_id, user, db)
    if body.tags:
        await _call(sess, "put_bucket_tagging", Bucket=bucket,
                    Tagging={"TagSet": [{"Key": k, "Value": v} for k, v in body.tags.items()]})
    else:
        await _call(sess, "delete_bucket_tagging", Bucket=bucket)
    return {"tags": body.tags}


@router.get("/buckets/{bucket}/objects")
async def list_objects(session_id: uuid.UUID, bucket: str, prefix: str = "",
                       user: User = Depends(Authz(Action.session_use)), db: AsyncSession = Depends(get_db)):
    sess = await _session(session_id, user, db)
    out = await _call(sess, "list_objects_v2", Bucket=bucket, Prefix=prefix, MaxKeys=1000)
    return {"objects": [{"key": o["Key"], "size": o["Size"], "last_modified": o.get("LastModified"),
                         "etag": o.get("ETag", "").strip('"')} for o in out.get("Contents", [])],
            "truncated": bool(out.get("IsTruncated"))}


@router.post("/buckets/{bucket}/objects", status_code=201)
async def upload_object(session_id: uuid.UUID, bucket: str, file: UploadFile = File(...),
                        key: str | None = Query(None, max_length=1024),
                        user: User = Depends(Authz(Action.session_use)), db: AsyncSession = Depends(get_db)):
    sess = await _session(session_id, user, db)
    limit = get_settings().console_max_upload_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise ApiError("too_large", f"uploads are limited to {limit // (1024 * 1024)} MiB", 413)
    name = key or file.filename or "upload"
    ctype = file.content_type if file.content_type and file.content_type != "application/octet-stream" \
        else (mimetypes.guess_type(name)[0] or "application/octet-stream")
    await _call(sess, "put_object", Bucket=bucket, Key=name, Body=data, ContentType=ctype)
    return {"key": name, "size": len(data), "content_type": ctype}


@router.delete("/buckets/{bucket}/objects", status_code=204)
async def delete_object(session_id: uuid.UUID, bucket: str, key: str = Query(..., max_length=1024),
                        user: User = Depends(Authz(Action.session_use)), db: AsyncSession = Depends(get_db)):
    sess = await _session(session_id, user, db)
    await _call(sess, "delete_object", Bucket=bucket, Key=key)


@router.get("/buckets/{bucket}/objects/download")
async def download_object(session_id: uuid.UUID, bucket: str, key: str = Query(..., max_length=1024),
                          user: User = Depends(Authz(Action.session_use)), db: AsyncSession = Depends(get_db)):
    sess = await _session(session_id, user, db)
    out = await _call(sess, "get_object", Bucket=bucket, Key=key)
    body = await asyncio.to_thread(out["Body"].read)
    safe = key.rsplit("/", 1)[-1].replace('"', "")
    return Response(body, media_type=out.get("ContentType") or "application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{safe}"',
                             "X-Content-Type-Options": "nosniff"})
