"""Lambda + SQS + DynamoDB (Mission 14): the trigger check, the end-to-end delivery probe, the lab's scoring,
the architecture edge and the console's Triggers API (FakeRunner = real Moto, with the trigger operations
switched on for the test because only MiniStack declares them). Real-runtime contract + labtest are
marker docker."""

from __future__ import annotations

import asyncio
import io
import shutil
import uuid
import zipfile
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from app.config import get_settings
from app.db import sessionmaker
from app.diagram import build_graph
from app.grader.checks.lambda_ import probe_key
from app.grader.evidence import delivery_key
from app.grader.grade import grade, probes_for
from app.labs.importer import import_package
from app.labs.package import load_pack
from app.labs.render import compute_variables
from app.models import Assignment
from app.runtime import capabilities as caps_mod, emulators
from app.sessions import state as st
from tests.conftest import LABS, idem, login, wait_state

LAB = Path(LABS) / "lambda-sqs-dynamodb"
TABLE, QUEUE, FN = "cafe-alice1-orders", "cafe-alice1-incoming", "cafe-alice1-worker"
ESM_OPS = ("CreateEventSourceMapping", "ListEventSourceMappings", "GetEventSourceMapping",
           "UpdateEventSourceMapping", "DeleteEventSourceMapping")


def _def():
    d = load_pack(LAB).definition
    return d, compute_variables(d, "alice1")


def _probes() -> tuple[dict, dict]:
    d, v = _def()
    ps = probes_for(d, v)
    return next(p for p in ps if p["kind"] == "lambda_invoke"), next(p for p in ps if p["kind"] == "sqs_deliver")


def trigger(**kw) -> dict:
    return {"function": FN, "service": "sqs", "source": QUEUE, "batch_size": 5, "enabled": True,
            "report_batch_item_failures": True} | kw


def evidence(*, trig: list | None = None, batch_reply=None, delivered: dict | None = None,
             saved_3001: bool = True, visibility="60") -> dict:
    inv, dlv = _probes()
    reply = {"batchItemFailures": [{"itemIdentifier": "msg-2"}]} if batch_reply is None else batch_reply
    items = {"orderId=3001": {"orderId": {"S": "3001"}, "total": {"N": "10.8"}}} if saved_3001 else {}
    return {"format": 1, "captured_at": "x", "collectors": {
        "lambda": {"functions": {FN: {"runtime": "python3.12", "handler": "lambda_function.lambda_handler",
                                      "role_name": "r", "memory": 256, "timeout": 10, "env": {"TABLE_NAME": TABLE}}},
                   "invocations": {probe_key(FN, inv["payload"]): {"status": 200, "error": None, "payload": reply}},
                   "event_sources": [trigger()] if trig is None else trig},
        "sqs": {"queues": {QUEUE: {"name": QUEUE, "fifo": False, "visibility_timeout": visibility,
                                   "retention_period": "345600", "delay_seconds": "0", "messages": 0,
                                   "in_flight": 0, "tags": {}}},
                "peeks": {},
                "deliveries": {delivery_key(dlv): {"queue": QUEUE, "table": TABLE, "sent": True,
                                                   "item": {"orderId": {"S": "9001"}, "total": {"N": "16.2"}}
                                                   if delivered is None else delivered["item"]}
                               | ({"error": delivered["error"]} if delivered and "error" in delivered else {})}},
        "dynamodb": {"tables": {TABLE: {"partition_key": {"name": "orderId", "type": "S"}, "sort_key": None,
                                        "billing_mode": "PAY_PER_REQUEST", "read_capacity": None,
                                        "write_capacity": None, "items": items, "item_count": len(items),
                                        "items_truncated": False}}},
    }}


def _grade(ev: dict) -> dict:
    d, v = _def()
    return grade(d, v, ev)


def _checks(r: dict) -> dict:
    return {c["check"]: c for t in r["tasks"] for c in t["checks"]}


