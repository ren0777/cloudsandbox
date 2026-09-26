"""Evidence capture (PLAN §5 step 2). Collectors read raw sandbox state through boto3 and return only
stable fields (no timestamps or request IDs), so the normalized form can be compared with a baseline."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from botocore.exceptions import ClientError

from ..runtime import emulators

MAX_OBJECTS_PER_BUCKET = 1000
MAX_ITEMS = 1000
EVIDENCE_FORMAT = 1


def collect_s3(adapter: emulators.EmulatorAdapter, endpoint: str) -> dict[str, Any]:
    c = adapter.client("s3", endpoint)
    buckets: dict[str, Any] = {}
    for b in sorted(x["Name"] for x in c.list_buckets().get("Buckets", [])):
        v = c.get_bucket_versioning(Bucket=b).get("Status")
        try:
            tags = {t["Key"]: t["Value"] for t in c.get_bucket_tagging(Bucket=b).get("TagSet", [])}
        except ClientError as e:
            if e.response["Error"]["Code"] not in ("NoSuchTagSet", "NoSuchTagSetError"):
                raise
            tags = {}
        objects: dict[str, Any] = {}
        truncated = False
        token = None
        while True:
            kw = {"Bucket": b, "MaxKeys": 1000}
            if token:
                kw["ContinuationToken"] = token
            page = c.list_objects_v2(**kw)
            for o in page.get("Contents", []):
                if len(objects) >= MAX_OBJECTS_PER_BUCKET:
                    truncated = True
                    break
                head = c.head_object(Bucket=b, Key=o["Key"])
                objects[o["Key"]] = {"size": o["Size"], "etag": o["ETag"].strip('"'),
                                     "content_type": head.get("ContentType")}
            if truncated or not page.get("IsTruncated"):
                break
            token = page.get("NextContinuationToken")
        buckets[b] = {"versioning": v, "tags": dict(sorted(tags.items())),
                      "objects": dict(sorted(objects.items())), "objects_truncated": truncated}
    return {"buckets": buckets}


def collect_dynamodb(adapter: emulators.EmulatorAdapter, endpoint: str) -> dict[str, Any]:
    """Tables with key schema, capacity mode and up to MAX_ITEMS typed items (canonical, timestamp-free)."""
    c = adapter.client("dynamodb", endpoint)
    names: list[str] = []
    kw: dict[str, Any] = {}
    while True:
        page = c.list_tables(**kw)
        names += page.get("TableNames", [])
        if not page.get("LastEvaluatedTableName"):
            break
        kw = {"ExclusiveStartTableName": page["LastEvaluatedTableName"]}
    tables: dict[str, Any] = {}
    for name in sorted(names):
        d = c.describe_table(TableName=name)["Table"]
        types = {a["AttributeName"]: a["AttributeType"] for a in d.get("AttributeDefinitions", [])}
        ks = {k["KeyType"]: k["AttributeName"] for k in d.get("KeySchema", [])}
        pk = {"name": ks["HASH"], "type": types.get(ks["HASH"], "S")}
        sk = {"name": ks["RANGE"], "type": types.get(ks["RANGE"], "S")} if "RANGE" in ks else None
        mode = (d.get("BillingModeSummary") or {}).get("BillingMode") or "PROVISIONED"
        pt = d.get("ProvisionedThroughput") or {}
        items: dict[str, Any] = {}
        truncated = False
        scan_kw: dict[str, Any] = {"TableName": name}
        while True:
            page = c.scan(**scan_kw)
            for it in page.get("Items", []):
                if len(items) >= MAX_ITEMS:
                    truncated = True
                    break
                key = "|".join(f"{a}={next(iter(it.get(a, {'NULL': True}).values()))}"
                               for a in [pk["name"]] + ([sk["name"]] if sk else []))
                items[key] = {k: it[k] for k in sorted(it)}
            if truncated or not page.get("LastEvaluatedKey"):
                break
            scan_kw["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        tables[name] = {"partition_key": pk, "sort_key": sk, "billing_mode": mode,
                        "read_capacity": pt.get("ReadCapacityUnits") if mode == "PROVISIONED" else None,
                        "write_capacity": pt.get("WriteCapacityUnits") if mode == "PROVISIONED" else None,
                        "items": dict(sorted(items.items())), "item_count": len(items), "items_truncated": truncated}
    return {"tables": tables}


def collect_iam(adapter: emulators.EmulatorAdapter, endpoint: str) -> dict[str, Any]:
    """Users/groups/roles with memberships, attached + inline policies, and the documents of every customer
    managed policy and every attached policy (AWS managed included). No dates or IDs."""
    from .iam_eval import parse_document
    c = adapter.client("iam", endpoint)

    def pages(fn: str, key: str, **kw: Any) -> list[Any]:
        out: list[Any] = []
        while True:
            page = getattr(c, fn)(**kw)
            out += page.get(key, [])
            if not page.get("IsTruncated"):
                return out
            kw["Marker"] = page["Marker"]

    def inline(list_fn: str, get_fn: str, **who: str) -> dict[str, Any]:
        return {n: parse_document(getattr(c, get_fn)(PolicyName=n, **who)["PolicyDocument"])
                for n in sorted(pages(list_fn, "PolicyNames", **who))}

    attached_arns: set[str] = set()
    users: dict[str, Any] = {}
    for u in sorted(x["UserName"] for x in pages("list_users", "Users")):
        att = sorted(p["PolicyArn"] for p in pages("list_attached_user_policies", "AttachedPolicies", UserName=u))
        attached_arns.update(att)
        users[u] = {"groups": sorted(g["GroupName"] for g in pages("list_groups_for_user", "Groups", UserName=u)),
                    "attached": att, "inline": inline("list_user_policies", "get_user_policy", UserName=u)}
    groups: dict[str, Any] = {}
    for g in sorted(x["GroupName"] for x in pages("list_groups", "Groups")):
        att = sorted(p["PolicyArn"] for p in pages("list_attached_group_policies", "AttachedPolicies", GroupName=g))
        attached_arns.update(att)
        groups[g] = {"attached": att, "inline": inline("list_group_policies", "get_group_policy", GroupName=g)}
    roles: dict[str, Any] = {}
    for r in sorted(x["RoleName"] for x in pages("list_roles", "Roles")):
        att = sorted(p["PolicyArn"] for p in pages("list_attached_role_policies", "AttachedPolicies", RoleName=r))
        attached_arns.update(att)
        roles[r] = {"trust": parse_document(c.get_role(RoleName=r)["Role"].get("AssumeRolePolicyDocument", {})),
                    "attached": att, "inline": inline("list_role_policies", "get_role_policy", RoleName=r)}
    local = {p["Arn"] for p in pages("list_policies", "Policies", Scope="Local")}
    policies: dict[str, Any] = {}
    for arn in sorted(local | attached_arns):
        meta = c.get_policy(PolicyArn=arn)["Policy"]
        doc = c.get_policy_version(PolicyArn=arn, VersionId=meta["DefaultVersionId"])["PolicyVersion"]["Document"]
        policies[arn] = {"name": meta["PolicyName"], "document": parse_document(doc),
                         "aws_managed": arn.startswith("arn:aws:iam::aws:")}
    return {"users": users, "groups": groups, "roles": roles, "policies": policies}


def _rules(perms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for perm in perms:
        for rng in perm.get("IpRanges", []):
            out.append({"protocol": str(perm.get("IpProtocol", "-1")), "from_port": perm.get("FromPort"),
                        "to_port": perm.get("ToPort"), "cidr": rng.get("CidrIp")})
    return sorted(out, key=lambda r: (r["protocol"], r["from_port"] or -1, r["cidr"] or ""))


def collect_ec2(adapter: emulators.EmulatorAdapter, endpoint: str) -> dict[str, Any]:
    """Instances (by Name tag), security groups (inbound rules) and key pair names. Engine-specific AMI
    IDs, launch times and IP addresses are deliberately left out."""
    c = adapter.client("ec2", endpoint)
    groups = c.describe_security_groups().get("SecurityGroups", [])
    by_id = {g["GroupId"]: g["GroupName"] for g in groups}
    sgs = {g["GroupName"]: {"description": g.get("Description", ""), "ingress": _rules(g.get("IpPermissions", []))}
           for g in groups}
    instances = []
    kw: dict[str, Any] = {}
    while True:
        page = c.describe_instances(**kw)
        for r in page.get("Reservations", []):
            for i in r.get("Instances", []):
                tags = {t["Key"]: t["Value"] for t in i.get("Tags", [])}
                instances.append({"id": i["InstanceId"], "name": tags.get("Name", ""), "state": i["State"]["Name"],
                                  "type": i.get("InstanceType"), "key_name": i.get("KeyName"),
                                  "security_groups": sorted(g.get("GroupName") or by_id.get(g.get("GroupId"), "")
                                                            for g in i.get("SecurityGroups", [])),
                                  "tags": dict(sorted(tags.items()))})
        if not page.get("NextToken"):
            break
        kw = {"NextToken": page["NextToken"]}
    keys = sorted(k["KeyName"] for k in c.describe_key_pairs().get("KeyPairs", []))
    return {"instances": sorted(instances, key=lambda i: (i["name"], i["id"])), "security_groups": dict(sorted(sgs.items())),
            "key_pairs": keys}


def collect_lambda(adapter: emulators.EmulatorAdapter, endpoint: str, probes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Runs the lab's invocation probes FIRST (their output and side effects become evidence), then records
    function configuration. No timestamps, versions or code locations."""
    import json as _json

    from .checks.lambda_ import probe_key
    c = adapter.client("lambda", endpoint)
    invocations: dict[str, Any] = {}
    for p in probes or []:
        if p.get("kind") != "lambda_invoke":
            continue
        key = probe_key(p["function"], p["payload"])
        try:
            r = c.invoke(FunctionName=p["function"], Payload=_json.dumps(p["payload"]).encode())
            raw = r["Payload"].read().decode("utf-8", "replace")
            try:
                body: Any = _json.loads(raw) if raw else None
            except ValueError:
                body = raw[:2000]
            invocations[key] = {"status": r.get("StatusCode"), "error": r.get("FunctionError"), "payload": body}
        except ClientError as e:
            invocations[key] = {"status": None, "error": e.response.get("Error", {}).get("Code", "error"), "payload": None}
    functions: dict[str, Any] = {}
    kw: dict[str, Any] = {}
    while True:
        page = c.list_functions(**kw)
        for f in page.get("Functions", []):
            functions[f["FunctionName"]] = {
                "runtime": f.get("Runtime"), "handler": f.get("Handler"),
                "role_name": (f.get("Role") or "").rsplit("/", 1)[-1] or None,
                "memory": f.get("MemorySize"), "timeout": f.get("Timeout"),
                "env": dict(sorted(((f.get("Environment") or {}).get("Variables") or {}).items()))}
        if not page.get("NextMarker"):
            break
        kw = {"Marker": page["NextMarker"]}
    return {"functions": dict(sorted(functions.items())), "invocations": dict(sorted(invocations.items()))}


