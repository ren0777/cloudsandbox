"""Student VPC console API (AWS-style: Your VPCs, Subnets, Route tables, Internet gateways, Security groups).

VPC rides the EC2 API: the adapter maps the CloudLabs service name `vpc` to the boto3 `ec2` client, and
every call is capability-filtered against `vpc:*` for the session's engine (PLAN emulator strategy §6).
Resource names are `Name` tags; the console and the labs address resources by name, never by engine id."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.policy import Action, AuthzAny
from ..db import get_db
from ..errors import ApiError
from ..models import LabSession, User
from .common import aws_call, console_session

router = APIRouter(prefix="/api/sessions/{session_id}/console/vpc", tags=["console"])
CIDR = r"^\d{1,3}(\.\d{1,3}){3}/\d{1,2}$"
ID = Field(min_length=3, max_length=128)
NAME = Field(min_length=1, max_length=255, pattern=r"^[\w .:/()#,@\[\]+=&;{}!$*-]+$")


async def _call(sess: LabSession, fn: str, **kw: Any) -> dict:
    return await aws_call(sess, "vpc", fn, **kw)


async def _name(sess: LabSession, resource_id: str, name: str) -> None:
    """Tagging is a generic EC2 operation (already supported on every engine)."""
    await aws_call(sess, "ec2", "create_tags", Resources=[resource_id], Tags=[{"Key": "Name", "Value": name}])


def _tags(res: dict[str, Any]) -> dict[str, str]:
    return {t["Key"]: t["Value"] for t in res.get("Tags", [])}


def _name_of(res: dict[str, Any], fallback: str = "") -> str:
    return _tags(res).get("Name") or fallback


class VpcIn(BaseModel):
    name: str = NAME
    cidr: str = Field(pattern=CIDR)


class SubnetIn(BaseModel):
    vpc_id: str = Field(min_length=3, max_length=64)
    name: str = NAME
    cidr: str = Field(pattern=CIDR)
    az: str | None = Field(None, max_length=64)
    public: bool = False


class RouteTableIn(BaseModel):
    vpc_id: str = Field(min_length=3, max_length=64)
    name: str = NAME


class RouteIn(BaseModel):
    destination_cidr: str = Field(pattern=CIDR)
    target: Literal["internet_gateway"] = "internet_gateway"
    internet_gateway_id: str = Field(min_length=3, max_length=64)


class DestinationIn(BaseModel):
    destination_cidr: str = Field(pattern=CIDR)


class AssociateIn(BaseModel):
    subnet_id: str = Field(min_length=3, max_length=64)


class DisassociateIn(BaseModel):
    association_id: str = Field(min_length=3, max_length=64)


class InternetGatewayIn(BaseModel):
    name: str = NAME


class AttachIn(BaseModel):
    vpc_id: str = Field(min_length=3, max_length=64)


class CreateSgIn(BaseModel):
    vpc_id: str = Field(min_length=3, max_length=64)
    name: str = NAME
    description: str = Field("Managed by the Stackora console", max_length=255)


class RuleIn(BaseModel):
    protocol: Literal["tcp", "udp", "icmp", "-1"] = "tcp"
    from_port: int = Field(ge=-1, le=65535)
    to_port: int = Field(ge=-1, le=65535)
    cidr: str = Field(pattern=CIDR)
    description: str = Field("", max_length=255)


class SgRulesIn(BaseModel):
    ingress: list[RuleIn] = Field(default_factory=list, max_length=50)
    egress: list[RuleIn] = Field(default_factory=list, max_length=50)


def _perm(r: RuleIn) -> dict[str, Any]:
    p: dict[str, Any] = {"IpProtocol": r.protocol,
                         "IpRanges": [{"CidrIp": r.cidr, **({"Description": r.description} if r.description else {})}]}
    if r.protocol != "-1":
        p["FromPort"], p["ToPort"] = r.from_port, r.to_port
    return p


def _rules_out(perms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"protocol": str(p.get("IpProtocol", "-1")), "from_port": p.get("FromPort"), "to_port": p.get("ToPort"),
             "cidr": rng.get("CidrIp"), "description": rng.get("Description", "")}
            for p in perms for rng in p.get("IpRanges", [])]


def _rule_key(r: dict[str, Any]) -> tuple:
    proto = str(r["protocol"])
    return (proto, None if proto == "-1" else r.get("from_port"), None if proto == "-1" else r.get("to_port"), r["cidr"])


# ------------------------------------------------------------------------------------- overview
@router.get("/overview")
async def overview(session_id: uuid.UUID, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                   db: AsyncSession = Depends(get_db)):
    """One page load: VPCs with their subnets and route tables, internet gateways and security groups."""
    sess = await console_session(session_id, user, db)
    vpcs = (await _call(sess, "describe_vpcs")).get("Vpcs", [])
    subnets = (await _call(sess, "describe_subnets")).get("Subnets", [])
    route_tables = (await _call(sess, "describe_route_tables")).get("RouteTables", [])
    gateways = (await _call(sess, "describe_internet_gateways")).get("InternetGateways", [])
    groups = (await _call(sess, "describe_security_groups")).get("SecurityGroups", [])

    vpc_name = {v["VpcId"]: _name_of(v, v["VpcId"]) for v in vpcs}
    subnet_name = {s["SubnetId"]: _name_of(s, s["SubnetId"]) for s in subnets}
    gw_name = {g["InternetGatewayId"]: _name_of(g, g["InternetGatewayId"]) for g in gateways}

    def route_out(r: dict[str, Any]) -> dict[str, Any]:
        local = r.get("Origin") == "CreateRouteTable" or (not r.get("GatewayId") and not r.get("NatGatewayId"))
        target = r.get("GatewayId") or r.get("NatGatewayId") or "local"
        return {"destination": r.get("DestinationCidrBlock") or r.get("DestinationIpv6CidrBlock", ""),
                "target_kind": "local" if local else "internet_gateway",
                "target": "local" if local else f"igw:{gw_name.get(target, target)}",
                "state": r.get("State", "active")}

    def _named_first(res: dict[str, Any], resource_id: str) -> tuple:
        """Named (lab) resources sort before the unnamed defaults the engine pre-creates."""
        name = _name_of(res)
        return (not name, name, resource_id)

    return {
        "vpcs": [{"id": v["VpcId"], "name": _name_of(v), "cidr": v.get("CidrBlock"),
                  "is_default": bool(v.get("IsDefault")), "state": v.get("State", "available"),
                  "subnet_count": sum(1 for s in subnets if s.get("VpcId") == v["VpcId"])}
                 for v in sorted(vpcs, key=lambda v: (bool(v.get("IsDefault")),) + _named_first(v, v["VpcId"]))],
        "subnets": [{"id": s["SubnetId"], "name": _name_of(s), "cidr": s.get("CidrBlock"),
                     "vpc_id": s.get("VpcId"), "vpc_name": vpc_name.get(s.get("VpcId"), ""),
                     "az": s.get("AvailabilityZone"), "public": bool(s.get("MapPublicIpOnLaunch")),
                     "available_ips": s.get("AvailableIpAddressCount")}
                    for s in sorted(subnets, key=lambda s: _named_first(s, s["SubnetId"]))],
        "route_tables": [{"id": r["RouteTableId"], "name": _name_of(r, r["RouteTableId"]),
                          "vpc_id": r.get("VpcId"), "vpc_name": vpc_name.get(r.get("VpcId"), ""),
                          "routes": [route_out(x) for x in r.get("Routes", [])],
                          "associations": [{"id": a.get("RouteTableAssociationId"), "subnet_id": a.get("SubnetId"),
                                            "subnet_name": subnet_name.get(a.get("SubnetId"), ""),
                                            "main": bool(a.get("Main"))} for a in r.get("Associations", [])]}
                         for r in sorted(route_tables, key=lambda r: _named_first(r, r["RouteTableId"]))],
        "internet_gateways": [{"id": g["InternetGatewayId"], "name": _name_of(g),
                               "vpc_id": (g.get("Attachments") or [{}])[0].get("VpcId"),
                               "vpc_name": vpc_name.get((g.get("Attachments") or [{}])[0].get("VpcId"), "")}
                              for g in sorted(gateways, key=lambda g: _named_first(g, g["InternetGatewayId"]))],
        "security_groups": [{"id": g["GroupId"], "name": g.get("GroupName", ""), "description": g.get("Description", ""),
                             "vpc_id": g.get("VpcId"), "vpc_name": vpc_name.get(g.get("VpcId"), ""),
                             "ingress": _rules_out(g.get("IpPermissions", [])),
                             "egress": _rules_out(g.get("IpPermissionsEgress", []))}
                            for g in sorted(groups, key=lambda g: (g.get("GroupName", ""), g["GroupId"]))],
    }


async def _default_az(sess: LabSession) -> str:
    subnets = (await _call(sess, "describe_subnets")).get("Subnets", [])
    azs = sorted({s["AvailabilityZone"] for s in subnets if s.get("AvailabilityZone")})
    return azs[0] if azs else "us-east-1a"


# ----------------------------------------------------------------------------------------- VPCs
@router.post("/vpcs", status_code=201)
async def create_vpc(session_id: uuid.UUID, body: VpcIn, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                     db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    vpc_id = (await _call(sess, "create_vpc", CidrBlock=body.cidr))["Vpc"]["VpcId"]
    await _name(sess, vpc_id, body.name)
    return {"id": vpc_id, "name": body.name}


@router.post("/vpcs/{vpc_id}/delete", status_code=204)
async def delete_vpc(session_id: uuid.UUID, vpc_id: str, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                     db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    await _call(sess, "delete_vpc", VpcId=vpc_id)


# --------------------------------------------------------------------------------------- subnets
@router.post("/subnets", status_code=201)
async def create_subnet(session_id: uuid.UUID, body: SubnetIn, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                        db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    subnet_id = (await _call(sess, "create_subnet", VpcId=body.vpc_id, CidrBlock=body.cidr,
                             AvailabilityZone=body.az or await _default_az(sess)))["Subnet"]["SubnetId"]
    await _name(sess, subnet_id, body.name)
    if body.public:
        await _call(sess, "modify_subnet_attribute", SubnetId=subnet_id, MapPublicIpOnLaunch={"Value": True})
    return {"id": subnet_id, "name": body.name, "public": body.public}


@router.post("/subnets/{subnet_id}/delete", status_code=204)
async def delete_subnet(session_id: uuid.UUID, subnet_id: str, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                        db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    await _call(sess, "delete_subnet", SubnetId=subnet_id)


# ---------------------------------------------------------------------------------- internet gateways
@router.post("/internet-gateways", status_code=201)
async def create_internet_gateway(session_id: uuid.UUID, body: InternetGatewayIn,
                                  user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                                  db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    gw_id = (await _call(sess, "create_internet_gateway"))["InternetGateway"]["InternetGatewayId"]
    await _name(sess, gw_id, body.name)
    return {"id": gw_id, "name": body.name}


@router.post("/internet-gateways/{gateway_id}/attach", status_code=204)
async def attach_internet_gateway(session_id: uuid.UUID, gateway_id: str, body: AttachIn,
                                  user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                                  db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    await _call(sess, "attach_internet_gateway", InternetGatewayId=gateway_id, VpcId=body.vpc_id)


@router.post("/internet-gateways/{gateway_id}/detach", status_code=204)
async def detach_internet_gateway(session_id: uuid.UUID, gateway_id: str,
                                  user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                                  db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    vpcs = (await _call(sess, "describe_internet_gateways", InternetGatewayIds=[gateway_id]))["InternetGateways"]
    attachments = (vpcs[0].get("Attachments") or []) if vpcs else []
    if not attachments:
        raise ApiError("not_attached", "This internet gateway is not attached to a VPC.", 409)
    await _call(sess, "detach_internet_gateway", InternetGatewayId=gateway_id, VpcId=attachments[0]["VpcId"])


@router.post("/internet-gateways/{gateway_id}/delete", status_code=204)
async def delete_internet_gateway(session_id: uuid.UUID, gateway_id: str,
                                  user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                                  db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    gateway = (await _call(sess, "describe_internet_gateways", InternetGatewayIds=[gateway_id]))["InternetGateways"][0]
    if gateway.get("Attachments"):
        raise ApiError("gateway_attached", "Detach the internet gateway from its VPC before deleting it.", 409)
    await _call(sess, "delete_internet_gateway", InternetGatewayId=gateway_id)


# ----------------------------------------------------------------------------------- route tables
@router.post("/route-tables", status_code=201)
async def create_route_table(session_id: uuid.UUID, body: RouteTableIn,
                             user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                             db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    rtb_id = (await _call(sess, "create_route_table", VpcId=body.vpc_id))["RouteTable"]["RouteTableId"]
    await _name(sess, rtb_id, body.name)
    return {"id": rtb_id, "name": body.name}


@router.post("/route-tables/{route_table_id}/routes", status_code=201)
async def create_route(session_id: uuid.UUID, route_table_id: str, body: RouteIn,
                       user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                       db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    await _call(sess, "create_route", RouteTableId=route_table_id, DestinationCidrBlock=body.destination_cidr,
                GatewayId=body.internet_gateway_id)
    return {"destination": body.destination_cidr, "target": body.internet_gateway_id}


@router.post("/route-tables/{route_table_id}/routes/delete", status_code=204)
async def delete_route(session_id: uuid.UUID, route_table_id: str, body: DestinationIn,
                       user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                       db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    await _call(sess, "delete_route", RouteTableId=route_table_id, DestinationCidrBlock=body.destination_cidr)


@router.post("/route-tables/{route_table_id}/associate", status_code=201)
async def associate_route_table(session_id: uuid.UUID, route_table_id: str, body: AssociateIn,
                                user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                                db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    out = await _call(sess, "associate_route_table", RouteTableId=route_table_id, SubnetId=body.subnet_id)
    return {"association_id": out["AssociationId"]}


@router.post("/route-tables/{route_table_id}/disassociate", status_code=204)
async def disassociate_route_table(session_id: uuid.UUID, route_table_id: str, body: DisassociateIn,
                                   user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                                   db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    await _call(sess, "disassociate_route_table", AssociationId=body.association_id)


@router.post("/route-tables/{route_table_id}/delete", status_code=204)
async def delete_route_table(session_id: uuid.UUID, route_table_id: str,
                             user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                             db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    await _call(sess, "delete_route_table", RouteTableId=route_table_id)


# -------------------------------------------------------------------------------- security groups
@router.post("/security-groups", status_code=201)
async def create_security_group(session_id: uuid.UUID, body: CreateSgIn,
                                user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                                db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    group_id = (await _call(sess, "create_security_group", GroupName=body.name, Description=body.description,
                            VpcId=body.vpc_id))["GroupId"]
    await _name(sess, group_id, body.name)
    return {"id": group_id, "name": body.name}


@router.put("/security-groups/{group_id}/rules")
async def set_security_group_rules(session_id: uuid.UUID, group_id: str, body: SgRulesIn,
                                   user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                                   db: AsyncSession = Depends(get_db)):
    """AWS 'Edit inbound/outbound rules' → 'Save rules': revoke removed rules, authorize new ones."""
    sess = await console_session(session_id, user, db)
    group = (await _call(sess, "describe_security_groups", GroupIds=[group_id]))["SecurityGroups"][0]
    added = removed = 0
    for direction, wanted in (("ingress", body.ingress), ("egress", body.egress)):
        perms_key = "IpPermissions" if direction == "ingress" else "IpPermissionsEgress"
        current = {_rule_key(r): r for r in _rules_out(group.get(perms_key, []))}
        wanted_map = {_rule_key(r.model_dump()): r for r in wanted}
        drop = [k for k in current if k not in wanted_map]
        new = [wanted_map[k] for k in wanted_map if k not in current]
        if drop:
            await _call(sess, f"revoke_security_group_{direction}", GroupId=group_id, IpPermissions=[
                _perm(RuleIn(protocol=k[0], from_port=k[1] if k[1] is not None else -1,
                             to_port=k[2] if k[2] is not None else -1, cidr=k[3])) for k in drop])
        if new:
            await _call(sess, f"authorize_security_group_{direction}", GroupId=group_id,
                        IpPermissions=[_perm(r) for r in new])
        added += len(new)
        removed += len(drop)
    return {"added": added, "removed": removed}


@router.delete("/security-groups/{group_id}", status_code=204)
async def delete_security_group(session_id: uuid.UUID, group_id: str,
                                user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                                db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    await _call(sess, "delete_security_group", GroupId=group_id)
