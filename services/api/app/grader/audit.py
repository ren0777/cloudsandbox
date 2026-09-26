"""API-call audit source (PLAN architecture). Slice 1 ships only the interface and a null
implementation; `audit.*` checks are registered as unsupported until the audit proxy exists."""

from typing import Any, Protocol


class AuditSource(Protocol):
    async def events(self, session_id: str) -> list[dict[str, Any]]: ...


class NullAuditSource:
    async def events(self, session_id: str) -> list[dict[str, Any]]:
        return []
