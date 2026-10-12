"""Audit proxy + audit.* checks (docs/NEXT.md milestone 50): operation resolution against botocore's own
serialiser, the pure checks, lab validation, Mission 16's scoring, and the session/console path through the
REAL proxy (FakeRunner runs images/terminal/audit_proxy.py in front of its Moto). The runner's Docker test and
labtest on every engine live in tests/test_audit_docker.py (marker docker)."""

from __future__ import annotations

import importlib.util
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

import boto3
import pytest
from botocore.config import Config

from app.db import sessionmaker
from app.grader import audit as audit_mod
from app.grader.grade import collectors_for, grade, needs_audit
from app.labs.importer import import_package
from app.labs.package import load_pack, validate_definition
from app.labs.render import compute_variables
from app.labs.schema import parse_definition
from app.models import Assignment, LabSession
from app.sessions import state as st
from tests.conftest import LABS, idem, login, wait_state
from tests.fakes import audit_proxy_path

LAB = Path(LABS) / "s3-versioning-order"
BUCKET = "cafe-alice1-ledger"


def _proxy_module():
    path = audit_proxy_path()
    if path is None:
        pytest.skip("audit proxy source not available")
    spec = importlib.util.spec_from_file_location("audit_proxy", path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ------------------------------------------------------------------------------ resolution
class _Captured(Exception):
    pass


def _event_for(service: str, method: str, **params) -> dict:
    """Serialise one call with botocore (exactly what the AWS CLI sends) and turn the request into the event the
    proxy would record, using the proxy's own parsing functions."""
    proxy = _proxy_module()
    client = boto3.client(service, endpoint_url="http://audit.test:1", region_name="us-east-1",
                          aws_access_key_id="testing", aws_secret_access_key="testing",
                          config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 0}))
    seen = {}

    def grab(request, **_):
        seen["req"] = request
        raise _Captured

    client.meta.events.register("before-send", grab)
    with pytest.raises(_Captured):
        getattr(client, method)(**params)
    req = seen["req"]
    split = urlsplit(req.url)
    body = req.body if isinstance(req.body, bytes | type(None)) else str(req.body).encode()
    def text(x):
        return x.decode() if isinstance(x, bytes) else x
    headers = {text(k): text(v) for k, v in req.headers.items()}  # what arrives on the wire: text headers
    ctype = headers.get("Content-Type") or ""
    from urllib.parse import parse_qs
    return {"method": req.method, "path": split.path, "query": split.query,
            "target": headers.get("X-Amz-Target", ""),
            "action": proxy.form_action(body) if body and ctype.startswith("application/x-www-form-urlencoded") else "",
            "service": proxy.sigv4_service(headers, parse_qs(split.query)),
            "headers": sorted(k.lower() for k in headers)}


