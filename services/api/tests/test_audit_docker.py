"""Audit proxy on the REAL runtime (marker docker): Mission 16's labtest on every primary engine, a student session
where the terminal and the console both act (terminal → cli, console → console, 100), and the gateway path of a
runner on another server (runner2, `--profile multi`)."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import boto3
import httpx
import pytest
from botocore.config import Config

from app.crypto import decrypt
from app.db import sessionmaker
from app.grader import audit as audit_mod
from app.labs.importer import import_package
from app.labs.package import load_pack
from app.models import Assignment, GradingEvidence, LabSession
from app.runtime import emulators
from app.sessions import state as st
from tests.conftest import LABS, idem, login, wait_state

pytestmark = pytest.mark.docker
LAB = Path(LABS) / "s3-versioning-order"


@pytest.mark.parametrize("lab_engine", emulators.ENGINES)
async def test_mission16_labtest_on_every_engine(real_runner, lab_engine):
    from app.labtest import check_pack
    results = await check_pack(LAB, real_runner, engine=lab_engine)
    got = {r.name.split("/")[1]: r.actual for r in results}
    assert got == {"empty": Decimal("0.00"), "partial": Decimal("70.00"), "solution": Decimal("100.00")}, \
        [(r.name, r.actual, r.detail) for r in results]


async def _terminal(endpoint: str, cred_enc: str, command: str, marker: str) -> None:
    import websockets
    auth = base64.b64encode(decrypt(cred_enc).encode()).decode()
    async with websockets.connect(endpoint, subprotocols=["tty"],
                                  additional_headers={"Authorization": f"Basic {auth}"}) as t:
        await t.send(json.dumps({"AuthToken": auth, "columns": 160, "rows": 40}))
        await t.send(b"0" + command.encode() + b"; echo DONE_$((6*7))" + marker.encode() + b"\r")
        seen = b""
        async with asyncio.timeout(90):
            while f"DONE_42{marker}".encode() not in seen:
                frame = await t.recv()
                seen += frame if isinstance(frame, bytes) else frame.encode()


async def test_terminal_is_cli_console_is_console_and_grading_is_not_logged(world, real_runner):
    async with sessionmaker()() as db:
        lv, _ = await import_package(db, load_pack(LAB))
        now = st.now()
        a = Assignment(course_id=world.course.id, lab_version_id=lv.id, title="Audit trail (docker)",
                       open_at=now - timedelta(hours=1), due_at=now + timedelta(days=1),
                       close_at=now + timedelta(days=2), max_attempts=3)
        db.add(a)
        await db.commit()
    c = await login(world.alice)
    sid = (await c.post(f"/api/assignments/{a.id}/sessions")).json()["id"]
    await wait_state(c, sid, {"READY"}, timeout=180)
    async with sessionmaker()() as db:
        sess = await db.get(LabSession, uuid.UUID(sid))
    assert sess.audit_endpoint and sess.audit_endpoint.endswith(":7690")
    bucket = f"cafe-{world.alice.short_id}-ledger"

    base = f"/api/sessions/{sid}/console/s3"
    assert (await c.post(f"{base}/buckets", json={"name": bucket})).status_code in (200, 201)
    r = await c.put(f"{base}/buckets/{bucket}/versioning", json={"status": "Enabled"})
    assert r.status_code == 200, r.text
    await _terminal(sess.terminal_endpoint, sess.ttyd_cred_enc,
                    f"echo date,total > ledger.csv && aws s3 cp ledger.csv s3://{bucket}/ledger.csv", "A")
    before = len(audit_mod.fetch_log(sess.audit_endpoint)["events"])
    assert (await c.post(f"/api/sessions/{sid}/progress")).json()["score"] == "100.00"
    assert len(audit_mod.fetch_log(sess.audit_endpoint)["events"]) == before  # grading reads bypass the proxy

    r = await c.post(f"/api/sessions/{sid}/submit", headers=idem())
    assert r.status_code == 200 and r.json()["result"]["score"] == "100.00", r.text
    async with sessionmaker()() as db:
        from sqlalchemy import select
        ev = await db.scalar(select(GradingEvidence).where(
            GradingEvidence.attempt_id == uuid.UUID(r.json()["attempt"]["id"]), GradingEvidence.kind == "final"))
    events = ev.payload["collectors"]["audit"]["events"]
    pairs = [(e["action"], e["source"]) for e in events]
    assert ("s3:CreateBucket", "console") in pairs and ("s3:PutBucketVersioning", "console") in pairs
    assert ("s3:PutObject", "cli") in pairs and ("s3:PutObject", "console") not in pairs


R2_URL = os.environ.get("CL_RUNNER2_URL", "http://runner2:7070")
R2_ID = os.environ.get("CL_RUNNER2_ID", "runner-local-2")
R2_SECRET = os.environ.get("CL_RUNNER2_SECRET", "cloudlabs-dev-runner2-hmac-secret-0123456789abcdef")


async def test_gateway_runner_serves_the_proxy_and_its_log():
    from app.config import get_settings
    from app.runtime.runner_client import HttpRunnerClient
    try:
        async with httpx.AsyncClient(timeout=3) as h:
            await h.get(f"{R2_URL}/v1/capacity")
    except httpx.HTTPError:
        pytest.skip("runner2 is not running (docker compose --profile multi up -d runner2)")
    s = get_settings()
    r2 = HttpRunnerClient(R2_ID, R2_URL, R2_SECRET, 120)
    sid = str(uuid.uuid4())
    try:
        info = await r2.create_sandbox({"sandbox_id": sid, "env": s.env, "engine": "moto", "audit": True,
                                        "terminal_credential": "student:secretpass1"})
        assert info["audit_endpoint"].endswith("/audit") and "/gw/" in info["audit_endpoint"]
        sess = type("S", (), {"audit_endpoint": info["audit_endpoint"], "emulator_endpoint": info["emulator_endpoint"],
                              "engine": "moto", "id": uuid.UUID(sid)})
        from app.console.common import console_client

        def act() -> None:
            console_client(sess, "s3").create_bucket(Bucket="gw-console")  # type: ignore[arg-type]
            boto3.client("s3", endpoint_url=info["audit_endpoint"], region_name="us-east-1",
                         aws_access_key_id="t", aws_secret_access_key="t",
                         config=Config(s3={"addressing_style": "path"})).create_bucket(Bucket="gw-direct")
            boto3.client("s3", endpoint_url=info["emulator_endpoint"], region_name="us-east-1",
                         aws_access_key_id="t", aws_secret_access_key="t",
                         config=Config(s3={"addressing_style": "path"})).create_bucket(Bucket="gw-grader")
        await asyncio.to_thread(act)
        log = await asyncio.to_thread(audit_mod.collect_audit, info["audit_endpoint"])
        assert [(e["action"], e["source"]) for e in log["events"]] == [
            ("s3:CreateBucket", "console"), ("s3:CreateBucket", "cli")]  # the emulator endpoint is not audited
        wrong = info["audit_endpoint"].replace(info["audit_endpoint"].split("/")[-2], "not-the-token")
        async with httpx.AsyncClient() as h:
            assert (await h.get(f"{wrong}{audit_mod.LOG_PATH}")).status_code == 404
    finally:
        await r2.destroy_sandbox(sid)
        await r2.aclose()
