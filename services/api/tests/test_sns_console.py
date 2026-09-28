"""SNS: pure check grading, the console API (FakeRunner = real Moto), the lab packs and the break-fix
baseline. Real-runtime contract + labtest on every engine live in tests/test_sns.py (marker docker)."""

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

GUIDED = Path(LABS) / "sns-basics"
BREAKFIX = Path(LABS) / "sns-breakfix"

QUEUE = "cafe-orders-alice1"
TOPIC = "cafe-alerts-alice1"
PEEK = f"{QUEUE}|10"


def sns_evidence(display_name="CloudCafé alerts", subscribed=True, bodies=(), queue=True, topic=True) -> dict:
    subs = [{"protocol": "sqs", "queue": QUEUE, "raw_delivery": False}] if subscribed else []
    return {"format": 1, "captured_at": "x", "collectors": {
        "sns": {"topics": {TOPIC: {"name": TOPIC, "display_name": display_name,
                                   "subscriptions": subs}} if topic else {}},
        "sqs": {"queues": {QUEUE: {"name": QUEUE, "fifo": False, "visibility_timeout": "30",
                                   "retention_period": "3600", "delay_seconds": "0", "messages": len(bodies),
                                   "in_flight": 0, "tags": {}}} if queue else {},
                "peeks": {PEEK: {"queue": QUEUE, "received": len(bodies), "bodies": list(bodies)}}},
    }}


def _grade(pack: Path, evidence: dict) -> dict:
    d = load_pack(pack).definition
    return grade(d, compute_variables(d, "alice1"), evidence)


# ------------------------------------------------------------------------------------ pure
def test_sns_labs_load_and_are_valid_on_every_engine():
    guided = load_pack(GUIDED).definition
    fixed = load_pack(BREAKFIX).definition
    for d in (guided, fixed):
        assert d.services == ["sqs", "sns"] and d.runtime.emulator == "default"
        assert emulators.candidates(d.runtime.emulator) == emulators.ENGINES
    assert guided.kind == "guided" and not guided.break_actions
    assert fixed.kind == "break_fix" and fixed.break_actions and not fixed.setup


def test_guided_scores_zero_partial_full_and_explains():
    assert _grade(GUIDED, {"collectors": {}})["score"] == Decimal("0.00")
    assert _grade(GUIDED, sns_evidence(subscribed=False, bodies=()))["score"] == Decimal("45.00")
    full = sns_evidence(bodies=['{"alert": "latte order waiting"}'])
    assert _grade(GUIDED, full)["score"] == Decimal("100.00")
    r = _grade(GUIDED, sns_evidence(display_name="", subscribed=False))
    failed = {c["check"]: c for t in r["tasks"] for c in t["checks"] if not c["passed"]}
    assert "display name" in failed["sns.topic_exists"]["message"]
    assert "not subscribed" in failed["sns.subscription"]["message"]


def test_breakfix_baseline_partial_solution():
    broken = sns_evidence(subscribed=False, bodies=())
    assert _grade(BREAKFIX, broken)["score"] == Decimal("20.00")  # topic + queue intact
    partial = sns_evidence(subscribed=True, bodies=())
    assert _grade(BREAKFIX, partial)["score"] == Decimal("70.00")  # subscription restored, no alert
    full = sns_evidence(subscribed=True, bodies=['{"alert": "latte"}'])
    assert _grade(BREAKFIX, full)["score"] == Decimal("100.00")


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


