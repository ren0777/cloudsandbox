"""DynamoDB: pure checks, lab pack, console API (FakeRunner = real Moto), and real-runtime contract +
labtest on every engine (marker docker)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.config import get_settings
from app.db import sessionmaker
from app.grader.grade import grade
from app.labs.importer import import_package
from app.labs.package import load_pack
from app.labs.render import compute_variables
from app.models import Assignment
from app.runtime import emulators
from app.sessions import state as st
from tests.conftest import LABS, idem, login, wait_state

DDB = Path(LABS) / "dynamodb-basics"
TABLE = "cafe-alice1-orders"


def ev(tables: dict) -> dict:
    return {"format": 1, "captured_at": "x", "collectors": {"dynamodb": {"tables": tables}}}


def table(mode="PAY_PER_REQUEST", items=None, pk=("orderId", "S"), sk=None) -> dict:
    items = items or {}
    return {"partition_key": {"name": pk[0], "type": pk[1]},
            "sort_key": {"name": sk[0], "type": sk[1]} if sk else None, "billing_mode": mode,
            "read_capacity": None, "write_capacity": None, "items": items, "item_count": len(items),
            "items_truncated": False}


def order(oid: str, drink="latte", qty=("N", "2")) -> tuple[str, dict]:
    return f"orderId={oid}", {"orderId": {"S": oid}, "drink": {"S": drink}, "quantity": {qty[0]: qty[1]}}


def _grade(evidence):
    d = load_pack(DDB).definition
    return grade(d, compute_variables(d, "alice1"), evidence)


# ------------------------------------------------------------------------------------ pure
def test_lab_loads_and_is_valid_on_every_engine():
    d = load_pack(DDB).definition
    assert d.id == "dynamodb-basics" and d.runtime.emulator == "default"
    assert emulators.candidates(d.runtime.emulator) == emulators.ENGINES


def test_scores_zero_partial_full():
    assert _grade(ev({}))["score"] == Decimal("0.00")
    full = dict([order("1001"), order("1002", "mocha", ("N", "1")), order("1003", "tea", ("N", "3"))])
    assert _grade(ev({TABLE: table(items=full)}))["score"] == Decimal("100.00")
    partial = dict([order("1001", qty=("S", "2")), order("1002"), order("1003")])
    r = _grade(ev({TABLE: table(mode="PROVISIONED", items=partial)}))
    assert r["score"] == Decimal("50.00")
    t3 = next(t for t in r["tasks"] if t["task_id"] == "first-order")
    hidden = [c for c in t3["checks"] if c["hidden"]][0]
    assert hidden["passed"] is False and hidden["actual"] == "quantity: S = 2"


def test_key_schema_and_messages():
    r = _grade(ev({TABLE: table(pk=("id", "N"))}))
    c = r["tasks"][0]["checks"][1]
    assert c["expected"] == "orderId (S)" and c["actual"] == "id (N)" and not c["passed"]
    r = _grade(ev({TABLE: table(sk=("ts", "N"))}))
    assert r["tasks"][0]["checks"][1]["passed"] is False  # no sort key allowed


def test_numbers_compare_canonically():
    items = dict([order("1001", qty=("N", "2.0")), order("1002"), order("1003")])
    r = _grade(ev({TABLE: table(items=items)}))
    assert next(t for t in r["tasks"] if t["task_id"] == "first-order")["passed"]


# ------------------------------------------------------------------------------- console API
async def ddb_assignment(world) -> Assignment:
    async with sessionmaker()() as db:
        lv, _ = await import_package(db, load_pack(DDB))
        now = st.now()
        a = Assignment(course_id=world.course.id, lab_version_id=lv.id, title="DynamoDB basics",
                       open_at=now - timedelta(hours=1), due_at=now + timedelta(days=1),
                       close_at=now + timedelta(days=2), max_attempts=3)
        db.add(a)
        await db.commit()
        return a


async def test_dynamodb_console_journey(world, fake_runner):
    a = await ddb_assignment(world)
    c = await login(world.alice)
    sid = (await c.post(f"/api/assignments/{a.id}/sessions")).json()["id"]
    await wait_state(c, sid, {"READY"})
    base = f"/api/sessions/{sid}/console/dynamodb"
    assert (await c.get(f"/api/console/services?session_id={sid}")).json()["services"]["dynamodb"] == "available"

    r = await c.post(f"{base}/tables", json={"name": "x", "partition_key": {"name": "orderId"}})
    assert r.status_code == 422  # table-name rule
    r = await c.post(f"{base}/tables", json={"name": TABLE, "partition_key": {"name": "orderId", "type": "S"},
                                             "billing_mode": "PROVISIONED", "read_capacity": 5, "write_capacity": 5,
                                             "tags": [{"key": "project", "value": "cloudcafe"}]})
    assert r.status_code == 201, r.text
    t = (await c.get(f"{base}/tables")).json()["tables"]
    assert t == [{"name": TABLE, "status": "ACTIVE", "partition_key": {"name": "orderId", "type": "S"},
                  "sort_key": None, "billing_mode": "PROVISIONED", "item_count": 0}]
    assert (await c.put(f"{base}/tables/{TABLE}/capacity", json={"billing_mode": "PAY_PER_REQUEST"})).status_code == 200
    d = (await c.get(f"{base}/tables/{TABLE}")).json()
    assert d["billing_mode"] == "PAY_PER_REQUEST" and d["tags"] == {"project": "cloudcafe"}

    bad = await c.post(f"{base}/tables/{TABLE}/items", json={"attributes": [
        {"name": "orderId", "type": "S", "value": "1"}, {"name": "quantity", "type": "N", "value": "two"}]})
    assert bad.status_code == 400
    for oid, drink, qty in (("1001", "latte", "2"), ("1002", "mocha", "1"), ("1003", "tea", "3")):
        r = await c.post(f"{base}/tables/{TABLE}/items", json={"attributes": [
            {"name": "orderId", "type": "S", "value": oid}, {"name": "drink", "type": "S", "value": drink},
            {"name": "quantity", "type": "N", "value": qty}]})
        assert r.status_code == 201, r.text
    items = (await c.get(f"{base}/tables/{TABLE}/items")).json()
    assert items["count"] == 3 and items["key_names"] == ["orderId"]
    assert items["items"][0] == [{"name": "orderId", "type": "S", "value": "1001"},
                                 {"name": "drink", "type": "S", "value": "latte"},
                                 {"name": "quantity", "type": "N", "value": "2"}]
    p = await c.post(f"/api/sessions/{sid}/progress")
    assert p.json()["score"] == "100.00", p.text

    r = await c.post(f"{base}/tables/{TABLE}/items/delete", json={"key": {"orderId": {"type": "S", "value": "1003"}}})
    assert r.status_code == 204
    assert (await c.get(f"{base}/tables/{TABLE}/items")).json()["count"] == 2

    # ownership + freeze
    bob = await login(world.bob)
    assert (await bob.get(f"{base}/tables")).status_code == 404
    r = await c.post(f"/api/sessions/{sid}/submit", headers=idem())
    assert r.status_code == 200 and r.json()["result"]["score"] == "75.00"
    r = await c.get(f"{base}/tables")
    assert r.status_code == 409


# ------------------------------------------------------------------------------ real runtime
DDB_CONTRACT = {
    "CreateTable": lambda c, t: c.create_table(TableName=t, BillingMode="PROVISIONED",
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5}),
    "ListTables": lambda c, t: t in c.list_tables()["TableNames"] or 1 / 0,
    "DescribeTable": lambda c, t: c.describe_table(TableName=t)["Table"]["KeySchema"][0]["AttributeName"] == "id" or 1 / 0,
    "UpdateTable": lambda c, t: c.update_table(TableName=t, BillingMode="PAY_PER_REQUEST"),
    "TagResource": lambda c, t: c.tag_resource(ResourceArn=c.describe_table(TableName=t)["Table"]["TableArn"],
                                               Tags=[{"Key": "k", "Value": "v"}]),
    "ListTagsOfResource": lambda c, t: c.list_tags_of_resource(
        ResourceArn=c.describe_table(TableName=t)["Table"]["TableArn"])["Tags"] == [{"Key": "k", "Value": "v"}] or 1 / 0,
    "PutItem": lambda c, t: c.put_item(TableName=t, Item={"id": {"S": "1"}, "n": {"N": "2"}}),
    "GetItem": lambda c, t: c.get_item(TableName=t, Key={"id": {"S": "1"}})["Item"]["n"] == {"N": "2"} or 1 / 0,
    "Query": lambda c, t: c.query(TableName=t, KeyConditionExpression="id = :v",
                                  ExpressionAttributeValues={":v": {"S": "1"}})["Count"] == 1 or 1 / 0,
    "Scan": lambda c, t: c.scan(TableName=t)["Count"] == 1 or 1 / 0,
    "DeleteItem": lambda c, t: c.delete_item(TableName=t, Key={"id": {"S": "1"}}),
    "DeleteTable": lambda c, t: c.delete_table(TableName=t),
}


@pytest.mark.docker
@pytest.mark.parametrize("contract_engine", emulators.ALL_ENGINES)
async def test_dynamodb_contract_for_every_declared_supported_operation(real_runner, contract_engine):
    caps = emulators.get(contract_engine).capabilities
    declared = {op for op, o in caps.services["dynamodb"].items() if o.level == "supported"}
    assert declared == set(DDB_CONTRACT), declared ^ set(DDB_CONTRACT)
    sid = str(uuid.uuid4())
    info = await real_runner.create_sandbox({"sandbox_id": sid, "env": get_settings().env, "engine": contract_engine,
                                             "terminal_credential": "contract:abcdefgh1234"})
    try:
        import asyncio
        c = emulators.get(contract_engine).client("dynamodb", info["emulator_endpoint"])
        for op in DDB_CONTRACT:
            await asyncio.to_thread(DDB_CONTRACT[op], c, "contract-table")
    finally:
        await real_runner.destroy_sandbox(sid)


@pytest.mark.docker
@pytest.mark.parametrize("lab_engine", emulators.ENGINES)
async def test_dynamodb_labtest_on_every_engine(real_runner, lab_engine):
    from app.labtest import check_pack
    results = await check_pack(DDB, real_runner, engine=lab_engine)
    assert [(r.name, str(r.actual)) for r in results] == [
        (f"{lab_engine}/empty", "0.00"), (f"{lab_engine}/partial", "50.00"), (f"{lab_engine}/solution", "100.00")], \
        [(r.name, r.actual, r.detail) for r in results]
