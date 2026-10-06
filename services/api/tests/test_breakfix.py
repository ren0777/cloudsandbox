"""Phase 6 — break-fix labs: setup creates the broken state (per student, again on Reset), grading checks the
repaired final state. Pure grading scenarios + real runtime (marker docker) on every default engine."""

from __future__ import annotations

import copy
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from app.grader.grade import grade
from app.labs.package import load_pack
from app.labs.render import compute_variables
from app.labs.schema import LabValidationError, parse_definition
from app.runtime import emulators
from tests.conftest import LABS

LAB = Path(LABS) / "iam-breakfix"
ID = "alice1"
ADMIN = "arn:aws:iam::aws:policy/AdministratorAccess"
ORDERS = f"arn:aws:iam::123456789012:policy/orders-rw-{ID}"
ALLOW_ALL = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]}
ORDERS_DOC = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": [
    "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"],
    "Resource": f"arn:aws:dynamodb:*:*:table/cafe-{ID}-orders"}]}

BROKEN = {
    "users": {f"barista-{ID}": {"groups": [f"baristas-{ID}"], "attached": [], "inline": {}},
              f"intern-{ID}": {"groups": [f"baristas-{ID}"], "attached": [], "inline": {"temp-everything": ALLOW_ALL}}},
    "groups": {f"baristas-{ID}": {"attached": [ADMIN], "inline": {}}},
    "roles": {},
    "policies": {ADMIN: {"name": "AdministratorAccess", "document": ALLOW_ALL, "aws_managed": True},
                 ORDERS: {"name": f"orders-rw-{ID}", "document": ORDERS_DOC, "aws_managed": False}},
}


def score(iam: dict) -> tuple[Decimal, dict[str, bool]]:
    d = load_pack(LAB).definition
    r = grade(d, compute_variables(d, ID), {"format": 1, "collectors": {"iam": iam}})
    return r["score"], {t["task_id"]: t["passed"] for t in r["tasks"]}


def fixed() -> dict:
    s = copy.deepcopy(BROKEN)
    s["groups"][f"baristas-{ID}"]["attached"] = [ORDERS]
    del s["users"][f"intern-{ID}"]
    return s


def test_untouched_broken_state_scores_zero():
    assert score(BROKEN) == (Decimal("0.00"), {"remove-admin": False, "keep-working": False,
                                               "offboard-intern": False, "least-privilege": False})


def test_repaired_state_scores_full_marks():
    assert score(fixed())[0] == Decimal("100.00")
    # offboarding by emptying the intern's access (without deleting the user) also counts
    s = fixed()
    s["users"][f"intern-{ID}"] = {"groups": [], "attached": [], "inline": {}}
    assert score(s)[0] == Decimal("100.00")


def test_typical_mistakes():
    # 1) removing admin only (the partial script) → 45
    s = copy.deepcopy(BROKEN)
    s["groups"][f"baristas-{ID}"]["attached"] = []
    assert score(s) == (Decimal("45.00"), {"remove-admin": True, "keep-working": False,
                                           "offboard-intern": False, "least-privilege": True})
    # 2) intern removed from the group but the inline "*" policy remains → still has access
    s = fixed()
    s["users"][f"intern-{ID}"] = {"groups": [], "attached": [], "inline": {"temp-everything": ALLOW_ALL}}
    assert score(s)[1]["offboard-intern"] is False
    # 3) orders policy attached to the user instead of the group → keep-working fails
    s = fixed()
    s["groups"][f"baristas-{ID}"]["attached"] = []
    s["users"][f"barista-{ID}"]["attached"] = [ORDERS]
    assert score(s)[1]["keep-working"] is False
    # 4) "fixing" by deleting the barista → admin check can't pass for a missing user
    s = fixed()
    del s["users"][f"barista-{ID}"]
    assert score(s)[1]["remove-admin"] is False
    # 5) a broad replacement policy → hidden least-privilege check fails
    s = fixed()
    s["policies"][ORDERS]["document"] = {"Statement": [{"Effect": "Allow", "Action": "dynamodb:*", "Resource": "*"}]}
    assert score(s)[1]["least-privilege"] is False


