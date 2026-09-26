"""Architecture diagram (phase 6): a pure function from grading-collector evidence to a graph of the
student's resources. It has no emulator access of its own, so it works the same for a live read-only snapshot
of a running sandbox (`/sessions/{id}/architecture`) and for the stored evidence of a submitted attempt.

Graph: nodes {id, service, kind, label, detail, state, flags} and edges {source, target, kind}. Lanes group
nodes for layout (principals, policies, compute, network, data). Flags are the same best-practice warnings
the AWS console shows (SSH/RDP open to the internet, AdministratorAccess attached) — never lab-specific."""

from __future__ import annotations

from typing import Any

LANES = ("principals", "policies", "compute", "network", "data")
ADMIN_POLICY = "AdministratorAccess"
REMOTE_PORTS = {22: "SSH", 3389: "RDP"}


def _node(nid: str, service: str, kind: str, label: str, lane: str, detail: str = "", state: str = "ok",
          flags: list[str] | None = None) -> dict[str, Any]:
    return {"id": nid, "service": service, "kind": kind, "label": label, "lane": lane, "detail": detail,
            "state": state, "flags": flags or []}


def _plural(n: int, word: str, plural: str | None = None) -> str:
    return f"{n} {word if n == 1 else (plural or word + 's')}"


def build_graph(collectors: dict[str, Any]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    # ---- S3
    for name, b in sorted((collectors.get("s3") or {}).get("buckets", {}).items()):
        n = len(b.get("objects", {}))
        more = "+" if b.get("objects_truncated") else ""
        v = b.get("versioning") or "Never enabled"
        nodes.append(_node(f"s3:{name}", "s3", "bucket", name, "data",
                           f"{n}{more} object{'' if n == 1 else 's'} · versioning {v.lower()}"))

    # ---- DynamoDB
    for name, t in sorted((collectors.get("dynamodb") or {}).get("tables", {}).items()):
        pk = t.get("partition_key") or {}
        sk = t.get("sort_key")
        key = f"{pk.get('name')} ({pk.get('type')})" + (f" + {sk['name']} ({sk['type']})" if sk else "")
        mode = "on-demand" if t.get("billing_mode") == "PAY_PER_REQUEST" else \
            f"provisioned {t.get('read_capacity')}/{t.get('write_capacity')}"
        nodes.append(_node(f"dynamodb:{name}", "dynamodb", "table", name, "data",
                           f"key {key} · {mode} · {_plural(t.get('item_count', 0), 'item')}"))

    # ---- IAM
    iam = collectors.get("iam") or {}
    policies = iam.get("policies", {})
    used_policies: set[str] = set()

    def policy_name(arn: str) -> str:
        return policies.get(arn, {}).get("name") or arn.rsplit("/", 1)[-1]

    def principal(kind: str, name: str, e: dict) -> None:
        attached = e.get("attached", [])
        flags = ["AdministratorAccess attached"] if any(policy_name(a) == ADMIN_POLICY for a in attached) else []
        inline = len(e.get("inline", {}))
        parts = [_plural(len(attached), "managed policy", "managed policies")]
        if inline:
            parts.append(_plural(inline, "inline policy", "inline policies"))
        if kind == "role":
            services = sorted({s for st in (e.get("trust", {}).get("Statement") or [])
                               for s in _as_list((st.get("Principal") or {}).get("Service"))})
            if services:
                parts.append("trusts " + ", ".join(s.replace(".amazonaws.com", "") for s in services))
        nid = f"iam:{kind}:{name}"
        nodes.append(_node(nid, "iam", kind, name, "principals", " · ".join(parts), "warn" if flags else "ok", flags))
        for arn in attached:
            used_policies.add(arn)
            edges.append({"source": nid, "target": f"iam:policy:{arn}", "kind": "attached"})

    for name, u in sorted(iam.get("users", {}).items()):
        principal("user", name, u)
        for g in u.get("groups", []):
            edges.append({"source": f"iam:user:{name}", "target": f"iam:group:{g}", "kind": "member of"})
    for name, g in sorted(iam.get("groups", {}).items()):
        principal("group", name, g)
    for name, r in sorted(iam.get("roles", {}).items()):
        principal("role", name, r)
    for arn, p in sorted(policies.items(), key=lambda kv: kv[1].get("name", kv[0])):
        if p.get("aws_managed") and arn not in used_policies:
            continue  # only show AWS managed policies that are actually attached
        flags = ["full admin"] if p.get("name") == ADMIN_POLICY else []
        nodes.append(_node(f"iam:policy:{arn}", "iam", "policy", p.get("name") or arn, "policies",
                           "AWS managed" if p.get("aws_managed") else "customer managed",
                           "warn" if flags else "ok", flags))

    # ---- EC2
    ec2 = collectors.get("ec2") or {}
    for i in ec2.get("instances", []):
        if i.get("state") == "terminated":
            continue
        nid = f"ec2:instance:{i['id']}"
        nodes.append(_node(nid, "ec2", "instance", i.get("name") or i["id"], "compute",
                           f"{i.get('type')} · {i.get('state')}", "ok" if i.get("state") == "running" else "off"))
        for g in i.get("security_groups", []):
            edges.append({"source": nid, "target": f"ec2:sg:{g}", "kind": "uses"})
        if i.get("key_name"):
            edges.append({"source": nid, "target": f"ec2:key:{i['key_name']}", "kind": "key pair"})
    for name, g in sorted(ec2.get("security_groups", {}).items()):
        flags = []
        for r in g.get("ingress", []):
            if r.get("cidr") != "0.0.0.0/0":
                continue
            for port, label in REMOTE_PORTS.items():
                lo, hi = r.get("from_port"), r.get("to_port")
                if r.get("protocol") == "-1" or (lo is not None and hi is not None and lo <= port <= hi):
                    flags.append(f"{label} open to the internet")
        flags = sorted(set(flags))
        nodes.append(_node(f"ec2:sg:{name}", "ec2", "security_group", name, "network",
                           _plural(len(g.get("ingress", [])), "inbound rule"), "warn" if flags else "ok", flags))
    for k in ec2.get("key_pairs", []):
        nodes.append(_node(f"ec2:key:{k}", "ec2", "key_pair", k, "network", "key pair"))

    # ---- Lambda
    for name, f in sorted((collectors.get("lambda") or {}).get("functions", {}).items()):
        nid = f"lambda:{name}"
        env = len(f.get("env") or {})
        nodes.append(_node(nid, "lambda", "function", name, "compute",
                           f"{f.get('runtime')} · {f.get('memory')} MB · {f.get('timeout')} s"
                           + (f" · {_plural(env, 'env var')}" if env else "")))
        if f.get("role_name"):
            edges.append({"source": nid, "target": f"iam:role:{f['role_name']}", "kind": "runs as"})

    ids = {n["id"] for n in nodes}
    edges = [e for e in edges if e["source"] in ids and e["target"] in ids]  # e.g. a deleted security group
    lanes = [lane for lane in LANES if any(n["lane"] == lane for n in nodes)]
    return {"nodes": nodes, "edges": edges, "lanes": lanes}


def _as_list(v: Any) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]
