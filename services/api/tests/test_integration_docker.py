"""Integration against the REAL runner + Docker (marker: docker). Runs inside the api-test container,
which the runner attaches to test sandboxes (decision D1).

Covers PLAN "Slice 1 is done when" items 2–3 and the terminal/ticket rules (§11), private bundles (§7b),
Moto contract tests (§8) and cleanup verification."""

from __future__ import annotations

import asyncio
import io
import json
import socket
import time
import uuid
from datetime import timedelta

import boto3
import httpx
import pytest
import uvicorn
import websockets
from botocore.config import Config
from sqlalchemy import update

from app.auth.security import CSRF_COOKIE, CSRF_HEADER
from app.config import get_settings
from app.db import sessionmaker
from app.labtest import check_pack
from app.main import app
from app.models import TerminalTicket
from app.runtime import emulators
from app.sessions import state as st
from app.tasks import background
from tests.conftest import LABS, PASSWORD, idem

pytestmark = pytest.mark.docker
ENGINES = list(emulators.ENGINES)  # every engine must pass the same real-runtime suite (promotion gate)


@pytest.fixture(params=ENGINES)
def engine(request, monkeypatch):
    """Run the test with this engine as the platform default (labs use runtime.emulator: default)."""
    monkeypatch.setattr(get_settings(), "default_emulator", request.param)
    return request.param
ORIGIN = get_settings().allowed_origins[0]  # an allowed browser origin for this deployment
BUCKET = "cafe-alice1-site"


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def live(real_runner):
    port = _port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="off",
                                           log_level="warning", ws="websockets"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    yield f"127.0.0.1:{port}"
    server.should_exit = True
    await task


class Live(httpx.AsyncClient):
    async def request(self, method, url, **kw):  # type: ignore[override]
        csrf = self.cookies.get(CSRF_COOKIE)
        if csrf and method.upper() not in ("GET", "HEAD"):
            kw["headers"] = {**(kw.get("headers") or {}), CSRF_HEADER: csrf}
        return await super().request(method, url, **kw)


async def live_login(host: str, email: str) -> Live:
    c = Live(base_url=f"http://{host}", timeout=180)
    r = await c.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return c


async def wait_ready(c: httpx.AsyncClient, sid: str, states=("READY",), timeout=120) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        s = (await c.get(f"/api/sessions/{sid}")).json()
        if s["state"] in states:
            return s
        if s["state"] == "FAILED":
            raise AssertionError(f"session failed: {s['failure_reason']}")
        await asyncio.sleep(0.5)
    raise AssertionError(f"timeout waiting for {states}")


class Term:
    """Minimal browser-protocol terminal client."""

    def __init__(self, ws):
        self.ws, self.buf = ws, ""

    @classmethod
    async def open(cls, host: str, c: httpx.AsyncClient, sid: str, origin: str = ORIGIN) -> "Term":
        t = (await c.post(f"/api/sessions/{sid}/terminal-ticket")).json()["ticket"]
        ws = await websockets.connect(f"ws://{host}/ws/terminal?ticket={t}", origin=origin)  # type: ignore[arg-type]
        return cls(ws)

    async def run(self, cmd: str, timeout: float = 60) -> str:
        marker = f"__done_{uuid.uuid4().hex[:8]}__"
        start = len(self.buf)
        await self.ws.send(json.dumps({"t": "i", "d": f"{cmd}; echo {marker[:-2]}$((1+1))__\r"}))
        want = marker[:-2] + "2__"
        deadline = time.monotonic() + timeout
        while want not in self.buf[start:]:
            left = deadline - time.monotonic()
            if left <= 0:
                raise AssertionError(f"timeout running {cmd!r}; output so far:\n{self.buf[start:][-2000:]}")
            frame = await asyncio.wait_for(self.ws.recv(), left)
            self.buf += frame.decode("utf-8", "replace") if isinstance(frame, bytes) else frame
        return self.buf[start:]


