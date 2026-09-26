"""Phase 6 — architecture diagram: pure graph from collector evidence; live read-only endpoint; attempt diagrams."""

from __future__ import annotations

from app.diagram import build_graph
from app.sessions import service
from tests.conftest import idem, login, wait_state

BUCKET = "cafe-alice1-site"


def ids(g):
    return {n["id"] for n in g["nodes"]}


def test_graph_from_every_collector():
    admin_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
    unused_aws = "arn:aws:iam::aws:policy/ReadOnlyAccess"
    mine = "arn:aws:iam::123456789012:policy/menu-read"
    g = build_graph({
        "s3": {"buckets": {"b1": {"versioning": "Enabled", "objects": {"a": {}, "b": {}}, "objects_truncated": False}}},
        "dynamodb": {"tables": {"orders": {"partition_key": {"name": "orderId", "type": "S"}, "sort_key": None,
                                           "billing_mode": "PAY_PER_REQUEST", "item_count": 1}}},
        "iam": {"users": {"sam": {"groups": ["baristas"], "attached": [], "inline": {"x": {}}}},
                "groups": {"baristas": {"attached": [admin_arn, mine], "inline": {}}},
                "roles": {"fn-role": {"trust": {"Statement": [{"Principal": {"Service": "lambda.amazonaws.com"}}]},
                                      "attached": [], "inline": {}}},
                "policies": {admin_arn: {"name": "AdministratorAccess", "aws_managed": True},
                             unused_aws: {"name": "ReadOnlyAccess", "aws_managed": True},
                             mine: {"name": "menu-read", "aws_managed": False}}},
        "ec2": {"instances": [{"id": "i-1", "name": "web", "state": "running", "type": "t3.micro", "key_name": "k",
                               "security_groups": ["web-sg", "gone-sg"]},
                              {"id": "i-2", "name": "old", "state": "terminated", "type": "t2.micro",
                               "key_name": None, "security_groups": []}],
                "security_groups": {"web-sg": {"ingress": [{"protocol": "tcp", "from_port": 22, "to_port": 22,
                                                            "cidr": "0.0.0.0/0"}]}},
                "key_pairs": ["k"]},
        "lambda": {"functions": {"fn": {"runtime": "python3.12", "memory": 256, "timeout": 10,
                                        "role_name": "fn-role", "env": {"A": "1"}}}},
    })
    assert ids(g) == {"s3:b1", "dynamodb:orders", "iam:user:sam", "iam:group:baristas", "iam:role:fn-role",
                      f"iam:policy:{admin_arn}", f"iam:policy:{mine}", "ec2:instance:i-1", "ec2:sg:web-sg",
                      "ec2:key:k", "lambda:fn"}  # unused AWS policy and terminated instance omitted
    edges = {(e["source"], e["target"], e["kind"]) for e in g["edges"]}
    assert ("iam:user:sam", "iam:group:baristas", "member of") in edges
    assert ("iam:group:baristas", f"iam:policy:{admin_arn}", "attached") in edges
    assert ("ec2:instance:i-1", "ec2:sg:web-sg", "uses") in edges
    assert ("lambda:fn", "iam:role:fn-role", "runs as") in edges
    assert not any(t == "ec2:sg:gone-sg" for _, t, _ in edges)  # dangling edges dropped
    by = {n["id"]: n for n in g["nodes"]}
    assert by["s3:b1"]["detail"] == "2 objects · versioning enabled"
    assert by["dynamodb:orders"]["detail"] == "key orderId (S) · on-demand · 1 item"
    assert by["iam:user:sam"]["detail"] == "0 managed policies · 1 inline policy"
    assert by["iam:group:baristas"]["flags"] == ["AdministratorAccess attached"]
    assert by["ec2:sg:web-sg"]["flags"] == ["SSH open to the internet"] and by["ec2:sg:web-sg"]["state"] == "warn"
    assert "trusts lambda" in by["iam:role:fn-role"]["detail"]
    assert g["lanes"] == ["principals", "policies", "compute", "network", "data"]
    assert build_graph({}) == {"nodes": [], "edges": [], "lanes": []}


def test_all_traffic_rule_flags_remote_ports():
    g = build_graph({"ec2": {"instances": [], "key_pairs": [], "security_groups": {
        "open": {"ingress": [{"protocol": "-1", "from_port": None, "to_port": None, "cidr": "0.0.0.0/0"}]},
        "campus": {"ingress": [{"protocol": "tcp", "from_port": 22, "to_port": 22, "cidr": "10.20.0.0/16"}]}}}})
    by = {n["id"]: n for n in g["nodes"]}
    assert by["ec2:sg:open"]["flags"] == ["RDP open to the internet", "SSH open to the internet"]
    assert by["ec2:sg:campus"]["flags"] == []


async def test_live_architecture_follows_the_sandbox(world, fake_runner, monkeypatch):
    monkeypatch.setattr(service, "INVENTORY_TTL_S", 0.0)
    c = await login(world.alice)
    sid = (await c.post(f"/api/assignments/{world.assignment.id}/sessions")).json()["id"]
    await wait_state(c, sid, {"READY"})
    url = f"/api/sessions/{sid}/architecture"
    r = (await c.get(url)).json()
    assert r["graph"]["nodes"] == [] and r["captured_at"]
    assert (await c.post(f"/api/sessions/{sid}/console/s3/buckets", json={"name": BUCKET})).status_code in (200, 201)
    r = (await c.get(url)).json()
    assert ids(r["graph"]) == {f"s3:{BUCKET}"}
    assert (await c.delete(f"/api/sessions/{sid}/console/s3/buckets/{BUCKET}")).status_code in (200, 204)
    assert (await c.get(url)).json()["graph"]["nodes"] == []
    # only the owner, only while running
    assert (await (await login(world.bob)).get(url)).status_code == 404
    assert (await (await login(world.instructor)).get(url)).status_code == 403
    assert (await c.post(f"/api/sessions/{sid}/console/s3/buckets", json={"name": BUCKET})).status_code in (200, 201)
    res = (await c.post(f"/api/sessions/{sid}/submit", headers=idem())).json()
    assert ids(res["insights"]["graph"]) == {f"s3:{BUCKET}"}  # what was built at submission (final evidence)
    assert (await c.get(url)).status_code == 409
    inst = await login(world.instructor)
    detail = (await inst.get(f"/api/instructor/attempts/{res['attempt']['id']}")).json()
    assert ids(detail["insights"]["graph"]) == {f"s3:{BUCKET}"}


async def test_snapshot_is_cached(world, fake_runner):
    c = await login(world.alice)
    sid = (await c.post(f"/api/assignments/{world.assignment.id}/sessions")).json()["id"]
    await wait_state(c, sid, {"READY"})
    first = (await c.get(f"/api/sessions/{sid}/architecture")).json()
    await c.post(f"/api/sessions/{sid}/console/s3/buckets", json={"name": BUCKET})
    second = (await c.get(f"/api/sessions/{sid}/architecture")).json()
    assert second == first  # within the cache window: polling can't hammer the sandbox
