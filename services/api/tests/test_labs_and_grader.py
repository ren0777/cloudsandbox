"""Lab schema/loader, capability validation, S3 checks and pure grading (no DB, no Docker)."""

from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from app.grader.grade import grade, student_view
from app.labs.package import load_pack
from app.labs.render import compute_variables, student_lab_view
from app.labs.schema import LabValidationError, parse_definition
from app.runtime import capabilities
from tests.conftest import LABS

S3_BASICS = Path(LABS) / "s3-basics"


def _pack(tmp_path: Path, mutate) -> Path:
    dst = tmp_path / "lab"
    shutil.copytree(S3_BASICS, dst)
    data = yaml.safe_load((dst / "lab.yaml").read_text(encoding="utf-8"))
    mutate(data)
    (dst / "lab.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return dst


def ev(buckets: dict) -> dict:
    return {"format": 1, "captured_at": "x", "collectors": {"s3": {"buckets": buckets}}}


def bucket(versioning=None, tags=None, objects=None) -> dict:
    return {"versioning": versioning, "tags": tags or {}, "objects": objects or {}, "objects_truncated": False}


HTML = {"index.html": {"size": 20, "etag": "e", "content_type": "text/html"}}
FULL = ev({"cafe-alice1-site": bucket("Enabled", {"project": "cloudcafe"}, HTML)})


# ------------------------------------------------------------------------------------ loader
def test_s3_basics_loads_and_bundles_are_deterministic():
    a, b = load_pack(S3_BASICS), load_pack(S3_BASICS)
    assert a.definition.id == "s3-basics" and a.definition.schema_version == 1
    assert a.content_sha256 == b.content_sha256 and a.public_bundle == b.public_bundle
    from app.labs.package import tar_members
    assert "lab.yaml" in tar_members(a.public_bundle)
    assert not any("solution" in n for n in tar_members(a.public_bundle))
    assert set(tar_members(a.private_bundle)) >= {"solution.sh", "partial.sh", "expected.yaml"}


@pytest.mark.parametrize("mutate,needle", [
    (lambda d: d.update(schema_version=2), "unsupported schema_version"),
    (lambda d: d.pop("schema_version"), "unsupported schema_version"),
    (lambda d: d.update(bogus=1), "bogus"),
    (lambda d: d["tasks"][0]["checks"].append({"type": "s3.nope", "bucket": "x"}), "unknown check type"),
    (lambda d: d["tasks"][0]["checks"].append({"type": "audit.called", "action": "s3:PutObject"}),
     "not available yet"),
    (lambda d: d["tasks"][0]["checks"].append({"type": "lambda.function", "name": "x"}), "not listed in services"),
    # Moto/Floci can't execute Lambda code, so an invoke check needs a code-running engine pinned
    (lambda d: (d["services"].append("lambda"), d["tasks"][0]["checks"].append(
        {"type": "lambda.invoke_returns", "name": "x", "payload": {}, "expect": {}})), "lambda:Invoke"),
    (lambda d: d["requires"].append("s3:PutBucketWebsite"), "unsupported emulator operations"),
    (lambda d: d["requires"].append("s3:MadeUpOperation"), "unsupported emulator operations"),
    (lambda d: d["tasks"][1]["checks"][0].update(status="Sometimes"), "status"),
    (lambda d: d["tasks"][0]["checks"][0].update(extra_param=1), "extra_param"),
    (lambda d: d.update(setup={"script": "setup.sh"}), "setup script"),
    (lambda d: d["tasks"].append(dict(d["tasks"][0])), "task ids must be unique"),
    (lambda d: d["tasks"][0].update(title="{{ undefined_var }}"), "template error"),
])
def test_invalid_labs_rejected(tmp_path, mutate, needle):
    with pytest.raises(LabValidationError) as e:
        load_pack(_pack(tmp_path, mutate))
    assert needle in str(e.value), e.value.errors


def test_capability_levels():
    caps = capabilities.load()
    assert caps.level("s3:CreateBucket") == "supported"
    assert caps.level("s3:PutBucketWebsite") == "unsupported"
    assert caps.level("s3:Nope") is None
    assert caps.service_status() == {"s3": "available", "iam": "available", "ec2": "available",
                                     "lambda": "available", "dynamodb": "available"}


def test_variables_render_per_student():
    d = load_pack(S3_BASICS).definition
    v = compute_variables(d, "alice1")
    assert v == {"student_short_id": "alice1", "bucket": "cafe-alice1-site"}
    view = student_lab_view(d, v)
    assert view["tasks"][0]["title"] == "Create the S3 bucket cafe-alice1-site"
    assert "checks" not in str(view) and "content_type" not in str(view)  # redacted (PLAN §7b)


# ------------------------------------------------------------------------------------ grading
def _grade(evidence):
    d = load_pack(S3_BASICS).definition
    return grade(d, compute_variables(d, "alice1"), evidence)


def test_score_zero_partial_full():
    assert _grade(ev({}))["score"] == Decimal("0.00")
    partial = ev({"cafe-alice1-site": bucket("Enabled", {}, {"index.html": {
        "size": 11, "etag": "e", "content_type": "text/plain"}})})
    assert _grade(partial)["score"] == Decimal("50.00")
    r = _grade(FULL)
    assert r["score"] == Decimal("100.00") and r["max_score"] == Decimal("100.00")
    assert all(t["passed"] for t in r["tasks"])


def test_same_evidence_same_score():
    assert _grade(FULL) == _grade(FULL)


def test_per_check_records_are_explainable():
    r = _grade(ev({"cafe-alice1-site": bucket("Suspended")}))
    t2 = next(t for t in r["tasks"] if t["task_id"] == "enable-versioning")
    c = t2["checks"][0]
    assert c["check"] == "s3.versioning" and c["expected"] == "Enabled" and c["actual"] == "Suspended"
    assert c["passed"] is False and c["marks_awarded"] == Decimal("0.00")
    assert c["marks_possible"] == Decimal("25.00") and "expected Enabled" in c["message"]


def test_all_scoring_splits_marks_by_weight():
    r = _grade(FULL)
    t3 = next(t for t in r["tasks"] if t["task_id"] == "upload-homepage")
    assert [c["marks_possible"] for c in t3["checks"]] == [Decimal("16.67"), Decimal("8.33")]


def test_student_view_hides_hidden_check_details():
    r = _grade(ev({"cafe-alice1-site": bucket("Enabled", {}, {"index.html": {
        "size": 11, "etag": "e", "content_type": "text/plain"}})}))
    sv = student_view(r)
    text = str(sv)
    assert "text/plain" not in text and "content_type" not in text and "expected" not in text
    hidden = [c for t in sv["tasks"] for c in t["checks"] if c["hidden"]]
    assert hidden and hidden[0]["message"] == "A hidden requirement for this task is not met yet."


def test_proportional_scoring():
    d = load_pack(S3_BASICS).definition
    d.tasks[2].scoring = "proportional"
    r = grade(d, compute_variables(d, "alice1"), ev({"cafe-alice1-site": bucket(objects={
        "index.html": {"size": 3, "etag": "e", "content_type": "text/plain"}})}))
    t3 = next(t for t in r["tasks"] if t["task_id"] == "upload-homepage")
    assert t3["marks_awarded"] == Decimal("16.67")


def test_unknown_schema_rejected_directly():
    with pytest.raises(LabValidationError):
        parse_definition({"schema_version": 99})
