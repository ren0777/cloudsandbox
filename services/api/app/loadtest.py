"""End-to-end load test (phase 7). Drives the REAL HTTP API the way a class would, and measures the platform.

    python -m app.loadtest --students 16 [--base http://127.0.0.1:8000] [--out /tmp/loadtest.json]

1. Setup through the API: an admin creates a course, imports a roster of N students (temporary passwords),
   assigns the S3 lab; every student signs in and sets a password.
2. The whole class presses Start at the same moment (concurrent Start requests). Students who get
   `capacity_full` retry with the platform's back-off (3 → 5 → 8 → 12 s) until a seat frees up.
3. Each student: wait until READY, create the bucket in the console, Submit, wait for TERMINATED.
4. Every 3 s the runners' read-only `/v1/stats` is sampled (sandbox memory, host memory).
5. Afterwards: every sandbox of the run must be gone from every runner (cleanup success).

Reported: provisioning latency (created → READY), grading latency (Submit round trip), capacity rejections,
failures by reason, peak sandbox memory, host memory headroom, cleanup success. Run it in the api container
of a stack with CL_DEMO_MODE=true (demo accounts; demo reset removes everything it created)."""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select

from .config import get_settings
from .db import sessionmaker
from .models import Runner
from .runtime.runner_client import client_for

BACKOFF = [3, 5, 8, 12]
TRANSPORT_RETRIES = {"count": 0}  # connection resets retried (browsers do the same for idempotent requests)


class RetryingClient(httpx.AsyncClient):
    """Retries transport errors (connection reset / closed keep-alive). Safe for every call this driver makes:
    GETs are idempotent, Start returns the existing session, Submit carries an Idempotency-Key."""

    async def send(self, request: httpx.Request, **kw):  # type: ignore[override]
        for attempt in range(4):
            try:
                return await super().send(request, **kw)
            except httpx.TransportError:
                if attempt == 3:
                    raise
                TRANSPORT_RETRIES["count"] += 1
                await asyncio.sleep(0.5 * (attempt + 1))
        raise AssertionError("unreachable")


