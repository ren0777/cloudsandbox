"""SQS: pure check grading (including the message peek probe), the console API (FakeRunner = real Moto),
the lab packs and the break-fix baseline. Real-runtime contract + labtest on every engine live in
tests/test_sqs.py (marker docker)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from app.db import sessionmaker
from app.grader.grade import grade
from app.labs.importer import import_package
from app.labs.package import load_pack
from app.labs.render import compute_variables
from app.models import Assignment
from app.runtime import emulators
from app.sessions import state as st
from tests.conftest import LABS, idem, login, wait_state

GUIDED = Path(LABS) / "sqs-basics"
BREAKFIX = Path(LABS) / "sqs-breakfix"

QUEUE = "cafe-orders-alice1"
PEEK = f"{QUEUE}|10"


def queue_evidence(visibility="30", retention="3600", delay="0", bodies=(), fifo=False, queue=True) -> dict:
    return {"format": 1, "captured_at": "x", "collectors": {"sqs": {
        "queues": {QUEUE: {"name": QUEUE, "fifo": fifo, "visibility_timeout": visibility,
                           "retention_period": retention, "delay_seconds": delay, "messages": len(bodies),
                           "in_flight": 0, "tags": {"project": "cloudcafe"}}} if queue else {},
        "peeks": {PEEK: {"queue": QUEUE, "received": len(bodies), "bodies": list(bodies)}},
    }}}


def _grade(pack: Path, evidence: dict) -> dict:
    d = load_pack(pack).definition
    return grade(d, compute_variables(d, "alice1"), evidence)


# ------------------------------------------------------------------------------------ pure
def test_sqs_labs_load_and_are_valid_on_every_engine():
    guided = load_pack(GUIDED).definition
    fixed = load_pack(BREAKFIX).definition
    for d in (guided, fixed):
        assert d.services == ["sqs"] and d.runtime.emulator == "default"
        assert emulators.candidates(d.runtime.emulator) == emulators.ENGINES
    assert guided.kind == "guided" and not guided.break_actions
    assert fixed.kind == "break_fix" and fixed.break_actions and not fixed.setup


def test_guided_scores_zero_partial_full_and_explains():
    assert _grade(GUIDED, {"collectors": {}})["score"] == Decimal("0.00")
    # queue with the default 4-day retention, no message
    partial = queue_evidence(retention="345600")
    assert _grade(GUIDED, partial)["score"] == Decimal("35.00")
    full = queue_evidence(bodies=['{"orderId": 1001, "drink": "latte"}'])
    assert _grade(GUIDED, full)["score"] == Decimal("100.00")
    r = _grade(GUIDED, queue_evidence(retention="345600", bodies=['{"drink": "tea"}']))
    failed = {c["check"]: c for t in r["tasks"] for c in t["checks"] if not c["passed"]}
    assert "retention_period = 345600, not 3600" in failed["sqs.queue_attribute"]["message"]
    assert "no message matching" in failed["sqs.message_present"]["message"]


def test_breakfix_baseline_partial_solution_and_anti_lazy():
    broken = queue_evidence(visibility="43200", retention="3600", delay="900")
    assert _grade(BREAKFIX, broken)["score"] == Decimal("20.00")  # only "leave the queue alone"
    partial = queue_evidence(visibility="30", retention="3600", delay="900")
    assert _grade(BREAKFIX, partial)["score"] == Decimal("70.00")
    assert _grade(BREAKFIX, queue_evidence())["score"] == Decimal("100.00")
    lazy = queue_evidence(visibility="30", retention="345600", delay="0")  # deleted + recreated
    assert _grade(BREAKFIX, lazy)["score"] == Decimal("80.00")


# ------------------------------------------------------------------------------- console API
async def _assignment(world, pack: Path, title: str) -> Assignment:
    async with sessionmaker()() as db:
        lv, _ = await import_package(db, load_pack(pack))
        now = st.now()
        a = Assignment(course_id=world.course.id, lab_version_id=lv.id, title=title,
                       open_at=now - timedelta(hours=1), due_at=now + timedelta(days=1),
                       close_at=now + timedelta(days=2), max_attempts=3)
        db.add(a)
        await db.commit()
        return a


async def test_sqs_console_journey(world, fake_runner):
    a = await _assignment(world, GUIDED, "SQS basics")
    c = await login(world.alice)
    sid = (await c.post(f"/api/assignments/{a.id}/sessions")).json()["id"]
    await wait_state(c, sid, {"READY"})
    base = f"/api/sessions/{sid}/console/sqs"
    assert (await c.get(f"/api/console/services?session_id={sid}")).json()["services"]["sqs"] == "available"

    assert (await c.post(f"{base}/queues", json={"name": "bad name"})).status_code == 422
    r = await c.post(f"{base}/queues", json={"name": QUEUE, "visibility_timeout": 45, "retention_period": 3600})
    assert r.status_code == 201, r.text
    queues = (await c.get(f"{base}/queues")).json()["queues"]
    assert [q["name"] for q in queues] == [QUEUE]
    assert queues[0]["visibility_timeout"] == "45" and queues[0]["retention_period"] == "3600"

    d = (await c.get(f"{base}/queues/{QUEUE}")).json()
    assert d["fifo"] is False and d["url"].endswith(f"/{QUEUE}")

    sent = await c.post(f"{base}/queues/{QUEUE}/messages", json={"body": '{"orderId": 1001, "drink": "latte"}'})
    assert sent.status_code == 201 and sent.json()["message_id"]
    polled = (await c.post(f"{base}/queues/{QUEUE}/poll", json={"max": 10, "wait_seconds": 1})).json()["messages"]
    assert len(polled) == 1 and "latte" in polled[0]["body"]
    assert (await c.post(f"{base}/queues/{QUEUE}/messages/delete",
                         json={"receipt_handle": polled[0]["receipt_handle"]})).status_code == 204

    assert (await c.put(f"{base}/queues/{QUEUE}/attributes", json={
        "visibility_timeout": 30, "retention_period": 3600, "delay_seconds": 0,
        "receive_wait_time": 1})).status_code == 200
    assert (await c.put(f"{base}/queues/{QUEUE}/tags", json={
        "tags": [{"key": "project", "value": "cloudcafe"}]})).status_code == 200
    d = (await c.get(f"{base}/queues/{QUEUE}")).json()
    assert d["visibility_timeout"] == "30" and d["tags"] == {"project": "cloudcafe"}

    # Progress checks are rate-limited (one per few seconds), so the journey checks the final state once.
    await c.post(f"{base}/queues/{QUEUE}/messages", json={"body": '{"drink": "latte"}'})
    p = await c.post(f"/api/sessions/{sid}/progress")
    assert p.status_code == 200, p.text
    assert p.json()["score"] == "100.00", p.text

    # FIFO naming rule + tags replacement + ownership + freeze
    assert (await c.post(f"{base}/queues", json={"name": "orders", "fifo": True})).status_code == 422
    assert (await c.put(f"{base}/queues/{QUEUE}/tags", json={"tags": []})).json()["tags"] == {}
    bob = await login(world.bob)
    assert (await bob.get(f"{base}/queues")).status_code == 404
    assert (await c.post(f"/api/sessions/{sid}/submit", headers=idem())).json()["result"]["score"] == "100.00"
    assert (await c.get(f"{base}/queues")).status_code == 409
    assert (await c.delete(f"{base}/queues/{QUEUE}")).status_code == 409


async def test_sqs_console_breakfix_attributes(world, fake_runner):
    """FakeRunner cannot run break-fix setup jobs; the broken state is built with the console API and the
    break-fix definition is graded by hand (labtest covers the compiled setup on real engines)."""
    fixed = load_pack(BREAKFIX).definition
    c = await login(world.alice)
    a = await _assignment(world, GUIDED, "SQS break-fix state")
    sid = (await c.post(f"/api/assignments/{a.id}/sessions")).json()["id"]
    await wait_state(c, sid, {"READY"})
    base = f"/api/sessions/{sid}/console/sqs"
    await c.post(f"{base}/queues", json={"name": QUEUE, "visibility_timeout": 43200,
                                         "retention_period": 3600, "delay_seconds": 900})

    from app.grader import evidence as ev_mod
    from app.grader.grade import collectors_for
    from app.models import LabSession

    async with sessionmaker()() as db:
        sess = await db.get(LabSession, sid)
    payload = await ev_mod.capture(sess.emulator_endpoint, collectors_for(fixed), sess.engine)
    assert grade(fixed, compute_variables(fixed, "alice1"), payload)["score"] == Decimal("20.00")

    await c.put(f"{base}/queues/{QUEUE}/attributes", json={"visibility_timeout": 30,
                                                           "retention_period": 3600, "delay_seconds": 0})
    payload = await ev_mod.capture(sess.emulator_endpoint, collectors_for(fixed), sess.engine)
    assert grade(fixed, compute_variables(fixed, "alice1"), payload)["score"] == Decimal("100.00")