CASES = [
    ("s3", "create_bucket", "CreateBucket", {"Bucket": "b"}),
    ("s3", "put_bucket_versioning", "PutBucketVersioning",
     {"Bucket": "b", "VersioningConfiguration": {"Status": "Enabled"}}),
    ("s3", "get_bucket_versioning", "GetBucketVersioning", {"Bucket": "b"}),
    ("s3", "put_bucket_tagging", "PutBucketTagging", {"Bucket": "b", "Tagging": {"TagSet": []}}),
    ("s3", "put_bucket_policy", "PutBucketPolicy", {"Bucket": "b", "Policy": "{}"}),
    ("s3", "put_object", "PutObject", {"Bucket": "b", "Key": "dir/ledger.csv", "Body": b"x"}),
    ("s3", "copy_object", "CopyObject", {"Bucket": "b", "Key": "k2", "CopySource": "b/k"}),
    ("s3", "get_object", "GetObject", {"Bucket": "b", "Key": "k"}),
    ("s3", "head_object", "HeadObject", {"Bucket": "b", "Key": "k"}),
    ("s3", "delete_object", "DeleteObject", {"Bucket": "b", "Key": "k"}),
    ("s3", "delete_objects", "DeleteObjects", {"Bucket": "b", "Delete": {"Objects": [{"Key": "k"}]}}),
    ("s3", "list_objects_v2", "ListObjectsV2", {"Bucket": "b"}),
    ("s3", "list_objects", "ListObjects", {"Bucket": "b"}),
    ("s3", "list_object_versions", "ListObjectVersions", {"Bucket": "b"}),
    ("s3", "list_buckets", "ListBuckets", {}),
    ("s3", "delete_bucket", "DeleteBucket", {"Bucket": "b"}),
    ("s3", "create_multipart_upload", "CreateMultipartUpload", {"Bucket": "b", "Key": "k"}),
    ("s3", "upload_part", "UploadPart", {"Bucket": "b", "Key": "k", "PartNumber": 1, "UploadId": "u", "Body": b"x"}),
    ("s3", "complete_multipart_upload", "CompleteMultipartUpload", {"Bucket": "b", "Key": "k", "UploadId": "u"}),
    ("lambda", "create_function", "CreateFunction",
     {"FunctionName": "f", "Runtime": "python3.12", "Role": "arn:aws:iam::000000000000:role/r", "Handler": "h.h",
      "Code": {"ZipFile": b"x"}}),
    ("lambda", "invoke", "Invoke", {"FunctionName": "f"}),
    ("lambda", "list_functions", "ListFunctions", {}),
    ("lambda", "get_function", "GetFunction", {"FunctionName": "f"}),
    ("lambda", "get_function_configuration", "GetFunctionConfiguration", {"FunctionName": "f"}),
    ("lambda", "update_function_code", "UpdateFunctionCode", {"FunctionName": "f", "ZipFile": b"x"}),
    ("lambda", "update_function_configuration", "UpdateFunctionConfiguration", {"FunctionName": "f", "Timeout": 3}),
    ("lambda", "create_event_source_mapping", "CreateEventSourceMapping",
     {"FunctionName": "f", "EventSourceArn": "arn:aws:sqs:us-east-1:000000000000:q"}),
    ("lambda", "list_event_source_mappings", "ListEventSourceMappings", {}),
    ("lambda", "delete_function", "DeleteFunction", {"FunctionName": "f"}),
    ("dynamodb", "put_item", "PutItem", {"TableName": "t", "Item": {"k": {"S": "v"}}}),
    ("sqs", "send_message", "SendMessage", {"QueueUrl": "http://audit.test:1/000000000000/q", "MessageBody": "m"}),
    ("iam", "create_user", "CreateUser", {"UserName": "u"}),
    ("ec2", "create_vpc", "CreateVpc", {"CidrBlock": "10.0.0.0/16"}),
    ("ec2", "run_instances", "RunInstances", {"ImageId": "ami-1", "MinCount": 1, "MaxCount": 1}),
    ("sns", "create_topic", "CreateTopic", {"Name": "t"}),
]


@pytest.mark.parametrize("service,method,operation,params", CASES, ids=[f"{c[0]}:{c[2]}" for c in CASES])
def test_resolve_matches_what_botocore_serialises(service, method, operation, params):
    assert audit_mod.resolve(_event_for(service, method, **params)) == f"{service}:{operation}"


def test_resolve_edge_cases():
    assert audit_mod.resolve({"service": "", "method": "GET", "path": "/b"}) == "unknown"
    assert audit_mod.resolve({"service": "s3", "method": "PATCH", "path": "/b/k"}) == "s3:?"
    # a future SDK that names the operation in the query
    assert audit_mod.resolve({"service": "s3", "method": "PUT", "path": "/b/k", "query": "x-id=PutObject"}) \
        == "s3:PutObject"
    assert audit_mod.resolve({"service": "s3", "method": "GET", "path": "/b/k", "query": "x-id=Nope"}) \
        == "s3:GetObject"