def csrf(c: httpx.AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": c.cookies.get("cl_csrf") or ""}


async def login(base: str, email: str, password: str) -> httpx.AsyncClient:
    # The stack marks cookies Secure; inside the API container we talk plain HTTP to 127.0.0.1, so the jar
    # wouldn't send them. Attach the session cookies explicitly (this is a test driver, not a browser).
    async def add_cookies(request: httpx.Request) -> None:
        jar = "; ".join(f"{k}={v}" for k, v in c.cookies.items())
        if jar:
            request.headers["Cookie"] = jar
    # uvicorn closes idle keep-alive connections after 5 s; our back-off sleeps are longer, so drop idle pooled
    # connections first (otherwise a request can race the server's close: "server disconnected").
    c = RetryingClient(base_url=base, timeout=180, event_hooks={"request": [add_cookies]},
                       limits=httpx.Limits(keepalive_expiry=2.0))
    r = await c.post("/api/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return c


@dataclass
class Student:
    email: str
    password: str
    client: httpx.AsyncClient | None = None
    session_id: str | None = None
    first_start: int | None = None          # HTTP status of the simultaneous first Start
    rejections: int = 0                     # capacity_full answers (first wave + retries)
    provision_s: float | None = None
    grading_s: float | None = None
    outcome: str = "pending"                # graded | failed:<reason> | error:<code> | timeout


async def setup(base: str, admin_email: str, admin_password: str, n: int, tag: str) -> tuple[str, list[Student]]:
    admin = await login(base, admin_email, admin_password)
    try:
        r = await admin.post("/api/instructor/courses", json={"code": f"LOAD-{tag}", "title": f"Load test {tag}"}, headers=csrf(admin))
        r.raise_for_status()
        course = r.json()["id"]
        csv = "email,name\n" + "".join(f"load{i:03d}-{tag}@cloudlabs.demo,Load Student {i:03d}\n" for i in range(n))
        p = (await admin.post(f"/api/instructor/courses/{course}/roster/preview", json={"csv": csv}, headers=csrf(admin))).json()
        assert p["ok"], p
        imp = (await admin.post(f"/api/instructor/courses/{course}/roster/import",
                                json={"csv": csv, "preview_token": p["preview_token"]}, headers=csrf(admin))).json()
        versions = (await admin.get("/api/instructor/lab-versions")).json()["lab_versions"]
        lv = [v for v in versions if v["lab"] == "s3-basics"][-1]
        now = datetime.now(timezone.utc)
        a = await admin.post("/api/instructor/assignments", headers=csrf(admin), json={
            "course_id": course, "lab_version_id": lv["id"], "title": f"Load {tag}", "open_at": (now - timedelta(minutes=1)).isoformat(),
            "due_at": (now + timedelta(days=1)).isoformat(), "close_at": (now + timedelta(days=2)).isoformat(), "max_attempts": 3})
        a.raise_for_status()
    finally:
        await admin.aclose()
    students = [Student(c["email"], c["temporary_password"]) for c in imp["credentials"]]

    async def activate(s: Student) -> None:
        s.client = await login(base, s.email, s.password)
        new = f"Load-{uuid.uuid4().hex[:12]}"
        r = await s.client.post("/api/auth/change-password", json={"current_password": s.password, "new_password": new},
                                headers=csrf(s.client))
        r.raise_for_status()
        s.password = new
    await asyncio.gather(*(activate(s) for s in students))
    return a.json()["id"], students


async def student_run(s: Student, assignment: str, barrier: asyncio.Event, deadline: float) -> None:
    c = s.client
    assert c is not None
    await barrier.wait()
    attempt = 0
    while True:  # Start, retrying on capacity_full like the web app does
        r = await c.post(f"/api/assignments/{assignment}/sessions", headers=csrf(c))
        if s.first_start is None:
            s.first_start = r.status_code
        if r.status_code in (200, 201):
            s.session_id = r.json()["id"]
            break
        code = r.json().get("error", {}).get("code", str(r.status_code))
        if code != "capacity_full" or time.monotonic() > deadline:
            s.outcome = f"error:{code}"
            return
        s.rejections += 1
        await asyncio.sleep(BACKOFF[min(attempt, 3)] * random.uniform(0.8, 1.2))
        attempt += 1
    sess = await wait_for(c, s.session_id, {"READY", "FAILED"}, deadline)
    if sess is None or sess["state"] != "READY":
        s.outcome = f"failed:{(sess or {}).get('failure_reason') or 'provision_timeout'}"
        return
    s.provision_s = (datetime.fromisoformat(sess["ready_at"]) - datetime.fromisoformat(sess["created_at"])).total_seconds()
    # some console work so grading has real state to read (marks are irrelevant here)
    await c.post(f"/api/sessions/{s.session_id}/console/s3/buckets", json={"name": f"lt-{uuid.uuid4().hex[:12]}"},
                 headers=csrf(c))
    t0 = time.monotonic()
    r = await c.post(f"/api/sessions/{s.session_id}/submit", headers={**csrf(c), "Idempotency-Key": str(uuid.uuid4())})
    s.grading_s = time.monotonic() - t0
    if r.status_code != 200:
        s.outcome = f"error:{r.json().get('error', {}).get('code', r.status_code)}"
        return
    end = await wait_for(c, s.session_id, {"TERMINATED", "FAILED"}, deadline)
    s.outcome = "graded" if end and end["state"] == "TERMINATED" else f"failed:{(end or {}).get('failure_reason') or 'teardown_timeout'}"


async def wait_for(c: httpx.AsyncClient, sid: str, states: set[str], deadline: float) -> dict | None:
    while time.monotonic() < deadline:
        r = await c.get(f"/api/sessions/{sid}")
        if r.status_code == 200 and r.json()["state"] in states:
            return r.json()
        await asyncio.sleep(1)
    return None


async def sample_memory(stop: asyncio.Event, env: str, out: dict[str, Any]) -> None:
    async with sessionmaker()() as db:
        runners = list((await db.scalars(select(Runner).where(Runner.status != "retired"))).all())
    while not stop.is_set():
        for r in runners:
            try:
                st = await client_for(r).stats(env)
            except Exception:
                continue
            row = out.setdefault(r.id, {"peak_sandbox_memory_mib": 0.0, "peak_sandboxes": 0, "per_sandbox_mib": [],
                                        "min_host_available_mib": None, "host_total_mib": st.get("mem_total_mib")})
            row["peak_sandbox_memory_mib"] = max(row["peak_sandbox_memory_mib"], st["sandbox_memory_mib"])
            row["peak_sandboxes"] = max(row["peak_sandboxes"], len(st["sandboxes"]))
            row["per_sandbox_mib"].extend(x["memory_mib"] for x in st["sandboxes"] if x["memory_mib"] > 0)
            if st.get("mem_available_mib") is not None:
                row["min_host_available_mib"] = st["mem_available_mib"] if row["min_host_available_mib"] is None \
                    else min(row["min_host_available_mib"], st["mem_available_mib"])
        try:
            await asyncio.wait_for(stop.wait(), timeout=3)
        except asyncio.TimeoutError:
            pass


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 2)
    return round(statistics.quantiles(values, n=100, method="inclusive")[int(q) - 1], 2)


async def cleanup_check(env: str, session_ids: set[str], wait_s: float = 90) -> dict[str, Any]:
    async with sessionmaker()() as db:
        runners = list((await db.scalars(select(Runner).where(Runner.status != "retired"))).all())
    end = time.monotonic() + wait_s
    left: set[str] = set(session_ids)
    while time.monotonic() < end:
        left = set()
        for r in runners:
            try:
                left |= {x["sandbox_id"] for x in await client_for(r).list_sandboxes(env=env)} & session_ids
            except Exception:
                pass
        if not left:
            break
        await asyncio.sleep(3)
    return {"sandboxes": len(session_ids), "removed": len(session_ids) - len(left), "leftover": sorted(left)}


async def run(args: argparse.Namespace) -> dict[str, Any]:
    s = get_settings()
    tag = args.tag or uuid.uuid4().hex[:6]
    t_setup = time.monotonic()
    assignment, students = await setup(args.base, args.admin_email, args.admin_password, args.students, tag)
    setup_s = time.monotonic() - t_setup
    async with sessionmaker()() as db:
        runners = list((await db.scalars(select(Runner).where(Runner.status != "retired", Runner.drain.is_(False)))).all())
    seats = sum(r.max_sandboxes for r in runners)

    barrier, stop, memory = asyncio.Event(), asyncio.Event(), {}
    sampler = asyncio.create_task(sample_memory(stop, s.env, memory))
    deadline = time.monotonic() + args.timeout
    tasks = [asyncio.create_task(student_run(st, assignment, barrier, deadline)) for st in students]
    t0 = time.monotonic()
    barrier.set()  # everyone presses Start now
    await asyncio.gather(*tasks)
    wall = time.monotonic() - t0
    stop.set()
    await sampler
    ids = {st.session_id for st in students if st.session_id}
    async with sessionmaker()() as db:
        from .models import LabSession
        placed = {str(x.id): x.runner_id for x in (await db.scalars(select(LabSession).where(LabSession.id.in_([uuid.UUID(i) for i in ids])))).all()} if ids else {}
    cleanup = await cleanup_check(s.env, ids)
    for st in students:
        if st.client:
            await st.client.aclose()
    prov = [st.provision_s for st in students if st.provision_s is not None]
    grade = [st.grading_s for st in students if st.grading_s is not None]
    outcomes: dict[str, int] = {}
    for st in students:
        outcomes[st.outcome] = outcomes.get(st.outcome, 0) + 1
    per_runner: dict[str, int] = {}
    for rid in placed.values():
        per_runner[rid] = per_runner.get(rid, 0) + 1
    for row in memory.values():
        vals = row.pop("per_sandbox_mib")
        row["avg_sandbox_mib"] = round(statistics.mean(vals), 1) if vals else None
        row["max_sandbox_mib"] = round(max(vals), 1) if vals else None
    return {
        "tag": tag, "students": len(students), "runners": [r.id for r in runners], "seats": seats,
        "setup_seconds": round(setup_s, 1), "wall_seconds": round(wall, 1),
        "first_wave": {"started": sum(1 for st in students if st.first_start in (200, 201)),
                       "capacity_full": sum(1 for st in students if st.first_start == 503)},
        "capacity_rejections_total": sum(st.rejections for st in students),
        "sessions_per_runner": per_runner,
        "provisioning_seconds": {"n": len(prov), "p50": pct(prov, 50), "p95": pct(prov, 95), "max": round(max(prov), 2) if prov else None},
        "grading_seconds": {"n": len(grade), "p50": pct(grade, 50), "p95": pct(grade, 95), "max": round(max(grade), 2) if grade else None},
        "outcomes": outcomes, "failures": {k: v for k, v in outcomes.items() if k != "graded"},
        "memory": memory, "cleanup": cleanup, "transport_retries": TRANSPORT_RETRIES["count"],
    }


def markdown(r: dict[str, Any]) -> str:
    lines = ["| Students | Runners (seats) | Wall time | First wave started / full | Capacity rejections | Provisioning p50 / p95 / max | "
             "Grading p50 / p95 / max | Failures | Cleanup |", "|---|---|---|---|---|---|---|---|---|"]
    p, g = r["provisioning_seconds"], r["grading_seconds"]
    lines.append(f"| {r['students']} | {len(r['runners'])} ({r['seats']}) | {r['wall_seconds']} s | {r['first_wave']['started']} / "
                 f"{r['first_wave']['capacity_full']} | {r['capacity_rejections_total']} | {p['p50']} / {p['p95']} / {p['max']} s | "
                 f"{g['p50']} / {g['p95']} / {g['max']} s | {sum(r['failures'].values()) or 0} | {r['cleanup']['removed']}/{r['cleanup']['sandboxes']} |")
    for rid, m in r["memory"].items():
        lines.append(f"\n- `{rid}`: {r['sessions_per_runner'].get(rid, 0)} labs, peak {m['peak_sandboxes']} sandboxes using "
                     f"{m['peak_sandbox_memory_mib']} MiB (avg {m['avg_sandbox_mib']} MiB, max {m['max_sandbox_mib']} MiB per sandbox), "
                     f"lowest host memory available {m['min_host_available_mib']} of {m['host_total_mib']} MiB")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--students", type=int, default=12)
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--admin-email", default="demo-admin@cloudlabs.demo")
    ap.add_argument("--admin-password", default="cloudlabs-demo")
    ap.add_argument("--timeout", type=float, default=900)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    result = asyncio.run(run(args))
    print(json.dumps(result, indent=2, default=str))
    print()
    print(markdown(result))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, default=str)
    ok = not result["failures"] and not result["cleanup"]["leftover"]
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
