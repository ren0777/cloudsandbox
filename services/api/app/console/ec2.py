"""Student EC2 console API (AWS-style: Instances + Launch instance, Security Groups, Key Pairs).
Instances are simulated records in the student's emulator: they have state, type, key pair, security
groups and tags, but no running machine (connecting is labelled unsupported)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.policy import Action, AuthzAny
from ..db import get_db
from ..errors import ApiError
from ..models import LabSession, User
from .common import aws_call, console_session

router = APIRouter(prefix="/api/sessions/{session_id}/console/ec2", tags=["console"])
INSTANCE_TYPES = ["t2.micro", "t3.micro", "t3.small", "t3.medium", "m5.large"]
FREE_TIER = {"t2.micro", "t3.micro"}
CIDR = r"^\d{1,3}(\.\d{1,3}){3}/\d{1,2}$"
NAME = Field(min_length=1, max_length=255, pattern=r"^[\w .:/()#,@\[\]+=&;{}!$*-]+$")


async def _call(sess: LabSession, fn: str, **kw: Any) -> dict:
    return await aws_call(sess, "ec2", fn, **kw)


class RuleIn(BaseModel):
    protocol: Literal["tcp", "udp", "icmp", "-1"] = "tcp"
    from_port: int = Field(ge=-1, le=65535)
    to_port: int = Field(ge=-1, le=65535)
    cidr: str = Field(pattern=CIDR)
    description: str = Field("", max_length=255)


class TagIn(BaseModel):
    key: str = Field(min_length=1, max_length=128)
    value: str = Field("", max_length=256)


class NewSgIn(BaseModel):
    name: str = NAME
    ssh_cidr: str | None = Field(None, pattern=CIDR)
    http: bool = False
    https: bool = False


class LaunchIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    image_id: str = Field(min_length=4, max_length=64)
    instance_type: str
    key_name: str | None = None
    security_group_ids: list[str] = Field(default_factory=list, max_length=5)
    create_security_group: NewSgIn | None = None
    tags: list[TagIn] = Field(default_factory=list, max_length=40)

    @model_validator(mode="after")
    def _check(self) -> "LaunchIn":
        if self.instance_type not in INSTANCE_TYPES:
            raise ValueError(f"instance type must be one of {', '.join(INSTANCE_TYPES)}")
        return self


class StateIn(BaseModel):
    action: Literal["start", "stop", "terminate"]


class CreateSgIn(BaseModel):
    name: str = NAME
    description: str = Field(min_length=1, max_length=255)
    rules: list[RuleIn] = Field(default_factory=list, max_length=50)


class RulesIn(BaseModel):
    rules: list[RuleIn] = Field(max_length=50)


class TagsIn(BaseModel):
    tags: list[TagIn] = Field(max_length=40)


class KeyPairIn(BaseModel):
    name: str = NAME
    key_type: Literal["rsa", "ed25519"] = "rsa"


def _perm(r: RuleIn) -> dict[str, Any]:
    p: dict[str, Any] = {"IpProtocol": r.protocol, "IpRanges": [{"CidrIp": r.cidr, **({"Description": r.description} if r.description else {})}]}
    if r.protocol != "-1":
        p["FromPort"], p["ToPort"] = r.from_port, r.to_port
    return p


def _rules_out(perms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"protocol": str(p.get("IpProtocol", "-1")), "from_port": p.get("FromPort"), "to_port": p.get("ToPort"),
             "cidr": rng.get("CidrIp"), "description": rng.get("Description", "")}
            for p in perms for rng in p.get("IpRanges", [])]


async def _default_vpc(sess: LabSession) -> tuple[str, str | None]:
    vpcs = (await _call(sess, "describe_vpcs", Filters=[{"Name": "isDefault", "Values": ["true"]}])).get("Vpcs", [])
    if not vpcs:
        raise ApiError("no_default_vpc", "This sandbox has no default VPC.", 409)
    vpc = vpcs[0]["VpcId"]
    subnets = (await _call(sess, "describe_subnets", Filters=[{"Name": "vpc-id", "Values": [vpc]}])).get("Subnets", [])
    return vpc, (sorted(subnets, key=lambda s: s.get("AvailabilityZone", ""))[0]["SubnetId"] if subnets else None)


def _instance_out(i: dict[str, Any]) -> dict[str, Any]:
    tags = {t["Key"]: t["Value"] for t in i.get("Tags", [])}
    return {"id": i["InstanceId"], "name": tags.get("Name", ""), "state": i["State"]["Name"],
            "type": i.get("InstanceType"), "image_id": i.get("ImageId"), "key_name": i.get("KeyName"),
            "security_groups": [{"id": g.get("GroupId"), "name": g.get("GroupName")} for g in i.get("SecurityGroups", [])],
            "private_ip": i.get("PrivateIpAddress"), "launched_at": i.get("LaunchTime"),
            "tags": [{"key": k, "value": v} for k, v in sorted(tags.items())]}


# ------------------------------------------------------------------------------------ catalogue
@router.get("/launch-options")
async def launch_options(session_id: uuid.UUID, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                         db: AsyncSession = Depends(get_db)):
    """Quick Start images (whatever the engine offers, Linux first), instance types, key pairs, groups."""
    sess = await console_session(session_id, user, db)
    images = (await _call(sess, "describe_images", Owners=["amazon"])).get("Images", [])

    def rank(img: dict) -> tuple:
        n = (img.get("Name") or "").lower()
        return (0 if ("amzn" in n or "al2023" in n) else 1 if ("ubuntu" in n or "debian" in n) else 2
                if "windows" not in n else 3, n)
    quick = [{"id": i["ImageId"], "name": i.get("Name") or i["ImageId"], "description": i.get("Description", ""),
              "platform": "Windows" if "windows" in (i.get("Name") or "").lower() else "Linux"}
             for i in sorted(images, key=rank)[:8]]
    keys = [k["KeyName"] for k in (await _call(sess, "describe_key_pairs")).get("KeyPairs", [])]
    groups = [{"id": g["GroupId"], "name": g["GroupName"]} for g in (await _call(sess, "describe_security_groups")).get("SecurityGroups", [])]
    vpc, subnet = await _default_vpc(sess)
    return {"images": quick, "instance_types": [{"name": t, "free_tier": t in FREE_TIER} for t in INSTANCE_TYPES],
            "key_pairs": keys, "security_groups": groups, "vpc_id": vpc, "subnet_id": subnet}


# ------------------------------------------------------------------------------------ instances
@router.get("/instances")
async def list_instances(session_id: uuid.UUID, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                         db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    out = []
    for r in (await _call(sess, "describe_instances")).get("Reservations", []):
        out += [_instance_out(i) for i in r.get("Instances", [])]
    out.sort(key=lambda i: (i["state"] == "terminated", i["name"], i["id"]))
    return {"instances": out}


@router.post("/instances", status_code=201)
async def launch_instance(session_id: uuid.UUID, body: LaunchIn, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                          db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    vpc, subnet = await _default_vpc(sess)
    sg_ids = list(body.security_group_ids)
    if body.create_security_group:
        n = body.create_security_group
        sg = (await _call(sess, "create_security_group", GroupName=n.name, Description=f"{n.name} created by launch-wizard",
                          VpcId=vpc))["GroupId"]
        perms = []
        if n.ssh_cidr:
            perms.append(_perm(RuleIn(from_port=22, to_port=22, cidr=n.ssh_cidr, description="SSH")))
        if n.http:
            perms.append(_perm(RuleIn(from_port=80, to_port=80, cidr="0.0.0.0/0", description="HTTP")))
        if n.https:
            perms.append(_perm(RuleIn(from_port=443, to_port=443, cidr="0.0.0.0/0", description="HTTPS")))
        if perms:
            await _call(sess, "authorize_security_group_ingress", GroupId=sg, IpPermissions=perms)
        sg_ids.append(sg)
    tags = [{"Key": "Name", "Value": body.name}] + [{"Key": t.key, "Value": t.value} for t in body.tags
                                                    if t.key.strip() and t.key != "Name"]
    kw: dict[str, Any] = {"ImageId": body.image_id, "InstanceType": body.instance_type, "MinCount": 1, "MaxCount": 1,
                          "TagSpecifications": [{"ResourceType": "instance", "Tags": tags}]}
    if body.key_name:
        kw["KeyName"] = body.key_name
    if sg_ids:
        kw["SecurityGroupIds"] = sg_ids
    if subnet:
        kw["SubnetId"] = subnet
    inst = (await _call(sess, "run_instances", **kw))["Instances"][0]
    return {"id": inst["InstanceId"]}


@router.get("/instances/{instance_id}")
async def get_instance(session_id: uuid.UUID, instance_id: str, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                       db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    res = (await _call(sess, "describe_instances", InstanceIds=[instance_id])).get("Reservations", [])
    if not res or not res[0].get("Instances"):
        raise ApiError("aws_error", "Instance not found", 400, extra={"aws_code": "InvalidInstanceID.NotFound"})
    return _instance_out(res[0]["Instances"][0])


@router.post("/instances/{instance_id}/state")
async def change_state(session_id: uuid.UUID, instance_id: str, body: StateIn,
                       user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)), db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    fn = {"start": "start_instances", "stop": "stop_instances", "terminate": "terminate_instances"}[body.action]
    await _call(sess, fn, InstanceIds=[instance_id])
    return {"action": body.action}


@router.put("/instances/{instance_id}/tags")
async def set_instance_tags(session_id: uuid.UUID, instance_id: str, body: TagsIn,
                            user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)), db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    tags = [{"Key": t.key, "Value": t.value} for t in body.tags if t.key.strip()]
    if tags:
        await _call(sess, "create_tags", Resources=[instance_id], Tags=tags)
    return {"tags": [t.model_dump() for t in body.tags]}


# ------------------------------------------------------------------------------ security groups
@router.get("/security-groups")
async def list_security_groups(session_id: uuid.UUID, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                               db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    groups = (await _call(sess, "describe_security_groups")).get("SecurityGroups", [])
    return {"security_groups": [{"id": g["GroupId"], "name": g["GroupName"], "description": g.get("Description", ""),
                                 "vpc_id": g.get("VpcId"), "inbound_rules": len(_rules_out(g.get("IpPermissions", [])))}
                                for g in sorted(groups, key=lambda g: g["GroupName"])]}


@router.post("/security-groups", status_code=201)
async def create_security_group(session_id: uuid.UUID, body: CreateSgIn, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                                db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    vpc, _ = await _default_vpc(sess)
    gid = (await _call(sess, "create_security_group", GroupName=body.name, Description=body.description, VpcId=vpc))["GroupId"]
    if body.rules:
        await _call(sess, "authorize_security_group_ingress", GroupId=gid, IpPermissions=[_perm(r) for r in body.rules])
    return {"id": gid}


@router.get("/security-groups/{group_id}")
async def get_security_group(session_id: uuid.UUID, group_id: str, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                             db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    g = (await _call(sess, "describe_security_groups", GroupIds=[group_id]))["SecurityGroups"][0]
    return {"id": g["GroupId"], "name": g["GroupName"], "description": g.get("Description", ""), "vpc_id": g.get("VpcId"),
            "inbound_rules": _rules_out(g.get("IpPermissions", []))}


@router.put("/security-groups/{group_id}/inbound-rules")
async def set_inbound_rules(session_id: uuid.UUID, group_id: str, body: RulesIn,
                            user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)), db: AsyncSession = Depends(get_db)):
    """AWS 'Edit inbound rules' → 'Save rules': revoke removed rules, authorize new ones."""
    sess = await console_session(session_id, user, db)
    g = (await _call(sess, "describe_security_groups", GroupIds=[group_id]))["SecurityGroups"][0]

    def key(r: dict) -> tuple:
        proto = str(r["protocol"])
        return (proto, None if proto == "-1" else r["from_port"], None if proto == "-1" else r["to_port"], r["cidr"])
    current = {key(r): r for r in _rules_out(g.get("IpPermissions", []))}
    wanted = {key(r.model_dump()): r for r in body.rules}
    removed = [k for k in current if k not in wanted]
    added = [wanted[k] for k in wanted if k not in current]
    if removed:
        await _call(sess, "revoke_security_group_ingress", GroupId=group_id, IpPermissions=[
            _perm(RuleIn(protocol=k[0], from_port=k[1] if k[1] is not None else -1, to_port=k[2] if k[2] is not None else -1, cidr=k[3]))
            for k in removed])
    if added:
        await _call(sess, "authorize_security_group_ingress", GroupId=group_id, IpPermissions=[_perm(r) for r in added])
    return {"added": len(added), "removed": len(removed)}


@router.delete("/security-groups/{group_id}", status_code=204)
async def delete_security_group(session_id: uuid.UUID, group_id: str, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                                db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    await _call(sess, "delete_security_group", GroupId=group_id)


# ---------------------------------------------------------------------------------- key pairs
@router.get("/key-pairs")
async def list_key_pairs(session_id: uuid.UUID, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                         db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    return {"key_pairs": [{"name": k["KeyName"], "fingerprint": k.get("KeyFingerprint", ""), "type": k.get("KeyType", "rsa")}
                          for k in (await _call(sess, "describe_key_pairs")).get("KeyPairs", [])]}


@router.post("/key-pairs", status_code=201)
async def create_key_pair(session_id: uuid.UUID, body: KeyPairIn, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                          db: AsyncSession = Depends(get_db)):
    """Returns the private key once, like AWS (it's only a training key for a simulated instance)."""
    sess = await console_session(session_id, user, db)
    out = await _call(sess, "create_key_pair", KeyName=body.name, KeyType=body.key_type)
    return {"name": body.name, "private_key": out.get("KeyMaterial", "")}


@router.delete("/key-pairs/{name}", status_code=204)
async def delete_key_pair(session_id: uuid.UUID, name: str, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                          db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    await _call(sess, "delete_key_pair", KeyName=name)
