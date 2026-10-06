"""EmulatorAdapter registry (PLAN "Emulator strategy").

Every emulator engine satisfies the same CloudLabs interface:
  - `capabilities`: its support-level declaration (capabilities/<engine>.yaml)
  - `client(service, endpoint)`: a boto3 client configured for that engine

Nothing outside this module (grader checks, lab definitions beyond `runtime.emulator`, FastAPI service
contracts, the student UI) may branch on the engine name. The runner owns how an engine is *run*; this
module owns how the control plane *talks* to it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import boto3
from botocore.config import Config

from ..config import get_settings
from . import capabilities as caps_mod

ENGINES: tuple[str, ...] = ("moto", "floci")  # primary engines: every 'default' lab must run on all of them
SPECIALISED: tuple[str, ...] = ("ministack",)  # only for labs that pin them (Lambda code execution)
ALL_ENGINES: tuple[str, ...] = ENGINES + SPECIALISED
DEFAULT_ALIAS = "default"

# CloudLabs service names that are not boto3 service names. VPC is part of the EC2 API, so a lab
# `requires: [vpc:CreateVpc, ...]` and the future VPC console page talk through the `ec2` client.
SERVICE_CLIENT: dict[str, str] = {"vpc": "ec2"}


@dataclass(frozen=True)
class EmulatorAdapter:
    name: str
    s3_addressing_style: str = "path"
    extra_config: dict[str, Any] = field(default_factory=dict)

    @property
    def capabilities(self) -> caps_mod.Capabilities:
        return caps_mod.load(self.name)

    def client(self, service: str, endpoint: str):
        boto_service = SERVICE_CLIENT.get(service, service)
        # Lambda invocations run real code and can take several seconds; EC2 DescribeImages loads the
        # emulator's AMI catalogue (slow under host load).
        read_timeout = {"lambda": 90, "ec2": 60}.get(boto_service, 20)
        return boto3.client(
            boto_service, endpoint_url=endpoint, region_name="us-east-1",
            aws_access_key_id="cloudlabs", aws_secret_access_key="cloudlabs",
            config=Config(s3={"addressing_style": self.s3_addressing_style},
                          retries={"max_attempts": 1 if boto_service == "lambda" else 2, "mode": "standard"},
                          connect_timeout=5, read_timeout=read_timeout, **self.extra_config),
        )


_ADAPTERS = {name: EmulatorAdapter(name) for name in ALL_ENGINES}


class UnknownEngine(ValueError):
    pass


def get(name: str) -> EmulatorAdapter:
    try:
        return _ADAPTERS[name]
    except KeyError:
        raise UnknownEngine(f"unknown emulator engine {name!r} (known: {', '.join(ALL_ENGINES)})") from None


def default_engine() -> str:
    name = get_settings().default_emulator
    get(name)  # validate configuration
    return name


def resolve(lab_runtime_emulator: str) -> str:
    """Engine for a session: the lab's explicit engine, else the platform default."""
    return default_engine() if lab_runtime_emulator == DEFAULT_ALIAS else get(lab_runtime_emulator).name


def candidates(lab_runtime_emulator: str) -> tuple[str, ...]:
    """Engines a lab must be valid for at import time. A lab on 'default' must work on every primary
    engine, so flipping the platform default can never break an already-imported lab."""
    return ENGINES if lab_runtime_emulator == DEFAULT_ALIAS else (get(lab_runtime_emulator).name,)


@lru_cache
def all_adapters() -> tuple[EmulatorAdapter, ...]:
    return tuple(_ADAPTERS[n] for n in ENGINES)
