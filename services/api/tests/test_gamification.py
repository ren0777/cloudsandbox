"""Phase 6 — XP/levels/badges from verified results only, and instructor-configurable leaderboards."""

from __future__ import annotations

import uuid
from dataclasses import replace
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.db import sessionmaker
from app.gamification import BADGES, BY_ID, AttemptFacts, award_for_attempt, level_for
from app.models import UserBadge
from tests.conftest import idem, login, wait_state
from tests.test_courses_roster import audits

BUCKET = "cafe-alice1-site"
BASE = AttemptFacts(attempt_no=2, score=Decimal("50"), max_score=Decimal("100"), lab_id="x", lab_kind="guided",
                    services=frozenset({"s3"}), running_instance_types=())


def earned(f: AttemptFacts) -> set[str]:
    return {b.id for b in BADGES if b.rule(f)}


def test_badge_rules_are_pure_and_specific():
    assert earned(BASE) == {"first-deploy"}
    assert earned(replace(BASE, score=Decimal("0"))) == set()
    perfect = replace(BASE, score=Decimal("100"))
    assert earned(perfect) == {"first-deploy", "flawless"}
    assert "first-try" in earned(replace(perfect, attempt_no=1))
    assert "incident-responder" in earned(replace(perfect, lab_kind="break_fix", services=frozenset({"iam"})))
    assert "least-privilege" in earned(replace(perfect, services=frozenset({"iam"})))
    assert "serverless-chef" in earned(replace(perfect, services=frozenset({"lambda"})))
    assert "right-sized" in earned(replace(perfect, services=frozenset({"ec2"}), running_instance_types=("t3.micro",)))
    assert "right-sized" not in earned(replace(perfect, running_instance_types=("t3.micro", "m5.large")))
    assert "right-sized" not in earned(replace(perfect, running_instance_types=()))
    assert "full-stack" in earned(replace(perfect, perfect_services=frozenset({"s3", "dynamodb", "iam", "ec2", "lambda"})))
    assert "full-stack" not in earned(replace(perfect, perfect_services=frozenset({"s3", "iam"})))
    assert len(BY_ID) == len(BADGES)


def test_levels():
    assert level_for(0) == {"level": 1, "title": "Trainee", "xp_for_level": 0, "xp_for_next": 100}
    assert level_for(260)["title"] == "Junior cloud engineer"
    assert level_for(10_000)["xp_for_next"] is None


async def submit(world, bucket: bool, who=None) -> dict:
    c = await login(who or world.alice)
    sid = (await c.post(f"/api/assignments/{world.assignment.id}/sessions")).json()["id"]
    await wait_state(c, sid, {"READY"})
    if bucket:
        await c.post(f"/api/sessions/{sid}/console/s3/buckets", json={"name": BUCKET if who is None else "cafe-bob222-site"})
    r = await c.post(f"/api/sessions/{sid}/submit", headers=idem())
    assert r.status_code == 200, r.text
    await wait_state(c, sid, {"TERMINATED"})
    return r.json()


async def test_xp_and_badges_come_from_graded_attempts(world, fake_runner):
    c = await login(world.alice)
    p0 = (await c.get("/api/me/progress")).json()
    assert (p0["xp"], p0["level"]) == (0, 1) and not any(b["earned"] for b in p0["badges"])

    res = await submit(world, bucket=True)
    assert [b["id"] for b in res["badges"]] == ["first-deploy"]  # shown on the result page
    p = (await c.get("/api/me/progress")).json()
    score_pct = round(float(res["result"]["score"]) * 100 / float(res["result"]["max_score"]))
    assert p["lab_xp"] == score_pct and p["badge_xp"] == BY_ID["first-deploy"].xp
    assert p["xp"] == score_pct + 10

    # a worse second attempt doesn't reduce XP (best counts) and awards nothing new
    res2 = await submit(world, bucket=False)
    assert res2["badges"] == []
    assert (await c.get("/api/me/progress")).json()["xp"] == p["xp"]

    # awarding is idempotent (backfill/regrade can run again)
    async with sessionmaker()() as db:
        assert await award_for_attempt(db, uuid.UUID(res["attempt"]["id"])) == []
        rows = (await db.scalars(select(UserBadge))).all()
        assert [(r.badge_id, str(r.attempt_id)) for r in rows] == [("first-deploy", res["attempt"]["id"])]
        with pytest.raises(Exception):
            await db.execute(text("DELETE FROM user_badges"))
        await db.rollback()


