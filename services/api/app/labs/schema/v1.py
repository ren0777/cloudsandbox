"""lab.yaml schema_version 1 (PLAN §7). Unknown keys are rejected everywhere except inside a check,
whose extra keys are that check's parameters (validated by the check registry)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SLUG = r"^[a-z0-9][a-z0-9-]{1,78}[a-z0-9]$"
TASK_ID = r"^[a-z0-9][a-z0-9_-]{0,39}$"
SEMVER = r"^\d+\.\d+\.\d+$"
Service = Literal["s3", "iam", "ec2", "lambda", "dynamodb"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CheckSpec(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: str = Field(pattern=r"^[a-z0-9]+\.[a-z0-9_]+$")
    hidden: bool = False
    weight: int = Field(1, ge=1, le=100)
    feedback: str | None = Field(None, max_length=500)

    @property
    def params(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


class TaskSpec(Strict):
    id: str = Field(pattern=TASK_ID)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field("", max_length=4000)
    hints: list[str] = Field(default_factory=list, max_length=10)
    marks: Decimal = Field(gt=0, le=1000, decimal_places=2)
    scoring: Literal["all", "proportional"] = "all"
    checks: list[CheckSpec] = Field(min_length=1, max_length=30)


class ResourceSpec(Strict):
    cpus: float | None = Field(None, gt=0)
    memory_mib: int | None = Field(None, ge=64)
    pids: int | None = Field(None, ge=16)


class ResourcesSpec(Strict):
    emulator: ResourceSpec | None = None
    terminal: ResourceSpec | None = None


class SetupSpec(Strict):
    script: str = Field(pattern=r"^[A-Za-z0-9_./-]+\.sh$")
    timeout_s: int = Field(60, ge=1, le=180)


class RuntimeSpec(Strict):
    # "default" = the platform's default engine. Naming an engine is for exceptional labs only (e.g. a
    # Lambda lab that needs an engine able to execute code); labs must not depend on engine quirks.
    emulator: Literal["default", "moto", "floci", "ministack"] = "default"


class LabV1(Strict):
    schema_version: Literal[1]
    id: str = Field(pattern=SLUG)
    version: str = Field(pattern=SEMVER)
    title: str = Field(min_length=1, max_length=200)
    # guided: build from scratch. break_fix: `setup` creates a broken environment; tasks grade the repaired state.
    kind: Literal["guided", "break_fix"] = "guided"
    summary: str = Field("", max_length=1000)
    story: str = Field("", max_length=8000)
    services: list[Service] = Field(min_length=1)
    runtime: RuntimeSpec = RuntimeSpec()
    duration_minutes: int = Field(ge=5, le=240)
    idle_minutes: int | None = Field(None, ge=1, le=240)
    max_attempts: int = Field(3, ge=1, le=20)
    variables: dict[str, str] = Field(default_factory=dict)
    requires: list[str] = Field(default_factory=list)
    resources: ResourcesSpec | None = None
    setup: SetupSpec | None = None
    tasks: list[TaskSpec] = Field(min_length=1, max_length=50)

    @field_validator("variables")
    @classmethod
    def _var_names(cls, v: dict[str, str]) -> dict[str, str]:
        for k in v:
            if not k.isidentifier() or k == "student_short_id":
                raise ValueError(f"invalid variable name {k!r}")
        return v

    @field_validator("requires")
    @classmethod
    def _ops(cls, v: list[str]) -> list[str]:
        for op in v:
            if ":" not in op:
                raise ValueError(f"requires entry {op!r} must look like 'service:Operation'")
        return v

    @model_validator(mode="after")
    def _unique_tasks(self) -> "LabV1":
        ids = [t.id for t in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("task ids must be unique")
        if self.kind == "break_fix" and self.setup is None:
            raise ValueError("a break_fix lab needs a setup script that creates the broken state")
        return self

    @property
    def max_score(self) -> Decimal:
        return sum((t.marks for t in self.tasks), Decimal(0))
