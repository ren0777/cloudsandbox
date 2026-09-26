"""IAM: CloudLabs policy evaluator, checks/lab grading, console API + policy simulator (FakeRunner = real
Moto), and real-runtime contract + labtest on every engine (marker docker)."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.config import get_settings
from app.db import sessionmaker
from app.grader.grade import grade
from app.grader.iam_eval import evaluate, parse_document, principal_policies
from app.labs.importer import import_package
from app.labs.package import load_pack
from app.labs.render import compute_variables
from app.models import Assignment
from app.runtime import emulators
from app.sessions import state as st
from tests.conftest import LABS, idem, login, wait_state

LAB = Path(LABS) / "iam-least-privilege"


def doc(*stmts):
    return {"Version": "2012-10-17", "Statement": list(stmts)}


def allow(action, resource="*"):
    return {"Effect": "Allow", "Action": action, "Resource": resource}


# ---------------------------------------------------------------------------------- evaluator
def test_evaluator_semantics():
    pols = [("p", doc(allow(["s3:Get*", "s3:ListBucket"], "arn:aws:s3:::menu/*")))]
    assert evaluate(pols, "s3:GetObject", "arn:aws:s3:::menu/a.html").allowed
    assert evaluate(pols, "S3:getobject", "arn:aws:s3:::menu/a.html").allowed  # actions case-insensitive
    assert not evaluate(pols, "s3:GetObject", "arn:aws:s3:::MENU/a.html").allowed  # resources case-sensitive
    assert evaluate(pols, "s3:PutObject", "arn:aws:s3:::menu/a.html").decision == "implicit_deny"
    deny = pols + [("d", doc({"Effect": "Deny", "Action": "s3:GetObject", "Resource": "*"}))]
    assert evaluate(deny, "s3:GetObject", "arn:aws:s3:::menu/a.html").decision == "explicit_deny"
    notact = [("n", doc({"Effect": "Allow", "NotAction": "iam:*", "Resource": "*"}))]
    assert evaluate(notact, "s3:DeleteObject", "x").allowed and not evaluate(notact, "iam:CreateUser", "x").allowed
    cond = [("c", doc({**allow("s3:*"), "Condition": {"Bool": {"aws:SecureTransport": "true"}}}))]
    d = evaluate(cond, "s3:GetObject", "x")
    assert not d.allowed and d.skipped_conditions == ["c"]
    single = [("s", {"Statement": allow("s3:GetObject", "arn:aws:s3:::b?/*")})]  # single statement dict + ?
    assert evaluate(single, "s3:GetObject", "arn:aws:s3:::b1/x").allowed


def test_parse_document_variants():
    d = doc(allow("s3:*"))
    assert parse_document(d) == d
    assert parse_document(json.dumps(d)) == d
    from urllib.parse import quote
    assert parse_document(quote(json.dumps(d))) == d


def test_principal_policies_include_groups():
    ev = {"users": {"u": {"groups": ["g"], "attached": [], "inline": {"i": doc(allow("a:B"))}}},
          "groups": {"g": {"attached": ["arn:p"], "inline": {}}}, "roles": {},
          "policies": {"arn:p": {"name": "p", "document": doc(allow("c:D")), "aws_managed": False}}}
    names = [n for n, _ in principal_policies(ev, "user:u")]
    assert names == ["inline:i", "p"] and principal_policies(ev, "user:nobody") is None


# ------------------------------------------------------------------------------------ grading
def _ev(policy_doc, attach_to="group") -> dict:
    arn = "arn:aws:iam::123456789012:policy/menu-read-alice1"
    grp_att = [arn] if attach_to == "group" else []
    usr_att = [arn] if attach_to == "user" else []
    return {"format": 1, "captured_at": "x", "collectors": {"iam": {
        "users": {"barista-alice1": {"groups": ["baristas-alice1"], "attached": usr_att, "inline": {}}},
        "groups": {"baristas-alice1": {"attached": grp_att, "inline": {}}}, "roles": {},
        "policies": {arn: {"name": "menu-read-alice1", "document": policy_doc, "aws_managed": False}}}}}


def _grade(evidence):
    d = load_pack(LAB).definition
    return grade(d, compute_variables(d, "alice1"), evidence)


def test_lab_scores():
    assert _grade({"format": 1, "collectors": {"iam": {}}})["score"] == Decimal("0.00")
    good = doc(allow("s3:GetObject", "arn:aws:s3:::cafe-alice1-site/*"))
    assert _grade(_ev(good))["score"] == Decimal("100.00")
    assert _grade(_ev(doc(allow("s3:*"))))["score"] == Decimal("70.00")
    # attached to the user instead of the group: the attachment check fails
    r = _grade(_ev(good, attach_to="user"))
    t3 = next(t for t in r["tasks"] if t["task_id"] == "read-policy")
    assert not t3["passed"] and "should be attached to group" in t3["checks"][0]["message"]
    # read-everything managed-style policy fails the payroll check
    r = _grade(_ev(doc(allow(["s3:Get*", "s3:List*"]))))
    t4 = next(t for t in r["tasks"] if t["task_id"] == "least-privilege")
    assert not t4["passed"] and "payroll" in str(t4["checks"])


# ------------------------------------------------------------------------------- console API
async def iam_assignment(world) -> Assignment:
    async with sessionmaker()() as db:
        lv, _ = await import_package(db, load_pack(LAB))
        now = st.now()
        a = Assignment(course_id=world.course.id, lab_version_id=lv.id, title="IAM", open_at=now - timedelta(hours=1),
                       due_at=now + timedelta(days=1), close_at=now + timedelta(days=2), max_attempts=3)
        db.add(a)
        await db.commit()
        return a


async def test_iam_console_journey_and_simulator(world, fake_runner):
    a = await iam_assignment(world)
    c = await login(world.alice)
    sid = (await c.post(f"/api/assignments/{a.id}/sessions")).json()["id"]
    await wait_state(c, sid, {"READY"})
    base = f"/api/sessions/{sid}/console/iam"

    assert (await c.post(f"{base}/groups", json={"name": "baristas-alice1"})).status_code == 201
    r = await c.post(f"{base}/users", json={"name": "barista-alice1", "groups": ["baristas-alice1"]})
    assert r.status_code == 201, r.text
    assert (await c.post(f"{base}/policies", json={"name": "bad", "document": "{not json"})).json()["error"]["code"] == "invalid_policy"
    pol = json.dumps(doc(allow("s3:GetObject", "arn:aws:s3:::cafe-alice1-site/*")))
    arn = (await c.post(f"{base}/policies", json={"name": "menu-read-alice1", "document": pol})).json()["arn"]
    assert (await c.post(f"{base}/groups/baristas-alice1/policies", json={"arn": arn})).status_code == 200

    aws = (await c.get(f"{base}/policies?scope=aws&search=S3ReadOnly")).json()["policies"]
    assert any(p["name"] == "AmazonS3ReadOnlyAccess" and p["type"] == "AWS managed" for p in aws)
    local = (await c.get(f"{base}/policies?scope=local")).json()["policies"]
    assert [p["name"] for p in local] == ["menu-read-alice1"]
    p = (await c.get(f"{base}/policy", params={"arn": arn})).json()
    assert p["document"]["Statement"][0]["Action"] == "s3:GetObject"
    u = (await c.get(f"{base}/users/barista-alice1")).json()
    assert u["groups"] == ["baristas-alice1"] and u["attached"] == []
    g = (await c.get(f"{base}/groups/baristas-alice1")).json()
    assert g["users"] == ["barista-alice1"] and g["attached"][0]["name"] == "menu-read-alice1"

    sim = (await c.post(f"{base}/simulate", json={"principal": "user:barista-alice1",
                                                   "actions": ["s3:GetObject", "s3:DeleteObject"],
                                                   "resource": "arn:aws:s3:::cafe-alice1-site/menu.html"})).json()
    assert [x["decision"] for x in sim["results"]] == ["allowed", "implicit_deny"]
    assert sim["results"][0]["matched_policies"] == ["menu-read-alice1"]

    r = await c.post(f"{base}/roles", json={"name": "fn-role", "service": "lambda"})
    assert r.status_code == 201
    roles = (await c.get(f"{base}/roles")).json()["roles"]
    assert roles[0]["trusted"] == ["lambda.amazonaws.com"]

    prog = await c.post(f"/api/sessions/{sid}/progress")
    assert prog.json()["score"] == "100.00", prog.text

    # deleting a user cleans memberships first (AWS console behaviour)
    assert (await c.delete(f"{base}/users/barista-alice1")).status_code == 204
    assert (await c.get(f"{base}/users")).json()["users"] == []
    # ownership + freeze
    bob = await login(world.bob)
    assert (await bob.get(f"{base}/users")).status_code == 404
    assert (await c.post(f"/api/sessions/{sid}/submit", headers=idem())).status_code == 200
    assert (await c.get(f"{base}/users")).status_code == 409


# ------------------------------------------------------------------------------ real runtime
POL = json.dumps(doc(allow("s3:GetObject", "arn:aws:s3:::menu/*")))
TRUST = json.dumps(doc({"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}))
MANAGED = "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"


def iam_contract(c) -> dict:
    s: dict = {}

    def arn():
        return s["arn"]
    return {
        "CreateUser": lambda: c.create_user(UserName="dev1"),
        "GetUser": lambda: c.get_user(UserName="dev1"),
        "ListUsers": lambda: [u["UserName"] for u in c.list_users()["Users"]] == ["dev1"] or 1 / 0,
        "CreateGroup": lambda: c.create_group(GroupName="devs"),
        "GetGroup": lambda: c.get_group(GroupName="devs"),
        "ListGroups": lambda: len(c.list_groups()["Groups"]) == 1 or 1 / 0,
        "AddUserToGroup": lambda: c.add_user_to_group(GroupName="devs", UserName="dev1"),
        "ListGroupsForUser": lambda: c.list_groups_for_user(UserName="dev1")["Groups"][0]["GroupName"] == "devs" or 1 / 0,
        "CreatePolicy": lambda: s.__setitem__("arn", c.create_policy(PolicyName="p", PolicyDocument=POL)["Policy"]["Arn"]),
        "GetPolicy": lambda: c.get_policy(PolicyArn=MANAGED)["Policy"]["PolicyName"] == "AmazonS3ReadOnlyAccess" or 1 / 0,
        "GetPolicyVersion": lambda: "Statement" in parse_document(c.get_policy_version(
            PolicyArn=arn(), VersionId="v1")["PolicyVersion"]["Document"]) or 1 / 0,
        "ListPolicies": lambda: len(c.list_policies(Scope="Local")["Policies"]) == 1 or 1 / 0,
        "AttachUserPolicy": lambda: c.attach_user_policy(UserName="dev1", PolicyArn=MANAGED),
        "ListAttachedUserPolicies": lambda: len(c.list_attached_user_policies(UserName="dev1")["AttachedPolicies"]) == 1 or 1 / 0,
        "DetachUserPolicy": lambda: c.detach_user_policy(UserName="dev1", PolicyArn=MANAGED),
        "AttachGroupPolicy": lambda: c.attach_group_policy(GroupName="devs", PolicyArn=arn()),
        "ListAttachedGroupPolicies": lambda: len(c.list_attached_group_policies(GroupName="devs")["AttachedPolicies"]) == 1 or 1 / 0,
        "DetachGroupPolicy": lambda: c.detach_group_policy(GroupName="devs", PolicyArn=arn()),
        "PutUserPolicy": lambda: c.put_user_policy(UserName="dev1", PolicyName="i", PolicyDocument=POL),
        "ListUserPolicies": lambda: c.list_user_policies(UserName="dev1")["PolicyNames"] == ["i"] or 1 / 0,
        "GetUserPolicy": lambda: "Statement" in parse_document(c.get_user_policy(UserName="dev1", PolicyName="i")["PolicyDocument"]) or 1 / 0,
        "DeleteUserPolicy": lambda: c.delete_user_policy(UserName="dev1", PolicyName="i"),
        "PutGroupPolicy": lambda: c.put_group_policy(GroupName="devs", PolicyName="gi", PolicyDocument=POL),
        "ListGroupPolicies": lambda: c.list_group_policies(GroupName="devs")["PolicyNames"] == ["gi"] or 1 / 0,
        "GetGroupPolicy": lambda: "Statement" in parse_document(c.get_group_policy(GroupName="devs", PolicyName="gi")["PolicyDocument"]) or 1 / 0,
        "DeleteGroupPolicy": lambda: c.delete_group_policy(GroupName="devs", PolicyName="gi"),
        "CreateRole": lambda: c.create_role(RoleName="r", AssumeRolePolicyDocument=TRUST),
        "GetRole": lambda: "Statement" in parse_document(c.get_role(RoleName="r")["Role"]["AssumeRolePolicyDocument"]) or 1 / 0,
        "ListRoles": lambda: "r" in [x["RoleName"] for x in c.list_roles()["Roles"]] or 1 / 0,
        "AttachRolePolicy": lambda: c.attach_role_policy(RoleName="r", PolicyArn=arn()),
        "ListAttachedRolePolicies": lambda: len(c.list_attached_role_policies(RoleName="r")["AttachedPolicies"]) == 1 or 1 / 0,
        "DetachRolePolicy": lambda: c.detach_role_policy(RoleName="r", PolicyArn=arn()),
        "PutRolePolicy": lambda: c.put_role_policy(RoleName="r", PolicyName="ri", PolicyDocument=POL),
        "ListRolePolicies": lambda: c.list_role_policies(RoleName="r")["PolicyNames"] == ["ri"] or 1 / 0,
        "GetRolePolicy": lambda: "Statement" in parse_document(c.get_role_policy(RoleName="r", PolicyName="ri")["PolicyDocument"]) or 1 / 0,
        "DeleteRolePolicy": lambda: c.delete_role_policy(RoleName="r", PolicyName="ri"),
        "DeleteRole": lambda: c.delete_role(RoleName="r"),
        "DeletePolicy": lambda: c.delete_policy(PolicyArn=arn()),
        "RemoveUserFromGroup": lambda: c.remove_user_from_group(GroupName="devs", UserName="dev1"),
        "DeleteGroup": lambda: c.delete_group(GroupName="devs"),
        "DeleteUser": lambda: c.delete_user(UserName="dev1"),
    }


@pytest.mark.docker
@pytest.mark.parametrize("contract_engine", emulators.ENGINES)
async def test_iam_contract_for_every_declared_supported_operation(real_runner, contract_engine):
    import asyncio
    caps = emulators.get(contract_engine).capabilities
    declared = {op for op, o in caps.services["iam"].items() if o.level == "supported"}
    sid = str(uuid.uuid4())
    info = await real_runner.create_sandbox({"sandbox_id": sid, "env": get_settings().env, "engine": contract_engine,
                                             "terminal_credential": "contract:abcdefgh1234"})
    try:
        c = emulators.get(contract_engine).client("iam", info["emulator_endpoint"])
        ops = iam_contract(c)
        assert declared == set(ops), declared ^ set(ops)
        for name, fn in ops.items():
            try:
                await asyncio.to_thread(fn)
            except Exception as e:  # pragma: no cover - diagnostic
                raise AssertionError(f"{contract_engine}: {name} failed: {e}") from e
    finally:
        await real_runner.destroy_sandbox(sid)


@pytest.mark.docker
@pytest.mark.parametrize("lab_engine", emulators.ENGINES)
async def test_iam_labtest_on_every_engine(real_runner, lab_engine):
    from app.labtest import check_pack
    results = await check_pack(LAB, real_runner, engine=lab_engine)
    assert [(r.name, str(r.actual)) for r in results] == [
        (f"{lab_engine}/empty", "0.00"), (f"{lab_engine}/partial", "70.00"), (f"{lab_engine}/solution", "100.00")], \
        [(r.name, r.actual, r.detail) for r in results]
