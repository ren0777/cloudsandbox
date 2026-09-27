"""Phase 9 milestone 42 — interactive preview sandbox.

The FakeRunner (a real Moto per sandbox) covers the lifecycle, the console/terminal reuse, ownership and the
reconciler. The docker-marked test at the end runs a break-fix preview on the real runner and proves that
Reset reconstructs the declared baseline, the terminal works, and no session/attempt/grade is ever created.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
import websockets
from sqlalchemy import func, select

from app.config import get_settings
from app.db import sessionmaker
from app.grader import evidence as ev
from app.grader.grade import collectors_for, grade, probes_for
from app.instructor import preview as pv
from app.labs import drafts as dr
from app.labs.render import compute_variables
from app.models import Attempt, Grade, LabDraft, LabSession, SessionEvent, TerminalTicket
from app.sessions import state as st
from app.sessions.reconciler import reconcile_once
from tests.conftest import login, seed_runner_row

B = "/api/instructor/builder"


async def new_draft(c, **body) -> dict:
    r = await c.post(f"{B}/drafts", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def start(c, draft_id: str) -> dict:
    r = await c.post(f"{B}/drafts/{draft_id}/preview-sandbox")
    assert r.status_code == 201, r.text
    return r.json()["preview"]


async def no_student_work() -> None:
    async with sessionmaker()() as db:
        for model in (LabSession, Attempt, Grade, SessionEvent):
            assert await db.scalar(select(func.count()).select_from(model)) == 0, \
                f"a preview must never create {model.__tablename__} rows"


# ------------------------------------------------------------------------------ lifecycle (FakeRunner)
async def test_preview_lifecycle_console_terminal_and_isolation(world, fake_runner):
    await seed_runner_row()
    c = await login(world.instructor)
    d = await new_draft(c, title="Preview me")
    sid = pv.sandbox_id_for(uuid.UUID(d["id"]))

    p = await start(c, d["id"])
    assert p["status"] == "running" and p["sandbox_id"] == sid and p["engine"] == "moto"
    assert p["console"] == f"/api/sessions/{sid}/console"
    assert ("create", sid) in fake_runner.calls
    # idempotent: a second start returns the same sandbox instead of creating another
    assert (await start(c, d["id"]))["sandbox_id"] == sid
    assert [x for x in fake_runner.calls if x[0] == "create"] == [("create", sid)]

    # the same console routes as a student lab, resolved to the preview sandbox
    r = await c.get(f"/api/console/services?session_id={sid}")
    assert r.status_code == 200 and r.json()["services"]["s3"] == "available"
    r = await c.get(f"/api/sessions/{sid}/console/s3/buckets")
    assert r.status_code == 200 and r.json()["buckets"] == []
    r = await c.post(f"/api/sessions/{sid}/console/s3/buckets", json={"name": "preview-bucket"})
    assert r.status_code == 201, r.text
    assert [b["name"] for b in (await c.get(f"/api/sessions/{sid}/console/s3/buckets")).json()["buckets"]] \
        == ["preview-bucket"]

    # the terminal ticket uses the same single-use machinery
    r = await c.post(f"/api/sessions/{sid}/terminal-ticket")
    assert r.status_code == 200 and r.json()["ticket"]
    assert r.json()["ws_path"] == "/ws/terminal"

    # reset reconstructs the declared starting state (the runner re-runs the compiled setup)
    r = await c.post(f"{B}/drafts/{d['id']}/preview-sandbox/reset")
    assert r.status_code == 200 and r.json()["preview"]["status"] == "running"
    assert ("reset", sid) in fake_runner.calls

    assert (await c.delete(f"{B}/drafts/{d['id']}/preview-sandbox")).status_code == 204
    assert sid not in fake_runner.sandboxes
    assert (await c.get(f"{B}/drafts/{d['id']}/preview-sandbox")).json()["preview"]["status"] == "stopped"
    await no_student_work()


async def test_preview_is_owner_or_admin_only_and_never_a_student_session(world, fake_runner):
    await seed_runner_row()
    c = await login(world.instructor)
    d = await new_draft(c, title="Mine")
    sid = (await start(c, d["id"]))["sandbox_id"]

    other = await login(world.other_instructor)
    for method, url in (("get", f"{B}/drafts/{d['id']}/preview-sandbox"), ("post", f"{B}/drafts/{d['id']}/preview-sandbox"),
                        ("post", f"{B}/drafts/{d['id']}/preview-sandbox/reset"), ("delete", f"{B}/drafts/{d['id']}/preview-sandbox")):
        assert (await getattr(other, method)(url)).status_code == 404
    # a student passes the route's role gate but can never resolve the preview sandbox
    stu = await login(world.alice)
    assert (await stu.get(f"/api/sessions/{sid}/console/s3/buckets")).status_code == 404
    assert (await stu.post(f"/api/sessions/{sid}/terminal-ticket")).status_code == 404
    assert (await stu.post(f"{B}/drafts/{d['id']}/preview-sandbox")).status_code == 403  # lab_manage

    # an admin may inspect (and stop) another author's preview
    admin = await login(world.admin)
    assert (await admin.get(f"{B}/drafts/{d['id']}/preview-sandbox")).status_code == 200
    assert (await admin.get(f"/api/sessions/{sid}/console/s3/buckets")).status_code == 200
    assert (await admin.delete(f"{B}/drafts/{d['id']}/preview-sandbox")).status_code == 204


async def test_preview_reconciler_keeps_it_then_expires_it(world, fake_runner):
    await seed_runner_row()
    c = await login(world.instructor)
    d = await new_draft(c)
    sid = (await start(c, d["id"]))["sandbox_id"]

    # a running preview is "known", so the orphan sweep leaves it alone
    await reconcile_once()
    assert sid in fake_runner.sandboxes

    async with sessionmaker()() as db:
        row = await db.get(LabDraft, uuid.UUID(d["id"]))
        row.last_preview = {**row.last_preview, "last_active": (st.now() - timedelta(hours=2)).isoformat()}
        await db.commit()
    stats = await reconcile_once()
    assert stats.get("preview_expired") == 1 and sid not in fake_runner.sandboxes
    async with sessionmaker()() as db:
        row = await db.get(LabDraft, uuid.UUID(d["id"]))
        assert row.last_preview["status"] == "stopped" and row.last_preview["ttyd_cred_enc"] is None


# ------------------------------------------------------------------------------- real runtime (docker)
@pytest.fixture
async def live(real_runner):
    """A real uvicorn server for the WebSocket test (the in-process client cannot open one)."""
    import uvicorn

    from app.main import app
    from tests.test_integration_docker import _port
    port = _port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="off",
                                           log_level="warning", ws="websockets"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    yield f"127.0.0.1:{port}"
    server.should_exit = True
    await task


@pytest.mark.docker
async def test_break_fix_preview_baseline_reset_console_and_terminal(world, real_runner, live):
    from tests.test_integration_docker import Term, live_login

    c = await login(world.instructor)
    d = await new_draft(c, title="Broken preview")
    actions = [{"type": "iam.create_group", "group": "baristas-{{ student_short_id }}"},
               {"type": "iam.attach_managed_policy", "target_type": "group",
                "target": "baristas-{{ student_short_id }}", "policy": "AdministratorAccess"}]
    lab = d["content"]["lab"] | {"kind": "break_fix", "services": ["s3", "iam"], "break_actions": actions}
    r = await c.put(f"{B}/drafts/{d['id']}", json={"lab": lab})
    assert r.json()["validation"]["ok"], r.json()["validation"]

    p = await start(c, d["id"])
    assert p["status"] == "running" and p["engine"] == "moto"
    pkg = dr.package(r.json()["content"])
    variables = compute_variables(pkg.definition, world.instructor.short_id)

    async def score() -> Decimal:
        async with sessionmaker()() as db:
            row = await db.get(LabDraft, uuid.UUID(d["id"]))
            endpoint = row.last_preview["emulator_endpoint"]
        payload = await ev.capture(endpoint, collectors_for(pkg.definition), p["engine"],
                                   probes_for(pkg.definition, variables))
        return grade(pkg.definition, variables, payload)["score"]

    first = await score()
    assert first == Decimal("0.00"), "the broken baseline must score 0"
    await c.post(f"{B}/drafts/{d['id']}/preview-sandbox/reset")
    assert await score() == first, "Reset must reconstruct the identical declared starting state"

    # console + terminal inspection on the same sandbox
    assert (await c.get(f"/api/sessions/{p['sandbox_id']}/console/iam/groups")).status_code == 200
    inst = await live_login(live, world.instructor.email)
    term = await Term.open(live, inst, p["sandbox_id"])
    out = await term.run("echo preview-terminal-ok")
    assert "preview-terminal-ok" in out
    await term.ws.close()

    assert (await c.delete(f"{B}/drafts/{d['id']}/preview-sandbox")).status_code == 204
    await no_student_work()
