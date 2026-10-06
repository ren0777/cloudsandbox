"""VPC: pure check grading, the console API (FakeRunner = real Moto), the lab packs and the break-fix
baseline. Real-runtime contract + labtest on every engine live in tests/test_vpc.py (marker docker)."""

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

GUIDED = Path(LABS) / "vpc-basics"
BREAKFIX = Path(LABS) / "vpc-breakfix"

VPC_NAME = "cafe-vpc-alice1"
SUBNET_NAME = "cafe-public-alice1"
IGW_NAME = "cafe-igw-alice1"
RTB_NAME = "cafe-public-rtb-alice1"
SG_NAME = "cafe-web-sg-alice1"
VPC_CIDR = "10.0.0.0/16"
SUBNET_CIDR = "10.0.1.0/24"


def vpc_evidence(vpc=True, subnet=True, public=True, igw=True, route=True, association=True, http=True,
                 ssh=False, ssh_world=False) -> dict:
    """A VPC collector payload shaped like the real one (names, no ids). Toggle pieces to score scenarios."""
    return {"format": 1, "captured_at": "x", "collectors": {"vpc": {
        "vpcs": {VPC_NAME: {"name": VPC_NAME, "cidr": VPC_CIDR, "is_default": False}} if vpc else {},
        "subnets": {SUBNET_NAME: {"name": SUBNET_NAME, "cidr": SUBNET_CIDR, "vpc": VPC_NAME,
                                  "public": public}} if subnet else {},
        "route_tables": {RTB_NAME: {
            "name": RTB_NAME, "vpc": VPC_NAME,
            "routes": ([{"destination": VPC_CIDR, "target": "local", "state": "active"}] if route else [])
                      + ([{"destination": "0.0.0.0/0", "target": f"igw:{IGW_NAME}", "state": "active"}] if route else []),
            "associations": [{"subnet": SUBNET_NAME, "main": False}] if association else []}} if route or association else {},
        "internet_gateways": {IGW_NAME: {"name": IGW_NAME, "vpc": VPC_NAME}} if igw else {},
        "security_groups": {SG_NAME: {
            "name": SG_NAME, "description": "web", "vpc": VPC_NAME,
            "ingress": ([{"protocol": "tcp", "from_port": 80, "to_port": 80, "cidr": "0.0.0.0/0"}] if http else [])
                       + ([{"protocol": "tcp", "from_port": 22, "to_port": 22, "cidr": VPC_CIDR}] if ssh else [])
                       + ([{"protocol": "tcp", "from_port": 22, "to_port": 22, "cidr": "0.0.0.0/0"}] if ssh_world else []),
            "egress": []}},
    }}}


def _grade(pack: Path, evidence: dict) -> dict:
    d = load_pack(pack).definition
    return grade(d, compute_variables(d, "alice1"), evidence)


# ------------------------------------------------------------------------------------ pure
def test_vpc_labs_load_and_are_valid_on_every_engine():
    guided = load_pack(GUIDED).definition
    fixed = load_pack(BREAKFIX).definition
    for d in (guided, fixed):
        assert d.services == ["vpc"] and d.runtime.emulator == "default"
        assert emulators.candidates(d.runtime.emulator) == emulators.ENGINES
    assert guided.kind == "guided" and not guided.break_actions
    assert fixed.kind == "break_fix" and fixed.break_actions and not fixed.setup


def test_guided_scores_zero_partial_full():
    assert _grade(GUIDED, {"collectors": {}})["score"] == Decimal("0.00")
    partial = vpc_evidence(route=False, association=False, http=False)
    assert _grade(GUIDED, partial)["score"] == Decimal("50.00")
    assert _grade(GUIDED, vpc_evidence())["score"] == Decimal("100.00")


def test_guided_checks_explain_what_is_missing():
    r = _grade(GUIDED, vpc_evidence(route=False, http=False))
    failed = {c["check"]: c for t in r["tasks"] for c in t["checks"] if not c["passed"]}
    assert "does not route 0.0.0.0/0" in failed["vpc.route"]["message"]
    assert "does not allow tcp/80" in failed["vpc.security_group_rule"]["message"]
    r = _grade(GUIDED, vpc_evidence(subnet=False, igw=False))
    failed = {c["check"]: c for t in r["tasks"] for c in t["checks"] if not c["passed"]}
    assert "No subnet named" in failed["vpc.subnet"]["message"]
    assert "No internet gateway named" in failed["vpc.internet_gateway_attached"]["message"]


