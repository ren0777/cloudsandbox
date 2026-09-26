"""Per-student variable rendering. Variables are computed once per session and stored, so grading is
deterministic for that attempt."""

from __future__ import annotations

from typing import Any

from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

from .schema import LabDefinition
from .schema.v1 import CheckSpec, TaskSpec

_env = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False)


def _render_str(s: str, ctx: dict[str, str]) -> str:
    if "{" not in s:
        return s
    return _env.from_string(s).render(**ctx)


def _render_any(v: Any, ctx: dict[str, str]) -> Any:
    if isinstance(v, str):
        return _render_str(v, ctx)
    if isinstance(v, list):
        return [_render_any(x, ctx) for x in v]
    if isinstance(v, dict):
        return {k: _render_any(x, ctx) for k, x in v.items()}
    return v


def compute_variables(definition: LabDefinition, student_short_id: str) -> dict[str, str]:
    ctx: dict[str, str] = {"student_short_id": student_short_id}
    for name, tmpl in definition.variables.items():  # declaration order; later vars may use earlier
        ctx[name] = _render_str(tmpl, ctx)
    return ctx


def render_task(task: TaskSpec, variables: dict[str, str]) -> TaskSpec:
    checks = [CheckSpec.model_validate({"type": c.type, "hidden": c.hidden, "weight": c.weight,
                                        "feedback": _render_any(c.feedback, variables),
                                        **_render_any(c.params, variables)}) for c in task.checks]
    return task.model_copy(update={
        "title": _render_str(task.title, variables),
        "description": _render_str(task.description, variables),
        "hints": [_render_str(h, variables) for h in task.hints],
        "checks": checks,
    })


def student_lab_view(definition: LabDefinition, variables: dict[str, str] | None) -> dict[str, Any]:
    """Redacted lab view for students (PLAN §7b): no check definitions, no private material."""
    tasks = []
    for t in definition.tasks:
        rt = render_task(t, variables) if variables else t
        tasks.append({"id": rt.id, "title": rt.title, "description": rt.description, "hints": rt.hints,
                      "marks": str(rt.marks)})
    story = _render_str(definition.story, variables) if variables else definition.story
    return {"id": definition.id, "version": definition.version, "title": definition.title,
            "summary": definition.summary, "story": story, "services": list(definition.services),
            "kind": definition.kind,
            "duration_minutes": definition.duration_minutes, "max_score": str(definition.max_score),
            "tasks": tasks}
