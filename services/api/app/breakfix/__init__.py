"""Typed break actions for break-fix labs (phase 9, milestone 41). See `registry.py` for the model."""

from .registry import (  # noqa: F401
    ActionParams,
    BreakActionDef,
    REGISTRY,
    compile_actions,
    get,
    load_all,
    register,
)
