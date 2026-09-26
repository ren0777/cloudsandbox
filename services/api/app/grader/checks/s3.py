"""S3 checks. Evidence shape (collector 's3'):
{"buckets": {name: {"versioning": "Enabled"|"Suspended"|None, "tags": {k: v},
                    "objects": {key: {"size": int, "etag": str, "content_type": str|None}},
                    "objects_truncated": bool}}}
"""

from typing import Literal

from pydantic import Field

from ..registry import CheckOutcome, Params, check

BUCKET = Field(min_length=3, max_length=63, pattern=r"^[a-z0-9][a-z0-9.-]+[a-z0-9]$")


def _buckets(ev: dict) -> dict:
    return ev.get("s3", {}).get("buckets", {})


class BucketParams(Params):
    bucket: str = BUCKET


@check("s3.bucket_exists", BucketParams, "s3", ["s3:ListBuckets"])
def bucket_exists(p: BucketParams, ev: dict) -> CheckOutcome:
    ok = p.bucket in _buckets(ev)
    return CheckOutcome(ok, "exists", "exists" if ok else "missing",
                        f"Bucket {p.bucket} exists" if ok else f"Bucket {p.bucket} was not found")


class VersioningParams(Params):
    bucket: str = BUCKET
    status: Literal["Enabled", "Suspended"] = "Enabled"


@check("s3.versioning", VersioningParams, "s3", ["s3:ListBuckets", "s3:GetBucketVersioning"])
def versioning(p: VersioningParams, ev: dict) -> CheckOutcome:
    b = _buckets(ev).get(p.bucket)
    if b is None:
        return CheckOutcome(False, p.status, "bucket missing", f"Bucket {p.bucket} was not found")
    actual = b.get("versioning") or "Never enabled"
    ok = actual == p.status
    return CheckOutcome(ok, p.status, actual,
                        f"Versioning on {p.bucket} is {actual}" if ok
                        else f"Versioning on {p.bucket} is {actual}; expected {p.status}")


class ObjectParams(Params):
    bucket: str = BUCKET
    key: str = Field(min_length=1, max_length=1024)
    min_size: int = Field(0, ge=0)


@check("s3.object_exists", ObjectParams, "s3", ["s3:ListBuckets", "s3:ListObjectsV2", "s3:HeadObject"])
def object_exists(p: ObjectParams, ev: dict) -> CheckOutcome:
    b = _buckets(ev).get(p.bucket)
    if b is None:
        return CheckOutcome(False, f"{p.key} present", "bucket missing", f"Bucket {p.bucket} was not found")
    obj = b.get("objects", {}).get(p.key)
    if obj is None:
        return CheckOutcome(False, f"{p.key} present", "missing", f"Object {p.key} is not in {p.bucket}")
    if obj["size"] < p.min_size:
        return CheckOutcome(False, f">= {p.min_size} bytes", f"{obj['size']} bytes",
                            f"Object {p.key} is too small ({obj['size']} bytes)")
    return CheckOutcome(True, f"{p.key} present", f"present ({obj['size']} bytes)",
                        f"Object {p.key} is in {p.bucket}")


class ContentTypeParams(Params):
    bucket: str = BUCKET
    key: str = Field(min_length=1, max_length=1024)
    content_type: str = Field(min_length=3, max_length=100)


@check("s3.object_content_type", ContentTypeParams, "s3",
       ["s3:ListBuckets", "s3:ListObjectsV2", "s3:HeadObject"])
def object_content_type(p: ContentTypeParams, ev: dict) -> CheckOutcome:
    obj = _buckets(ev).get(p.bucket, {}).get("objects", {}).get(p.key)
    if obj is None:
        return CheckOutcome(False, p.content_type, "object missing", f"Object {p.key} is not in {p.bucket}")
    actual = (obj.get("content_type") or "").split(";")[0].strip()
    ok = actual == p.content_type
    return CheckOutcome(ok, p.content_type, actual or "none",
                        f"{p.key} has content type {actual}" if ok
                        else f"{p.key} has content type {actual or 'none'}; expected {p.content_type}")


class TagParams(Params):
    bucket: str = BUCKET
    key: str = Field(min_length=1, max_length=128)
    value: str = Field(max_length=256)


@check("s3.bucket_tag", TagParams, "s3", ["s3:ListBuckets", "s3:GetBucketTagging"])
def bucket_tag(p: TagParams, ev: dict) -> CheckOutcome:
    b = _buckets(ev).get(p.bucket)
    if b is None:
        return CheckOutcome(False, f"{p.key}={p.value}", "bucket missing", f"Bucket {p.bucket} was not found")
    actual = b.get("tags", {}).get(p.key)
    ok = actual == p.value
    return CheckOutcome(ok, f"{p.key}={p.value}", f"{p.key}={actual}" if actual is not None else "tag missing",
                        f"Tag {p.key}={p.value} is set" if ok
                        else f"Bucket {p.bucket} should have tag {p.key}={p.value}")
