"""Check registry. A check is a pure function (params, evidence) -> CheckOutcome, plus the evidence
collector it needs and the emulator operations that collector reads (validated against the capability
declaration at lab import, PLAN §8)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict


class NotSupportedInSlice(Exception):
    pass


class Params(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class CheckOutcome:
    passed: bool
    expected: Any
    actual: Any
    message: str


CheckFn = Callable[[Any, dict], CheckOutcome]


@dataclass(frozen=True)
class CheckDef:
    type: str
    params_model: type[Params]
    collector: str
    reads: tuple[str, ...]
    fn: CheckFn
    probe: Callable[[Any], dict] | None = None  # asks the collector to run something (e.g. invoke) first
    supported: bool = True
    unsupported_reason: str = field(default="")

    def ensure_supported(self) -> None:
        if not self.supported:
            raise NotSupportedInSlice(f"check {self.type!r} is not available yet: {self.unsupported_reason}")


REGISTRY: dict[str, CheckDef] = {}


def check(type_: str, params: type[Params], collector: str, reads: list[str],
          probe: Callable[[Any], dict] | None = None):
    def deco(fn: CheckFn) -> CheckFn:
        if type_ in REGISTRY:
            raise RuntimeError(f"duplicate check {type_}")
        REGISTRY[type_] = CheckDef(type_, params, collector, tuple(reads), fn, probe)
        return fn
    return deco


def stub(type_: str, reason: str, collector: str = "none") -> None:
    def _fn(_: Any, __: dict) -> CheckOutcome:
        raise NotSupportedInSlice(reason)
    REGISTRY[type_] = CheckDef(type_, Params, collector, (), _fn, None, supported=False,
                               unsupported_reason=reason)


def get(type_: str) -> CheckDef:
    # Import side-effect modules so the registry is populated.
    from .checks import load_all
    load_all()
    if type_ not in REGISTRY:
        raise KeyError(type_)
    return REGISTRY[type_]


def namespaces() -> set[str]:
    from .checks import load_all
    load_all()
    return {t.split(".")[0] for t in REGISTRY}
