"""VPC preparation (M44): capability parity and the real-runtime contract on every engine (marker docker).

VPC rides the EC2 API; the adapter maps the CloudLabs service name `vpc` to the boto3 `ec2` client.
The lab packs are exercised by `app.labtest` on every primary engine (empty / partial / solution, plus
Reset for the break-fix pack).
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from app.config import get_settings
from app.runtime import emulators


def must(cond, msg: str = "") -> None:
    if not cond:
        raise AssertionError(msg or "assertion failed")


# Ops run in declaration order; `st` carries ids between them. Teardown ops come last, as a console
# session would delete resources.
VPC_CONTRACT = {
    "CreateVpc": lambda c, st: st.update(vpc=c.create_vpc(CidrBlock="10.42.0.0/16")["Vpc"]["VpcId"]),
    "DescribeVpcs": lambda c, st: must(
        [v for v in c.describe_vpcs(VpcIds=[st["vpc"]])["Vpcs"] if v["CidrBlock"] == "10.42.0.0/16"],
        "created VPC not returned by DescribeVpcs"),
    "ModifyVpcAttribute": lambda c, st: c.modify_vpc_attribute(VpcId=st["vpc"], EnableDnsSupport={"Value": True}),
    "DescribeVpcAttribute": lambda c, st: must(
        c.describe_vpc_attribute(VpcId=st["vpc"], Attribute="enableDnsSupport")["EnableDnsSupport"]["Value"] is True,
        "EnableDnsSupport did not round-trip"),
    "CreateSubnet": lambda c, st: st.update(subnet=c.create_subnet(
        VpcId=st["vpc"], CidrBlock="10.42.1.0/24", AvailabilityZone="us-east-1a")["Subnet"]["SubnetId"]),
    "DescribeSubnets": lambda c, st: must(
        [s for s in c.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [st["vpc"]]}])["Subnets"]
         if s["SubnetId"] == st["subnet"]], "subnet not returned for its VPC"),
    "ModifySubnetAttribute": lambda c, st: c.modify_subnet_attribute(
        SubnetId=st["subnet"], MapPublicIpOnLaunch={"Value": True}),
    "CreateInternetGateway": lambda c, st: st.update(
        igw=c.create_internet_gateway()["InternetGateway"]["InternetGatewayId"]),
    "AttachInternetGateway": lambda c, st: c.attach_internet_gateway(InternetGatewayId=st["igw"], VpcId=st["vpc"]),
    "DescribeInternetGateways": lambda c, st: must(
        any(a.get("VpcId") == st["vpc"] for a in
            c.describe_internet_gateways(InternetGatewayIds=[st["igw"]])["InternetGateways"][0].get("Attachments", [])),
        "internet gateway not attached"),
    "CreateRouteTable": lambda c, st: st.update(
        rtb=c.create_route_table(VpcId=st["vpc"])["RouteTable"]["RouteTableId"]),
    "CreateRoute": lambda c, st: c.create_route(
        RouteTableId=st["rtb"], DestinationCidrBlock="0.0.0.0/0", GatewayId=st["igw"]),
    "AssociateRouteTable": lambda c, st: st.update(assoc=c.associate_route_table(
        RouteTableId=st["rtb"], SubnetId=st["subnet"])["AssociationId"]),
    "DescribeRouteTables": lambda c, st: must(
        any(r.get("GatewayId") == st["igw"] for r in
            c.describe_route_tables(RouteTableIds=[st["rtb"]])["RouteTables"][0].get("Routes", []))
        and any(a.get("SubnetId") == st["subnet"] and a.get("RouteTableAssociationId") == st["assoc"] for a in
                c.describe_route_tables(RouteTableIds=[st["rtb"]])["RouteTables"][0].get("Associations", [])),
        "route or subnet association missing"),
    "CreateSecurityGroup": lambda c, st: st.update(sg=c.create_security_group(
        GroupName="m44-contract-sg", Description="m44 contract", VpcId=st["vpc"])["GroupId"]),
    "AuthorizeSecurityGroupIngress": lambda c, st: c.authorize_security_group_ingress(GroupId=st["sg"],
        IpPermissions=[{"IpProtocol": "tcp", "FromPort": 80, "ToPort": 80,
                        "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "http"}]}]),
    "AuthorizeSecurityGroupEgress": lambda c, st: c.authorize_security_group_egress(GroupId=st["sg"],
        IpPermissions=[{"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443,
                        "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}]),
    "DescribeSecurityGroups": lambda c, st: must(
        c.describe_security_groups(GroupIds=[st["sg"]])["SecurityGroups"][0]["VpcId"] == st["vpc"]
        and any(p.get("FromPort") == 80 for p in
                c.describe_security_groups(GroupIds=[st["sg"]])["SecurityGroups"][0].get("IpPermissions", []))
        and any(p.get("FromPort") == 443 for p in
                c.describe_security_groups(GroupIds=[st["sg"]])["SecurityGroups"][0].get("IpPermissionsEgress", [])),
        "security group rules did not round-trip"),
    "RevokeSecurityGroupIngress": lambda c, st: c.revoke_security_group_ingress(GroupId=st["sg"],
        IpPermissions=[{"IpProtocol": "tcp", "FromPort": 80, "ToPort": 80,
                        "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}]),
    "RevokeSecurityGroupEgress": lambda c, st: c.revoke_security_group_egress(GroupId=st["sg"],
        IpPermissions=[{"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443,
                        "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}]),
    "DisassociateRouteTable": lambda c, st: c.disassociate_route_table(AssociationId=st["assoc"]),
    "DeleteRoute": lambda c, st: c.delete_route(RouteTableId=st["rtb"], DestinationCidrBlock="0.0.0.0/0"),
    "DetachInternetGateway": lambda c, st: c.detach_internet_gateway(InternetGatewayId=st["igw"], VpcId=st["vpc"]),
    "DeleteInternetGateway": lambda c, st: c.delete_internet_gateway(InternetGatewayId=st["igw"]),
    "DeleteRouteTable": lambda c, st: c.delete_route_table(RouteTableId=st["rtb"]),
    "DeleteSecurityGroup": lambda c, st: c.delete_security_group(GroupId=st["sg"]),
    "DeleteSubnet": lambda c, st: c.delete_subnet(SubnetId=st["subnet"]),
    "DeleteVpc": lambda c, st: c.delete_vpc(VpcId=st["vpc"]),
}


def test_vpc_service_maps_to_the_ec2_client():
    c = emulators.get("moto").client("vpc", "http://127.0.0.1:9")
    assert c.meta.service_model.service_name == "ec2"


def test_vpc_declaration_is_identical_on_every_engine():
    declared = {e: frozenset(op for op, o in emulators.get(e).capabilities.services["vpc"].items()
                             if o.level == "supported") for e in emulators.ALL_ENGINES}
    assert len(set(declared.values())) == 1, declared
    assert set(declared["moto"]) == set(VPC_CONTRACT), set(declared["moto"]) ^ set(VPC_CONTRACT)


@pytest.mark.docker
@pytest.mark.parametrize("contract_engine", emulators.ALL_ENGINES)
async def test_vpc_contract_for_every_declared_supported_operation(real_runner, contract_engine):
    caps = emulators.get(contract_engine).capabilities
    declared = {op for op, o in caps.services["vpc"].items() if o.level == "supported"}
    assert declared == set(VPC_CONTRACT), declared ^ set(VPC_CONTRACT)
    sid = str(uuid.uuid4())
    info = await real_runner.create_sandbox({"sandbox_id": sid, "env": get_settings().env, "engine": contract_engine,
                                             "terminal_credential": "contract:abcdefgh1234"})
    try:
        c = emulators.get(contract_engine).client("vpc", info["emulator_endpoint"])
        st: dict = {}
        for op, fn in VPC_CONTRACT.items():
            await asyncio.to_thread(fn, c, st)
    finally:
        await real_runner.destroy_sandbox(sid)


# ------------------------------------------------------------------------------- lab packs
LABS_DIR = Path(get_settings().labs_dir)


@pytest.mark.docker
@pytest.mark.parametrize("pack,expected", [
    ("vpc-basics", [("empty", "0.00"), ("partial", "50.00"), ("solution", "100.00")]),
    ("vpc-breakfix", [("empty", "25.00"), ("partial", "65.00"), ("solution", "100.00"), ("reset", "25.00")]),
])
@pytest.mark.parametrize("lab_engine", emulators.ENGINES)
async def test_vpc_labtest_on_every_engine(real_runner, lab_engine, pack, expected):
    from app.labtest import check_pack
    results = await check_pack(LABS_DIR / pack, real_runner, engine=lab_engine)
    assert [(r.name, str(r.actual)) for r in results] == [(f"{lab_engine}/{name}", score) for name, score in expected], \
        [(r.name, r.actual, r.detail) for r in results]