# ------------------------------------------------------------------------------------ labtest
async def test_labtest_scores_on_real_runtime(real_runner, engine):
    results = await check_pack(f"{LABS}/s3-basics", real_runner, engine=engine)
    assert [(r.name, str(r.actual), r.ok) for r in results] == [
        (f"{engine}/empty", "0.00", True), (f"{engine}/partial", "50.00", True),
        (f"{engine}/solution", "100.00", True)]
    assert await real_runner.list_sandboxes(env=get_settings().env) == []


# --------------------------------------------------------------------------- full journey
async def test_student_journey_gui_and_cli(engine, world, live, real_runner):
    alice = await live_login(live, world.alice.email)
    r = await alice.post(f"/api/assignments/{world.assignment.id}/sessions")
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    await wait_ready(alice, sid)
    base = f"/api/sessions/{sid}/console/s3"
    async with sessionmaker()() as db:
        from app.models import LabSession
        assert (await db.get(LabSession, uuid.UUID(sid))).engine == engine
    assert (await real_runner.sandbox_status(sid))["exists"]

    # 1) GUI creates the bucket → CLI sees it
    assert (await alice.post(f"{base}/buckets", json={"name": BUCKET})).status_code == 201
    term = await Term.open(live, alice, sid)
    out = await term.run("aws s3 ls")
    assert BUCKET in out

    # 2) CLI enables versioning and uploads → GUI sees it
    await term.run(f"aws s3api put-bucket-versioning --bucket {BUCKET} "
                   f"--versioning-configuration Status=Enabled")
    await term.run(f"echo '<h1>CloudCafe</h1>' > index.html && aws s3 cp index.html s3://{BUCKET}/")
    d = (await alice.get(f"{base}/buckets/{BUCKET}")).json()
    assert d["versioning"] == "Enabled"
    objs = (await alice.get(f"{base}/buckets/{BUCKET}/objects")).json()["objects"]
    assert [o["key"] for o in objs] == ["index.html"]

    # 3) progress sees GUI + CLI work (75: tag still missing)
    p = await alice.post(f"/api/sessions/{sid}/progress")
    assert p.json()["score"] == "75.00", p.text

    # 4) the terminal holds no lab-private material and has no internet
    out = await term.run("echo PRIV=$(find / -xdev \\( -name solution.sh -o -name partial.sh -o -name "
                         "expected.yaml -o -name notes.md \\) 2>/dev/null | wc -l) WORK=$(ls -A /work | wc -l)")
    assert "PRIV=0 WORK=0" in out, out
    out = await term.run("python3 -c \"import socket;socket.create_connection(('1.1.1.1',80),3)\" "
                         "&& echo NET_OK || echo NET_BLOCKED")
    assert "NET_BLOCKED" in out and "NET_OK\r" not in out

    # 5) finish in GUI, submit → terminal is closed with reason 'submitted'
    await alice.put(f"{base}/buckets/{BUCKET}/tags", json={"tags": {"project": "cloudcafe"}})
    r = await alice.post(f"/api/sessions/{sid}/submit", headers=idem())
    assert r.status_code == 200 and r.json()["result"]["score"] == "100.00", r.text
    with pytest.raises(websockets.ConnectionClosed) as closed:
        for _ in range(100):
            await asyncio.wait_for(term.ws.recv(), 10)
    assert closed.value.rcvd is not None and closed.value.rcvd.reason == "submitted"
    # session freeze: after submit the console is read-only and no new terminal can be opened
    r = await alice.post(f"{base}/buckets", json={"name": "late-bucket-after-submit"})
    assert r.status_code == 409 and r.json()["error"]["code"] in ("session_frozen", "invalid_state")
    assert (await alice.post(f"/api/sessions/{sid}/terminal-ticket")).status_code == 409

    # 6) instructor sees the stored result with per-check evidence
    inst = await live_login(live, world.instructor.email)
    res = (await inst.get(f"/api/instructor/assignments/{world.assignment.id}/results")).json()
    row = next(s for s in res["students"] if s["user"]["short_id"] == "alice1")
    assert row["final_score"] == "100.00"
    det = (await inst.get(f"/api/instructor/attempts/{row['attempts'][0]['id']}")).json()
    assert det["evidence"]["final"]["payload"]["collectors"]["s3"]["buckets"][BUCKET]["versioning"] == "Enabled"

    # 7) cleanup: sandbox gone on the runner (containers + network)
    await wait_ready(alice, sid, states=("TERMINATED",))
    await background.drain()
    status = await real_runner.sandbox_status(sid)
    assert status["exists"] is False and status["emulator"]["state"] == "missing"
    assert all(sb["sandbox_id"] != sid for sb in await real_runner.list_sandboxes())


