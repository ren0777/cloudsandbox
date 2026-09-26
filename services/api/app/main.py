from __future__ import annotations

import asyncio
import re
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import select, text

from . import db as dbmod
from . import errors
from .admin.manage import instructor_router as course_audit_router
from .admin.manage import router as admin_manage_router
from .admin.routes import router as admin_router
from .admin.runners import router as admin_runners_router
from .auth.routes import router as auth_router
from .config import get_settings
from .console.dynamodb import router as dynamodb_console_router
from .console.ec2 import router as ec2_console_router
from .console.iam import router as iam_console_router
from .console.lambda_ import router as lambda_console_router
from .console.s3 import router as s3_console_router
from .fun import router as fun_router
from .instructor.builder import router as builder_router
from .instructor.courses import router as courses_router
from .instructor.gradebook import router as gradebook_router
from .instructor.live import router as live_router
from .instructor.routes import router as instructor_router
from .obs import logging as obslog
from .obs.metrics import registry
from .models import Runner
from .sessions.reconciler import reconcile_once
from .student.routes import router as student_router
from .tasks import background
from .tasks.janitor import expire_once, heartbeat_once, seed_runner
from .terminal.routes import router as terminal_router

_RID = re.compile(r"^[A-Za-z0-9-]{1,64}$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    obslog.configure(strict=False)
    loops: list[asyncio.Task] = []
    if s.background_loops:
        await seed_runner()
        await heartbeat_once()
        try:
            await reconcile_once()  # crash recovery before serving traffic (PLAN §3)
        except Exception as e:  # never block startup
            structlog.get_logger("cloudlabs").error("background.task.failed", loop="startup-reconcile",
                                                    error=repr(e))
        loops = [background.loop(s.heartbeat_interval_s, heartbeat_once, "heartbeat"),
                 background.loop(s.janitor_interval_s, _expire, "janitor"),
                 background.loop(s.reconciler_interval_s, _reconcile, "reconciler")]
    yield
    for t in loops:
        t.cancel()
    await background.drain(10)
    await dbmod.dispose()


async def _expire() -> None:
    await expire_once()


async def _reconcile() -> None:
    await reconcile_once()


def create_app() -> FastAPI:
    app = FastAPI(title="CloudLabs API", version="0.1.0", lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    errors.install(app)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("X-Request-ID")
        if not rid or not _RID.match(rid):
            rid = uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=rid)
        try:
            response = await call_next(request)
        finally:
            pass
        response.headers["X-Request-ID"] = rid
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    for r in (auth_router, student_router, terminal_router, s3_console_router, dynamodb_console_router,
              iam_console_router, ec2_console_router, lambda_console_router, instructor_router,
              courses_router, gradebook_router, live_router, admin_router,
              admin_manage_router, course_audit_router, fun_router, admin_runners_router, builder_router):
        app.include_router(r)

    @app.get("/healthz")
    async def healthz():
        out = {"database": False, "runner": False}
        try:
            async with dbmod.sessionmaker()() as db:
                await db.execute(text("SELECT 1"))
            out["database"] = True
        except Exception:
            pass
        # healthy when at least one registered runner has a fresh, healthy heartbeat (phase 7: many runners)
        try:
            from .runtime.scheduler import healthy
            async with dbmod.sessionmaker()() as db:
                out["runner"] = any(healthy(r) for r in (await db.scalars(select(Runner))).all())
        except Exception:
            pass
        return JSONResponse(out, 200 if all(out.values()) else 503)

    @app.get("/metrics")
    async def metrics():
        return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()

# Routes that intentionally have no Authz dependency (checked by tests/test_authz_coverage.py).
PUBLIC_ROUTES = {("GET", "/healthz"), ("GET", "/metrics"), ("GET", "/api/docs"),
                 ("GET", "/api/openapi.json"), ("GET", "/api/docs/oauth2-redirect"),
                 ("WS", "/ws/terminal")}