# ------------------------------------------------------------------------------------ pure
def test_lab_pins_ministack_and_declares_both_probes():
    d, v = _def()
    assert d.runtime.emulator == "ministack" and d.services == ["dynamodb", "sqs", "lambda"]
    inv, dlv = _probes()
    assert [r["messageId"] for r in inv["payload"]["Records"]] == ["msg-1", "msg-2"]
    assert dlv == {"kind": "sqs_deliver", "queue": QUEUE, "table": TABLE, "key": {"orderId": "9001"}, "wait": 20,
                   "body": {"orderId": "9001", "items": [{"price": 5, "qty": 3}]}}
    # the trigger operations are only declared usable where function code runs
    for engine in emulators.ALL_ENGINES:
        usable = emulators.get(engine).capabilities.is_usable("lambda:CreateEventSourceMapping")
        assert usable == (engine == "ministack"), engine


def test_scores_empty_partial_full():
    assert _grade({"collectors": {}})["score"] == Decimal("0.00")
    assert _grade(evidence())["score"] == Decimal("100.00")
    # everything but the trigger: nothing drains the queue into the table (the labtest partial)
    partial = evidence(trig=[], delivered={"item": None})
    assert _grade(partial)["score"] == Decimal("70.00")


def test_trigger_check_explains_each_problem():
    msg = lambda trig: _checks(_grade(evidence(trig=trig)))["lambda.event_source"]["message"]  # noqa: E731
    assert msg([]) == f"Function {FN} has no trigger from queue {QUEUE}"
    assert "it is triggered by other-q" in msg([trigger(source="other-q")])
    assert "the trigger is disabled" in msg([trigger(enabled=False)])
    assert "batch size is 10, not 5" in msg([trigger(batch_size=10)])
    assert "report batch item failures should be on" in msg([trigger(report_batch_item_failures=False)])
    assert msg([trigger()]) == f"Queue {QUEUE} triggers {FN}"


def test_batch_must_report_only_the_bad_message():
    # failing the whole batch (every record listed) is exactly what partial batch responses avoid
    both = {"batchItemFailures": [{"itemIdentifier": "msg-1"}, {"itemIdentifier": "msg-2"}]}
    r = _grade(evidence(batch_reply=both, saved_3001=False))
    t = next(t for t in r["tasks"] if t["task_id"] == "process-batch")
    assert not t["passed"] and t["marks_awarded"] == Decimal("0.00")
    assert _grade(evidence(batch_reply={"batchItemFailures": []}))["score"] == Decimal("75.00")


def test_delivery_check_messages():
    c = lambda **kw: _checks(_grade(evidence(**kw)))["sqs.delivers_item"]  # noqa: E731
    assert c()["passed"] and "was processed and saved" in c()["message"]
    assert "never reached" in c(delivered={"item": None})["message"]
    wrong = {"item": {"orderId": {"S": "9001"}, "total": {"N": "15"}}}
    assert "saved with the wrong total" in c(delivered=wrong)["message"]
    gone = {"item": None, "error": "queue: AWS.SimpleQueueService.NonExistentQueue"}
    assert c(delivered=gone)["message"] == f"Could not use {QUEUE} for the test message (AWS.SimpleQueueService.NonExistentQueue)"
    assert "Could not use " + TABLE in c(delivered={"item": None, "error": "table: ResourceNotFoundException"})["message"]


def test_diagram_draws_the_trigger():
    g = build_graph(evidence()["collectors"])
    assert {"source": f"sqs:{QUEUE}", "target": f"lambda:{FN}", "kind": "triggers"} in g["edges"]
    off = build_graph(evidence(trig=[trigger(enabled=False)])["collectors"])
    assert {"source": f"sqs:{QUEUE}", "target": f"lambda:{FN}", "kind": "triggers (disabled)"} in off["edges"]


def test_template_is_offered():
    from app.instructor.templates import TEMPLATES
    t = next(t for t in TEMPLATES if t.id == "lambda-sqs-dynamodb")
    assert t.source_lab_id == "lambda-sqs-dynamodb" and set(t.services) == {"lambda", "sqs", "dynamodb"}