async def test_terminal_ticket_rules(engine, world, live, real_runner):
    alice = await live_login(live, world.alice.email)
    sid = (await alice.post(f"/api/assignments/{world.assignment.id}/sessions")).json()["id"]
    await wait_ready(alice, sid)

    async def close_code(url: str, origin: str = ORIGIN) -> tuple[int, str]:
        try:
            ws = await websockets.connect(url, origin=origin)  # type: ignore[arg-type]
            await asyncio.wait_for(ws.recv(), 10)
        except websockets.InvalidStatus as e:
            return e.response.status_code, "http"
        except websockets.ConnectionClosed as e:
            return e.rcvd.code, e.rcvd.reason
        return 0, "open"

    # wrong origin
    t = (await alice.post(f"/api/sessions/{sid}/terminal-ticket")).json()["ticket"]
    code, reason = await close_code(f"ws://{live}/ws/terminal?ticket={t}", origin="http://evil.example")
    assert (code, reason) == (4403, "origin_not_allowed")
    # single use: first connect works, reuse is rejected
    t = (await alice.post(f"/api/sessions/{sid}/terminal-ticket")).json()["ticket"]
    ws = await websockets.connect(f"ws://{live}/ws/terminal?ticket={t}", origin=ORIGIN)  # type: ignore[arg-type]
    code, reason = await close_code(f"ws://{live}/ws/terminal?ticket={t}")
    assert (code, reason) == (4401, "invalid_ticket")
    await ws.close()
    # expired
    t = (await alice.post(f"/api/sessions/{sid}/terminal-ticket")).json()["ticket"]
    async with sessionmaker()() as db:
        await db.execute(update(TerminalTicket).values(expires_at=st.now() - timedelta(seconds=1)))
        await db.commit()
    code, _ = await close_code(f"ws://{live}/ws/terminal?ticket={t}")
    assert code == 4401
    # garbage
    code, _ = await close_code(f"ws://{live}/ws/terminal?ticket=nope")
    assert code == 4401
    # at most 2 terminals per session
    t1 = await Term.open(live, alice, sid)
    t2 = await Term.open(live, alice, sid)
    t = (await alice.post(f"/api/sessions/{sid}/terminal-ticket")).json()["ticket"]
    code, _ = await close_code(f"ws://{live}/ws/terminal?ticket={t}")
    assert code == 4429
    await t1.ws.close()
    await t2.ws.close()
    # reset closes open terminals with reason 'reset'
    t3 = await Term.open(live, alice, sid)
    await t3.run("echo hello")
    r = await alice.post(f"/api/sessions/{sid}/reset", headers=idem())
    assert r.status_code == 200, r.text
    with pytest.raises(websockets.ConnectionClosed) as closed:
        for _ in range(100):
            await asyncio.wait_for(t3.ws.recv(), 10)
    assert closed.value.rcvd.reason == "reset"
    # and the new terminal works after reset
    t4 = await Term.open(live, alice, sid)
    assert "0" in await t4.run("aws s3 ls | wc -l")
    await t4.ws.close()
    await alice.post(f"/api/sessions/{sid}/stop")


