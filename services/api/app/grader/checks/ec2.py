"""EC2 checks. Evidence shape (collector 'ec2'), engine-independent (no AMI IDs, times or IPs):
{"instances": [{"id", "name", "state", "type", "key_name", "security_groups": [names], "tags": {k: v}}],
 "security_groups": {name: {"description", "ingress": [{"protocol", "from_port", "to_port", "cidr"}]}},
 "key_pairs": [names]}
Instances are matched by their Name tag and must not be terminated."""

from typing import Literal

from pydantic import Field

from ..registry import CheckOutcome, Params, check

NAME = Field(min_length=1, max_length=255)
READS = ["ec2:DescribeInstances", "ec2:DescribeSecurityGroups", "ec2:DescribeKeyPairs"]


def _ec2(ev: dict) -> dict:
    return ev.get("ec2", {})


def _instance(ev: dict, name: str) -> dict | None:
    live = [i for i in _ec2(ev).get("instances", []) if i["name"] == name and i["state"] != "terminated"]
    return live[0] if live else None


class InstanceParams(Params):
    name: str = NAME
    state: Literal["running", "stopped", "any"] = "running"
    instance_type: str | None = Field(None, pattern=r"^[a-z0-9]+\.[a-z0-9]+$")
    key_name: str | None = None


@check("ec2.instance", InstanceParams, "ec2", READS)
def instance(p: InstanceParams, ev: dict) -> CheckOutcome:
    want = [f"state={p.state}"] + ([f"type={p.instance_type}"] if p.instance_type else []) + \
           ([f"key={p.key_name}"] if p.key_name else [])
    i = _instance(ev, p.name)
    if i is None:
        return CheckOutcome(False, ", ".join(want), "not found", f"No instance named {p.name} (terminated instances don't count)")
    actual = f"state={i['state']}, type={i['type']}, key={i.get('key_name') or '-'}"
    problems = []
    if p.state != "any" and i["state"] != p.state:
        problems.append(f"it is {i['state']}")
    if p.instance_type and i["type"] != p.instance_type:
        problems.append(f"its type is {i['type']}, not {p.instance_type}")
    if p.key_name and i.get("key_name") != p.key_name:
        problems.append(f"it doesn't use key pair {p.key_name}")
    return CheckOutcome(not problems, ", ".join(want), actual,
                        f"Instance {p.name} is {i['state']} ({i['type']})" if not problems
                        else f"Instance {p.name}: " + "; ".join(problems))


class InstanceTagParams(Params):
    name: str = NAME
    key: str = Field(min_length=1, max_length=128)
    value: str = Field(max_length=256)


@check("ec2.instance_tag", InstanceTagParams, "ec2", READS)
def instance_tag(p: InstanceTagParams, ev: dict) -> CheckOutcome:
    i = _instance(ev, p.name)
    if i is None:
        return CheckOutcome(False, f"{p.key}={p.value}", "instance missing", f"No instance named {p.name}")
    actual = i.get("tags", {}).get(p.key)
    ok = actual == p.value
    return CheckOutcome(ok, f"{p.key}={p.value}", f"{p.key}={actual}" if actual is not None else "tag missing",
                        f"Instance {p.name} is tagged {p.key}={p.value}" if ok
                        else f"Instance {p.name} should have tag {p.key}={p.value}")


class InstanceSgParams(Params):
    name: str = NAME
    group: str = NAME


@check("ec2.instance_security_group", InstanceSgParams, "ec2", READS)
def instance_security_group(p: InstanceSgParams, ev: dict) -> CheckOutcome:
    i = _instance(ev, p.name)
    if i is None:
        return CheckOutcome(False, p.group, "instance missing", f"No instance named {p.name}")
    ok = p.group in i.get("security_groups", [])
    return CheckOutcome(ok, p.group, ", ".join(i.get("security_groups", [])) or "none",
                        f"Instance {p.name} uses {p.group}" if ok else f"Instance {p.name} should use security group {p.group}")


class RuleParams(Params):
    group: str = NAME
    protocol: Literal["tcp", "udp", "icmp", "-1"] = "tcp"
    port: int = Field(ge=-1, le=65535)
    cidr: str = Field(pattern=r"^\d{1,3}(\.\d{1,3}){3}/\d{1,2}$")
    expect: Literal["present", "absent"] = "present"


def _covers(rule: dict, protocol: str, port: int) -> bool:
    if rule["protocol"] == "-1":
        return True
    return rule["protocol"] == protocol and (rule["from_port"] is None or rule["from_port"] <= port <= rule["to_port"])


@check("ec2.security_group_rule", RuleParams, "ec2", READS)
def security_group_rule(p: RuleParams, ev: dict) -> CheckOutcome:
    g = _ec2(ev).get("security_groups", {}).get(p.group)
    exp = f"{p.protocol}/{p.port} from {p.cidr} {p.expect}"
    if g is None:
        return CheckOutcome(False, exp, "group missing", f"Security group {p.group} was not found")
    matching = [r for r in g.get("ingress", []) if r["cidr"] == p.cidr and _covers(r, p.protocol, p.port)]
    present = bool(matching)
    actual = "; ".join(f"{r['protocol']}/{r['from_port']}-{r['to_port']} from {r['cidr']}" for r in g.get("ingress", [])) or "no inbound rules"
    ok = present == (p.expect == "present")
    if ok:
        msg = f"{p.group} {'allows' if present else 'does not allow'} port {p.port} from {p.cidr}"
    else:
        msg = f"{p.group} should {'allow' if p.expect == 'present' else 'not allow'} port {p.port} from {p.cidr}"
    return CheckOutcome(ok, exp, actual, msg)


class KeyPairParams(Params):
    key: str = NAME


@check("ec2.key_pair_exists", KeyPairParams, "ec2", READS)
def key_pair_exists(p: KeyPairParams, ev: dict) -> CheckOutcome:
    ok = p.key in _ec2(ev).get("key_pairs", [])
    return CheckOutcome(ok, "exists", "exists" if ok else "missing",
                        f"Key pair {p.key} exists" if ok else f"Key pair {p.key} was not found")


class CountParams(Params):
    min: int = Field(0, ge=0, le=100)
    max: int = Field(ge=0, le=100)


@check("ec2.running_instance_count", CountParams, "ec2", READS)
def running_instance_count(p: CountParams, ev: dict) -> CheckOutcome:
    n = sum(1 for i in _ec2(ev).get("instances", []) if i["state"] == "running")
    ok = p.min <= n <= p.max
    exp = f"{p.min}-{p.max} running" if p.min != p.max else f"{p.max} running"
    if ok:
        msg = f"{n} instance(s) running"
    elif n > p.max:
        msg = f"{n} instances are running; keep at most {p.max} to control cost"
    else:
        msg = f"{n} instances are running; at least {p.min} should be"
    return CheckOutcome(ok, exp, f"{n} running", msg)
