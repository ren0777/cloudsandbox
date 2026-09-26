"""DockerDriver: one internal (no-egress) bridge network per sandbox holding an emulator and a terminal.

Labels on every object: cloudlabs.session / cloudlabs.runner / cloudlabs.env / cloudlabs.component.
Control-plane containers (label cloudlabs.role=control-plane, same cloudlabs.env) are connected to the
sandbox network so the API can reach the emulator and ttyd (STATUS.md decision D1).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import os
import secrets
import socket
import tarfile
import threading
import time
from collections import defaultdict

import docker
import structlog
from docker.errors import APIError, NotFound
from docker.models.containers import Container
from docker.models.networks import Network

from .config import EmulatorSpec, Settings
from .driver import (
    Capacity,
    ComponentStatus,
    CreateSandbox,
    JobResult,
    JobSpec,
    ResetSandbox,
    Resources,
    RunnerStats,
    SandboxInfo,
    SandboxStatus,
    SandboxUsage,
)

log = structlog.get_logger()

L_SESSION = "cloudlabs.session"
L_RUNNER = "cloudlabs.runner"
L_ENV = "cloudlabs.env"
L_COMPONENT = "cloudlabs.component"
L_ROLE = "cloudlabs.role"
L_EMULATOR = "cloudlabs.engine"
L_GW_TOKEN = "cloudlabs.gateway_token"  # gateway mode: per-sandbox access token for the control plane
L_CREATED = "cloudlabs.created_at"  # unix seconds; lets the control plane age orphan candidates

TTYD_PORT = 7681
EMULATOR_UID = "10001"
STUDENT_UID = "10002"


class DriverError(Exception):
    def __init__(self, code: str, message: str, status: int = 500):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def net_name(sandbox_id: str) -> str:
    return f"cl-sbx-{sandbox_id}"


def container_name(sandbox_id: str, component: str) -> str:
    return f"cl-sbx-{sandbox_id}-{component}"


def host_memory_mib() -> tuple[int | None, int | None]:
    """(total, available) MiB of the host (Linux /proc/meminfo; inside a container this is the VM/host)."""
    try:
        info = {}
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.strip().split()[0])  # kB
        return info["MemTotal"] // 1024, info.get("MemAvailable", info.get("MemFree", 0)) // 1024
    except (OSError, KeyError, ValueError):
        return None, None


class DockerDriver:
    def __init__(self, settings: Settings, client: docker.DockerClient | None = None):
        self.s = settings
        self.client = client or docker.from_env()
        self._locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
        self._leaked: set[str] = set()  # sandbox ids whose empty network Docker won't remove (stale endpoints)
        self._global = threading.Lock()

    # ------------------------------------------------------------------ helpers
    def _lock(self, sandbox_id: str) -> threading.Lock:
        with self._global:
            return self._locks[sandbox_id]

    def _labels(self, sandbox_id: str, env: str, component: str) -> dict[str, str]:
        return {L_SESSION: sandbox_id, L_RUNNER: self.s.id, L_ENV: env, L_COMPONENT: component}

    def _clamp(self, r: Resources) -> Resources:
        return Resources(
            cpus=min(r.cpus, self.s.cap_cpus),
            memory_mib=min(r.memory_mib, self.s.cap_memory_mib),
            pids=min(r.pids, self.s.cap_pids),
        )

    def _limits(self, r: Resources) -> dict:
        r = self._clamp(r)
        mem = f"{r.memory_mib}m"
        return {
            "nano_cpus": int(r.cpus * 1e9),
            "mem_limit": mem,
            "memswap_limit": mem,  # no swap
            "pids_limit": r.pids,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges"],
        }

    def _endpoint_config(self, aliases: list[str]):
        return self.client.api.create_endpoint_config(aliases=aliases)

    def _get_network(self, sandbox_id: str) -> Network | None:
        try:
            net = self.client.networks.get(net_name(sandbox_id))
        except NotFound:
            return None
        if net.attrs.get("Labels", {}).get(L_RUNNER) != self.s.id:
            raise DriverError("foreign_sandbox", "sandbox belongs to another runner", 409)
        return net

    def _get_container(self, sandbox_id: str, component: str) -> Container | None:
        try:
            c = self.client.containers.get(container_name(sandbox_id, component))
        except NotFound:
            return None
        if c.labels.get(L_RUNNER) != self.s.id:
            raise DriverError("foreign_sandbox", "sandbox belongs to another runner", 409)
        return c

    def _remove_container(self, c: Container | None) -> None:
        if c is None:
            return
        try:
            c.remove(force=True, v=True)
        except NotFound:
            pass

    def _ip_on(self, c: Container, network: str) -> str:
        c.reload()
        nets = c.attrs["NetworkSettings"]["Networks"]
        ip = nets.get(network, {}).get("IPAddress")
        if not ip:
            raise DriverError("no_ip", f"container {c.name} has no IP on {network}")
        return ip

    def _wait_healthy(self, c: Container, what: str) -> None:
        deadline = time.monotonic() + self.s.health_timeout_s
        while time.monotonic() < deadline:
            c.reload()
            state = c.attrs["State"]
            if state.get("Status") in ("exited", "dead"):
                raise DriverError("component_exited", f"{what} exited during startup "
                                  f"(code {state.get('ExitCode')})")
            if state.get("Health", {}).get("Status") == "healthy":
                return
            time.sleep(0.4)
        raise DriverError("health_timeout", f"{what} did not become healthy in time", 504)

    def _attach_access(self, net: Network, env: str) -> None:
        """Give the control plane a path to the sandbox: attach its containers (direct mode, one Docker host)
        or attach this runner itself, which then forwards per sandbox (gateway mode, any host)."""
        if self.s.access_mode == "gateway":
            self._attach_self(net)
        else:
            self._attach_control_plane(net, env)

    def _attach_self(self, net: Network) -> None:
        net.reload()
        me = self.client.containers.get(socket.gethostname())  # the runner's own container
        if me.id in (net.attrs.get("Containers") or {}):
            return
        try:
            net.connect(me)
        except APIError as e:
            if "already exists" not in str(e):
                raise

    def gateway_target(self, sandbox_id: str, token: str) -> dict[str, str]:
        """Upstream URLs for a gateway request, only for this runner's sandbox with the right token.
        Any mismatch answers not_found, so tokens and sandbox ids can't be probed."""
        if self.s.access_mode != "gateway":
            raise DriverError("not_found", "not found", 404)
        try:
            net = self._get_network(sandbox_id)
        except DriverError:
            net = None
        expected = (net.attrs.get("Labels", {}).get(L_GW_TOKEN) if net else None) or ""
        if not net or not expected or not hmac.compare_digest(expected, token):
            raise DriverError("not_found", "not found", 404)
        _, spec = self._net_spec(net)
        emu_c = self._get_container(sandbox_id, "emulator")
        term_c = self._get_container(sandbox_id, "terminal")
        name = net_name(sandbox_id)
        out = {}
        if emu_c is not None:
            out["emulator"] = f"http://{self._ip_on(emu_c, name)}:{spec.port}"
        if term_c is not None:
            out["terminal"] = f"ws://{self._ip_on(term_c, name)}:{TTYD_PORT}/ws"
        return out

    def _attach_control_plane(self, net: Network, env: str) -> None:
        net.reload()
        attached = set((net.attrs.get("Containers") or {}).keys())
        for c in self.client.containers.list(filters={"label": [f"{L_ROLE}=control-plane",
                                                                 f"{L_ENV}={env}"]}):
            if c.id in attached:
                continue
            try:
                net.connect(c)
            except APIError as e:  # already connected / container going away
                if "already exists" not in str(e) and "not found" not in str(e).lower():
                    raise

    def _spec(self, name: str | None) -> tuple[str, EmulatorSpec]:
        name = name or self.s.default_emulator
        spec = self.s.emulators.get(name)
        if spec is None:
            raise DriverError("unknown_emulator", f"emulator {name!r} is not configured on this runner", 400)
        return name, spec

    def _net_spec(self, net: Network) -> tuple[str, EmulatorSpec]:
        return self._spec(net.attrs.get("Labels", {}).get(L_EMULATOR))

    def _client_endpoint(self, spec: EmulatorSpec, emu_c: Container, net: str) -> str:
        """Endpoint that in-sandbox clients (terminal, jobs) use to reach the emulator."""
        host = self._ip_on(emu_c, net) if spec.endpoint_by_ip else "emulator"
        return f"http://{host}:{spec.port}"

    def _image_id(self, ref: str) -> str:
        return self.client.images.get(ref).id

    # --------------------------------------------------------------- components
    def _start_emulator(self, sandbox_id: str, env: str, r: Resources, net: str, emu: str,
                        spec: EmulatorSpec) -> Container:
        c = self.client.containers.create(
            spec.image,
            name=container_name(sandbox_id, "emulator"),
            hostname="emulator",
            labels={**self._labels(sandbox_id, env, "emulator"), L_EMULATOR: emu},
            user=EMULATOR_UID,
            read_only=True,
            tmpfs={"/tmp": "size=32m", **spec.tmpfs},
            environment=spec.env,
            network=net,
            networking_config={net: self._endpoint_config(["emulator"])},
            detach=True,
            **self._limits(r),
        )
        c.start()
        self._wait_healthy(c, "emulator")
        return c

    def _start_terminal(self, sandbox_id: str, env: str, r: Resources, net: str,
                        credential: str, endpoint: str) -> Container:
        c = self.client.containers.create(
            self.s.terminal_image,
            name=container_name(sandbox_id, "terminal"),
            hostname="cloudlabs",
            labels=self._labels(sandbox_id, env, "terminal"),
            user=STUDENT_UID,
            read_only=True,
            tmpfs={"/tmp": "size=32m", "/home/student": f"size=64m,uid={STUDENT_UID},gid={STUDENT_UID}"},
            environment={
                "AWS_ENDPOINT_URL": endpoint,
                "AWS_DEFAULT_REGION": "us-east-1",
                "TTYD_CREDENTIAL": credential,
            },
            healthcheck={
                "test": ["CMD", "bash", "-c", f"exec 3<>/dev/tcp/127.0.0.1/{TTYD_PORT}"],
                "interval": 1_000_000_000, "timeout": 1_000_000_000, "retries": 60,
            },
            network=net,
            networking_config={net: self._endpoint_config(["terminal"])},
            detach=True,
            **self._limits(r),
        )
        c.start()
        self._wait_healthy(c, "terminal")
        return c

    def _run_job(self, sandbox_id: str, env: str, net: str, job: JobSpec, endpoint: str) -> JobResult:
        data = base64.b64decode(job.bundle_b64)
        if hashlib.sha256(data).hexdigest() != job.sha256:
            raise DriverError("bundle_hash_mismatch", "job bundle hash does not match", 400)
        with tarfile.open(fileobj=io.BytesIO(data)) as tf:  # validate archive + script presence
            names = set(tf.getnames())
            for m in tf.getmembers():
                if m.name.startswith("/") or ".." in m.name.split("/") or not (m.isfile() or m.isdir()):
                    raise DriverError("bad_bundle", f"illegal member {m.name!r}", 400)
        if job.script not in names and f"./{job.script}" not in names:
            raise DriverError("bad_bundle", f"script {job.script!r} not in bundle", 400)
        timeout = min(job.timeout_s, self.s.job_timeout_cap_s)
        c = self.client.containers.create(
            self.s.terminal_image,
            command=["job", job.script],
            name=f"{container_name(sandbox_id, 'job')}-{int(time.time() * 1000)}",
            labels=self._labels(sandbox_id, env, "job"),
            user=STUDENT_UID,
            environment={"AWS_ENDPOINT_URL": endpoint,
                         "AWS_DEFAULT_REGION": "us-east-1"},
            healthcheck={"test": ["NONE"]},
            network=net,
            detach=True,
            **self._limits(Resources(cpus=0.5, memory_mib=256, pids=128)),
        )
        try:
            c.put_archive("/work", data)
            c.start()
            timed_out = False
            try:
                res = c.wait(timeout=timeout)
                code = int(res.get("StatusCode", 1))
            except Exception:  # requests ReadTimeout
                timed_out, code = True, 124
                c.kill()
            out = c.logs(stdout=True, stderr=True)[-8192:].decode("utf-8", "replace")
            return JobResult(exit_code=code, output=out, timed_out=timed_out)
        finally:
            self._remove_container(c)

    # ------------------------------------------------------------------ public
    def _info(self, sid: str, env: str, emu: str, spec: EmulatorSpec, emu_c: Container, term_c: Container,
              net: str, token: str | None = None) -> SandboxInfo:
        if self.s.access_mode == "gateway":
            base = f"{(self.s.public_url or '').rstrip('/')}/gw/{sid}/{token}"
            emulator_endpoint = f"{base}/emulator"
            terminal_endpoint = base.replace("http://", "ws://", 1).replace("https://", "wss://", 1) + "/terminal/ws"
        else:
            emulator_endpoint = f"http://{self._ip_on(emu_c, net)}:{spec.port}"
            terminal_endpoint = f"ws://{self._ip_on(term_c, net)}:{TTYD_PORT}/ws"
        return SandboxInfo(
            sandbox_id=sid, env=env, engine=emu,
            emulator_endpoint=emulator_endpoint, terminal_endpoint=terminal_endpoint,
            emulator_image_id=self._image_id(spec.image),
            terminal_image_id=self._image_id(self.s.terminal_image),
        )

    def create(self, req: CreateSandbox) -> SandboxInfo:
        sid = req.sandbox_id
        emu, spec = self._spec(req.engine)
        with self._lock(sid):
            if self._get_network(sid) is None and self._count_active() >= self.s.max_sandboxes:
                raise DriverError("capacity_full", "runner is at capacity", 503)
            self._destroy_unlocked(sid)  # a retried create starts from scratch
            name = net_name(sid)
            t0 = time.monotonic()
            token = secrets.token_urlsafe(24) if self.s.access_mode == "gateway" else None
            net = self.client.networks.create(
                name, driver="bridge", internal=True, check_duplicate=True,
                labels={**self._labels(sid, req.env, "network"), L_EMULATOR: emu, L_CREATED: str(int(time.time())),
                        **({L_GW_TOKEN: token} if token else {})},
            )
            try:
                self._attach_access(net, req.env)
                emu_c = self._start_emulator(sid, req.env, req.emulator, name, emu, spec)
                ep = self._client_endpoint(spec, emu_c, name)
                if req.setup:
                    res = self._run_job(sid, req.env, name, req.setup, ep)
                    if res.exit_code != 0:
                        raise DriverError("setup_failed", f"setup exited {res.exit_code}: {res.output[-500:]}")
                term = self._start_terminal(sid, req.env, req.terminal, name, req.terminal_credential, ep)
                info = self._info(sid, req.env, emu, spec, emu_c, term, name, token)
                log.info("sandbox.create.succeeded", sandbox_id=sid, env=req.env, engine=emu,
                         duration_ms=int((time.monotonic() - t0) * 1000))
                return info
            except Exception:
                self._destroy_unlocked(sid)
                raise

    def reset(self, sandbox_id: str, req: ResetSandbox) -> SandboxInfo:
        with self._lock(sandbox_id):
            net = self._get_network(sandbox_id)
            if net is None:
                raise DriverError("not_found", "sandbox not found", 404)
            env = net.attrs["Labels"][L_ENV]
            emu, spec = self._net_spec(net)  # a reset keeps the sandbox's emulator
            name = net_name(sandbox_id)
            for comp in ("terminal", "emulator"):
                self._remove_container(self._get_container(sandbox_id, comp))
            self._attach_access(net, env)
            emu_c = self._start_emulator(sandbox_id, env, req.emulator, name, emu, spec)
            ep = self._client_endpoint(spec, emu_c, name)
            if req.setup:
                res = self._run_job(sandbox_id, env, name, req.setup, ep)
                if res.exit_code != 0:
                    raise DriverError("setup_failed", f"setup exited {res.exit_code}")
            term = self._start_terminal(sandbox_id, env, req.terminal, name, req.terminal_credential, ep)
            return self._info(sandbox_id, env, emu, spec, emu_c, term, name, net.attrs["Labels"].get(L_GW_TOKEN))

    def destroy(self, sandbox_id: str) -> None:
        with self._lock(sandbox_id):
            self._destroy_unlocked(sandbox_id)

    def _destroy_unlocked(self, sandbox_id: str) -> None:
        for c in self.client.containers.list(all=True, filters={"label": [f"{L_SESSION}={sandbox_id}",
                                                                          f"{L_RUNNER}={self.s.id}"]}):
            self._remove_container(c)
        try:
            net = self.client.networks.get(net_name(sandbox_id))
        except NotFound:
            return
        if net.attrs.get("Labels", {}).get(L_RUNNER) != self.s.id:
            return
        for attempt in range(3):  # a control-plane container can still hold an endpoint: detach and retry
            net.reload()
            for cid in list((net.attrs.get("Containers") or {}).keys()):
                try:
                    net.disconnect(cid, force=True)
                except (NotFound, APIError):
                    pass
            try:
                net.remove()
                break
            except NotFound:
                break
            except APIError as e:
                if "active endpoints" not in str(e):
                    raise
                if attempt == 2:
                    net.reload()
                    if net.attrs.get("Containers"):
                        raise
                    # Docker kept a stale endpoint (no container behind it): the sandbox's containers are gone, so
                    # the lab is destroyed; the empty network is recorded as leaked instead of failing forever.
                    self._leaked.add(sandbox_id)
                    log.warning("sandbox.network_leaked", sandbox_id=sandbox_id, error=str(e)[:200])
                    return
                time.sleep(0.5)
        self._leaked.discard(sandbox_id)
        log.info("sandbox.destroy.succeeded", sandbox_id=sandbox_id)

    def _component_status(self, sandbox_id: str, comp: str) -> ComponentStatus:
        c = self._get_container(sandbox_id, comp)
        if c is None:
            return ComponentStatus(state="missing")
        st = c.attrs["State"]
        if st.get("OOMKilled"):
            return ComponentStatus(state="oom", exit_code=st.get("ExitCode"))
        if st.get("Status") == "running":
            health = st.get("Health", {}).get("Status")
            return ComponentStatus(state="starting" if health == "starting" else "running")
        if st.get("Status") == "created":
            return ComponentStatus(state="starting")
        return ComponentStatus(state="exited", exit_code=st.get("ExitCode"))

    def status(self, sandbox_id: str) -> SandboxStatus:
        net = self._get_network(sandbox_id)
        created: float | None = None
        if net is not None:
            raw = (net.attrs.get("Labels") or {}).get(L_CREATED)
            try:
                created = float(raw) if raw else None
            except ValueError:
                created = None
        return SandboxStatus(
            sandbox_id=sandbox_id,
            env=net.attrs["Labels"].get(L_ENV) if net else None,
            exists=net is not None,
            emulator=self._component_status(sandbox_id, "emulator"),
            terminal=self._component_status(sandbox_id, "terminal"),
            created_at=created,
        )

    def _sandbox_networks(self, env: str | None = None) -> list[Network]:
        labels = [f"{L_RUNNER}={self.s.id}", f"{L_COMPONENT}=network"]
        if env:
            labels.append(f"{L_ENV}={env}")
        return [n for n in self.client.networks.list(filters={"label": labels})
                if n.attrs.get("Labels", {}).get(L_SESSION) not in self._leaked]

    def list(self, env: str | None) -> list[SandboxStatus]:
        ids: set[str] = {n.attrs["Labels"][L_SESSION] for n in self._sandbox_networks(env)}
        labels = [f"{L_RUNNER}={self.s.id}"] + ([f"{L_ENV}={env}"] if env else [])
        for c in self.client.containers.list(all=True, filters={"label": labels}):
            if L_SESSION in c.labels:
                ids.add(c.labels[L_SESSION])
        return [self.status(i) for i in sorted(ids)]

    def run_job(self, sandbox_id: str, job: JobSpec) -> JobResult:
        with self._lock(sandbox_id):
            net = self._get_network(sandbox_id)
            if net is None:
                raise DriverError("not_found", "sandbox not found", 404)
            _, spec = self._net_spec(net)
            emu_c = self._get_container(sandbox_id, "emulator")
            if emu_c is None:
                raise DriverError("not_found", "sandbox emulator not found", 404)
            return self._run_job(sandbox_id, net.attrs["Labels"][L_ENV], net_name(sandbox_id), job,
                                 self._client_endpoint(spec, emu_c, net_name(sandbox_id)))

    def stats(self, env: str | None) -> RunnerStats:
        """Memory per sandbox (Docker stats snapshot of this runner's own containers, in parallel)."""
        from concurrent.futures import ThreadPoolExecutor
        labels = [f"{L_RUNNER}={self.s.id}"] + ([f"{L_ENV}={env}"] if env else [])
        containers = [c for c in self.client.containers.list(filters={"label": labels}) if L_SESSION in c.labels]

        def one(c: Container) -> tuple[str, float, float]:
            try:
                m = c.stats(stream=False).get("memory_stats", {})
                usage = m.get("usage", 0) - (m.get("stats", {}) or {}).get("inactive_file", 0)
                return c.labels[L_SESSION], max(0, usage) / 1048576, m.get("limit", 0) / 1048576
            except Exception:
                return c.labels[L_SESSION], 0.0, 0.0
        per: dict[str, list[float]] = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            for sid, used, limit in pool.map(one, containers):
                acc = per.setdefault(sid, [0.0, 0.0])
                acc[0] += used
                acc[1] += limit
        total, avail = host_memory_mib()
        items = [SandboxUsage(sandbox_id=k, memory_mib=round(v[0], 1), memory_limit_mib=round(v[1], 1)) for k, v in sorted(per.items())]
        return RunnerStats(runner_id=self.s.id, sandboxes=items, sandbox_memory_mib=round(sum(i.memory_mib for i in items), 1),
                           mem_total_mib=total, mem_available_mib=avail)

    def _count_active(self) -> int:
        return len(self._sandbox_networks())

    def capacity(self) -> Capacity:
        try:
            ok = bool(self.client.ping())
        except Exception:
            ok = False
        active = self._count_active() if ok else 0
        present: dict[str, bool] = {}
        terminal_ok = False
        if ok:
            for name, spec in self.s.emulators.items():
                present[name] = self._has_image_cached(spec.image)
            terminal_ok = self._has_image_cached(self.s.terminal_image)
        images_ok = terminal_ok and present.get(self.s.default_emulator, False)
        # an engine is usable only if its emulator image AND the terminal image are present
        engines = {name: bool(v and terminal_ok) for name, v in present.items()}
        total, avail = host_memory_mib()
        return Capacity(runner_id=self.s.id, version=self.s.version, max_sandboxes=self.s.max_sandboxes,
                        active=active, docker_ok=ok, images_ok=images_ok,
                        default_engine=self.s.default_emulator, engines=engines,
                        cpu_count=os.cpu_count(), mem_total_mib=total, mem_available_mib=avail,
                        leaked_networks=len(self._leaked))

    _image_cache: dict[str, tuple[float, bool]] = {}
    IMAGE_CACHE_S = 30.0

    def _has_image_cached(self, ref: str) -> bool:
        """Heartbeats ask every ~15 s; image presence changes rarely, so avoid Docker calls under load."""
        hit = self._image_cache.get(ref)
        if hit and time.monotonic() - hit[0] < self.IMAGE_CACHE_S:
            return hit[1]
        ok = self._has_image(ref)
        self._image_cache[ref] = (time.monotonic(), ok)
        return ok

    def _has_image(self, ref: str) -> bool:
        try:
            self.client.images.get(ref)
            return True
        except NotFound:
            return False

    def reattach_all(self) -> None:
        """Keep control-plane containers attached to every sandbox network (e.g. after an API
        container is recreated)."""
        for net in self._sandbox_networks():
            sid = net.attrs["Labels"].get(L_SESSION, "")
            lock = self._lock(sid)
            if not lock.acquire(blocking=False):
                continue  # being created, reset or destroyed right now: that operation handles access itself
            try:
                if self._get_container(sid, "emulator") is None:
                    continue  # half-destroyed sandbox: re-attaching would block the network's removal
                self._attach_access(net, net.attrs["Labels"][L_ENV])
            except Exception as e:  # never let the loop die
                log.warning("runner.reattach_failed", network=net.name, error=str(e))
            finally:
                lock.release()