def test_collector_shapes_and_bounds(monkeypatch):
    assert audit_mod.collect_audit(None) == {"available": False, "dropped": 0, "events": []}
    raw = [{"seq": i, "method": "PUT", "path": "/b", "service": "s3", "status": 200,
            "source": "console" if i % 2 else "forged"} for i in range(1, audit_mod.MAX_STORED_EVENTS + 6)]
    monkeypatch.setattr(audit_mod, "fetch_log", lambda _: {"dropped": 3, "events": list(reversed(raw))})
    out = audit_mod.collect_audit("http://x")
    assert out["available"] and out["dropped"] == 3 + 5 and len(out["events"]) == audit_mod.MAX_STORED_EVENTS
    assert out["events"][0]["seq"] == 6 and {e["source"] for e in out["events"]} == {"cli", "console"}
    assert set(out["events"][0]) == {"seq", "action", "source", "status"}  # no paths, query strings or times


# ------------------------------------------------------------------------------ checks
def ev(*events, available=True) -> dict:
    return {"audit": {"available": available, "dropped": 0,
                      "events": [{"seq": i, "action": a, "source": s, "status": code}
                                 for i, (a, s, code) in enumerate(events, 1)]}}


def run(type_: str, params: dict, evidence: dict):
    from app.grader import registry
    d = registry.get(type_)
    d.ensure_supported()
    return d.fn(d.params_model.model_validate(params), evidence)


def test_called_counts_successes_by_source():
    e = ev(("s3:PutObject", "console", 200), ("s3:PutObject", "cli", 403), ("s3:PutObject", "cli", 200))
    assert run("audit.called", {"action": "s3:PutObject"}, e).passed
    assert run("audit.called", {"action": "s3:PutObject", "source": "cli"}, e).passed
    assert not run("audit.called", {"action": "s3:PutObject", "source": "cli", "min_count": 2}, e).passed
    r = run("audit.called", {"action": "s3:PutObject", "source": "cli"},
            ev(("s3:PutObject", "console", 200)))
    assert not r.passed and "from the console" in r.message and "from the terminal" in r.message
    r = run("audit.called", {"action": "s3:PutObject"}, ev(("s3:PutObject", "cli", 404)))
    assert not r.passed and "did not succeed" in r.message
    r = run("audit.called", {"action": "s3:DeleteBucket"}, e)
    assert not r.passed and r.message == "No successful s3:DeleteBucket call yet"
    r = run("audit.called", {"action": "s3:PutObject"}, ev(available=False))
    assert not r.passed and "not available" in r.message


def test_order_is_an_ordered_subsequence_of_successful_calls():
    order = {"actions": ["s3:PutBucketVersioning", "s3:PutObject"]}
    ok = ev(("s3:CreateBucket", "cli", 200), ("s3:PutBucketVersioning", "console", 200),
            ("s3:ListObjectsV2", "cli", 200), ("s3:PutObject", "cli", 200))
    assert run("audit.order", order, ok).passed
    wrong = ev(("s3:PutObject", "cli", 200), ("s3:PutBucketVersioning", "cli", 200))
    r = run("audit.order", order, wrong)
    assert not r.passed and "must happen after s3:PutBucketVersioning" in r.message
    assert r.actual == "s3:PutObject → s3:PutBucketVersioning"
    fixed = ev(("s3:PutObject", "cli", 200), ("s3:PutBucketVersioning", "cli", 200), ("s3:PutObject", "cli", 200))
    assert run("audit.order", order, fixed).passed  # re-uploading after versioning is the fix
    failed_put = ev(("s3:PutBucketVersioning", "cli", 200), ("s3:PutObject", "cli", 500))
    assert "No successful s3:PutObject" in run("audit.order", order, failed_put).message
    assert not run("audit.order", {**order, "source": "cli"},
                   ev(("s3:PutBucketVersioning", "cli", 200), ("s3:PutObject", "console", 200))).passed


