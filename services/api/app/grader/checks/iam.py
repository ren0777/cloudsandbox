"""IAM checks. Evidence shape (collector 'iam'), engine-independent, no dates or IDs:
{"users":  {name: {"groups": [..], "attached": [arn], "inline": {policy_name: document}}},
 "groups": {name: {"attached": [arn], "inline": {...}}},
 "roles":  {name: {"trust": document, "attached": [arn], "inline": {...}}},
 "policies": {arn: {"name": str, "document": document, "aws_managed": bool}}}
`iam.policy_allows` uses the CloudLabs evaluator (grader/iam_eval.py, support level `simulated`)."""

from typing import Literal

from pydantic import Field

from ..iam_eval import evaluate, principal_policies
from ..registry import CheckOutcome, Params, check

NAME = Field(min_length=1, max_length=128, pattern=r"^[\w+=,.@-]+$")
PRINCIPAL = Field(pattern=r"^(user|group|role):[\w+=,.@-]{1,128}$")
READS = ["iam:ListUsers", "iam:ListGroupsForUser", "iam:ListGroups", "iam:ListRoles",
         "iam:ListAttachedUserPolicies", "iam:ListAttachedGroupPolicies", "iam:ListAttachedRolePolicies",
         "iam:ListUserPolicies", "iam:GetUserPolicy", "iam:ListPolicies", "iam:GetPolicy", "iam:GetPolicyVersion"]


def _iam(ev: dict) -> dict:
    return ev.get("iam", {})


class UserParams(Params):
    user: str = NAME


@check("iam.user_exists", UserParams, "iam", READS)
def user_exists(p: UserParams, ev: dict) -> CheckOutcome:
    ok = p.user in _iam(ev).get("users", {})
    return CheckOutcome(ok, "exists", "exists" if ok else "missing",
                        f"IAM user {p.user} exists" if ok else f"IAM user {p.user} was not found")


class GroupParams(Params):
    group: str = NAME


@check("iam.group_exists", GroupParams, "iam", READS)
def group_exists(p: GroupParams, ev: dict) -> CheckOutcome:
    ok = p.group in _iam(ev).get("groups", {})
    return CheckOutcome(ok, "exists", "exists" if ok else "missing",
                        f"User group {p.group} exists" if ok else f"User group {p.group} was not found")


class MemberParams(Params):
    user: str = NAME
    group: str = NAME
    expect: Literal["present", "absent"] = "present"  # absent: break-fix "remove this membership"


@check("iam.user_in_group", MemberParams, "iam", READS)
def user_in_group(p: MemberParams, ev: dict) -> CheckOutcome:
    u = _iam(ev).get("users", {}).get(p.user)
    if p.expect == "absent":
        groups = (u or {}).get("groups", [])
        ok = p.group not in groups
        return CheckOutcome(ok, f"not a member of {p.group}", "user deleted" if u is None else (", ".join(groups) or "no groups"),
                            f"{p.user} is not in {p.group}" if ok else f"{p.user} should no longer be a member of {p.group}")
    if u is None:
        return CheckOutcome(False, f"member of {p.group}", "user missing", f"IAM user {p.user} was not found")
    groups = u.get("groups", [])
    ok = p.group in groups
    return CheckOutcome(ok, f"member of {p.group}", ", ".join(groups) or "no groups",
                        f"{p.user} is in {p.group}" if ok else f"{p.user} should be a member of {p.group}")


class AttachedParams(Params):
    principal: str = PRINCIPAL
    policy: str = Field(min_length=1, max_length=2048)  # policy name or ARN
    expect: Literal["present", "absent"] = "present"  # absent: break-fix "detach this policy"


@check("iam.policy_attached", AttachedParams, "iam", READS)
def policy_attached(p: AttachedParams, ev: dict) -> CheckOutcome:
    kind, _, name = p.principal.partition(":")
    e = _iam(ev).get(f"{kind}s", {}).get(name)
    if e is None:
        return CheckOutcome(False, f"{p.policy} attached", f"{kind} missing", f"{kind.capitalize()} {name} was not found")
    policies = _iam(ev).get("policies", {})
    names = [policies.get(arn, {}).get("name", arn.rsplit("/", 1)[-1]) for arn in e.get("attached", [])]
    attached = p.policy in e.get("attached", []) or p.policy in names
    if p.expect == "absent":
        return CheckOutcome(not attached, f"{p.policy} not attached", ", ".join(names) or "no managed policies",
                            f"{p.policy} is no longer attached to {kind} {name}" if not attached
                            else f"{p.policy} should be detached from {kind} {name}")
    return CheckOutcome(attached, f"{p.policy} attached", ", ".join(names) or "no managed policies",
                        f"{p.policy} is attached to {kind} {name}" if attached
                        else f"{p.policy} should be attached to {kind} {name}")


class TrustParams(Params):
    role: str = NAME
    service: str = Field(pattern=r"^[a-z0-9.-]+\.amazonaws\.com$")


@check("iam.role_trusts", TrustParams, "iam", READS + ["iam:GetRole"])
def role_trusts(p: TrustParams, ev: dict) -> CheckOutcome:
    r = _iam(ev).get("roles", {}).get(p.role)
    if r is None:
        return CheckOutcome(False, p.service, "role missing", f"Role {p.role} was not found")
    services: list[str] = []
    for st in (r.get("trust") or {}).get("Statement", []):
        if st.get("Effect") == "Allow" and "sts:AssumeRole" in ([st.get("Action")] if isinstance(st.get("Action"), str) else st.get("Action", [])):
            svc = (st.get("Principal") or {}).get("Service", [])
            services += [svc] if isinstance(svc, str) else svc
    ok = p.service in services
    return CheckOutcome(ok, p.service, ", ".join(services) or "no service principal",
                        f"{p.role} can be assumed by {p.service}" if ok
                        else f"{p.role} should trust {p.service}")


class AllowsParams(Params):
    principal: str = PRINCIPAL
    action: str = Field(pattern=r"^[a-z0-9-]+:[A-Za-z0-9*]+$")
    resource: str = Field(min_length=1, max_length=2048)
    expect: Literal["allow", "deny"] = "allow"
    # With expect=deny: a principal that no longer exists has no access, so it passes (break-fix offboarding).
    absent_ok: bool = False


@check("iam.policy_allows", AllowsParams, "iam", READS)
def policy_allows(p: AllowsParams, ev: dict) -> CheckOutcome:
    pols = principal_policies(_iam(ev), p.principal)
    want = "allowed" if p.expect == "allow" else "denied"
    if pols is None and p.absent_ok and p.expect == "deny":
        return CheckOutcome(True, want, "principal deleted",
                            f"{p.principal.split(':', 1)[1]} no longer exists, so it has no access")
    if pols is None:
        return CheckOutcome(False, want, "principal missing", f"{p.principal} was not found")
    d = evaluate(pols, p.action, p.resource)
    actual = "allowed" if d.allowed else ("denied (explicit)" if d.decision == "explicit_deny" else "denied")
    ok = d.allowed == (p.expect == "allow")
    note = f" (statements with conditions not evaluated: {', '.join(sorted(set(d.skipped_conditions)))})" \
        if d.skipped_conditions else ""
    msg = (f"{p.principal.split(':', 1)[1]} is {'allowed' if d.allowed else 'denied'} {p.action} on {p.resource}"
           if ok else f"{p.principal.split(':', 1)[1]} should be {want} {p.action} on {p.resource}")
    return CheckOutcome(ok, want, actual + note, msg)
