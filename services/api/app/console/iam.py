"""Student IAM console API (AWS-style: User groups, Users, Roles, Policies, Policy simulator).
Acts on the student's own emulator through the EmulatorAdapter. The policy simulator is `simulated`:
CloudLabs evaluates the live policies with its own evaluator (grader/iam_eval.py)."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.policy import Action, AuthzAny
from ..db import get_db
from ..errors import ApiError
from ..grader.evidence import collect_iam
from ..grader.iam_eval import evaluate, parse_document, principal_policies
from ..models import LabSession, User
from ..runtime import emulators
from .common import aws_call, console_session

router = APIRouter(prefix="/api/sessions/{session_id}/console/iam", tags=["console"])
NAME = Field(min_length=1, max_length=64, pattern=r"^[\w+=,.@-]+$")
TRUSTED_SERVICES = {"lambda": "lambda.amazonaws.com", "ec2": "ec2.amazonaws.com"}


async def _call(sess: LabSession, fn: str, **kw: Any) -> dict:
    return await aws_call(sess, "iam", fn, **kw)


async def _pages(sess: LabSession, fn: str, key: str, **kw: Any) -> list[Any]:
    out: list[Any] = []
    while True:
        page = await _call(sess, fn, **kw)
        out += page.get(key, [])
        if not page.get("IsTruncated"):
            return out
        kw["Marker"] = page["Marker"]


def _policy_doc(text: str) -> dict[str, Any]:
    try:
        doc = json.loads(text)
    except ValueError:
        raise ApiError("invalid_policy", "The policy document must be valid JSON.", 400) from None
    if not isinstance(doc, dict) or "Statement" not in doc:
        raise ApiError("invalid_policy", "A policy document needs a Version and at least one Statement.", 400)
    return doc


class TagIn(BaseModel):
    key: str = Field(min_length=1, max_length=128)
    value: str = Field("", max_length=256)


class CreateUserIn(BaseModel):
    name: str = NAME
    groups: list[str] = Field(default_factory=list, max_length=10)
    policy_arns: list[str] = Field(default_factory=list, max_length=10)
    tags: list[TagIn] = Field(default_factory=list, max_length=50)


class CreateGroupIn(BaseModel):
    name: str = NAME
    policy_arns: list[str] = Field(default_factory=list, max_length=10)


class CreateRoleIn(BaseModel):
    name: str = NAME
    service: Literal["lambda", "ec2"]
    policy_arns: list[str] = Field(default_factory=list, max_length=10)
    description: str = Field("", max_length=1000)


class CreatePolicyIn(BaseModel):
    name: str = NAME
    document: str = Field(min_length=2, max_length=6144)
    description: str = Field("", max_length=1000)


class ArnIn(BaseModel):
    arn: str = Field(min_length=20, max_length=2048)


class GroupsIn(BaseModel):
    groups: list[str] = Field(max_length=10)


class SimulateIn(BaseModel):
    principal: str = Field(pattern=r"^(user|group|role):[\w+=,.@-]{1,128}$")
    actions: list[str] = Field(min_length=1, max_length=20)
    resource: str = Field("*", min_length=1, max_length=2048)


async def _attached(sess: LabSession, kind: str, name: str) -> list[dict[str, str]]:
    fn = {"user": "list_attached_user_policies", "group": "list_attached_group_policies",
          "role": "list_attached_role_policies"}[kind]
    who = {"user": "UserName", "group": "GroupName", "role": "RoleName"}[kind]
    return [{"name": p["PolicyName"], "arn": p["PolicyArn"]}
            for p in await _pages(sess, fn, "AttachedPolicies", **{who: name})]


# ------------------------------------------------------------------------------------------ users
@router.get("/users")
async def list_users(session_id: uuid.UUID, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                     db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    out = []
    for u in await _pages(sess, "list_users", "Users"):
        groups = await _pages(sess, "list_groups_for_user", "Groups", UserName=u["UserName"])
        out.append({"name": u["UserName"], "arn": u["Arn"], "groups": [g["GroupName"] for g in groups],
                    "created_at": u.get("CreateDate")})
    return {"users": out}


@router.post("/users", status_code=201)
async def create_user(session_id: uuid.UUID, body: CreateUserIn, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                      db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    kw: dict[str, Any] = {"UserName": body.name}
    tags = [{"Key": t.key, "Value": t.value} for t in body.tags if t.key.strip()]
    if tags:
        kw["Tags"] = tags
    await _call(sess, "create_user", **kw)
    for g in body.groups:
        await _call(sess, "add_user_to_group", GroupName=g, UserName=body.name)
    for arn in body.policy_arns:
        await _call(sess, "attach_user_policy", UserName=body.name, PolicyArn=arn)
    return {"name": body.name}


@router.get("/users/{name}")
async def get_user(session_id: uuid.UUID, name: str, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                   db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    u = (await _call(sess, "get_user", UserName=name))["User"]
    groups = await _pages(sess, "list_groups_for_user", "Groups", UserName=name)
    inline = await _pages(sess, "list_user_policies", "PolicyNames", UserName=name)
    return {"name": name, "arn": u["Arn"], "created_at": u.get("CreateDate"),
            "groups": [g["GroupName"] for g in groups], "attached": await _attached(sess, "user", name),
            "inline": inline}


@router.put("/users/{name}/groups")
async def set_user_groups(session_id: uuid.UUID, name: str, body: GroupsIn,
                          user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)), db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    current = {g["GroupName"] for g in await _pages(sess, "list_groups_for_user", "Groups", UserName=name)}
    for g in sorted(set(body.groups) - current):
        await _call(sess, "add_user_to_group", GroupName=g, UserName=name)
    for g in sorted(current - set(body.groups)):
        await _call(sess, "remove_user_from_group", GroupName=g, UserName=name)
    return {"groups": sorted(body.groups)}


@router.delete("/users/{name}", status_code=204)
async def delete_user(session_id: uuid.UUID, name: str, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                      db: AsyncSession = Depends(get_db)):
    """Like the AWS console: removes memberships and policies first, then the user."""
    sess = await console_session(session_id, user, db)
    for g in await _pages(sess, "list_groups_for_user", "Groups", UserName=name):
        await _call(sess, "remove_user_from_group", GroupName=g["GroupName"], UserName=name)
    for p in await _attached(sess, "user", name):
        await _call(sess, "detach_user_policy", UserName=name, PolicyArn=p["arn"])
    for pn in await _pages(sess, "list_user_policies", "PolicyNames", UserName=name):
        await _call(sess, "delete_user_policy", UserName=name, PolicyName=pn)
    await _call(sess, "delete_user", UserName=name)


# ------------------------------------------------------------------------------------- groups
@router.get("/groups")
async def list_groups(session_id: uuid.UUID, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                      db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    out = []
    for g in await _pages(sess, "list_groups", "Groups"):
        members = (await _call(sess, "get_group", GroupName=g["GroupName"])).get("Users", [])
        out.append({"name": g["GroupName"], "arn": g["Arn"], "users": len(members),
                    "policies": len(await _attached(sess, "group", g["GroupName"])), "created_at": g.get("CreateDate")})
    return {"groups": out}


@router.post("/groups", status_code=201)
async def create_group(session_id: uuid.UUID, body: CreateGroupIn, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                       db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    await _call(sess, "create_group", GroupName=body.name)
    for arn in body.policy_arns:
        await _call(sess, "attach_group_policy", GroupName=body.name, PolicyArn=arn)
    return {"name": body.name}


@router.get("/groups/{name}")
async def get_group(session_id: uuid.UUID, name: str, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                    db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    g = await _call(sess, "get_group", GroupName=name)
    return {"name": name, "arn": g["Group"]["Arn"], "users": [u["UserName"] for u in g.get("Users", [])],
            "attached": await _attached(sess, "group", name)}


@router.delete("/groups/{name}", status_code=204)
async def delete_group(session_id: uuid.UUID, name: str, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                       db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    for u in (await _call(sess, "get_group", GroupName=name)).get("Users", []):
        await _call(sess, "remove_user_from_group", GroupName=name, UserName=u["UserName"])
    for p in await _attached(sess, "group", name):
        await _call(sess, "detach_group_policy", GroupName=name, PolicyArn=p["arn"])
    for pn in await _pages(sess, "list_group_policies", "PolicyNames", GroupName=name):
        await _call(sess, "delete_group_policy", GroupName=name, PolicyName=pn)
    await _call(sess, "delete_group", GroupName=name)


# -------------------------------------------------------------------------------------- roles
@router.get("/roles")
async def list_roles(session_id: uuid.UUID, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                     db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    out = []
    for r in await _pages(sess, "list_roles", "Roles"):
        trust = parse_document(r.get("AssumeRolePolicyDocument", {}))
        services = sorted({s for st in trust.get("Statement", []) for s in
                           ([(st.get("Principal") or {}).get("Service")] if isinstance((st.get("Principal") or {}).get("Service"), str)
                            else (st.get("Principal") or {}).get("Service", []))})
        out.append({"name": r["RoleName"], "arn": r["Arn"], "trusted": services, "created_at": r.get("CreateDate")})
    return {"roles": out}


@router.post("/roles", status_code=201)
async def create_role(session_id: uuid.UUID, body: CreateRoleIn, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                      db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    trust = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "sts:AssumeRole",
                                                     "Principal": {"Service": TRUSTED_SERVICES[body.service]}}]}
    await _call(sess, "create_role", RoleName=body.name, AssumeRolePolicyDocument=json.dumps(trust),
                Description=body.description)
    for arn in body.policy_arns:
        await _call(sess, "attach_role_policy", RoleName=body.name, PolicyArn=arn)
    return {"name": body.name}


@router.get("/roles/{name}")
async def get_role(session_id: uuid.UUID, name: str, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                   db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    r = (await _call(sess, "get_role", RoleName=name))["Role"]
    return {"name": name, "arn": r["Arn"], "description": r.get("Description", ""),
            "trust": parse_document(r.get("AssumeRolePolicyDocument", {})), "attached": await _attached(sess, "role", name)}


@router.delete("/roles/{name}", status_code=204)
async def delete_role(session_id: uuid.UUID, name: str, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                      db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    for p in await _attached(sess, "role", name):
        await _call(sess, "detach_role_policy", RoleName=name, PolicyArn=p["arn"])
    for pn in await _pages(sess, "list_role_policies", "PolicyNames", RoleName=name):
        await _call(sess, "delete_role_policy", RoleName=name, PolicyName=pn)
    await _call(sess, "delete_role", RoleName=name)


# ------------------------------------------------------------ attach / detach (users, groups, roles)
_ATTACH = {"users": ("attach_user_policy", "detach_user_policy", "UserName"),
           "groups": ("attach_group_policy", "detach_group_policy", "GroupName"),
           "roles": ("attach_role_policy", "detach_role_policy", "RoleName")}


@router.post("/{kind}/{name}/policies")
async def attach_policy(session_id: uuid.UUID, kind: Literal["users", "groups", "roles"], name: str, body: ArnIn,
                        user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)), db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    fn, _, who = _ATTACH[kind]
    await _call(sess, fn, PolicyArn=body.arn, **{who: name})
    return {"attached": body.arn}


@router.delete("/{kind}/{name}/policies", status_code=204)
async def detach_policy(session_id: uuid.UUID, kind: Literal["users", "groups", "roles"], name: str,
                        arn: str = Query(..., min_length=20, max_length=2048),
                        user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)), db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    _, fn, who = _ATTACH[kind]
    await _call(sess, fn, PolicyArn=arn, **{who: name})


# ----------------------------------------------------------------------------------- policies
@router.get("/policies")
async def list_policies(session_id: uuid.UUID, scope: Literal["local", "aws", "all"] = "all",
                        search: str = Query("", max_length=128),
                        user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)), db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    out = []
    scopes = {"local": ["Local"], "aws": ["AWS"], "all": ["Local", "AWS"]}[scope]
    for sc in scopes:
        for p in await _pages(sess, "list_policies", "Policies", Scope=sc):
            if search.lower() in p["PolicyName"].lower():
                out.append({"name": p["PolicyName"], "arn": p["Arn"], "type": "Customer managed" if sc == "Local" else "AWS managed",
                            "attachments": p.get("AttachmentCount", 0)})
    out.sort(key=lambda x: (x["type"] != "Customer managed", x["name"].lower()))
    return {"policies": out[:100], "truncated": len(out) > 100}


@router.post("/policies", status_code=201)
async def create_policy(session_id: uuid.UUID, body: CreatePolicyIn, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                        db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    doc = _policy_doc(body.document)
    out = await _call(sess, "create_policy", PolicyName=body.name, PolicyDocument=json.dumps(doc),
                      Description=body.description)
    return {"name": body.name, "arn": out["Policy"]["Arn"]}


@router.get("/policy")
async def get_policy(session_id: uuid.UUID, arn: str = Query(..., min_length=20, max_length=2048),
                     user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)), db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    meta = (await _call(sess, "get_policy", PolicyArn=arn))["Policy"]
    doc = (await _call(sess, "get_policy_version", PolicyArn=arn, VersionId=meta["DefaultVersionId"]))["PolicyVersion"]["Document"]
    return {"name": meta["PolicyName"], "arn": arn, "description": meta.get("Description", ""),
            "type": "AWS managed" if arn.startswith("arn:aws:iam::aws:") else "Customer managed",
            "attachments": meta.get("AttachmentCount", 0), "document": parse_document(doc)}


@router.delete("/policy", status_code=204)
async def delete_policy(session_id: uuid.UUID, arn: str = Query(..., min_length=20, max_length=2048),
                        user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)), db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    await _call(sess, "delete_policy", PolicyArn=arn)


# ---------------------------------------------------------------------------- policy simulator
@router.post("/simulate")
async def simulate(session_id: uuid.UUID, body: SimulateIn, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                   db: AsyncSession = Depends(get_db)):
    """CloudLabs policy simulator (support level `simulated`)."""
    sess = await console_session(session_id, user, db)
    adapter = emulators.get(sess.engine)
    evidence = await asyncio.to_thread(collect_iam, adapter, sess.emulator_endpoint or "")
    pols = principal_policies(evidence, body.principal)
    if pols is None:
        raise ApiError("aws_error", f"{body.principal} was not found", 400, extra={"aws_code": "NoSuchEntity"})
    results = []
    for a in body.actions:
        d = evaluate(pols, a, body.resource)
        results.append({"action": a, "resource": body.resource, "decision": d.decision,
                        "matched_policies": d.matched, "conditions_not_evaluated": sorted(set(d.skipped_conditions))})
    return {"results": results}