def test_params_are_validated():
    from pydantic import ValidationError

    from app.grader import registry
    for bad in ({"action": "PutObject"}, {"action": "s3:putObject"}, {"action": "s3:PutObject", "source": "web"},
                {"action": "s3:PutObject", "min_count": 0}):
        with pytest.raises(ValidationError):
            registry.get("audit.called").params_model.model_validate(bad)
    for bad in ({"actions": ["s3:PutObject"]}, {"actions": ["s3:PutObject", "nope"]}):
        with pytest.raises(ValidationError):
            registry.get("audit.order").params_model.model_validate(bad)


# ------------------------------------------------------------------------------ validation + lab
def _definition(services: list[str], checks: list[dict]):
    return parse_definition({
        "schema_version": 1, "id": "audit-x", "version": "1.0.0", "title": "t", "summary": "s", "story": "s",
        "services": services, "runtime": {"emulator": "default"}, "duration_minutes": 30, "max_attempts": 1,
        "tasks": [{"id": "t1", "title": "t", "marks": 10, "checks": checks}]})


def test_validation_requires_the_audited_service_in_the_lab():
    ok = _definition(["s3"], [{"type": "audit.called", "action": "s3:PutObject"}])
    assert validate_definition(ok, set()) == [] and needs_audit(ok)
    bad = _definition(["s3"], [{"type": "audit.order", "actions": ["s3:CreateBucket", "dynamodb:CreateTable"]}])
    assert any("'dynamodb' is not listed in services" in e for e in validate_definition(bad, set()))
    vpc = _definition(["vpc"], [{"type": "audit.called", "action": "ec2:CreateVpc"}])
    assert validate_definition(vpc, set()) == []  # VPC operations are ec2:… (signing name)
    plain = _definition(["s3"], [{"type": "s3.bucket_exists", "bucket": "b"}])
    assert not needs_audit(plain) and "audit" not in collectors_for(plain)


def test_mission16_scores_order_and_source_from_the_audit_log():
    d = load_pack(LAB).definition
    assert needs_audit(d) and validate_definition(d, set()) == []
    variables = compute_variables(d, "alice1")
    assert variables["bucket"] == BUCKET
    state = {"s3": {"buckets": {BUCKET: {"versioning": "Enabled", "tags": {}, "objects_truncated": False,
                                         "objects": {"ledger.csv": {"size": 11, "etag": "e", "content_type": "text/csv"}}}}}}

    def score(*events):
        return grade(d, variables, {"collectors": {**state, **ev(*events)}})["score"]
    assert grade(d, variables, {"collectors": {}})["score"] == Decimal("0.00")
    solution = [("s3:CreateBucket", "cli", 200), ("s3:PutBucketVersioning", "cli", 200), ("s3:PutObject", "cli", 200)]
    assert score(*solution) == Decimal("100.00")
    partial = [("s3:CreateBucket", "cli", 200), ("s3:PutObject", "cli", 200), ("s3:PutBucketVersioning", "cli", 200)]
    assert score(*partial) == Decimal("70.00")
    console = [("s3:CreateBucket", "console", 200), ("s3:PutBucketVersioning", "console", 200),
               ("s3:PutObject", "console", 200)]
    assert score(*console) == Decimal("80.00")
    r = grade(d, variables, {"collectors": {**state, **ev(*partial)}})
    msg = next(c["message"] for t in r["tasks"] for c in t["checks"] if c["check"] == "audit.order")
    assert "version ID is null" in msg  # the lab's own feedback


# ------------------------------------------------------------------------------ session + console (real proxy)
async def _assignment(world) -> Assignment:
    async with sessionmaker()() as db:
        lv, _ = await import_package(db, load_pack(LAB))
        now = st.now()
        a = Assignment(course_id=world.course.id, lab_version_id=lv.id, title="Audit trail",
                       open_at=now - timedelta(hours=1), due_at=now + timedelta(days=1),
                       close_at=now + timedelta(days=2), max_attempts=3)
        db.add(a)
        await db.commit()
        return a


