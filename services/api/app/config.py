from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CL_")

    env: str = Field("dev", pattern=r"^[a-z][a-z0-9-]{0,30}$")  # also the cloudlabs.env label
    database_url: str = "postgresql+asyncpg://cloudlabs_app:app@postgres:5432/cloudlabs"
    # Owner connection: migrations, demo reset, test truncation. Never used by request handlers.
    database_owner_url: str = "postgresql+asyncpg://cloudlabs_owner:owner@postgres:5432/cloudlabs"
    secret_key: str = "dev-insecure-change-me-dev-insecure-change-me"
    cookie_secure: bool = True
    allowed_origins: list[str] = ["http://localhost:3000"]
    allow_self_register: bool = False
    demo_mode: bool = False

    access_token_minutes: int = 15
    refresh_token_days: int = 7
    login_rate_per_minute: int = 10

    # Runner (slice 1: exactly one runner row, seeded at startup)
    runner_id: str = "runner-local-1"
    runner_url: str = "http://runner:7070"
    runner_secret: str = "dev-runner-secret"
    # Must exceed the runner's job cap (job_timeout_cap_s, 180 s): sandbox creation runs the lab's setup
    # synchronously, and a CLI-heavy compiled setup (a VPC network) can legitimately use the whole cap.
    runner_timeout_s: float = 240.0
    heartbeat_interval_s: float = 15.0
    runner_unhealthy_after_s: int = 90
    runner_lost_after_s: int = 300  # unreachable this long → its sessions fail (runner_lost), never migrate

    # Sessions (PLAN §2, §4)
    max_active_sessions_per_student: int = 1
    provision_deadline_s: int = 180
    reset_deadline_s: int = 180
    submit_deadline_s: int = 120
    requested_stale_s: int = 60
    idle_timeout_minutes: int = 20
    idle_warning_minutes: int = 15
    progress_min_interval_s: float = 10.0
    heartbeat_write_min_interval_s: float = 30.0
    janitor_interval_s: float = 15.0
    reconciler_interval_s: float = 30.0
    # A sandbox with no session/draft row is reaped as an orphan, except within this window: one-off
    # `labtest` sandboxes (no DB row) are in flight here. Older orphans are destroyed as before.
    orphan_grace_s: int = 300
    background_loops: bool = True

    # Per-sandbox quotas (PLAN §12) — platform defaults and admin caps
    emulator_cpus: float = 0.5
    emulator_memory_mib: int = 384
    emulator_pids: int = 128
    terminal_cpus: float = 0.5
    terminal_memory_mib: int = 256
    terminal_pids: int = 128
    cap_cpus: float = 1.0
    cap_memory_mib: int = 1024
    cap_pids: int = 512
    cap_ttl_minutes: int = 120
    cap_extended_ttl_minutes: int = 240  # a session's total lifetime including staff extensions
    cap_idle_min_minutes: int = 10
    cap_idle_max_minutes: int = 30

    console_max_upload_bytes: int = 5 * 1024 * 1024
    terminal_max_per_session: int = 2
    terminal_ticket_ttl_s: int = 30
    terminal_max_frame_bytes: int = 64 * 1024

    labs_dir: str = "/labs"
    # Lab Builder test runs (phase 8): one sandbox at a time per run, on the platform runner
    builder_max_concurrent_tests: int = 2
    builder_test_timeout_s: float = 900.0  # a run still "testing" after this is reported as interrupted
    # Interactive preview sandboxes (M42): idle lifetime and how many one author may keep running.
    preview_ttl_s: int = 1800
    preview_max_per_user: int = 2
    # Single-check runs against a preview sandbox (M47): minimum spacing between two runs for one draft.
    preview_check_min_interval_s: float = 1.0
    default_emulator: str = "floci"  # engine for labs with runtime.emulator = default (promoted, EMULATOR-EVALUATION.md)
    grader_version: str = "1.0.0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
