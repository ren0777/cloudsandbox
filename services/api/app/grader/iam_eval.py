"""CloudLabs IAM policy evaluator (support level `simulated`, PLAN §8).

Neither emulator enforces IAM or implements the policy simulator, so CloudLabs evaluates identity-based
policies itself, deterministically, from collected evidence:

  1. gather every statement that applies to the principal (inline + attached managed policies of the
     user, of each group the user is in, or of the role)
  2. an explicit Deny that matches wins
  3. otherwise an Allow that matches allows
  4. otherwise the request is implicitly denied

Supported: Effect, Action/NotAction, Resource/NotResource with `*` and `?` wildcards (actions matched
case-insensitively, resources case-sensitively). Statements with a Condition are *not* evaluated: they're
skipped and reported, which is conservative for "allow" tasks and flagged for "deny" tasks.
Out of scope: resource-based policies, permission boundaries, SCPs, session policies.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote


def parse_document(doc: Any) -> dict[str, Any]:
    """Policy documents arrive as dicts or (URL-encoded) JSON strings depending on the engine."""
    if isinstance(doc, dict):
        return doc
    if isinstance(doc, str):
        text = doc if doc.lstrip().startswith("{") else unquote(doc)
        return json.loads(text)
    return {}


def _as_list(v: Any) -> list[str]:
    if v is None:
        return []
    return [v] if isinstance(v, str) else list(v)


def _glob(pattern: str, value: str, case_insensitive: bool) -> bool:
    if case_insensitive:
        pattern, value = pattern.lower(), value.lower()
    regex = "^" + re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".") + "$"
    return re.match(regex, value, re.S) is not None


@dataclass
class Decision:
    decision: str  # "allowed" | "explicit_deny" | "implicit_deny"
    matched: list[str] = field(default_factory=list)  # policy names whose statements decided it
    skipped_conditions: list[str] = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return self.decision == "allowed"


def _matches(stmt: dict[str, Any], action: str, resource: str) -> bool:
    if "Action" in stmt:
        a_ok = any(_glob(p, action, True) for p in _as_list(stmt["Action"]))
    elif "NotAction" in stmt:
        a_ok = not any(_glob(p, action, True) for p in _as_list(stmt["NotAction"]))
    else:
        return False
    if not a_ok:
        return False
    if "Resource" in stmt:
        return any(_glob(p, resource, False) for p in _as_list(stmt["Resource"]))
    if "NotResource" in stmt:
        return not any(_glob(p, resource, False) for p in _as_list(stmt["NotResource"]))
    return False


def evaluate(policies: list[tuple[str, dict[str, Any]]], action: str, resource: str) -> Decision:
    """policies: (policy name, document) pairs that apply to one principal."""
    allow_by: list[str] = []
    skipped: list[str] = []
    for name, doc in policies:
        for stmt in _as_list_of_statements(doc):
            if "Condition" in stmt:
                skipped.append(name)
                continue
            if not _matches(stmt, action, resource):
                continue
            if stmt.get("Effect") == "Deny":
                return Decision("explicit_deny", [name], skipped)
            if stmt.get("Effect") == "Allow":
                allow_by.append(name)
    if allow_by:
        return Decision("allowed", sorted(set(allow_by)), skipped)
    return Decision("implicit_deny", [], skipped)


def _as_list_of_statements(doc: dict[str, Any]) -> list[dict[str, Any]]:
    st = doc.get("Statement", [])
    return [st] if isinstance(st, dict) else list(st)


def principal_policies(iam_evidence: dict[str, Any], principal: str) -> list[tuple[str, dict[str, Any]]] | None:
    """Every (name, document) applying to 'user:NAME' | 'group:NAME' | 'role:NAME'. None if missing."""
    kind, _, name = principal.partition(":")
    managed = iam_evidence.get("policies", {})
    out: list[tuple[str, dict[str, Any]]] = []

    def add(entity: dict[str, Any]) -> None:
        for pname, doc in sorted(entity.get("inline", {}).items()):
            out.append((f"inline:{pname}", doc))
        for arn in entity.get("attached", []):
            p = managed.get(arn)
            if p is not None:
                out.append((p["name"], p["document"]))

    if kind == "user":
        u = iam_evidence.get("users", {}).get(name)
        if u is None:
            return None
        add(u)
        for g in u.get("groups", []):
            grp = iam_evidence.get("groups", {}).get(g)
            if grp:
                add(grp)
    elif kind in ("group", "role"):
        e = iam_evidence.get(f"{kind}s", {}).get(name)
        if e is None:
            return None
        add(e)
    else:
        return None
    return out


__all__ = ["Decision", "evaluate", "parse_document", "principal_policies"]
