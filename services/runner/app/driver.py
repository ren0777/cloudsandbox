"""SandboxDriver interface. DockerDriver is the first implementation; Swarm/Kubernetes drivers can be
added behind the same protocol without touching the control plane."""

from typing import Literal, Protocol

from pydantic import BaseModel, Field

ENV_PATTERN = r"^[a-z][a-z0-9-]{0,30}$"


class Resources(BaseModel):
    cpus: float = Field(0.5, gt=0)
    memory_mib: int = Field(256, ge=64)
    pids: int = Field(128, ge=16)


class JobSpec(BaseModel):
    bundle_b64: str  # tar archive, extracted into /work of the job container
    sha256: str  # sha256 of the decoded bundle bytes; verified by the runner
    script: str = Field(pattern=r"^[A-Za-z0-9_./-]+$")
    timeout_s: int = Field(60, ge=1)


EMULATOR_PATTERN = r"^[a-z][a-z0-9-]{1,30}$"


class CreateSandbox(BaseModel):
    sandbox_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    env: str = Field(pattern=ENV_PATTERN)
    engine: str | None = Field(None, pattern=EMULATOR_PATTERN)  # emulator engine; None → runner default
    emulator: Resources = Resources(cpus=0.5, memory_mib=384, pids=128)
    terminal: Resources = Resources(cpus=0.5, memory_mib=256, pids=128)
    terminal_credential: str = Field(pattern=r"^[A-Za-z0-9_-]{4,64}:[A-Za-z0-9_-]{8,128}$")
    setup: JobSpec | None = None


class ResetSandbox(BaseModel):
    emulator: Resources = Resources(cpus=0.5, memory_mib=384, pids=128)
    terminal: Resources = Resources(cpus=0.5, memory_mib=256, pids=128)
    terminal_credential: str = Field(pattern=r"^[A-Za-z0-9_-]{4,64}:[A-Za-z0-9_-]{8,128}$")
    setup: JobSpec | None = None


class SandboxInfo(BaseModel):
    sandbox_id: str
    env: str
    engine: str
    emulator_endpoint: str  # http://<ip>:5000 on the sandbox network
    terminal_endpoint: str  # ws://<ip>:7681/ws on the sandbox network
    emulator_image_id: str
    terminal_image_id: str


ComponentState = Literal["running", "starting", "exited", "oom", "missing"]


class ComponentStatus(BaseModel):
    state: ComponentState
    exit_code: int | None = None


class SandboxStatus(BaseModel):
    sandbox_id: str
    env: str | None
    exists: bool
    emulator: ComponentStatus
    terminal: ComponentStatus


class JobResult(BaseModel):
    exit_code: int
    output: str  # last 8 KiB of combined stdout/stderr
    timed_out: bool = False


class Capacity(BaseModel):
    runner_id: str
    version: str
    max_sandboxes: int
    active: int
    docker_ok: bool
    images_ok: bool = False  # default emulator + terminal images present
    default_engine: str = ""
    engines: dict[str, bool] = {}  # engine name -> image present
    # Host resources for the control plane's scheduler (phase 7). None when unknown.
    cpu_count: int | None = None
    mem_total_mib: int | None = None
    mem_available_mib: int | None = None
    # sandbox networks Docker refused to remove although they hold no containers (stale endpoints); they hold no
    # student resources and don't count as seats. Cleared by a Docker daemon restart during maintenance.
    leaked_networks: int = 0


class SandboxUsage(BaseModel):
    sandbox_id: str
    memory_mib: float  # emulator + terminal (+ jobs) current usage
    memory_limit_mib: float


class RunnerStats(BaseModel):
    """Read-only resource usage of this runner's sandboxes (load testing and capacity planning)."""
    runner_id: str
    sandboxes: list[SandboxUsage]
    sandbox_memory_mib: float
    mem_total_mib: int | None = None
    mem_available_mib: int | None = None


class SandboxDriver(Protocol):
    def create(self, req: CreateSandbox) -> SandboxInfo: ...
    def reset(self, sandbox_id: str, req: ResetSandbox) -> SandboxInfo: ...
    def destroy(self, sandbox_id: str) -> None: ...
    def status(self, sandbox_id: str) -> SandboxStatus: ...
    def list(self, env: str | None) -> list[SandboxStatus]: ...
    def run_job(self, sandbox_id: str, job: JobSpec) -> JobResult: ...
    def capacity(self) -> Capacity: ...
