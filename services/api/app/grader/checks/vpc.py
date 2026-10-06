"""VPC checks. Evidence shape (collector 'vpc'), engine-independent (no ids, ARNs or AZs):
{"vpcs": {name: {"name", "cidr", "is_default"}},
 "subnets": {name: {"name", "cidr", "vpc", "public"}},
 "route_tables": {name: {"name", "vpc", "routes": [{"destination", "target"}],
                          "associations": [{"subnet", "main"}]}},
 "internet_gateways": {name: {"name", "vpc"}},
 "security_groups": {name: {"name", "description", "vpc", "ingress": [...], "egress": [...]}}}

Resources are addressed by their `Name` tag, exactly as the VPC console shows them. Routes name their
target as "local" or "igw:<internet-gateway name>"."""

from typing import Literal

from pydantic import Field

from ..registry import CheckOutcome, Params, check

NAME = Field(min_length=1, max_length=255)
CIDR = r"^\d{1,3}(\.\d{1,3}){3}/\d{1,2}$"


def _vpc(ev: dict) -> dict:
    return ev.get("vpc", {})


def _covers(rule: dict, protocol: str, port: int) -> bool:
    if rule.get("protocol") == "-1":
        return True
    return rule.get("protocol") == protocol and (
        rule.get("from_port") is None or rule["from_port"] <= port <= (rule.get("to_port") or port))


class VpcParams(Params):
    name: str = NAME
    cidr: str = Field(pattern=CIDR)


@check("vpc.exists", VpcParams, "vpc", ["vpc:DescribeVpcs"])
def exists(p: VpcParams, ev: dict) -> CheckOutcome:
    want = f"{p.name} ({p.cidr})"
    v = _vpc(ev).get("vpcs", {}).get(p.name)
    if v is None:
        return CheckOutcome(False, want, "not found",
                            f"No VPC named {p.name} (deleted or never created; the default VPC has no name)")
    actual = f"{v['name']} ({v.get('cidr')})" if v.get("name") else f"(unnamed) ({v.get('cidr')})"
    ok = v.get("cidr") == p.cidr
    return CheckOutcome(ok, want, actual,
                        f"VPC {p.name} has CIDR {p.cidr}" if ok
                        else f"VPC {p.name} has CIDR {v.get('cidr')}, not {p.cidr}")


class SubnetParams(Params):
    name: str = NAME
    cidr: str = Field(pattern=CIDR)
    vpc: str | None = NAME
    public: bool | None = None


@check("vpc.subnet", SubnetParams, "vpc", ["vpc:DescribeVpcs", "vpc:DescribeSubnets"])
def subnet(p: SubnetParams, ev: dict) -> CheckOutcome:
    want = ", ".join([f"{p.name} ({p.cidr})"] + ([f"in VPC {p.vpc}"] if p.vpc else [])
                     + ([f"public={p.public}"] if p.public is not None else []))
    s = _vpc(ev).get("subnets", {}).get(p.name)
    if s is None:
        return CheckOutcome(False, want, "not found", f"No subnet named {p.name}")
    problems = []
    if s.get("cidr") != p.cidr:
        problems.append(f"its CIDR is {s.get('cidr')}")
    if p.vpc and s.get("vpc") != p.vpc:
        problems.append(f"it is in VPC {s.get('vpc') or '-'}, not {p.vpc}")
    if p.public is not None and bool(s.get("public")) != p.public:
        problems.append(f"public is {bool(s.get('public'))}")
    actual = f"{s['name']} ({s.get('cidr')}) in {s.get('vpc') or '-'}, public={bool(s.get('public'))}"
    return CheckOutcome(not problems, want, actual,
                        f"Subnet {p.name} is in {s.get('vpc')}, CIDR {s.get('cidr')}" if not problems
                        else f"Subnet {p.name}: " + "; ".join(problems))


class RouteParams(Params):
    route_table: str = NAME
    destination: str = Field(pattern=CIDR)
    target: str = Field(pattern=r"^(local|igw:.+)$")
    expect: Literal["present", "absent"] = "present"


@check("vpc.route", RouteParams, "vpc", ["vpc:DescribeRouteTables"])
def route(p: RouteParams, ev: dict) -> CheckOutcome:
    want = f"{p.destination} -> {p.target} ({p.expect})"
    rt = _vpc(ev).get("route_tables", {}).get(p.route_table)
    if rt is None:
        return CheckOutcome(False, want, "no route table", f"No route table named {p.route_table}")
    hit = any(r.get("destination") == p.destination and r.get("target") == p.target for r in rt.get("routes", []))
    routes = ", ".join(f"{r.get('destination')}->{r.get('target')}" for r in rt.get("routes", [])) or "no routes"
    if p.expect == "absent":
        return CheckOutcome(not hit, want, routes,
                            f"{p.route_table} has no route {p.destination} -> {p.target}" if not hit
                            else f"{p.route_table} still has {p.destination} -> {p.target}")
    return CheckOutcome(hit, want, routes,
                        f"{p.route_table} routes {p.destination} to {p.target}" if hit
                        else f"{p.route_table} does not route {p.destination} to {p.target} (routes: {routes})")