async def test_console_calls_go_through_the_proxy_as_console(world, fake_runner):
    if audit_proxy_path() is None:
        pytest.skip("audit proxy source not available")
    a = await _assignment(world)
    c = await login(world.alice)
    sid = (await c.post(f"/api/assignments/{a.id}/sessions")).json()["id"]
    await wait_state(c, sid, {"READY"})
    assert fake_runner.sandboxes[sid]["audit"] is True  # the lab's audit checks asked for a proxy
    async with sessionmaker()() as db:
        sess = await db.get(LabSession, sid)
        assert sess.audit_endpoint and sess.audit_endpoint != sess.emulator_endpoint

    base = f"/api/sessions/{sid}/console/s3"
    assert (await c.post(f"{base}/buckets", json={"name": BUCKET})).status_code in (200, 201)
    raw = audit_mod.fetch_log(sess.audit_endpoint)["events"]
    assert raw and {e["source"] for e in raw} == {"console"}
    # grading reads go straight to the emulator: nothing new appears in the log
    p = await c.post(f"/api/sessions/{sid}/progress")
    assert p.status_code == 200, p.text
    assert len(audit_mod.fetch_log(sess.audit_endpoint)["events"]) == len(raw)

    # a CLI upload (any client without the console marker) before versioning: the classic mistake
    s3 = boto3.client("s3", endpoint_url=sess.audit_endpoint, region_name="us-east-1",
                      aws_access_key_id="testing", aws_secret_access_key="testing",
                      config=Config(s3={"addressing_style": "path"}))
    s3.put_object(Bucket=BUCKET, Key="ledger.csv", Body=b"date,total\n")
    s3.put_bucket_versioning(Bucket=BUCKET, VersioningConfiguration={"Status": "Enabled"})
    events = audit_mod.collect_audit(sess.audit_endpoint)["events"]
    assert [(e["action"], e["source"]) for e in events if e["action"] != "s3:ListBuckets"][-2:] == \
        [("s3:PutObject", "cli"), ("s3:PutBucketVersioning", "cli")]
    r = await c.post(f"/api/sessions/{sid}/submit", headers=idem())
    assert r.status_code == 200, r.text
    assert r.json()["result"]["score"] == "70.00"


def test_console_marker_is_sent_but_never_signed():
    """The proxy strips X-CloudLabs-Source before forwarding, so a signed copy would break any engine that ever
    verifies SigV4. The marker is added after signing."""
    import uuid as _uuid

    from app.console.common import SandboxContext, console_client
    ctx = SandboxContext(id=_uuid.uuid4(), engine="moto", emulator_endpoint="http://emu.test:1",
                         touch=lambda: None, audit_endpoint="http://audit.test:7690")  # type: ignore[arg-type,return-value]
    client = console_client(ctx, "s3")
    seen = {}

    def grab(request, **_):
        seen["headers"] = {k.lower(): (v.decode() if isinstance(v, bytes) else v) for k, v in request.headers.items()}
        seen["url"] = request.url
        raise _Captured
    client.meta.events.register("before-send", grab)  # registered after the marker, so it runs after it
    with pytest.raises(_Captured):
        client.list_buckets()
    assert seen["url"].startswith("http://audit.test:7690")
    assert seen["headers"]["x-cloudlabs-source"] == "console"
    signed = seen["headers"]["authorization"].split("SignedHeaders=", 1)[1].split(",", 1)[0]
    assert "x-cloudlabs-source" not in signed.split(";")
    plain = console_client(SandboxContext(id=_uuid.uuid4(), engine="moto", emulator_endpoint="http://emu.test:1",
                                          touch=lambda: None), "s3")  # type: ignore[arg-type,return-value]
    assert plain.meta.endpoint_url == "http://emu.test:1"  # no proxy: straight to the emulator, unmarked