# --------------------------------------------------------------------------- contract (§8)
CONTRACT = {  # insertion order is a valid lifecycle (objects before versioning: see note below)
    "CreateBucket": lambda c, b: c.create_bucket(Bucket=b),
    "ListBuckets": lambda c, b: c.list_buckets(),
    "GetBucketLocation": lambda c, b: c.get_bucket_location(Bucket=b),
    "PutPublicAccessBlock": lambda c, b: c.put_public_access_block(Bucket=b, PublicAccessBlockConfiguration={
        "BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": False, "RestrictPublicBuckets": True}),
    "GetPublicAccessBlock": lambda c, b: c.get_public_access_block(Bucket=b)[
        "PublicAccessBlockConfiguration"]["BlockPublicPolicy"] is False or 1 / 0,
    "PutObject": lambda c, b: c.put_object(Bucket=b, Key="k.html", Body=b"<p>", ContentType="text/html"),
    "HeadObject": lambda c, b: c.head_object(Bucket=b, Key="k.html")["ContentType"] == "text/html" or 1 / 0,
    "GetObject": lambda c, b: c.get_object(Bucket=b, Key="k.html")["Body"].read() == b"<p>" or 1 / 0,
    "ListObjectsV2": lambda c, b: [o["Key"] for o in c.list_objects_v2(Bucket=b)["Contents"]] == ["k.html"] or 1 / 0,
    # Like real AWS, deleting in a versioned bucket only adds a delete marker, so objects go first.
    "DeleteObject": lambda c, b: c.delete_object(Bucket=b, Key="k.html"),
    "PutBucketVersioning": lambda c, b: c.put_bucket_versioning(
        Bucket=b, VersioningConfiguration={"Status": "Enabled"}),
    "GetBucketVersioning": lambda c, b: c.get_bucket_versioning(Bucket=b)["Status"] == "Enabled" or 1 / 0,
    "PutBucketTagging": lambda c, b: c.put_bucket_tagging(Bucket=b, Tagging={"TagSet": [{"Key": "k", "Value": "v"}]}),
    "GetBucketTagging": lambda c, b: c.get_bucket_tagging(Bucket=b)["TagSet"] == [{"Key": "k", "Value": "v"}] or 1 / 0,
    "DeleteBucketTagging": lambda c, b: c.delete_bucket_tagging(Bucket=b),
    "PutBucketPolicy": lambda c, b: c.put_bucket_policy(Bucket=b, Policy=json.dumps({
        "Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": "*", "Action": "s3:GetObject",
                                                "Resource": f"arn:aws:s3:::{b}/*"}]})),
    "GetBucketPolicy": lambda c, b: json.loads(c.get_bucket_policy(Bucket=b)["Policy"]),
    "DeleteBucketPolicy": lambda c, b: c.delete_bucket_policy(Bucket=b),
    "DeleteBucket": lambda c, b: c.delete_bucket(Bucket=b),
}


@pytest.mark.parametrize("contract_engine", ENGINES)
async def test_contract_for_every_declared_supported_s3_operation(real_runner, contract_engine):
    caps = emulators.get(contract_engine).capabilities
    declared = {op for op, o in caps.services["s3"].items() if o.level == "supported"}
    assert declared == set(CONTRACT), f"every supported op needs a contract test: {declared ^ set(CONTRACT)}"
    sid = str(uuid.uuid4())
    info = await real_runner.create_sandbox({"sandbox_id": sid, "env": get_settings().env,
                                             "engine": contract_engine,
                                             "terminal_credential": "contract:abcdefgh1234"})
    assert info["engine"] == contract_engine
    try:
        c = emulators.get(contract_engine).client("s3", info["emulator_endpoint"])
        for op in CONTRACT:  # dict order is a valid lifecycle
            await asyncio.to_thread(CONTRACT[op], c, "contract-bucket")
    finally:
        await real_runner.destroy_sandbox(sid)