class SubnetRouteTableParams(Params):
    subnet: str = NAME
    route_table: str = NAME
    expect: Literal["present", "absent"] = "present"


@check("vpc.subnet_route_table", SubnetRouteTableParams, "vpc",
       ["vpc:DescribeSubnets", "vpc:DescribeRouteTables"])
def subnet_route_table(p: SubnetRouteTableParams, ev: dict) -> CheckOutcome:
    want = f"{p.subnet} uses {p.route_table} ({p.expect})"
    rt = _vpc(ev).get("route_tables", {}).get(p.route_table)
    if rt is None:
        return CheckOutcome(False, want, "no route table", f"No route table named {p.route_table}")
    attached = [a.get("subnet") for a in rt.get("associations", [])]
    hit = p.subnet in attached
    if p.expect == "absent":
        return CheckOutcome(not hit, want, ", ".join(attached) or "no subnets",
                            f"{p.route_table} is not associated with {p.subnet}" if not hit
                            else f"{p.route_table} is still associated with {p.subnet}")
    return CheckOutcome(hit, want, ", ".join(attached) or "no subnets",
                        f"{p.route_table} is associated with {p.subnet}" if hit
                        else f"{p.route_table} is not associated with {p.subnet} "
                             f"(associated subnets: {', '.join(attached) or 'none'})")


class IgwParams(Params):
    internet_gateway: str = NAME
    vpc: str = NAME
    expect: Literal["present", "absent"] = "present"


@check("vpc.internet_gateway_attached", IgwParams, "vpc",
       ["vpc:DescribeInternetGateways", "vpc:DescribeVpcs"])
def internet_gateway_attached(p: IgwParams, ev: dict) -> CheckOutcome:
    want = f"{p.internet_gateway} attached to {p.vpc} ({p.expect})"
    g = _vpc(ev).get("internet_gateways", {}).get(p.internet_gateway)
    if g is None:
        return CheckOutcome(False, want, "not found", f"No internet gateway named {p.internet_gateway}")
    hit = g.get("vpc") == p.vpc
    actual = f"attached to {g.get('vpc') or '-'}"
    if p.expect == "absent":
        return CheckOutcome(not hit, want, actual,
                            f"{p.internet_gateway} is not attached to {p.vpc}" if not hit
                            else f"{p.internet_gateway} is still attached to {p.vpc}")
    return CheckOutcome(hit, want, actual,
                        f"{p.internet_gateway} is attached to {p.vpc}" if hit
                        else f"{p.internet_gateway} is not attached to {p.vpc}")


class SgRuleParams(Params):
    group: str = NAME
    direction: Literal["ingress", "egress"] = "ingress"
    protocol: Literal["tcp", "udp", "icmp", "-1"] = "tcp"
    port: int = Field(ge=-1, le=65535)
    cidr: str = Field(pattern=CIDR)
    expect: Literal["present", "absent"] = "present"


@check("vpc.security_group_rule", SgRuleParams, "vpc", ["vpc:DescribeSecurityGroups"])
def security_group_rule(p: SgRuleParams, ev: dict) -> CheckOutcome:
    want = f"{p.direction} {p.protocol}/{p.port} from {p.cidr} ({p.expect})"
    g = _vpc(ev).get("security_groups", {}).get(p.group)
    if g is None:
        return CheckOutcome(False, want, "no security group", f"No security group named {p.group}")
    rules = g.get(p.direction, [])
    hit = any(r.get("cidr") == p.cidr and _covers(r, p.protocol, p.port) for r in rules)
    actual = ", ".join(f"{r.get('protocol')}/{r.get('from_port')}-{r.get('to_port')} {r.get('cidr')}"
                       for r in rules) or "no rules"
    if p.expect == "absent":
        return CheckOutcome(not hit, want, actual,
                            f"{p.group} no longer allows {p.protocol}/{p.port} from {p.cidr}" if not hit
                            else f"{p.group} still allows {p.protocol}/{p.port} from {p.cidr}")
    return CheckOutcome(hit, want, actual,
                        f"{p.group} allows {p.protocol}/{p.port} from {p.cidr}" if hit
                        else f"{p.group} does not allow {p.protocol}/{p.port} from {p.cidr} ({actual})")
