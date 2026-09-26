"""Lambda: pure checks/lab grading (probe evidence), console API (FakeRunner = real Moto, which manages
functions but can't execute them), and real-runtime contract + labtest (marker docker). Invocation needs
the MiniStack engine, which the lambda-basics lab pins."""

from __future__ import annotations

import asyncio
import io
import json
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
from app.grader.checks.lambda_ import probe_key
from app.grader.grade import grade, probes_for
from app.labs.importer import import_package
from app.labs.package import load_pack
from app.labs.render import compute_variables
from app.models import Assignment
from app.runtime import emulators
from app.sessions import state as st
from tests.conftest import LABS, idem, login, wait_state

LAB = Path(LABS) / "lambda-basics"
FN = "cafe-alice1-orders"
ORDER = {"items": [{"price": 3, "qty": 2}, {"price": 4.5, "qty": 1}]}
EMPTY = {"items": []}


def fn(runtime="python3.12", env=None, timeout=3, memory=128):
    return {"runtime": runtime, "handler": "lambda_function.lambda_handler", "role_name": "r",
            "memory": memory, "timeout": timeout, "env": env or {}}


def ev(functions=None, invocations=None):
    return {"format": 1, "captured_at": "x", "collectors": {"lambda": {
        "functions": functions or {}, "invocations": invocations or {}}}}


def ok(payload):
    return {"status": 200, "error": None, "payload": payload}


def _def():
    d = load_pack(LAB).definition
    return d, compute_variables(d, "alice1")


def _grade(evidence):
    d, v = _def()
    return grade(d, v, evidence)


def test_lab_is_pinned_to_the_code_running_engine_and_declares_probes():
    d, v = _def()
    assert d.runtime.emulator == "ministack"
    assert probes_for(d, v) == [{"kind": "lambda_invoke", "function": FN, "payload": ORDER},
                                {"kind": "lambda_invoke", "function": FN, "payload": EMPTY}]


def test_lab_scores():
    assert _grade(ev())["score"] == Decimal("0.00")
    good = fn(env={"TAX_RATE": "0.08"}, timeout=10, memory=256)
    inv = {probe_key(FN, ORDER): ok({"total": 11.340000000000002}), probe_key(FN, EMPTY): ok({"total": 0})}
    assert _grade(ev({FN: good}, inv))["score"] == Decimal("100.00")
    # configured but still the template code (returns statusCode/body) and default memory
    hello = ok({"statusCode": 200, "body": "\"Hello from Lambda!\""})
    partial = ev({FN: fn(env={"TAX_RATE": "0.08"}, timeout=10)}, {probe_key(FN, ORDER): hello, probe_key(FN, EMPTY): hello})
    assert _grade(partial)["score"] == Decimal("45.00")


def test_hidden_empty_order_and_error_messages():
    good = fn(env={"TAX_RATE": "0.08"}, timeout=10, memory=256)
    crash = {"status": 200, "error": "Unhandled", "payload": {"errorMessage": "division by zero"}}
    r = _grade(ev({FN: good}, {probe_key(FN, ORDER): ok({"total": 11.34}), probe_key(FN, EMPTY): crash}))
    t = next(t for t in r["tasks"] if t["task_id"] == "compute-total")
    assert not t["passed"] and [c["passed"] for c in t["checks"]] == [True, False]
    assert "raised an error" in t["checks"][1]["message"]
    r = _grade(ev({FN: fn(runtime="nodejs20.x", timeout=1)}, {}))
    msgs = {t["task_id"]: t["checks"][0]["message"] for t in r["tasks"]}
    assert "runtime is nodejs20.x" in msgs["create-function"]
    assert "TAX_RATE should be 0.08" in msgs["configure"] and "timeout is 1 s" in msgs["configure"]
    assert "could not be invoked" in msgs["compute-total"]


