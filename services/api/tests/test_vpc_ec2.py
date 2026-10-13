"""VPC + EC2 (Mission 15): the instance placement check, the lab's scoring from hand-built evidence, the
diagram's instance → subnet edge, the EC2 console launching into a chosen subnet (FakeRunner = real Moto),
and — marker docker — the labtest on every primary engine."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.db import sessionmaker
from app.diagram import build_graph
from app.grader.grade import grade
from app.labs.importer import import_package
from app.labs.package import load_pack
from app.labs.render import compute_variables
from app.models import Assignment
from app.runtime import emulators
from app.sessions import state as st
from tests.conftest import LABS, idem, login, wait_state
from tests.test_vpc_console import IGW_NAME, RTB_NAME, SG_NAME, SUBNET_CIDR, SUBNET_NAME, VPC_CIDR, VPC_NAME, vpc_evidence

LAB = Path(LABS) / "vpc-ec2-web"
INSTANCE = "cafe-web-alice1"


def instance(**kw) -> dict:
    return {"id": "i-1", "name": INSTANCE, "state": "running", "type": "t3.micro", "key_name": None,
            "security_groups": [SG_NAME], "vpc": VPC_NAME, "subnet": SUBNET_NAME, "tags": {"Name": INSTANCE}} | kw


def evidence(*instances: dict, sg_vpc: str = VPC_NAME, ssh_world: bool = False) -> dict:
    ev = vpc_evidence()
    ingress = [{"protocol": "tcp", "from_port": 80, "to_port": 80, "cidr": "0.0.0.0/0"}]
    if ssh_world:
        ingress.append({"protocol": "tcp", "from_port": 22, "to_port": 22, "cidr": "0.0.0.0/0"})
    ev["collectors"]["ec2"] = {
        "instances": list(instances),
        "security_groups": {SG_NAME: {"description": "web", "ingress": ingress, "vpc": sg_vpc},
                            "default": {"description": "default", "ingress": [], "vpc": "default"}},
        "key_pairs": []}
    return ev


def _grade(ev: dict) -> dict:
    d = load_pack(LAB).definition
    return grade(d, compute_variables(d, "alice1"), ev)


def _check(r: dict, type_: str) -> dict:
    return next(c for t in r["tasks"] for c in t["checks"] if c["check"] == type_)


# ------------------------------------------------------------------------------------ pure
def test_lab_runs_on_every_primary_engine():
    d = load_pack(LAB).definition
    assert d.services == ["vpc", "ec2"] and d.runtime.emulator == "default"
    assert emulators.candidates(d.runtime.emulator) == emulators.ENGINES


def test_scores_and_the_default_vpc_mistake():
    assert _grade({"collectors": {}})["score"] == Decimal("0.00")
    assert _grade(evidence(instance()))["score"] == Decimal("100.00")
    # the labtest partial: perfect network, server launched into the default VPC without the group
    wrong = instance(vpc="default", subnet="", security_groups=["default"])
    r = _grade(evidence(wrong))
    assert r["score"] == Decimal("65.00")
    msg = _check(r, "ec2.instance_network")["message"]
    assert msg == (f"Instance {INSTANCE}: it runs in VPC default, not {VPC_NAME}; "
                   f"it runs in an unnamed subnet, not {SUBNET_NAME}")
    # a second server left running costs the last task
    assert _grade(evidence(instance(), instance(id="i-2", name="practice")))["score"] == Decimal("90.00")
    # SSH open to the world is the hidden part of the security group task
    assert _grade(evidence(instance(), ssh_world=True))["score"] == Decimal("85.00")


def test_instance_network_flags_a_group_from_another_vpc():
    r = _grade(evidence(instance(), sg_vpc="default"))
    c = _check(r, "ec2.instance_network")
    assert not c["passed"] and c["message"] == f"Instance {INSTANCE}: security group {SG_NAME} belongs to another VPC"
    # every VPC has a group called "default", so it never counts as foreign
    ok = _check(_grade(evidence(instance(security_groups=[SG_NAME, "default"]))), "ec2.instance_network")
    assert ok["passed"] and ok["message"] == f"Instance {INSTANCE} runs in {SUBNET_NAME}"


def test_diagram_places_the_instance_in_its_subnet():
    g = build_graph(evidence(instance())["collectors"])
    assert {"source": "ec2:instance:i-1", "target": f"vpc:subnet:{SUBNET_NAME}", "kind": "in"} in g["edges"]
    # without VPC evidence (an EC2-only lab) there is no subnet node, so no dangling edge
    g = build_graph({"ec2": evidence(instance())["collectors"]["ec2"]})
    assert not any(e["kind"] == "in" for e in g["edges"])


def test_template_is_offered():
    from app.instructor.templates import TEMPLATES
    t = next(t for t in TEMPLATES if t.id == "vpc-ec2-web")
    assert t.source_lab_id == "vpc-ec2-web" and set(t.services) == {"vpc", "ec2"}


# ------------------------------------------------------------------------------- console API
async def test_console_launches_into_the_chosen_subnet(world, fake_runner):
    async with sessionmaker()() as db:
        lv, _ = await import_package(db, load_pack(LAB))
        now = st.now()
        a = Assignment(course_id=world.course.id, lab_version_id=lv.id, title="Web in VPC",
                       open_at=now - timedelta(hours=1), due_at=now + timedelta(days=1),
                       close_at=now + timedelta(days=2), max_attempts=3)
        db.add(a)
        await db.commit()
    c = await login(world.alice)
    sid = (await c.post(f"/api/assignments/{a.id}/sessions")).json()["id"]
    await wait_state(c, sid, {"READY"})
    vpc_base, ec2 = f"/api/sessions/{sid}/console/vpc", f"/api/sessions/{sid}/console/ec2"

    vpc = (await c.post(f"{vpc_base}/vpcs", json={"name": VPC_NAME, "cidr": VPC_CIDR})).json()["id"]
    subnet = (await c.post(f"{vpc_base}/subnets", json={"vpc_id": vpc, "name": SUBNET_NAME, "cidr": SUBNET_CIDR,
                                                        "public": True})).json()["id"]
    igw = (await c.post(f"{vpc_base}/internet-gateways", json={"name": IGW_NAME})).json()["id"]
    assert (await c.post(f"{vpc_base}/internet-gateways/{igw}/attach", json={"vpc_id": vpc})).status_code == 204
    rtb = (await c.post(f"{vpc_base}/route-tables", json={"vpc_id": vpc, "name": RTB_NAME})).json()["id"]
    assert (await c.post(f"{vpc_base}/route-tables/{rtb}/routes", json={
        "destination_cidr": "0.0.0.0/0", "internet_gateway_id": igw})).status_code == 201
    assert (await c.post(f"{vpc_base}/route-tables/{rtb}/associate", json={"subnet_id": subnet})).status_code in (200, 201)

    # Create security group in the chosen VPC (EC2 console), and the VPC list it picks from
    vpcs = (await c.get(f"{ec2}/vpcs")).json()["vpcs"]
    assert vpcs[0]["is_default"] and any(v["id"] == vpc and v["name"] == VPC_NAME for v in vpcs)
    sg = (await c.post(f"{ec2}/security-groups", json={"name": SG_NAME, "description": "web", "vpc_id": vpc, "rules": [
        {"protocol": "tcp", "from_port": 80, "to_port": 80, "cidr": "0.0.0.0/0"}]})).json()["id"]
    default_sg = (await c.post(f"{ec2}/security-groups", json={"name": "in-default", "description": "x"})).json()["id"]

    o = (await c.get(f"{ec2}/launch-options")).json()
    assert any(x["id"] == subnet and x["vpc_id"] == vpc and x["public"] and x["name"] == SUBNET_NAME for x in o["subnets"])
    assert {g["id"]: g["vpc_id"] for g in o["security_groups"]}[sg] == vpc
    image = o["images"][0]["id"]
    launch = {"name": INSTANCE, "image_id": image, "instance_type": "t3.micro", "subnet_id": subnet}

    # a group from another VPC is refused, as AWS would (the simulator alone would accept it)
    r = await c.post(f"{ec2}/instances", json=launch | {"security_group_ids": [default_sg]})
    assert r.status_code == 400 and "belongs to a different VPC" in r.json()["error"]["message"], r.text
    assert (await c.post(f"{ec2}/instances", json=launch | {"subnet_id": "subnet-nope"})).status_code == 400

    iid = (await c.post(f"{ec2}/instances", json=launch | {"security_group_ids": [sg]})).json()["id"]
    i = (await c.get(f"{ec2}/instances/{iid}")).json()
    assert (i["vpc_id"], i["subnet_id"]) == (vpc, subnet)

    p = (await c.post(f"/api/sessions/{sid}/progress")).json()
    assert p["score"] == "100.00", p
    r = await c.post(f"/api/sessions/{sid}/submit", headers=idem())
    assert r.status_code == 200 and r.json()["result"]["score"] == "100.00", r.text


# ------------------------------------------------------------------------------ real runtime
@pytest.mark.docker
@pytest.mark.parametrize("lab_engine", emulators.ENGINES)
async def test_vpc_ec2_labtest_on_every_engine(real_runner, lab_engine):
    from app.labtest import check_pack
    results = await check_pack(LAB, real_runner, engine=lab_engine)
    assert [(r.name, str(r.actual)) for r in results] == [
        (f"{lab_engine}/empty", "0.00"), (f"{lab_engine}/partial", "65.00"), (f"{lab_engine}/solution", "100.00")], \
        [(r.name, r.actual, r.detail) for r in results]