def test_break_fix_requires_setup():
    import yaml
    data = yaml.safe_load((LAB / "lab.yaml").read_text(encoding="utf-8"))
    data.pop("setup")
    with pytest.raises(LabValidationError) as e:
        parse_definition(data)
    assert "setup script" in str(e.value)


def test_negative_checks_default_to_existing_behaviour():
    from app.grader.registry import get
    assert get("iam.user_in_group").params_model.model_validate({"user": "u", "group": "g"}).expect == "present"
    assert get("iam.policy_attached").params_model.model_validate({"principal": "user:u", "policy": "p"}).expect == "present"
    assert get("iam.policy_allows").params_model.model_validate(
        {"principal": "user:u", "action": "s3:GetObject", "resource": "*"}).absent_ok is False


# ------------------------------------------------------------------------------ real runtime
@pytest.mark.docker
@pytest.mark.parametrize("lab_engine", emulators.ENGINES)
async def test_breakfix_labtest_on_every_engine(real_runner, lab_engine):
    from app.labtest import check_pack
    results = await check_pack(LAB, real_runner, engine=lab_engine)
    assert [(r.name, str(r.actual)) for r in results] == [
        (f"{lab_engine}/empty", "0.00"), (f"{lab_engine}/partial", "45.00"),
        (f"{lab_engine}/solution", "100.00"), (f"{lab_engine}/reset", "0.00")], \
        [(r.name, r.actual, r.detail) for r in results]
    reset = results[-1]
    assert reset.ok and "reset reproduced the baseline" in reset.detail


@pytest.mark.docker
async def test_setup_creates_broken_state_in_a_session_and_reset_restores_it(real_runner, monkeypatch):
    """Through the real session lifecycle: the student's sandbox starts broken, the baseline is the broken
    state (so an untouched auto-submit doesn't count), and Reset recreates the broken state."""
    from datetime import timedelta

    from app.db import sessionmaker
    from app.labs.importer import import_package
    from app.models import Assignment
    from app.sessions import service
    from app.sessions import state as st
    from tests.conftest import idem, login, make_world, wait_state

    monkeypatch.setattr(service, "INVENTORY_TTL_S", 0.0)
    world = await make_world()
    async with sessionmaker()() as db:
        lv, _ = await import_package(db, load_pack(LAB))
        now = st.now()
        a = Assignment(course_id=world.course.id, lab_version_id=lv.id, title="Break-fix", open_at=now - timedelta(hours=1),
                       due_at=now + timedelta(days=1), close_at=now + timedelta(days=2), max_attempts=3)
        db.add(a)
        await db.commit()
    c = await login(world.alice)
    sid = (await c.post(f"/api/assignments/{a.id}/sessions")).json()["id"]
    await wait_state(c, sid, {"READY"}, timeout=180)
    arch = (await c.get(f"/api/sessions/{sid}/architecture")).json()["graph"]
    group = next(n for n in arch["nodes"] if n["id"] == f"iam:group:baristas-{ID}")
    assert group["flags"] == ["AdministratorAccess attached"]
    assert f"iam:user:intern-{ID}" in {n["id"] for n in arch["nodes"]}
    assert (await c.post(f"/api/sessions/{sid}/progress")).json()["score"] == "0.00"

    # student deletes the intern in the console, then resets: the broken state comes back
    base = f"/api/sessions/{sid}/console/iam"
    r = await c.delete(f"{base}/users/intern-{ID}")
    assert r.status_code in (200, 204), r.text
    assert f"iam:user:intern-{ID}" not in {n["id"] for n in (await c.get(f"/api/sessions/{sid}/architecture")).json()["graph"]["nodes"]}
    assert (await c.post(f"/api/sessions/{sid}/reset", headers=idem())).status_code in (200, 202)
    await wait_state(c, sid, {"READY"}, timeout=180)
    assert f"iam:user:intern-{ID}" in {n["id"] for n in (await c.get(f"/api/sessions/{sid}/architecture")).json()["graph"]["nodes"]}

    # an untouched automatic submit compares against the BROKEN baseline → not counted
    attempt = await service.submit(uuid.UUID(sid), "ttl", "test")
    assert attempt.counts is False and attempt.score == Decimal("0.00")