async def test_uncounted_attempts_earn_nothing(world, fake_runner):
    from uuid import UUID

    from app.sessions import service
    c = await login(world.alice)
    sid = (await c.post(f"/api/assignments/{world.assignment.id}/sessions")).json()["id"]
    await wait_state(c, sid, {"READY"})
    attempt = await service.submit(UUID(sid), "ttl", "test")  # untouched auto-submit → counts=false
    assert attempt.counts is False
    p = (await c.get("/api/me/progress")).json()
    assert p["xp"] == 0 and not any(b["earned"] for b in p["badges"])


async def test_regrade_updates_xp(world, fake_runner, monkeypatch):
    res = await submit(world, bucket=True)
    c = await login(world.alice)
    before = (await c.get("/api/me/progress")).json()["lab_xp"]
    # simulate a regrade that gives full marks (e.g. a fixed checker) by inserting a newer grade row
    from app.models import Grade
    async with sessionmaker()() as db:
        db.add(Grade(attempt_id=uuid.UUID(res["attempt"]["id"]), grader_version="x", score=Decimal("100"),
                     max_score=Decimal("100"), result={}, created_by=world.instructor.id, reason="test"))
        await db.commit()
    after = (await c.get("/api/me/progress")).json()
    assert after["lab_xp"] == 100 > before


async def test_leaderboard_off_by_default_then_anonymous_then_named(world, fake_runner):
    await submit(world, bucket=True)
    stu = await login(world.alice)
    url = f"/api/courses/{world.course.id}/leaderboard"
    assert (await stu.get(url)).json() == {"mode": "off", "entries": [], "me": None}

    inst = await login(world.instructor)
    settings = f"/api/instructor/courses/{world.course.id}/settings"
    assert (await inst.patch(settings, json={"leaderboard": "anonymous"})).json() == {"leaderboard": "anonymous"}
    board = (await stu.get(url)).json()
    assert board["mode"] == "anonymous" and board["students"] == 2
    names = [e["name"] for e in board["entries"]]
    assert "Alice" not in names and "Bob" not in names and all(len(n.split()) == 3 for n in names)
    assert board["entries"][0]["you"] is True and board["entries"][0]["rank"] == 1 and board["me"]["rank"] == 1
    assert "user_id" not in board["entries"][0]
    assert (await stu.get(url)).json()["entries"][0]["name"] == names[0]  # stable alias
    # staff always see real names
    staff_view = (await inst.get(url)).json()
    assert {e["name"] for e in staff_view["entries"]} == {"Alice", "Bob"}

    assert (await inst.patch(settings, json={"leaderboard": "named"})).status_code == 200
    assert (await stu.get(url)).json()["entries"][0]["name"] == "Alice"
    assert (await inst.patch(settings, json={"leaderboard": "loud"})).status_code == 422
    changes = [e.details["changes"]["leaderboard"] for e in await audits("course.settings_changed")]
    assert changes == [["off", "anonymous"], ["anonymous", "named"]]

    # scoping: other course's students/staff can't see it; students can't change settings
    assert (await (await login(world.other_instructor)).get(url)).status_code == 404
    assert (await stu.patch(settings, json={"leaderboard": "off"})).status_code == 403
    assert (await (await login(world.other_instructor)).patch(settings, json={"leaderboard": "off"})).status_code == 404
