"""Sandbox gateway (phase 7, RUNNER_ACCESS_MODE=gateway): how a control plane on ANOTHER server reaches a
student's sandbox. The runner attaches itself to each sandbox's internal network and forwards two things only:

    ANY  /gw/<sandbox>/<token>/emulator/<path>   → that sandbox's emulator (console, grading, probes)
    WS   /gw/<sandbox>/<token>/terminal/ws        → that sandbox's ttyd (browser terminal, via the API proxy)

The per-sandbox token is created with the sandbox, returned only to the control plane (inside its signed
create/reset answer) and checked in constant time. These routes don't use the runner's HMAC channel because
boto3 and WebSocket clients can't sign each request. Keep the runner port reachable ONLY from the API
servers (firewall, see docs/DEPLOYMENT.md). There is no generic proxy: the upstream is always the sandbox's own
emulator or terminal container, resolved by the runner. A client can't choose a host or port."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

import httpx
import websockets
from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocketDisconnect

from .docker_driver import DockerDriver, DriverError

HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
       "transfer-encoding", "upgrade", "host", "content-length"}
TARGET_TTL_S = 5.0
MAX_BODY = 8 * 1024 * 1024
_targets: dict[tuple[str, str], tuple[float, dict[str, str]]] = {}


def invalidate(sandbox_id: str) -> None:
    """Called on reset/destroy: container IPs change, so cached upstreams must be dropped."""
    for key in [k for k in _targets if k[0] == sandbox_id]:
        _targets.pop(key, None)


def make_router(get_driver: Callable[[], DockerDriver]) -> APIRouter:
    router = APIRouter()
    client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0))

    async def upstream(sid: str, token: str, component: str) -> str:
        hit = _targets.get((sid, token))
        if hit and hit[0] > time.monotonic():
            targets = hit[1]
        else:
            targets = await run_in_threadpool(get_driver().gateway_target, sid, token)
            _targets[(sid, token)] = (time.monotonic() + TARGET_TTL_S, targets)
        if component not in targets:
            raise DriverError("not_found", "not found", 404)
        return targets[component]

    @router.api_route("/gw/{sid}/{token}/emulator", methods=["GET", "POST", "PUT", "DELETE", "HEAD", "PATCH"])
    @router.api_route("/gw/{sid}/{token}/emulator/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "HEAD", "PATCH"])
    async def emulator(sid: str, token: str, request: Request, path: str = "") -> Response:
        base = await upstream(sid, token, "emulator")
        body = await request.body()
        if len(body) > MAX_BODY:
            return JSONResponse({"error": {"code": "too_large", "message": "request body too large"}}, 413)
        url = f"{base}/{path}" + (f"?{request.url.query}" if request.url.query else "")
        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
        try:
            r = await client.request(request.method, url, headers=headers, content=body)
        except httpx.HTTPError as e:
            return JSONResponse({"error": {"code": "sandbox_unreachable", "message": e.__class__.__name__}}, 502)
        out = {k: v for k, v in r.headers.items() if k.lower() not in HOP | {"content-encoding"}}
        return Response(r.content, r.status_code, out)

    @router.websocket("/gw/{sid}/{token}/terminal/ws")
    async def terminal(ws: WebSocket, sid: str, token: str) -> None:
        try:
            url = await upstream(sid, token, "terminal")
        except DriverError:
            await ws.close(code=4404)
            return
        requested = [p.strip() for p in (ws.headers.get("sec-websocket-protocol") or "").split(",") if p.strip()]
        headers = {"Authorization": ws.headers["authorization"]} if "authorization" in ws.headers else {}
        try:
            up = await websockets.connect(url, subprotocols=requested or None,  # type: ignore[arg-type]
                                          additional_headers=headers, open_timeout=10, max_size=1024 * 1024)
        except Exception:
            await ws.close(code=1011)
            return
        await ws.accept(subprotocol=up.subprotocol)

        async def browser_to_sandbox() -> None:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    return
                if msg.get("bytes") is not None:
                    await up.send(msg["bytes"])
                elif msg.get("text") is not None:
                    await up.send(msg["text"])

        async def sandbox_to_browser() -> None:
            async for frame in up:
                if isinstance(frame, bytes):
                    await ws.send_bytes(frame)
                else:
                    await ws.send_text(frame)

        tasks = [asyncio.create_task(browser_to_sandbox()), asyncio.create_task(sandbox_to_browser())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        except (WebSocketDisconnect, websockets.ConnectionClosed):
            pass
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await up.close()
            try:
                await ws.close()
            except RuntimeError:
                pass

    return router