async def test_sns_console_journey(world, fake_runner):
    a = await _assignment(world, GUIDED, "SNS basics")
    c = await login(world.alice)
    sid = (await c.post(f"/api/assignments/{a.id}/sessions")).json()["id"]
    await wait_state(c, sid, {"READY"})
    sqs = f"/api/sessions/{sid}/console/sqs"
    base = f"/api/sessions/{sid}/console/sns"
    services = (await c.get(f"/api/console/services?session_id={sid}")).json()["services"]
    assert services["sns"] == "available" and services["sqs"] == "available"

    await c.post(f"{sqs}/queues", json={"name": QUEUE, "retention_period": 3600})
    r = await c.post(f"{base}/topics", json={"name": TOPIC, "display_name": "CloudCafé alerts"})
    assert r.status_code == 201, r.text
    topics = (await c.get(f"{base}/topics")).json()["topics"]
    assert [t["name"] for t in topics] == [TOPIC] and topics[0]["display_name"] == "CloudCafé alerts"

    assert (await c.post(f"{base}/topics/{TOPIC}/subscriptions", json={"queue": "nope"})).status_code == 404
    r = await c.post(f"{base}/topics/{TOPIC}/subscriptions", json={"queue": QUEUE})
    sub_arn = r.json()["subscription_arn"]
    assert sub_arn and sub_arn != "PendingConfirmation"

    d = (await c.get(f"{base}/topics/{TOPIC}")).json()
    assert d["subscriptions"] == 1
    sub = d["subscriptions_list"][0]
    assert sub["protocol"] == "sqs" and sub["queue"] == QUEUE

    # Publish, then prove delivery with the SQS console's non-destructive poll.
    assert (await c.post(f"{base}/topics/{TOPIC}/publish", json={
        "message": '{"alert": "latte order waiting"}'})).status_code == 201
    polled = (await c.post(f"{sqs}/queues/{QUEUE}/poll", json={"max": 10, "wait_seconds": 1})).json()["messages"]
    assert len(polled) == 1 and "latte" in polled[0]["body"]

    p = await c.post(f"/api/sessions/{sid}/progress")
    assert p.status_code == 200, p.text
    assert p.json()["score"] == "100.00", p.text

    # Unsubscribe, then the score drops (subscription + delivery checks fail).
    assert (await c.post(f"{base}/topics/{TOPIC}/subscriptions/delete",
                         json={"subscription_arn": sub_arn})).status_code == 204
    d = (await c.get(f"{base}/topics/{TOPIC}")).json()
    assert d["subscriptions"] == 0

    bob = await login(world.bob)
    assert (await bob.get(f"{base}/topics")).status_code == 404
    assert (await c.post(f"/api/sessions/{sid}/submit", headers=idem())).json()["result"]["score"] == "75.00"
    assert (await c.get(f"{base}/topics")).status_code == 409


async def test_sns_console_breakfix_restore(world, fake_runner):
    """FakeRunner cannot run break-fix setup jobs; the broken state is built with the console API and the
    break-fix definition is graded by hand (labtest covers the compiled setup on real engines)."""
    fixed = load_pack(BREAKFIX).definition
    c = await login(world.alice)
    a = await _assignment(world, GUIDED, "SNS break-fix state")
    sid = (await c.post(f"/api/assignments/{a.id}/sessions")).json()["id"]
    await wait_state(c, sid, {"READY"})
    sqs = f"/api/sessions/{sid}/console/sqs"
    base = f"/api/sessions/{sid}/console/sns"
    await c.post(f"{sqs}/queues", json={"name": QUEUE, "retention_period": 3600})
    await c.post(f"{base}/topics", json={"name": TOPIC})
    sub = (await c.post(f"{base}/topics/{TOPIC}/subscriptions", json={"queue": QUEUE})).json()["subscription_arn"]
    await c.post(f"{base}/topics/{TOPIC}/subscriptions/delete", json={"subscription_arn": sub})

    from app.grader import evidence as ev_mod
    from app.grader.grade import collectors_for, probes_for
    from app.models import LabSession

    async with sessionmaker()() as db:
        sess = await db.get(LabSession, sid)
    variables = compute_variables(fixed, "alice1")
    payload = await ev_mod.capture(sess.emulator_endpoint, collectors_for(fixed), sess.engine,
                                   probes_for(fixed, variables))
    assert grade(fixed, compute_variables(fixed, "alice1"), payload)["score"] == Decimal("20.00")

    await c.post(f"{base}/topics/{TOPIC}/subscriptions", json={"queue": QUEUE})
    await c.post(f"{base}/topics/{TOPIC}/publish", json={"message": '{"alert": "latte"}'})
    payload = await ev_mod.capture(sess.emulator_endpoint, collectors_for(fixed), sess.engine,
                                   probes_for(fixed, variables))
    assert grade(fixed, compute_variables(fixed, "alice1"), payload)["score"] == Decimal("100.00")