def test_breakfix_baseline_partial_solution_and_anti_lazy():
    broken = vpc_evidence(route=False, association=True, http=False, ssh=True)
    assert _grade(BREAKFIX, broken)["score"] == Decimal("25.00")  # only "leave the network intact"
    partial = vpc_evidence(route=True, http=False, ssh=True)
    assert _grade(BREAKFIX, partial)["score"] == Decimal("65.00")  # route restored, port still closed
    full = vpc_evidence(route=True, http=True, ssh=True)
    assert _grade(BREAKFIX, full)["score"] == Decimal("100.00")
    lazy = vpc_evidence(route=True, http=True, ssh=False, ssh_world=True)  # opened SSH to the world
    assert _grade(BREAKFIX, lazy)["score"] == Decimal("75.00")


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


async def test_vpc_console_journey(world, fake_runner):
    a = await _assignment(world, GUIDED, "VPC basics")
    c = await login(world.alice)
    sid = (await c.post(f"/api/assignments/{a.id}/sessions")).json()["id"]
    await wait_state(c, sid, {"READY"})
    base = f"/api/sessions/{sid}/console/vpc"
    assert (await c.get(f"/api/console/services?session_id={sid}")).json()["services"]["vpc"] == "available"

    vpc = (await c.post(f"{base}/vpcs", json={"name": VPC_NAME, "cidr": VPC_CIDR})).json()["id"]
    subnet = (await c.post(f"{base}/subnets", json={"vpc_id": vpc, "name": SUBNET_NAME, "cidr": SUBNET_CIDR,
                                                    "public": True})).json()["id"]
    igw = (await c.post(f"{base}/internet-gateways", json={"name": IGW_NAME})).json()["id"]
    assert (await c.post(f"{base}/internet-gateways/{igw}/attach", json={"vpc_id": vpc})).status_code == 204
    rtb = (await c.post(f"{base}/route-tables", json={"vpc_id": vpc, "name": RTB_NAME})).json()["id"]
    assert (await c.post(f"{base}/route-tables/{rtb}/routes", json={
        "destination_cidr": "0.0.0.0/0", "internet_gateway_id": igw})).status_code == 201
    assoc = (await c.post(f"{base}/route-tables/{rtb}/associate", json={"subnet_id": subnet})).json()["association_id"]
    sg = (await c.post(f"{base}/security-groups", json={
        "vpc_id": vpc, "name": SG_NAME, "description": "web"})).json()["id"]
    rules = {"ingress": [{"protocol": "tcp", "from_port": 80, "to_port": 80, "cidr": "0.0.0.0/0",
                          "description": "http"}],
             "egress": [{"protocol": "-1", "from_port": -1, "to_port": -1, "cidr": "0.0.0.0/0"}]}
    # The created security group already has the default allow-all egress rule, so only HTTP is new.
    assert (await c.put(f"{base}/security-groups/{sg}/rules", json=rules)).json() == {"added": 1, "removed": 0}

    o = (await c.get(f"{base}/overview")).json()
    assert any(v["name"] == VPC_NAME and v["cidr"] == VPC_CIDR for v in o["vpcs"])
    assert any(s["name"] == SUBNET_NAME and s["public"] and s["vpc_name"] == VPC_NAME for s in o["subnets"])
    assert any(g["name"] == IGW_NAME and g["vpc_name"] == VPC_NAME for g in o["internet_gateways"])
    rt = next(t for t in o["route_tables"] if t["name"] == RTB_NAME)
    assert any(x["destination"] == "0.0.0.0/0" and x["target"] == f"igw:{IGW_NAME}" for x in rt["routes"])
    assert any(a["subnet_name"] == SUBNET_NAME and a["id"] == assoc for a in rt["associations"])
    group = next(g for g in o["security_groups"] if g["name"] == SG_NAME)
    assert any(r["protocol"] == "tcp" and r["from_port"] == 80 and r["cidr"] == "0.0.0.0/0" for r in group["ingress"])

    p = await c.post(f"/api/sessions/{sid}/progress")
    assert p.json()["score"] == "100.00", p.text

    # Deleting an unused route and re-creating it is a normal console action; the score survives.
    assert (await c.post(f"{base}/route-tables/{rtb}/routes/delete",
                         json={"destination_cidr": "0.0.0.0/0"})).status_code == 204
    assert (await c.post(f"{base}/route-tables/{rtb}/routes", json={
        "destination_cidr": "0.0.0.0/0", "internet_gateway_id": igw})).status_code == 201

    # ownership + freeze
    bob = await login(world.bob)
    assert (await bob.get(f"{base}/overview")).status_code == 404
    assert (await c.post(f"/api/sessions/{sid}/submit", headers=idem())).json()["result"]["score"] == "100.00"
    assert (await c.get(f"{base}/overview")).status_code == 409


