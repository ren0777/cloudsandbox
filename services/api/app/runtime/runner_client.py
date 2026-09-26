"""Control plane side of the runner contract. The API talks to sandbox infrastructure ONLY through
this client (PLAN §10); it never imports the Docker SDK."""

from __future__ import annotations

import json
import time
from typing import Any, Protocol

import httpx
import structlog

from ..config import get_settings
from .signing import SIGNATURE_HEADER, TIMESTAMP_HEADER, compute


class RunnerError(Exception):
    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class RunnerClient(Protocol):
    runner_id: str

    async def capacity(self) -> dict[str, Any]: ...
    async def list_sandboxes(self, env: str | None = None) -> list[dict[str, Any]]: ...
    async def create_sandbox(self, req: dict[str, Any]) -> dict[str, Any]: ...
    async def reset_sandbox(self, sandbox_id: str, req: dict[str, Any]) -> dict[str, Any]: ...
    async def destroy_sandbox(self, sandbox_id: str) -> None: ...
    async def sandbox_status(self, sandbox_id: str) -> dict[str, Any]: ...
    async def run_job(self, sandbox_id: str, job: dict[str, Any]) -> dict[str, Any]: ...


class HttpRunnerClient:
    """HMAC + timestamp over the internal network (slice 1). mTLS is layered on later with the same
    request format (PLAN §10, college deployment)."""

    def __init__(self, runner_id: str, base_url: str, secret: str, timeout_s: float):
        self.runner_id = runner_id
        self._secret = secret
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout_s)

    async def _req(self, method: str, path: str, body: Any = None) -> httpx.Response:
        raw = b"" if body is None else json.dumps(body, separators=(",", ":")).encode()
        ts = str(int(time.time()))
        headers = {TIMESTAMP_HEADER: ts, SIGNATURE_HEADER: compute(self._secret, method, path, raw, ts),
                   "Content-Type": "application/json"}
        rid = structlog.contextvars.get_contextvars().get("request_id")
        if rid:
            headers["X-Request-ID"] = rid
        try:
            resp = await self._client.request(method, path, content=raw or None, headers=headers)
        except httpx.HTTPError as e:
            raise RunnerError("runtime_unavailable", f"runner unreachable: {e.__class__.__name__}",
                              503) from e
        if resp.status_code >= 400:
            try:
                err = resp.json()["error"]
                code, msg = err.get("code", "runner_error"), err.get("message", "")
            except Exception:
                code, msg = "runner_error", resp.text[:300]
            raise RunnerError(code, msg, resp.status_code)
        return resp

    async def capacity(self) -> dict[str, Any]:
        return (await self._req("GET", "/v1/capacity")).json()

    async def list_sandboxes(self, env: str | None = None) -> list[dict[str, Any]]:
        path = "/v1/sandboxes" + (f"?env={env}" if env else "")
        return (await self._req("GET", path)).json()

    async def create_sandbox(self, req: dict[str, Any]) -> dict[str, Any]:
        return (await self._req("POST", "/v1/sandboxes", req)).json()

    async def reset_sandbox(self, sandbox_id: str, req: dict[str, Any]) -> dict[str, Any]:
        return (await self._req("POST", f"/v1/sandboxes/{sandbox_id}/reset", req)).json()

    async def destroy_sandbox(self, sandbox_id: str) -> None:
        await self._req("DELETE", f"/v1/sandboxes/{sandbox_id}")

    async def sandbox_status(self, sandbox_id: str) -> dict[str, Any]:
        return (await self._req("GET", f"/v1/sandboxes/{sandbox_id}")).json()

    async def run_job(self, sandbox_id: str, job: dict[str, Any]) -> dict[str, Any]:
        return (await self._req("POST", f"/v1/sandboxes/{sandbox_id}/jobs", job)).json()

    async def stats(self, env: str | None = None) -> dict[str, Any]:
        """Memory per sandbox on this runner (read-only; load tests and capacity planning)."""
        return (await self._req("GET", "/v1/stats" + (f"?env={env}" if env else ""))).json()

    async def aclose(self) -> None:
        await self._client.aclose()


# ------------------------------------------------------------------------------------ registry (phase 7)
# Every registered runner (table `runners`) gets its own client: its URL and its own HMAC secret (stored
# encrypted; NULL = the platform's CL_RUNNER_SECRET for the seeded local runner). A session always talks to the
# runner that holds its sandbox (`lab_sessions.runner_id`): sandboxes are never moved between runners.
_cache: dict[str, tuple[tuple, HttpRunnerClient]] = {}
_override: RunnerClient | None = None          # test hook: one client for every runner
_overrides: dict[str, RunnerClient] = {}       # test hook: per runner id


def client_for(runner: Any) -> RunnerClient:
    """Client for a `Runner` row."""
    if runner.id in _overrides:
        return _overrides[runner.id]
    if _override is not None:
        return _override
    key = (runner.url, runner.secret_enc)
    hit = _cache.get(runner.id)
    if hit and hit[0] == key:
        return hit[1]
    from ..crypto import decrypt
    s = get_settings()
    secret = decrypt(runner.secret_enc) if runner.secret_enc else s.runner_secret
    client = HttpRunnerClient(runner.id, runner.url, secret, s.runner_timeout_s)
    _cache[runner.id] = (key, client)
    return client


async def client_for_id(runner_id: str) -> RunnerClient:
    if runner_id in _overrides:
        return _overrides[runner_id]
    if _override is not None:
        return _override
    from ..db import sessionmaker
    from ..models import Runner
    async with sessionmaker()() as db:
        r = await db.get(Runner, runner_id)
    if r is None:
        raise RunnerError("runtime_unavailable", f"runner {runner_id} is not registered", 503)
    return client_for(r)


def get_runner() -> RunnerClient:
    """The platform's default runner (CL_RUNNER_ID/URL/SECRET): labtest, health checks, one-server installs."""
    s = get_settings()
    if s.runner_id in _overrides:
        return _overrides[s.runner_id]
    if _override is not None:
        return _override
    hit = _cache.get(s.runner_id)
    key = (s.runner_url, None)
    if hit and hit[0] == key:
        return hit[1]
    client = HttpRunnerClient(s.runner_id, s.runner_url, s.runner_secret, s.runner_timeout_s)
    _cache[s.runner_id] = (key, client)
    return client


def set_runner(client: RunnerClient | None) -> None:
    """Test hook: route every runner id to this client (None restores real clients)."""
    global _override
    _override = client
    _overrides.clear()


def set_runners(clients: dict[str, RunnerClient]) -> None:
    """Test hook: one client per runner id."""
    _overrides.clear()
    _overrides.update(clients)
