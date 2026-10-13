"""Audit checks: grade HOW a student worked, from the sandbox's recorded AWS calls (collector 'audit', see
grader/audit.py). End-state checks can't tell "versioning enabled, then uploaded" from "uploaded, then enabled
versioning"; the audit log can.

Only successful calls (HTTP 2xx) count. Both checks are positive: a call that bypassed the proxy is simply not
seen, so a student can't gain marks by avoiding it (and there is deliberately no "never called" check)."""

from typing import Annotated, Literal

from pydantic import Field

from ..registry import CheckOutcome, Params, check

ACTION_PATTERN = r"^[a-z0-9-]+:[A-Z][A-Za-z0-9]*$"
Action = Annotated[str, Field(pattern=ACTION_PATTERN)]
Source = Literal["any", "cli", "console"]
FROM = {"cli": " from the terminal (AWS CLI)", "console": " from the console", "any": ""}


def _ok(e: dict) -> bool:
    return 200 <= int(e.get("status", 0)) < 300


def _events(ev: dict, source: str) -> list[dict]:
    return [e for e in ev.get("audit", {}).get("events", []) if _ok(e) and source in ("any", e.get("source"))]


def _unavailable(ev: dict) -> bool:
    return not ev.get("audit", {}).get("available", False)


UNAVAILABLE = "API call recording is not available for this lab session"


def _times(n: int) -> str:
    return "once" if n == 1 else f"{n} times"


class CalledParams(Params):
    action: str = Field(pattern=ACTION_PATTERN, description="service:Operation, e.g. s3:PutObject")
    source: Source = "any"
    min_count: int = Field(1, ge=1, le=100)


@check("audit.called", CalledParams, "audit", [])
def called(p: CalledParams, ev: dict) -> CheckOutcome:
    want = f"{p.action} at least {_times(p.min_count)}{FROM[p.source]}"
    if _unavailable(ev):
        return CheckOutcome(False, want, "no audit log", UNAVAILABLE)
    hits = [e for e in _events(ev, p.source) if e["action"] == p.action]
    if len(hits) >= p.min_count:
        return CheckOutcome(True, want, f"{len(hits)} successful", f"{p.action} was called {_times(len(hits))}"
                                                                   f"{FROM[p.source]}")
    every = ev["audit"].get("events", [])
    elsewhere = [e for e in _events(ev, "any") if e["action"] == p.action and e not in hits]
    failed = [e for e in every if e.get("action") == p.action and not _ok(e)]
    actual = f"{len(hits)} successful{FROM[p.source]}" + (f", {len(elsewhere)} from elsewhere" if elsewhere else "") \
        + (f", {len(failed)} failed" if failed else "")
    if elsewhere and p.source != "any":
        where = "the console" if p.source == "cli" else "the terminal"
        message = f"{p.action} was done from {where}; this task asks for it{FROM[p.source]}"
    elif hits:
        message = f"{p.action} was called {_times(len(hits))}{FROM[p.source]}; {p.min_count} needed"
    elif failed:
        message = f"{p.action} was attempted but did not succeed"
    else:
        message = f"No successful {p.action} call yet{FROM[p.source]}"
    return CheckOutcome(False, want, actual, message)


class OrderParams(Params):
    actions: list[Action] = Field(min_length=2, max_length=10, description="service:Operation names, in order")
    source: Source = "any"


@check("audit.order", OrderParams, "audit", [])
def order(p: OrderParams, ev: dict) -> CheckOutcome:
    want = " → ".join(p.actions) + FROM[p.source]
    if _unavailable(ev):
        return CheckOutcome(False, want, "no audit log", UNAVAILABLE)
    relevant = [e["action"] for e in _events(ev, p.source) if e["action"] in p.actions]
    i = 0
    for action in relevant:  # earliest-match subsequence: each step after the previous one
        if i < len(p.actions) and action == p.actions[i]:
            i += 1
    seen = relevant if len(relevant) <= 20 else relevant[:10] + ["…"] + relevant[-9:]
    actual = " → ".join(seen) or "none of these calls"
    if i == len(p.actions):
        return CheckOutcome(True, want, actual, "The steps were done in the right order")
    missing = [a for a in p.actions if a not in relevant]
    if missing:
        return CheckOutcome(False, want, actual, f"No successful {missing[0]} call yet{FROM[p.source]}")
    return CheckOutcome(False, want, actual,
                        f"{p.actions[i]} must happen after {p.actions[i - 1]}: the order of the steps matters here"
                        if i > 0 else f"{p.actions[0]} must come first")
