"""Scoring is a pure function: grade(definition, variables, evidence) -> result (PLAN §5 step 3).
It performs no I/O, so the same stored evidence always yields the same score (and regrades are
reproducible)."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Any

from ..labs.render import render_task
from ..labs.schema import LabDefinition
from . import registry

TWO = Decimal("0.01")
HIDDEN_MESSAGE = "A hidden requirement for this task is not met yet."


def _dec(f: Fraction) -> Decimal:
    return (Decimal(f.numerator) / Decimal(f.denominator)).quantize(TWO, rounding=ROUND_HALF_UP)


def grade(definition: LabDefinition, variables: dict[str, str], evidence: dict[str, Any]) -> dict[str, Any]:
    collectors = evidence.get("collectors", {})
    tasks_out: list[dict[str, Any]] = []
    total, max_total = Fraction(0), Fraction(0)
    for task in definition.tasks:
        t = render_task(task, variables)
        marks = Fraction(str(task.marks))
        weights = sum(c.weight for c in t.checks)
        results, passed_weight = [], 0
        for c in t.checks:
            d = registry.get(c.type)
            d.ensure_supported()
            params = d.params_model.model_validate(c.params)
            out = d.fn(params, collectors)
            share = marks * Fraction(c.weight, weights)
            if out.passed:
                passed_weight += c.weight
            message = out.message if out.passed or not c.feedback else c.feedback
            results.append({"task": task.id, "check": c.type, "params": params.model_dump(),
                            "expected": out.expected, "actual": out.actual, "passed": out.passed,
                            "hidden": c.hidden, "message": message, "_share": share})
        all_passed = passed_weight == weights
        if task.scoring == "proportional":
            awarded = marks * Fraction(passed_weight, weights)
            for r in results:
                r["marks_awarded"] = _dec(r["_share"] if r["passed"] else Fraction(0))
        else:
            awarded = marks if all_passed else Fraction(0)
            for r in results:
                r["marks_awarded"] = _dec(r["_share"] if all_passed else Fraction(0))
        for r in results:
            r["marks_possible"] = _dec(r.pop("_share"))
        total += awarded
        max_total += marks
        tasks_out.append({"task_id": task.id, "title": t.title, "marks_awarded": _dec(awarded),
                          "marks_possible": _dec(marks), "passed": all_passed, "checks": results})
    return {"score": _dec(total), "max_score": _dec(max_total), "tasks": tasks_out}


def to_json(result: dict[str, Any]) -> dict[str, Any]:
    """Decimals -> strings for JSONB storage/API output."""
    def conv(v: Any) -> Any:
        if isinstance(v, Decimal):
            return str(v)
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        if isinstance(v, list):
            return [conv(x) for x in v]
        return v
    return conv(result)


def student_view(result: dict[str, Any]) -> dict[str, Any]:
    """What a student may see: pass/fail, marks and messages. Never expected/actual/params, and hidden
    checks only reveal a generic message."""
    r = to_json(result)
    tasks = []
    for t in r["tasks"]:
        checks = []
        for c in t["checks"]:
            if c["hidden"]:
                checks.append({"hidden": True, "passed": c["passed"],
                               "message": "Hidden requirement met." if c["passed"] else HIDDEN_MESSAGE,
                               "marks_awarded": c["marks_awarded"], "marks_possible": c["marks_possible"]})
            else:
                checks.append({"hidden": False, "passed": c["passed"], "message": c["message"],
                               "marks_awarded": c["marks_awarded"], "marks_possible": c["marks_possible"]})
        tasks.append({"task_id": t["task_id"], "title": t["title"], "passed": t["passed"],
                      "marks_awarded": t["marks_awarded"], "marks_possible": t["marks_possible"],
                      "checks": checks})
    return {"score": r["score"], "max_score": r["max_score"], "tasks": tasks}


def probes_for(definition: LabDefinition, variables: dict[str, str]) -> list[dict[str, Any]]:
    """Rendered probe requests (e.g. Lambda invocations) declared by the lab's checks."""
    out: list[dict[str, Any]] = []
    for task in definition.tasks:
        for c in render_task(task, variables).checks:
            d = registry.get(c.type)
            if d.probe is not None:
                probe = d.probe(d.params_model.model_validate(c.params))
                if probe not in out:
                    out.append(probe)
    return out


def collectors_for(definition: LabDefinition) -> list[str]:
    names = set()
    for task in definition.tasks:
        for c in task.checks:
            names.add(registry.get(c.type).collector)
    return sorted(names)
