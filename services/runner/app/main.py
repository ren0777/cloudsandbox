"""Runner Agent HTTP API. Typed operations only — there is deliberately no generic exec endpoint.
Every request must carry a valid HMAC signature (PLAN §10)."""

from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from .config import Settings, get_settings
from .docker_driver import DockerDriver, DriverError
from .driver import (
    Capacity,
    CreateSandbox,
    JobResult,
    JobSpec,
    ResetSandbox,
    RunnerStats,
    SandboxInfo,
    SandboxStatus,
)
from . import gateway
from .signing import SIGNATURE_HEADER, TIMESTAMP_HEADER, verify

structlog.configure(
    processors=[structlog.contextvars.merge_contextvars, structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"), structlog.processors.JSONRenderer()],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
)
log = structlog.get_logger()


def create_app(settings: Settings | None = None, driver: DockerDriver | None = None) -> FastAPI:
    settings = settings or get_settings()
    state: dict = {"driver": driver}

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if settings.reattach_interval_s > 0:
            def loop() -> None:
                while True:
                    time.sleep(settings.reattach_interval_s)
                    try:
                        get_driver().reattach_all()
                    except Exception as e:  # pragma: no cover - defensive
                        log.warning("runner.reattach_failed", error=str(e))

            threading.Thread(target=loop, name="reattach", daemon=True).start()
        yield

    app = FastAPI(title="CloudLabs Runner", version=settings.version, docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)

    def get_driver() -> DockerDriver:
        if state["driver"] is None:
            state["driver"] = DockerDriver(settings)
        return state["driver"]

    if settings.access_mode == "gateway" and not settings.public_url:
        raise RuntimeError("RUNNER_ACCESS_MODE=gateway needs RUNNER_PUBLIC_URL (how the API server reaches this runner)")
    app.include_router(gateway.make_router(get_driver))

    @app.middleware("http")
    async def hmac_auth(request: Request, call_next):
        if request.url.path.startswith("/gw/"):  # sandbox gateway: per-sandbox token, see gateway.py
            return await call_next(request)
        body = await request.body()
        path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        ok = verify(settings.secret, request.method, path, body,
                    request.headers.get(TIMESTAMP_HEADER), request.headers.get(SIGNATURE_HEADER),
                    settings.signature_window_s)
        if not ok:
            return JSONResponse({"error": {"code": "unauthorized", "message": "bad signature"}}, 401)
        structlog.contextvars.bind_contextvars(request_id=request.headers.get("X-Request-ID"))
        try:
            return await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()

    @app.exception_handler(DriverError)
    async def driver_error(_: Request, e: DriverError):
        return JSONResponse({"error": {"code": e.code, "message": e.message}}, e.status)

    # Sync handlers run in the threadpool; the Docker SDK is blocking.
    @app.get("/v1/capacity", response_model=Capacity)
    def capacity(d: DockerDriver = Depends(get_driver)) -> Capacity:
        return d.capacity()

    @app.get("/v1/stats", response_model=RunnerStats)
    def stats(env: str | None = None, d: DockerDriver = Depends(get_driver)) -> RunnerStats:
        return d.stats(env)

    @app.get("/v1/sandboxes", response_model=list[SandboxStatus])
    def list_sandboxes(env: str | None = None, d: DockerDriver = Depends(get_driver)):
        return d.list(env)

    @app.post("/v1/sandboxes", response_model=SandboxInfo)
    def create_sandbox(req: CreateSandbox, d: DockerDriver = Depends(get_driver)) -> SandboxInfo:
        log.info("sandbox.create.started", sandbox_id=req.sandbox_id, env=req.env)
        try:
            return d.create(req)
        except Exception as e:
            log.warning("sandbox.create.failed", sandbox_id=req.sandbox_id, error=str(e))
            raise

    @app.get("/v1/sandboxes/{sandbox_id}", response_model=SandboxStatus)
    def sandbox_status(sandbox_id: str, d: DockerDriver = Depends(get_driver)) -> SandboxStatus:
        return d.status(sandbox_id)

    @app.post("/v1/sandboxes/{sandbox_id}/reset", response_model=SandboxInfo)
    def reset_sandbox(sandbox_id: str, req: ResetSandbox,
                      d: DockerDriver = Depends(get_driver)) -> SandboxInfo:
        gateway.invalidate(sandbox_id)
        return d.reset(sandbox_id, req)

    @app.delete("/v1/sandboxes/{sandbox_id}", status_code=204)
    def destroy_sandbox(sandbox_id: str, d: DockerDriver = Depends(get_driver)) -> None:
        log.info("sandbox.destroy.started", sandbox_id=sandbox_id)
        gateway.invalidate(sandbox_id)
        d.destroy(sandbox_id)

    @app.post("/v1/sandboxes/{sandbox_id}/jobs", response_model=JobResult)
    def run_job(sandbox_id: str, job: JobSpec, d: DockerDriver = Depends(get_driver)) -> JobResult:
        return d.run_job(sandbox_id, job)

    return app


app = create_app()