# ------------------------------------------------------------------------------- console API
async def lambda_assignment(world, tmp_path) -> Assignment:
    """The real lab pins MiniStack; the FakeRunner is Moto, so the console test uses a copy of the pack on
    the default engine without the invoke task (management operations only)."""
    pack = tmp_path / "lambda-console"
    shutil.copytree(LAB, pack)
    data = yaml.safe_load((pack / "lab.yaml").read_text(encoding="utf-8"))
    data.update(id="lambda-console", runtime={"emulator": "default"})
    data["requires"] = [r for r in data["requires"] if r != "lambda:Invoke"]
    data["tasks"] = [t for t in data["tasks"] if t["id"] != "compute-total"]
    (pack / "lab.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    async with sessionmaker()() as db:
        lv, _ = await import_package(db, load_pack(pack))
        now = st.now()
        a = Assignment(course_id=world.course.id, lab_version_id=lv.id, title="Lambda", open_at=now - timedelta(hours=1),
                       due_at=now + timedelta(days=1), close_at=now + timedelta(days=2), max_attempts=3)
        db.add(a)
        await db.commit()
        return a


async def test_lambda_console_create_configure_and_invoke_capability(world, fake_runner, tmp_path):
    a = await lambda_assignment(world, tmp_path)
    c = await login(world.alice)
    sid = (await c.post(f"/api/assignments/{a.id}/sessions")).json()["id"]
    await wait_state(c, sid, {"READY"})
    base = f"/api/sessions/{sid}/console/lambda"

    assert (await c.get(f"{base}/functions")).json() == {"functions": []}
    r = await c.post(f"{base}/functions", json={"name": FN, "runtime": "python3.12"})
    assert r.status_code == 201, r.text
    assert f"{FN}-role-" in r.json()["role"]
    roles = (await c.get(f"{base}/execution-roles")).json()["roles"]
    assert [x["arn"] for x in roles] == [r.json()["role"]]
    assert (await c.post(f"{base}/functions", json={"name": "x", "architecture": "arm64"})).status_code == 409
    assert (await c.post(f"{base}/functions", json={"name": "bad name!"})).status_code == 422

    f = (await c.get(f"{base}/functions/{FN}")).json()
    assert f["runtime"] == "python3.12" and f["handler"] == "lambda_function.lambda_handler" and "code_available" in f
    code = {"lambda_function.py": "def lambda_handler(event, context):\n    return {'total': 0}\n"}
    assert (await c.put(f"{base}/functions/{FN}/code", json={"files": code})).status_code == 200
    assert (await c.put(f"{base}/functions/{FN}/code", json={"files": {"../x.py": "x"}})).status_code == 400
    r = await c.put(f"{base}/functions/{FN}/configuration",
                    json={"memory": 256, "timeout": 10, "env": {"TAX_RATE": "0.08"}})
    assert r.status_code == 200, r.text
    f = (await c.get(f"{base}/functions/{FN}")).json()
    assert (f["memory"], f["timeout"], f["env"]) == (256, 10, {"TAX_RATE": "0.08"})

    # the Test button needs an engine that executes code: capability filtering answers before the emulator
    r = await c.post(f"{base}/functions/{FN}/invoke", json={"event": ORDER})
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_in_simulator", r.text

    prog = await c.post(f"/api/sessions/{sid}/progress")
    assert (prog.json()["score"], prog.json()["max_score"]) == ("60.00", "60.00"), prog.text
    bob = await login(world.bob)
    assert (await bob.get(f"{base}/functions")).status_code == 404
    assert (await c.delete(f"{base}/functions/{FN}")).status_code == 204
    r = await c.post(f"/api/sessions/{sid}/submit", headers=idem())
    assert r.status_code == 200 and r.json()["result"]["score"] == "0.00", r.text
    assert (await c.get(f"{base}/functions")).status_code == 409


# ------------------------------------------------------------------------------ real runtime
TRUST = json.dumps({"Version": "2012-10-17", "Statement": [
    {"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]})
CODE = "import os\n\ndef lambda_handler(event, context):\n    return {'rate': os.environ.get('RATE'), 'echo': event}\n"


def _zip(src: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("lambda_function.py", src)
    return buf.getvalue()


def lambda_contract(c, iam) -> dict:
    s: dict = {}
    return {
        "CreateFunction": lambda: s.__setitem__("fn", c.create_function(
            FunctionName="f", Runtime="python3.12", Handler="lambda_function.lambda_handler", Timeout=10,
            Role=iam.create_role(RoleName="f-role", AssumeRolePolicyDocument=TRUST)["Role"]["Arn"],
            Code={"ZipFile": _zip(CODE)})["FunctionName"]),
        "GetFunction": lambda: c.get_function(FunctionName="f")["Configuration"]["Runtime"] == "python3.12" or 1 / 0,
        "ListFunctions": lambda: [f["FunctionName"] for f in c.list_functions()["Functions"]] == ["f"] or 1 / 0,
        "UpdateFunctionConfiguration": lambda: c.update_function_configuration(
            FunctionName="f", MemorySize=256, Environment={"Variables": {"RATE": "0.5"}}),
        "GetFunctionConfiguration": lambda: c.get_function_configuration(FunctionName="f")["MemorySize"] == 256 or 1 / 0,
        "UpdateFunctionCode": lambda: c.update_function_code(FunctionName="f", ZipFile=_zip(CODE)),
        "Invoke": lambda: json.loads(c.invoke(FunctionName="f", Payload=b'{"a": 1}')["Payload"].read()) ==
        {"rate": "0.5", "echo": {"a": 1}} or 1 / 0,
        "DeleteFunction": lambda: c.delete_function(FunctionName="f"),
    }


@pytest.mark.docker
@pytest.mark.parametrize("contract_engine", emulators.ALL_ENGINES)
async def test_lambda_contract_for_every_declared_supported_operation(real_runner, contract_engine):
    caps = emulators.get(contract_engine).capabilities
    declared = {op for op, o in caps.services["lambda"].items() if o.level == "supported"}
    sid = str(uuid.uuid4())
    info = await real_runner.create_sandbox({"sandbox_id": sid, "env": get_settings().env, "engine": contract_engine,
                                             "terminal_credential": "contract:abcdefgh1234"})
    try:
        adapter = emulators.get(contract_engine)
        ops = lambda_contract(adapter.client("lambda", info["emulator_endpoint"]),
                              adapter.client("iam", info["emulator_endpoint"]))
        assert declared <= set(ops), declared - set(ops)
        for name, op in ops.items():
            if name not in declared:
                continue
            try:
                await asyncio.to_thread(op)
            except Exception as e:  # pragma: no cover - diagnostic
                raise AssertionError(f"{contract_engine}: {name} failed: {e}") from e
    finally:
        await real_runner.destroy_sandbox(sid)


@pytest.mark.docker
async def test_lambda_labtest_on_ministack(real_runner):
    from app.labtest import check_pack
    results = await check_pack(LAB, real_runner)
    assert [(r.name, str(r.actual)) for r in results] == [
        ("ministack/empty", "0.00"), ("ministack/partial", "45.00"), ("ministack/solution", "100.00")], \
        [(r.name, r.actual, r.detail) for r in results]