async def test_vpc_console_rules_are_replaced_not_appended(world, fake_runner):
    """Editing a security group in the console replaces rules: removed ones are revoked, new ones added."""
    a = await _assignment(world, GUIDED, "VPC rules edit")
    c = await login(world.alice)
    sid = (await c.post(f"/api/assignments/{a.id}/sessions")).json()["id"]
    await wait_state(c, sid, {"READY"})
    base = f"/api/sessions/{sid}/console/vpc"
    vpc = (await c.post(f"{base}/vpcs", json={"name": VPC_NAME, "cidr": VPC_CIDR})).json()["id"]
    sg = (await c.post(f"{base}/security-groups", json={
        "vpc_id": vpc, "name": SG_NAME, "description": "web"})).json()["id"]
    put = await c.put(f"{base}/security-groups/{sg}/rules", json={
        "ingress": [{"protocol": "tcp", "from_port": 80, "to_port": 80, "cidr": "0.0.0.0/0"},
                    {"protocol": "tcp", "from_port": 22, "to_port": 22, "cidr": VPC_CIDR}],
        "egress": []})
    assert put.json() == {"added": 2, "removed": 1}  # two ingress added, default egress revoked
    group = next(g for g in (await c.get(f"{base}/overview")).json()["security_groups"] if g["id"] == sg)
    assert {r["from_port"] for r in group["ingress"]} == {22, 80} and group["egress"] == []
    reset = await c.put(f"{base}/security-groups/{sg}/rules", json={
        "ingress": [{"protocol": "tcp", "from_port": 80, "to_port": 80, "cidr": "0.0.0.0/0"}],
        "egress": [{"protocol": "-1", "from_port": -1, "to_port": -1, "cidr": "0.0.0.0/0"}]})
    assert reset.json() == {"added": 1, "removed": 1}  # SSH ingress revoked, default egress restored


async def test_vpc_console_breakfix_state_is_graded_by_the_pack(world, fake_runner):
    """FakeRunner cannot run break-fix setup jobs, so the broken state is built through the console API
    and graded against the break-fix definition by hand: the fix scoring is covered end-to-end by
    `app.labtest` on real engines (tests/test_vpc.py)."""
    broken = load_pack(BREAKFIX).definition
    c = await login(world.alice)
    a = await _assignment(world, GUIDED, "VPC break-fix state")
    sid = (await c.post(f"/api/assignments/{a.id}/sessions")).json()["id"]
    await wait_state(c, sid, {"READY"})
    base = f"/api/sessions/{sid}/console/vpc"
    vpc = (await c.post(f"{base}/vpcs", json={"name": VPC_NAME, "cidr": VPC_CIDR})).json()["id"]
    subnet = (await c.post(f"{base}/subnets", json={"vpc_id": vpc, "name": SUBNET_NAME, "cidr": SUBNET_CIDR,
                                                    "public": True})).json()["id"]
    igw = (await c.post(f"{base}/internet-gateways", json={"name": IGW_NAME})).json()["id"]
    await c.post(f"{base}/internet-gateways/{igw}/attach", json={"vpc_id": vpc})
    rtb = (await c.post(f"{base}/route-tables", json={"vpc_id": vpc, "name": RTB_NAME})).json()["id"]
    await c.post(f"{base}/route-tables/{rtb}/associate", json={"subnet_id": subnet})
    sg = (await c.post(f"{base}/security-groups", json={
        "vpc_id": vpc, "name": SG_NAME, "description": "web"})).json()["id"]
    await c.put(f"{base}/security-groups/{sg}/rules", json={
        "ingress": [{"protocol": "tcp", "from_port": 22, "to_port": 22, "cidr": VPC_CIDR}], "egress": []})

    from app.grader import evidence as ev_mod
    from app.grader.grade import collectors_for
    from app.labs.render import compute_variables
    from app.models import LabSession

    async with sessionmaker()() as db:
        sess = await db.get(LabSession, sid)
    payload = await ev_mod.capture(sess.emulator_endpoint, collectors_for(broken), sess.engine)
    result = grade(broken, compute_variables(broken, "alice1"), payload)
    assert result["score"] == Decimal("25.00")  # intact network passes, route and HTTP are missing

    await c.post(f"{base}/route-tables/{rtb}/routes", json={"destination_cidr": "0.0.0.0/0",
                                                            "internet_gateway_id": igw})
    payload = await ev_mod.capture(sess.emulator_endpoint, collectors_for(broken), sess.engine)
    assert grade(broken, compute_variables(broken, "alice1"), payload)["score"] == Decimal("65.00")
    group = next(g for g in (await c.get(f"{base}/overview")).json()["security_groups"] if g["id"] == sg)
    await c.put(f"{base}/security-groups/{sg}/rules", json={
        "ingress": group["ingress"] + [{"protocol": "tcp", "from_port": 80, "to_port": 80, "cidr": "0.0.0.0/0"}],
        "egress": group["egress"]})
    payload = await ev_mod.capture(sess.emulator_endpoint, collectors_for(broken), sess.engine)
    assert grade(broken, compute_variables(broken, "alice1"), payload)["score"] == Decimal("100.00")
