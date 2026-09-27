from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

Level = Literal["supported", "simulated", "unsupported"]
USABLE: frozenset[str] = frozenset({"supported", "simulated"})

# Operations each CloudLabs console page calls. A service shows as available in the console only when
# ALL of them are usable on the session's engine, so a student never meets a half-working page.
CONSOLE_OPS: dict[str, tuple[str, ...]] = {
    "s3": ("ListBuckets", "CreateBucket", "DeleteBucket", "GetBucketVersioning", "PutBucketVersioning",
           "GetBucketTagging", "PutBucketTagging", "GetBucketLocation", "GetPublicAccessBlock",
           "PutPublicAccessBlock", "GetBucketPolicy", "PutBucketPolicy", "ListObjectsV2", "PutObject",
           "GetObject", "DeleteObject"),
    "dynamodb": ("ListTables", "CreateTable", "DescribeTable", "DeleteTable", "UpdateTable", "Scan", "PutItem",
                 "DeleteItem", "TagResource", "ListTagsOfResource"),
    "iam": ("ListUsers", "CreateUser", "ListGroups", "CreateGroup", "ListRoles", "CreateRole", "ListPolicies",
            "CreatePolicy", "GetPolicy", "GetPolicyVersion", "AttachUserPolicy", "AttachGroupPolicy",
            "AttachRolePolicy", "ListGroupsForUser", "GetGroup"),
    "ec2": ("DescribeImages", "DescribeVpcs", "DescribeSubnets", "RunInstances", "DescribeInstances",
            "StopInstances", "StartInstances", "TerminateInstances", "CreateSecurityGroup",
            "DescribeSecurityGroups", "AuthorizeSecurityGroupIngress", "CreateKeyPair", "DescribeKeyPairs"),
    "lambda": ("ListFunctions", "CreateFunction", "GetFunction", "GetFunctionConfiguration",
               "UpdateFunctionCode", "UpdateFunctionConfiguration", "DeleteFunction"),
}


class OpSupport(BaseModel):
    level: Level
    note: str | None = None


class Capabilities(BaseModel):
    emulator: str
    engine_version: str
    limitations: list[str]
    services: dict[str, dict[str, OpSupport]]

    def level(self, op: str) -> Level | None:
        """op is 'service:Operation'."""
        svc, _, name = op.partition(":")
        entry = self.services.get(svc, {}).get(name)
        return entry.level if entry else None

    def is_usable(self, op: str) -> bool:
        return self.level(op) in USABLE

    def unusable(self, ops: list[str]) -> list[str]:
        return sorted({op for op in ops if not self.is_usable(op)})

    def service_status(self) -> dict[str, str]:
        """Console nav: 'available' only when every operation its console page needs is usable.
        Services with no console page (no CONSOLE_OPS entry) are not part of the catalogue: a service
        only reaches students once its page exists and declares the operations it calls."""
        out = {}
        for svc in self.services:
            needed = CONSOLE_OPS.get(svc)
            if not needed:
                continue
            out[svc] = "available" if all(self.is_usable(f"{svc}:{op}") for op in needed) else "unavailable"
        return out

    def features(self, service: str) -> dict[str, dict]:
        return {op: o.model_dump() for op, o in self.services.get(service, {}).items()}


@lru_cache
def load(emulator: str = "moto") -> Capabilities:
    data = yaml.safe_load((Path(__file__).parent / f"{emulator}.yaml").read_text())
    return Capabilities.model_validate(data)