# ------------------------------------------------------------------------------- console API
@pytest.fixture
def moto_triggers(monkeypatch):
    """Moto manages SQS event source mappings (it never runs them); declare them usable for the console
    test only, so the API logic is exercised without a code-running engine."""
    for engine in emulators.ENGINES:  # the FakeRunner is Moto under whichever default engine is configured
        lam = caps_mod.load(engine).services["lambda"]
        for op in ESM_OPS:
            monkeypatch.setitem(lam, op, caps_mod.OpSupport(level="supported"))


async def console_assignment(world, tmp_path) -> Assignment:
    pack = tmp_path / "lambda-sqs-console"
    shutil.copytree(LAB, pack)
    data = yaml.safe_load((pack / "lab.yaml").read_text(encoding="utf-8"))
    data.update(id="lambda-sqs-console", runtime={"emulator": "default"}, requires=[])
    data["tasks"] = [t for t in data["tasks"] if t["id"] in ("create-table", "create-queue", "create-function")]
    (pack / "lab.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    async with sessionmaker()() as db:
        lv, _ = await import_package(db, load_pack(pack))
        now = st.now()
        a = Assignment(course_id=world.course.id, lab_version_id=lv.id, title="Pipeline", open_at=now - timedelta(hours=1),
                       due_at=now + timedelta(days=1), close_at=now + timedelta(days=2), max_attempts=3)
        db.add(a)
        await db.commit()
        return a


async def _session(world, tmp_path):
    a = await console_assignment(world, tmp_path)
    c = await login(world.alice)
    sid = (await c.post(f"/api/assignments/{a.id}/sessions")).json()["id"]
    await wait_state(c, sid, {"READY"})
    base = f"/api/sessions/{sid}/console"
    assert (await c.post(f"{base}/sqs/queues", json={"name": QUEUE})).status_code == 201
    assert (await c.post(f"{base}/lambda/functions", json={"name": FN})).status_code == 201
    return c, sid, f"{base}/lambda/functions/{FN}/triggers"


async def test_console_triggers_need_a_code_running_engine(world, fake_runner, tmp_path):
    c, _, url = await _session(world, tmp_path)
    for r in (await c.get(url), await c.post(url, json={"queue": QUEUE})):
        assert r.status_code == 409 and r.json()["error"]["code"] == "not_in_simulator", r.text
        assert "MiniStack" in r.json()["error"]["message"]


async def test_console_add_update_and_delete_a_trigger(world, fake_runner, tmp_path, moto_triggers):
    c, sid, url = await _session(world, tmp_path)
    assert (await c.get(url)).json() == {"triggers": []}
    r = await c.post(url, json={"queue": QUEUE, "batch_size": 5, "report_batch_item_failures": True})
    assert r.status_code == 201, r.text
    t = r.json()
    assert (t["service"], t["source"], t["batch_size"], t["report_batch_item_failures"]) == ("sqs", QUEUE, 5, True)
    assert (await c.post(url, json={"queue": "no-such-queue"})).status_code == 400
    assert (await c.post(url, json={"queue": QUEUE, "batch_size": 11})).status_code == 422

    r = await c.patch(f"{url}/{t['uuid']}", json={"batch_size": 3, "report_batch_item_failures": False})
    assert r.status_code == 200, r.text
    listed = (await c.get(url)).json()["triggers"]
    assert [(x["uuid"], x["batch_size"], x["report_batch_item_failures"]) for x in listed] == [(t["uuid"], 3, False)]

    # a trigger is addressed through its own function only
    other = f"/api/sessions/{sid}/console/lambda/functions"
    assert (await c.post(other, json={"name": "someone-else"})).status_code == 201
    assert (await c.delete(f"{other}/someone-else/triggers/{t['uuid']}")).status_code == 404
    bob = await login(world.bob)
    assert (await bob.get(url)).status_code == 404

    assert (await c.delete(f"{url}/{t['uuid']}")).status_code == 204
    assert (await c.get(url)).json() == {"triggers": []}
    r = await c.post(f"/api/sessions/{sid}/submit", headers=idem())
    assert r.status_code == 200, r.text


# ------------------------------------------------------------------------------ real runtime
CODE = ("import json, os, boto3\nDB = boto3.client('dynamodb')\n\n"
        "def lambda_handler(event, context):\n"
        "    for r in event['Records']:\n"
        "        o = json.loads(r['body'])\n"
        "        DB.put_item(TableName=os.environ['T'], Item={'orderId': {'S': o['orderId']}})\n"
        "    return {'batchItemFailures': []}\n")


def _zip(src: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("lambda_function.py", src)
    return buf.getvalue()


@pytest.mark.docker
async def test_trigger_contract_and_delivery_probe_on_ministack(real_runner):
    """MiniStack runs the trigger: every declared mapping operation works, and the `sqs_deliver` probe sees
    the item a triggered function writes (and nothing once the trigger is disabled)."""
    from app.grader.evidence import _deliver, collect_lambda
    sid = str(uuid.uuid4())
    info = await real_runner.create_sandbox({"sandbox_id": sid, "env": get_settings().env, "engine": "ministack",
                                             "terminal_credential": "contract:abcdefgh1234"})
    adapter = emulators.get("ministack")
    endpoint = info["emulator_endpoint"]
    lam, sqs, ddb = (adapter.client(s, endpoint) for s in ("lambda", "sqs", "dynamodb"))
    probe = {"kind": "sqs_deliver", "queue": "q", "table": "orders", "key": {"orderId": "p1"}, "wait": 20,
             "body": {"orderId": "p1"}}

    def run() -> None:
        ddb.create_table(TableName="orders", BillingMode="PAY_PER_REQUEST",
                         AttributeDefinitions=[{"AttributeName": "orderId", "AttributeType": "S"}],
                         KeySchema=[{"AttributeName": "orderId", "KeyType": "HASH"}])
        url = sqs.create_queue(QueueName="q", Attributes={"VisibilityTimeout": "60"})["QueueUrl"]
        arn = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
        lam.create_function(FunctionName="f", Runtime="python3.12", Handler="lambda_function.lambda_handler",
                            Role="arn:aws:iam::000000000000:role/r", Code={"ZipFile": _zip(CODE)}, Timeout=10,
                            Environment={"Variables": {"T": "orders"}})
        m = lam.create_event_source_mapping(FunctionName="f", EventSourceArn=arn, BatchSize=5,
                                            FunctionResponseTypes=["ReportBatchItemFailures"])
        assert [x["UUID"] for x in lam.list_event_source_mappings(FunctionName="f")["EventSourceMappings"]] == [m["UUID"]]
        assert lam.get_event_source_mapping(UUID=m["UUID"])["BatchSize"] == 5
        assert collect_lambda(adapter, endpoint)["event_sources"] == [
            {"function": "f", "service": "sqs", "source": "q", "batch_size": 5, "enabled": True,
             "report_batch_item_failures": True}]
        got = _deliver(adapter, endpoint, sqs, probe)
        assert got["sent"] and got["item"] == {"orderId": {"S": "p1"}}, got
        lam.update_event_source_mapping(UUID=m["UUID"], Enabled=False)
        assert collect_lambda(adapter, endpoint)["event_sources"][0]["enabled"] is False
        assert _deliver(adapter, endpoint, sqs, probe | {"wait": 8})["item"] is None  # removed, never rewritten
        lam.delete_event_source_mapping(UUID=m["UUID"])
        assert lam.list_event_source_mappings(FunctionName="f")["EventSourceMappings"] == []
    try:
        await asyncio.to_thread(run)
    finally:
        await real_runner.destroy_sandbox(sid)


@pytest.mark.docker
async def test_lambda_sqs_dynamodb_labtest_on_ministack(real_runner):
    from app.labtest import check_pack
    results = await check_pack(LAB, real_runner)
    assert [(r.name, str(r.actual)) for r in results] == [
        ("ministack/empty", "0.00"), ("ministack/partial", "70.00"), ("ministack/solution", "100.00")], \
        [(r.name, r.actual, r.detail) for r in results]


def test_moto_declares_triggers_unusable_with_a_reason():
    lam = caps_mod.load("moto").services["lambda"]
    assert all(lam[op].level == "unsupported" and "MiniStack" in (lam[op].note or "") for op in ESM_OPS)
