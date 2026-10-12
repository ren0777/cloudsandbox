"""FakeRunner: implements the RunnerClient protocol without Docker. Each "sandbox" is a real Moto
server subprocess (isolated state, real S3 semantics), so evidence capture, grading and the console
behave exactly as against the real runner. Terminal endpoints are not available.

A sandbox created with `audit=True` also runs the REAL audit proxy (images/terminal/audit_proxy.py) in front of
its Moto, as a subprocess; console calls then go through it exactly as on the runner."""

from __future__ import annotations

import asyncio
import base64
import io
import os
import socket
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.runtime.runner_client import RunnerError


def audit_proxy_path() -> Path | None:
    """The proxy source: the repo checkout (CI, local) or the file the api-test container mounts."""
    here = Path(__file__).resolve()
    candidates = [Path(os.environ["CL_AUDIT_PROXY"])] if os.environ.get("CL_AUDIT_PROXY") else []
    if len(here.parents) > 3:
        candidates.append(here.parents[3] / "images" / "terminal" / "audit_proxy.py")
    candidates.append(Path("/opt/cloudlabs/audit_proxy.py"))
    return next((c for c in candidates if c.is_file()), None)


def _wait_port(port: int, path: str = "/") -> bool:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=1)
            return True
        except urllib.error.HTTPError:
            return True
        except Exception:
            time.sleep(0.1)
    return False


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeRunner:
    def __init__(self, max_sandboxes: int = 4, runner_id: str | None = None,
                 engines: dict[str, bool] | None = None):
        self.runner_id = runner_id or get_settings().runner_id
        self.engines = engines if engines is not None else {"moto": True, "floci": True, "ministack": True}
        self.max_sandboxes = max_sandboxes
        self.sandboxes: dict[str, dict[str, Any]] = {}
        self.fail_create: str | None = None
        self.create_delay_s = 0.0
        self.calls: list[tuple[str, str]] = []
        self.healthy = True
        # run_job hook: (emulator_endpoint, job files {name: bytes}) -> (exit_code, output). Tests use it to
        # apply a lab script's effect with boto3 (there is no terminal image to run bash + aws CLI in).
        self.job_handler: Callable[[str, dict[str, bytes]], tuple[int, str]] | None = None

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

    def _spawn_audit(self, upstream_port: int) -> tuple[subprocess.Popen, int]:
        path = audit_proxy_path()
        if path is None:
            raise RunnerError("not_supported", "audit proxy source not found (set CL_AUDIT_PROXY)", 400)
        port = _free_port()
        # 192.0.2.1 (TEST-NET) as the terminal: the API process is never it, so console calls count as console
        env = {**os.environ, "AUDIT_PORT": str(port), "AUDIT_UPSTREAM": f"127.0.0.1:{upstream_port}",
               "AUDIT_TERMINAL_HOST": "192.0.2.1"}
        proc = subprocess.Popen([sys.executable, "-I", str(path)], env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not _wait_port(port, "/_cloudlabs/audit"):
            proc.kill()
            raise RuntimeError("audit proxy did not start")
        return proc, port

    def _start(self, sb: dict[str, Any]) -> None:
        sb["proc"], sb["port"] = self._spawn()
        if sb.get("audit"):
            sb["audit_proc"], sb["audit_port"] = self._spawn_audit(sb["port"])

    @staticmethod
    def _stop(sb: dict[str, Any]) -> None:
        for key in ("audit_proc", "proc"):
            if sb.get(key) is not None:
                sb[key].kill()

    def _info(self, sid: str) -> dict[str, Any]:
        sb = self.sandboxes[sid]
        return {"sandbox_id": sid, "env": sb["env"], "engine": sb.get("engine", "moto"),
                "audit_endpoint": f"http://127.0.0.1:{sb['audit_port']}" if sb.get("audit") else None,
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
            self._stop(sb)
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
            self._stop(old)
        sb = {"env": req["env"], "dead": None, "engine": req.get("engine") or "moto",
              "credential": req["terminal_credential"], "audit": bool(req.get("audit"))}
        await asyncio.to_thread(self._start, sb)
        self.sandboxes[req["sandbox_id"]] = sb
        return self._info(req["sandbox_id"])

    async def reset_sandbox(self, sandbox_id: str, req: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("reset", sandbox_id))
        sb = self.sandboxes.get(sandbox_id)
        if sb is None:
            raise RunnerError("not_found", "sandbox not found", 404)
        self._stop(sb)
        await asyncio.to_thread(self._start, sb)
        sb.update(dead=None, credential=req["terminal_credential"])
        return self._info(sandbox_id)

    async def destroy_sandbox(self, sandbox_id: str) -> None:
        self.calls.append(("destroy", sandbox_id))
        sb = self.sandboxes.pop(sandbox_id, None)
        if sb:
            self._stop(sb)

    async def sandbox_status(self, sandbox_id: str) -> dict[str, Any]:
        sb = self.sandboxes.get(sandbox_id)
        if sb is None:
            missing = {"state": "missing", "exit_code": None}
            return {"sandbox_id": sandbox_id, "env": None, "exists": False, "emulator": missing,
                    "terminal": missing}
        emu = {"state": sb["dead"] or "running", "exit_code": None}
        return {"sandbox_id": sandbox_id, "env": sb["env"], "exists": True, "emulator": emu,
                "terminal": {"state": "running", "exit_code": None}, "created_at": sb.get("created_at")}

    async def run_job(self, sandbox_id: str, job: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("job", sandbox_id))
        if self.job_handler is None:
            raise RunnerError("not_supported", "FakeRunner cannot run jobs", 400)
        sb = self.sandboxes.get(sandbox_id)
        if sb is None:
            raise RunnerError("not_found", "sandbox not found", 404)
        with tarfile.open(fileobj=io.BytesIO(base64.b64decode(job["bundle_b64"]))) as tf:
            files = {m.name: tf.extractfile(m).read() for m in tf.getmembers() if m.isfile()}  # type: ignore[union-attr]
        port = sb["audit_port"] if job.get("audited") and sb.get("audit") else sb["port"]  # like the runner
        code, output = await asyncio.to_thread(self.job_handler, f"http://127.0.0.1:{port}", files)
        return {"exit_code": code, "output": output}
