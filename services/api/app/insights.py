"""What the student sees about their built environment, derived only from collector evidence: the
architecture diagram and the simulated (educational) cost estimate."""

from __future__ import annotations

from typing import Any

from .cost import estimate
from .diagram import build_graph


def insights(payload: dict[str, Any]) -> dict[str, Any]:
    collectors = payload.get("collectors", {})
    return {"graph": build_graph(collectors), "cost": estimate(collectors)}
