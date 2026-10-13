"""Lambda checks. Evidence shape (collector 'lambda'):
{"functions": {name: {"runtime", "handler", "role_name", "memory", "timeout", "env": {k: v}}},
 "invocations": {probe_key: {"status": int|None, "error": str|None, "payload": json|str|None}},
 "event_sources": [{"function", "service", "source", "batch_size", "enabled", "report_batch_item_failures"}]}
(`event_sources` is present only on engines where ListEventSourceMappings is usable.)

`lambda.invoke_returns` declares a *probe*: during evidence capture the collector invokes the function
with the lab's payload (before other collectors run) and stores the result in the evidence. Grading then
compares stored results, so it stays a pure function of the evidence."""

from __future__ import annotations

import json
from typing import Any

from pydantic import Field

from ..registry import CheckOutcome, Params, check

NAME = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
READS = ["lambda:ListFunctions", "lambda:GetFunctionConfiguration"]


def probe_key(function: str, payload: Any) -> str:
    return f"{function}::{json.dumps(payload, sort_keys=True, separators=(',', ':'))}"


def _lam(ev: dict) -> dict:
    return ev.get("lambda", {})


class FunctionParams(Params):
    name: str = NAME
    runtime: str | None = Field(None, pattern=r"^[a-z0-9.]+$")
    handler: str | None = None
    role_name: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    memory_min: int | None = Field(None, ge=128, le=10240)
    timeout_min: int | None = Field(None, ge=1, le=900)


@check("lambda.function", FunctionParams, "lambda", READS)
def function(p: FunctionParams, ev: dict) -> CheckOutcome:
    f = _lam(ev).get("functions", {}).get(p.name)
    want = [x for x in [f"runtime={p.runtime}" if p.runtime else "", f"handler={p.handler}" if p.handler else "",
                        f"role={p.role_name}" if p.role_name else "", *[f"{k}={v}" for k, v in p.env.items()],
                        f"memory>={p.memory_min}" if p.memory_min else "", f"timeout>={p.timeout_min}" if p.timeout_min else ""] if x]
    exp = ", ".join(want) or "exists"
    if f is None:
        return CheckOutcome(False, exp, "missing", f"Function {p.name} was not found")
    problems = []
    if p.runtime and f["runtime"] != p.runtime:
        problems.append(f"runtime is {f['runtime']}, not {p.runtime}")
    if p.handler and f["handler"] != p.handler:
        problems.append(f"handler is {f['handler']}, not {p.handler}")
    if p.role_name and f.get("role_name") != p.role_name:
        problems.append(f"execution role is {f.get('role_name')}, not {p.role_name}")
    for k, v in p.env.items():
        if f.get("env", {}).get(k) != v:
            problems.append(f"environment variable {k} should be {v}")
    if p.memory_min and (f.get("memory") or 0) < p.memory_min:
        problems.append(f"memory is {f.get('memory')} MB (needs at least {p.memory_min})")
    if p.timeout_min and (f.get("timeout") or 0) < p.timeout_min:
        problems.append(f"timeout is {f.get('timeout')} s (needs at least {p.timeout_min})")
    actual = f"runtime={f['runtime']}, handler={f['handler']}, memory={f.get('memory')}, timeout={f.get('timeout')}, env={f.get('env')}"
    return CheckOutcome(not problems, exp, actual, f"Function {p.name} is configured correctly" if not problems
                        else f"Function {p.name}: " + "; ".join(problems))


class InvokeParams(Params):
    name: str = NAME
    payload: Any = Field(default_factory=dict)
    expect: Any  # the response must contain these keys/values (dicts are matched as a subset)


def _subset(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and _subset(v, actual[k]) for k, v in expected.items())
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)) and not isinstance(expected, bool):
        return abs(float(expected) - float(actual)) < 1e-9
    return expected == actual


def _invoke_probe(p: InvokeParams) -> dict:
    return {"kind": "lambda_invoke", "function": p.name, "payload": p.payload}


@check("lambda.invoke_returns", InvokeParams, "lambda", READS + ["lambda:Invoke"], probe=_invoke_probe)
def invoke_returns(p: InvokeParams, ev: dict) -> CheckOutcome:
    exp = json.dumps(p.expect, sort_keys=True)
    inv = _lam(ev).get("invocations", {}).get(probe_key(p.name, p.payload))
    if inv is None or inv.get("status") is None:
        why = (inv or {}).get("error") or "function missing"
        return CheckOutcome(False, exp, why, f"Function {p.name} could not be invoked ({why})")
    if inv.get("error"):
        return CheckOutcome(False, exp, f"error: {json.dumps(inv.get('payload'))[:200]}",
                            f"Function {p.name} raised an error for input {json.dumps(p.payload)}")
    ok = _subset(p.expect, inv.get("payload"))
    actual = json.dumps(inv.get("payload"), sort_keys=True)[:300]
    return CheckOutcome(ok, exp, actual, f"Function {p.name} returned the expected result" if ok
                        else f"Function {p.name} returned {actual} for input {json.dumps(p.payload)}")


class EventSourceParams(Params):
    name: str = NAME
    queue: str = Field(min_length=1, max_length=80)
    batch_size: int | None = Field(None, ge=1, le=10000)
    enabled: bool = True
    report_batch_item_failures: bool | None = None


@check("lambda.event_source", EventSourceParams, "lambda", READS + ["lambda:ListEventSourceMappings"])
def event_source(p: EventSourceParams, ev: dict) -> CheckOutcome:
    """An SQS trigger connects the queue to the function, with the expected batch size and settings."""
    want = [f"SQS {p.queue} → {p.name}", "enabled" if p.enabled else "disabled",
            f"batch size {p.batch_size}" if p.batch_size else "",
            {True: "reports batch item failures", False: "no partial batch responses", None: ""}[p.report_batch_item_failures]]
    exp = ", ".join(x for x in want if x)
    mappings = [m for m in _lam(ev).get("event_sources", [])
                if m["function"] == p.name and m["service"] == "sqs" and m["source"] == p.queue]
    if not mappings:
        others = [m["source"] for m in _lam(ev).get("event_sources", []) if m["function"] == p.name]
        why = f" (it is triggered by {', '.join(others)})" if others else ""
        return CheckOutcome(False, exp, "no trigger", f"Function {p.name} has no trigger from queue {p.queue}{why}")
    m = mappings[0]
    problems = []
    if m["enabled"] != p.enabled:
        problems.append("the trigger is " + ("disabled" if p.enabled else "still enabled"))
    if p.batch_size and m.get("batch_size") != p.batch_size:
        problems.append(f"batch size is {m.get('batch_size')}, not {p.batch_size}")
    if p.report_batch_item_failures is not None and m.get("report_batch_item_failures") != p.report_batch_item_failures:
        problems.append("report batch item failures should be " + ("on" if p.report_batch_item_failures else "off"))
    actual = (f"{'enabled' if m['enabled'] else 'disabled'}, batch size {m.get('batch_size')}, "
              f"batch item failures {'on' if m.get('report_batch_item_failures') else 'off'}")
    return CheckOutcome(not problems, exp, actual, f"Queue {p.queue} triggers {p.name}" if not problems
                        else f"Trigger {p.queue} → {p.name}: " + "; ".join(problems))
