"""FakeRunner: implements the RunnerClient protocol without Docker. Each "sandbox" is a real Moto
server subprocess (isolated state, real S3 semantics), so evidence capture, grading and the console
behave exactly as against the real runner. Terminal endpoints are not available."""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
import urllib.request
from typing import Any

from app.runtime.runner_client import RunnerError


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeRunner:
    def __init__(self, max_sandboxes: int = 4, runner_id: str = "runner-local-1",
                 engines: dict[str, bool] | None = None):
        self.runner_id = runner_id
        self.engines = engines if engines is not None else {"moto": True, "floci": True, "ministack": True}
        self.max_sandboxes = max_sandboxes
        self.sandboxes: dict[str, dict[str, Any]] = {}
        self.fail_create: str | None = None
        self.create_delay_s = 0.0
        self.calls: list[tuple[str, str]] = []
        self.healthy = True

    # --- helpers
    def _spawn(self) -> tuple[subprocess.Popen, int]:
        port = _free_port()
        env = {**os.environ, "MOTO_IAM_LOAD_MANAGED_POLICIES": "true"}  # same as the runner's moto EmulatorSpec
        proc = subprocess.Popen([sys.executable, "-m", "moto.server", "-H", "127.0.0.1", "-p", str(port)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/moto-api/", timeout=1)
                return proc, port
            except Exception:
                time.sleep(0.1)
        proc.kill()
        raise RuntimeError("moto did not start")

    def _info(self, sid: str) -> dict[str, Any]:
        sb = self.sandboxes[sid]
        return {"sandbox_id": sid, "env": sb["env"], "engine": sb.get("engine", "moto"),
                "emulator_endpoint": f"http://127.0.0.1:{sb['port']}",
                "terminal_endpoint": "ws://127.0.0.1:9/ws", "emulator_image_id": "sha256:fake-emulator",
                "terminal_image_id": "sha256:fake-terminal"}

    def kill(self, sid: str, oom: bool = False) -> None:
        """Simulate the emulator dying (sandbox_lost / OOM)."""
        sb = self.sandboxes[sid]
        sb["proc"].kill()
        sb["dead"] = "oom" if oom else "exited"

    def shutdown(self) -> None:
        for sb in self.sandboxes.values():
            sb["proc"].kill()
        self.sandboxes.clear()

    # --- RunnerClient protocol
    async def capacity(self) -> dict[str, Any]:
        if not self.healthy:
            raise RunnerError("runtime_unavailable", "fake runner down", 503)
        return {"runner_id": self.runner_id, "version": "fake", "max_sandboxes": self.max_sandboxes,
                "active": len(self.sandboxes), "docker_ok": True, "engines": dict(self.engines),
                "default_engine": "floci", "cpu_count": 4, "mem_total_mib": 8192, "mem_available_mib": 4096}

    async def list_sandboxes(self, env: str | None = None) -> list[dict[str, Any]]:
        return [await self.sandbox_status(sid) for sid, sb in self.sandboxes.items()
                if env is None or sb["env"] == env]

    async def create_sandbox(self, req: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("create", req["sandbox_id"]))
        if self.create_delay_s:
            await asyncio.sleep(self.create_delay_s)
        if self.fail_create:
            raise RunnerError(self.fail_create, "fake failure", 503)
        if req.get("setup"):
            raise RunnerError("not_supported", "FakeRunner cannot run setup jobs", 400)
        old = self.sandboxes.pop(req["sandbox_id"], None)
        if old:
            old["proc"].kill()
        proc, port = await asyncio.to_thread(self._spawn)
        self.sandboxes[req["sandbox_id"]] = {"proc": proc, "port": port, "env": req["env"], "dead": None,
                                             "engine": req.get("engine") or "moto",
                                             "credential": req["terminal_credential"]}
        return self._info(req["sandbox_id"])

    async def reset_sandbox(self, sandbox_id: str, req: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("reset", sandbox_id))
        sb = self.sandboxes.get(sandbox_id)
        if sb is None:
            raise RunnerError("not_found", "sandbox not found", 404)
        sb["proc"].kill()
        proc, port = await asyncio.to_thread(self._spawn)
        sb.update(proc=proc, port=port, dead=None, credential=req["terminal_credential"])
        return self._info(sandbox_id)

    async def destroy_sandbox(self, sandbox_id: str) -> None:
        self.calls.append(("destroy", sandbox_id))
        sb = self.sandboxes.pop(sandbox_id, None)
        if sb:
            sb["proc"].kill()

    async def sandbox_status(self, sandbox_id: str) -> dict[str, Any]:
        sb = self.sandboxes.get(sandbox_id)
        if sb is None:
            missing = {"state": "missing", "exit_code": None}
            return {"sandbox_id": sandbox_id, "env": None, "exists": False, "emulator": missing,
                    "terminal": missing}
        emu = {"state": sb["dead"] or "running", "exit_code": None}
        return {"sandbox_id": sandbox_id, "env": sb["env"], "exists": True, "emulator": emu,
                "terminal": {"state": "running", "exit_code": None}}

    async def run_job(self, sandbox_id: str, job: dict[str, Any]) -> dict[str, Any]:
        raise RunnerError("not_supported", "FakeRunner cannot run jobs", 400)
