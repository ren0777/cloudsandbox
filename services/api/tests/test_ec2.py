"""EC2: pure checks/lab grading, console API (FakeRunner = real Moto), and real-runtime contract + labtest
on every engine (marker docker)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.config import get_settings
from app.db import sessionmaker
from app.grader.grade import grade
from app.labs.importer import import_package
from app.labs.package import load_pack
from app.labs.render import compute_variables
from app.models import Assignment
from app.runtime import emulators
from app.sessions import state as st
from tests.conftest import LABS, idem, login, wait_state

LAB = Path(LABS) / "ec2-web-server"
SG, KEY, INST = "cafe-web-sg-alice1", "cafe-key-alice1", "cafe-web-alice1"


def rule(port, cidr, proto="tcp"):
    return {"protocol": proto, "from_port": port, "to_port": port, "cidr": cidr}


def inst(name, state="running", itype="t3.micro", key=KEY, sgs=(SG,), tags=None):
    return {"id": f"i-{name}", "name": name, "state": state, "type": itype, "key_name": key,
            "security_groups": list(sgs), "tags": {"Name": name, **(tags or {"Project": "cloudcafe"})}}


def ev(instances=(), rules=(), keys=(KEY,)):
    return {"format": 1, "captured_at": "x", "collectors": {"ec2": {
        "instances": list(instances), "security_groups": {SG: {"description": "d", "ingress": list(rules)}},
        "key_pairs": list(keys)}}}


def _grade(evidence):
    d = load_pack(LAB).definition
    return grade(d, compute_variables(d, "alice1"), evidence)


def test_lab_scores():
    assert _grade({"format": 1, "collectors": {"ec2": {}}})["score"] == Decimal("0.00")
    full = ev([inst(INST)], [rule(80, "0.0.0.0/0"), rule(22, "10.20.0.0/16")])
    assert _grade(full)["score"] == Decimal("100.00")
    partial = ev([inst(INST, itype="t2.micro"), inst("test-box", key=None, sgs=())],
                 [rule(80, "0.0.0.0/0"), rule(22, "0.0.0.0/0")])
    assert _grade(partial)["score"] == Decimal("30.00")


def test_hidden_world_ssh_and_all_traffic_rule():
    # campus SSH present but a catch-all "-1" rule from anywhere also opens 22 → hidden check fails
    r = _grade(ev([inst(INST)], [rule(80, "0.0.0.0/0"), rule(22, "10.20.0.0/16"),
                                  {"protocol": "-1", "from_port": None, "to_port": None, "cidr": "0.0.0.0/0"}]))
    t2 = next(t for t in r["tasks"] if t["task_id"] == "ssh-campus-only")
    assert not t2["passed"] and [c["passed"] for c in t2["checks"]] == [True, False]


def test_terminated_instances_dont_count_and_messages():
    r = _grade(ev([inst(INST, state="terminated")], [rule(80, "0.0.0.0/0")]))
    t4 = next(t for t in r["tasks"] if t["task_id"] == "launch")
    assert "No instance named" in t4["checks"][0]["message"]
    r = _grade(ev([inst(INST, state="stopped", itype="t2.micro")], []))
    msg = next(t for t in r["tasks"] if t["task_id"] == "launch")["checks"][0]["message"]
    assert "it is stopped" in msg and "not t3.micro" in msg


# ------------------------------------------------------------------------------- console API
async def ec2_assignment(world) -> Assignment:
    async with sessionmaker()() as db:
        lv, _ = await import_package(db, load_pack(LAB))
        now = st.now()
        a = Assignment(course_id=world.course.id, lab_version_id=lv.id, title="EC2", open_at=now - timedelta(hours=1),
                       due_at=now + timedelta(days=1), close_at=now + timedelta(days=2), max_attempts=3)
        db.add(a)
        await db.commit()
        return a


async def test_ec2_console_launch_wizard_rules_and_state(world, fake_runner):
    a = await ec2_assignment(world)
    c = await login(world.alice)
    sid = (await c.post(f"/api/assignments/{a.id}/sessions")).json()["id"]
    await wait_state(c, sid, {"READY"})
    base = f"/api/sessions/{sid}/console/ec2"

    opts = (await c.get(f"{base}/launch-options")).json()
    assert opts["images"] and opts["vpc_id"] and {"name": "t3.micro", "free_tier": True} in opts["instance_types"]
    k = (await c.post(f"{base}/key-pairs", json={"name": KEY})).json()
    assert "PRIVATE KEY" in k["private_key"]
    # launch with a wizard-created security group (SSH from campus + HTTP)
    r = await c.post(f"{base}/instances", json={
        "name": INST, "image_id": opts["images"][0]["id"], "instance_type": "t3.micro", "key_name": KEY,
        "create_security_group": {"name": SG, "ssh_cidr": "10.20.0.0/16", "http": True},
        "tags": [{"key": "Project", "value": "cloudcafe"}]})
    assert r.status_code == 201, r.text
    iid = r.json()["id"]
    i = (await c.get(f"{base}/instances/{iid}")).json()
    assert i["name"] == INST and i["state"] == "running" and i["security_groups"][0]["name"] == SG
    assert {"key": "Project", "value": "cloudcafe"} in i["tags"]
    assert (await c.post(f"{base}/instances", json={"name": "x", "image_id": "ami-1", "instance_type": "p5.48xlarge"})).status_code == 422

    prog = await c.post(f"/api/sessions/{sid}/progress")
    assert prog.json()["score"] == "100.00", prog.text

    # edit inbound rules: open SSH to the world → hidden check now fails
    sg = next(g for g in (await c.get(f"{base}/security-groups")).json()["security_groups"] if g["name"] == SG)
    rules = (await c.get(f"{base}/security-groups/{sg['id']}")).json()["inbound_rules"]
    assert sorted((x["from_port"], x["cidr"]) for x in rules) == [(22, "10.20.0.0/16"), (80, "0.0.0.0/0")]
    new = [{"protocol": "tcp", "from_port": 80, "to_port": 80, "cidr": "0.0.0.0/0"},
           {"protocol": "tcp", "from_port": 22, "to_port": 22, "cidr": "0.0.0.0/0"}]
    out = (await c.put(f"{base}/security-groups/{sg['id']}/inbound-rules", json={"rules": new})).json()
    assert out == {"added": 1, "removed": 1}

    # stop → cost check still fine, instance check fails (state)
    assert (await c.post(f"{base}/instances/{iid}/state", json={"action": "stop"})).status_code == 200
    assert (await c.get(f"{base}/instances/{iid}")).json()["state"] == "stopped"
    bob = await login(world.bob)
    assert (await bob.get(f"{base}/instances")).status_code == 404
    r = await c.post(f"/api/sessions/{sid}/submit", headers=idem())
    assert r.status_code == 200 and r.json()["result"]["score"] == "30.00", r.text  # sg80 20 + key 10 (none running)
    assert (await c.get(f"{base}/instances")).status_code == 409


# ------------------------------------------------------------------------------ real runtime
def ec2_contract(c) -> dict:
    s: dict = {}
    return {
        "DescribeImages": lambda: s.__setitem__("ami", c.describe_images(Owners=["amazon"])["Images"][0]["ImageId"]),
        "DescribeInstanceTypes": lambda: len(c.describe_instance_types(InstanceTypes=["t3.micro"])["InstanceTypes"]) == 1 or 1 / 0,
        "DescribeVpcs": lambda: s.__setitem__("vpc", c.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"][0]["VpcId"]),
        "DescribeSubnets": lambda: len(c.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [s["vpc"]]}])["Subnets"]) > 0 or 1 / 0,
        "CreateSecurityGroup": lambda: s.__setitem__("sg", c.create_security_group(GroupName="g", Description="d", VpcId=s["vpc"])["GroupId"]),
        "AuthorizeSecurityGroupIngress": lambda: c.authorize_security_group_ingress(GroupId=s["sg"], IpPermissions=[
            {"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": [{"CidrIp": "10.20.0.0/16"}]}]),
        "DescribeSecurityGroups": lambda: c.describe_security_groups(GroupIds=[s["sg"]])["SecurityGroups"][0]["IpPermissions"][0]["FromPort"] == 22 or 1 / 0,
        "RevokeSecurityGroupIngress": lambda: c.revoke_security_group_ingress(GroupId=s["sg"], IpPermissions=[
            {"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": [{"CidrIp": "10.20.0.0/16"}]}]),
        "CreateKeyPair": lambda: "KeyMaterial" in c.create_key_pair(KeyName="k") or 1 / 0,
        "DescribeKeyPairs": lambda: c.describe_key_pairs()["KeyPairs"][0]["KeyName"] == "k" or 1 / 0,
        "RunInstances": lambda: s.__setitem__("i", c.run_instances(ImageId=s["ami"], InstanceType="t3.micro", MinCount=1, MaxCount=1,
                                                                    KeyName="k", SecurityGroupIds=[s["sg"]])["Instances"][0]["InstanceId"]),
        "DescribeInstances": lambda: c.describe_instances(InstanceIds=[s["i"]])["Reservations"][0]["Instances"][0]["KeyName"] == "k" or 1 / 0,
        "CreateTags": lambda: c.create_tags(Resources=[s["i"]], Tags=[{"Key": "Name", "Value": "web"}]),
        "DescribeTags": lambda: any(t["Value"] == "web" for t in c.describe_tags(Filters=[{"Name": "resource-id", "Values": [s["i"]]}])["Tags"]) or 1 / 0,
        "StopInstances": lambda: c.stop_instances(InstanceIds=[s["i"]]),
        "StartInstances": lambda: c.start_instances(InstanceIds=[s["i"]]),
        "TerminateInstances": lambda: c.terminate_instances(InstanceIds=[s["i"]]),
        "DeleteKeyPair": lambda: c.delete_key_pair(KeyName="k"),
        "DeleteSecurityGroup": lambda: c.delete_security_group(GroupId=s["sg"]),
    }


@pytest.mark.docker
@pytest.mark.parametrize("contract_engine", emulators.ENGINES)
async def test_ec2_contract_for_every_declared_supported_operation(real_runner, contract_engine):
    import asyncio
    caps = emulators.get(contract_engine).capabilities
    declared = {op for op, o in caps.services["ec2"].items() if o.level == "supported"}
    sid = str(uuid.uuid4())
    info = await real_runner.create_sandbox({"sandbox_id": sid, "env": get_settings().env, "engine": contract_engine,
                                             "terminal_credential": "contract:abcdefgh1234"})
    try:
        ops = ec2_contract(emulators.get(contract_engine).client("ec2", info["emulator_endpoint"]))
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
async def test_ec2_labtest_on_every_engine(real_runner, lab_engine):
    from app.labtest import check_pack
    results = await check_pack(LAB, real_runner, engine=lab_engine)
    assert [(r.name, str(r.actual)) for r in results] == [
        (f"{lab_engine}/empty", "0.00"), (f"{lab_engine}/partial", "30.00"), (f"{lab_engine}/solution", "100.00")], \
        [(r.name, r.actual, r.detail) for r in results]