COLLECTORS: dict[str, Callable[[emulators.EmulatorAdapter, str], dict[str, Any]]] = {
    "s3": collect_s3, "dynamodb": collect_dynamodb, "iam": collect_iam, "ec2": collect_ec2, "lambda": collect_lambda}


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()


def normalized(payload: dict[str, Any]) -> dict[str, Any]:
    """Graded-resource state only: drops volatile envelope fields."""
    return {"format": payload.get("format"), "collectors": payload.get("collectors", {})}


def digest(payload: dict[str, Any]) -> tuple[str, str]:
    return (hashlib.sha256(canonical(payload)).hexdigest(),
            hashlib.sha256(canonical(normalized(payload))).hexdigest())


async def capture(endpoint: str, collectors: list[str], engine: str,
                  probes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Run collectors in a thread (boto3 is blocking). Raises on any infrastructure error. The evidence
    format is engine-independent; the engine only selects the client configuration."""
    adapter = emulators.get(engine)

    def run() -> dict[str, Any]:
        out: dict[str, Any] = {}
        names = sorted(set(collectors))
        if "lambda" in names:  # probes run first so their side effects are visible to the other collectors
            names.remove("lambda")
            out["lambda"] = collect_lambda(adapter, endpoint, probes)
        for name in names:
            if name not in COLLECTORS:
                raise RuntimeError(f"no collector {name!r}")
            out[name] = COLLECTORS[name](adapter, endpoint)
        return out
    data = await asyncio.to_thread(run)
    return {"format": EVIDENCE_FORMAT, "captured_at": datetime.now(timezone.utc).isoformat(),
            "collectors": data}
