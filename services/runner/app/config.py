from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EmulatorSpec(BaseModel):
    """How to run one AWS emulator engine inside a sandbox. Everything engine-specific lives here, so the
    rest of the runner (and the whole control plane) stays emulator-agnostic."""
    image: str
    port: int
    tmpfs: dict[str, str] = Field(default_factory=dict)  # extra writable dirs (rootfs is read-only)
    env: dict[str, str] = Field(default_factory=dict)
    # Some engines mis-route requests addressed by a bare host alias (MiniStack treats it as an S3
    # virtual-host bucket); point in-sandbox clients at the emulator IP instead.
    endpoint_by_ip: bool = False


DEFAULT_EMULATORS = {
    "moto": EmulatorSpec(image="cloudlabs/emulator:dev", port=5000,
                         env={"MOTO_IAM_LOAD_MANAGED_POLICIES": "true"}),  # AWS managed policies for IAM labs
    "floci": EmulatorSpec(image="cloudlabs/emulator-floci:dev", port=4566,
                          tmpfs={"/app/data": "size=64m,mode=1777"},
                          env={"FLOCI_STORAGE_MODE": "memory"}),
    # Only for labs that pin runtime.emulator: ministack (in-process Lambda execution, no Docker socket).
    "ministack": EmulatorSpec(image="cloudlabs/emulator-ministack:dev", port=4566, endpoint_by_ip=True),
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RUNNER_")

    id: str = "runner-local-1"
    secret: str  # shared HMAC secret with the control plane (required)
    max_sandboxes: int = 4
    emulators: dict[str, EmulatorSpec] = Field(default_factory=lambda: dict(DEFAULT_EMULATORS))
    default_emulator: str = "floci"  # promoted 2026-09-25, see docs/EMULATOR-EVALUATION.md
    terminal_image: str = "cloudlabs/terminal:dev"
    # Hard caps enforced by the runner regardless of what the control plane asks for.
    cap_cpus: float = 1.0
    cap_memory_mib: int = 1024
    cap_pids: int = 512
    job_timeout_cap_s: int = 180
    health_timeout_s: float = 60.0
    reattach_interval_s: float = 10.0
    signature_window_s: int = 30
    version: str = "0.1.0"
    # How the control plane reaches sandboxes (phase 7):
    #   direct  – the control plane's containers are attached to each sandbox network (one Docker host, D1)
    #   gateway – this runner attaches ITSELF and forwards emulator HTTP / terminal WebSocket traffic for each
    #             sandbox at <public_url>/gw/<sandbox>/<token>/… (runners on other servers)
    access_mode: Literal["direct", "gateway"] = "direct"
    public_url: str | None = None  # e.g. http://10.0.0.12:7070, as the API server reaches this runner


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
