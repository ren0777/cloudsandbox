"""Auth: cookies, refresh rotation, CSRF, rate limit, and the authorization matrix (PLAN §9), plus the
architecture invariant that the API never talks to Docker.

Route coverage for that matrix — every route either carries `Authz(action)` or is on the reviewed public
allowlist — lives in `tests/test_authz_coverage.py`."""

from __future__ import annotations

import ast
from pathlib import Path

from app.auth.security import REFRESH_COOKIE
from app.runtime.signing import compute
from tests.conftest import PASSWORD, client, login


# ------------------------------------------------------------------------------- architecture
def test_api_never_imports_docker():
    root = Path(__file__).resolve().parent.parent / "app"
    for py in root.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            assert not any(n == "docker" or n.startswith("docker.") for n in names), \
                f"{py} imports the Docker SDK — only the runner may (PLAN §10)"


def test_signing_known_answer_matches_runner():
    assert compute("test-secret", "POST", "/v1/sandboxes", b'{"a":1}', "1700000000") == \
        "fa636268028634194c8034692c7170927406acdd5caf029f11dd608934c1571a"


# ---------------------------------------------------------------------------------------- auth
async def test_login_me_logout(world):
    c = await login(world.alice)
    r = await c.get("/api/auth/me")
    assert r.status_code == 200 and r.json()["role"] == "student" and r.json()["short_id"] == "alice1"
    assert (await c.post("/api/auth/logout")).status_code == 204
    assert (await c.get("/api/auth/me")).status_code == 401


async def test_bad_password_and_unknown_user(world):
    c = client()
    for email in ("alice@x.edu", "nobody@x.edu"):
        r = await c.post("/api/auth/login", json={"email": email, "password": "wrong-password"})
        assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"
        assert r.json()["error"]["request_id"]


async def test_login_rate_limited(world):
    c = client()
    codes = [(await c.post("/api/auth/login", json={"email": "alice@x.edu", "password": "nope"})).status_code
             for _ in range(11)]
    assert codes[-1] == 429 and codes[0] == 401


async def test_demo_accounts_public_only_when_seeded_and_in_demo_mode(world, monkeypatch):
    """The login page's one-click demo sign-in: the endpoint is public, but lists accounts only while
    CL_DEMO_MODE is on AND the demo reset has actually seeded them."""
    from app.auth.routes import create_user
    from app.config import get_settings
    from app.db import sessionmaker
    from app.models import Role

    c = client()
    empty = {"enabled": False, "password": None, "accounts": []}
    assert (await c.get("/api/auth/demo-accounts")).json() == empty
    monkeypatch.setattr(get_settings(), "demo_mode", True)
    assert (await c.get("/api/auth/demo-accounts")).json() == empty, "not seeded yet: no dead buttons"

    async with sessionmaker()() as db:
        await create_user(db, "demo-student1@cloudlabs.demo", "Sam Student", Role.student,
                          "cloudlabs-demo", short_id="demo01")
        await db.commit()
    b = (await c.get("/api/auth/demo-accounts")).json()
    assert b["enabled"] is True and b["password"] == "cloudlabs-demo"
    assert [a["email"] for a in b["accounts"]] == ["demo-student1@cloudlabs.demo"]
    assert b["accounts"][0]["role"] == "student" and b["accounts"][0]["name"] == "Sam Student"


async def test_unauthenticated_is_401():
    r = await client().get("/api/me/assignments")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthenticated"


async def test_csrf_required_on_mutations(world):
    c = await login(world.alice)
    url = f"/api/assignments/{world.assignment.id}/sessions"
    r = await c.post(url, headers={"X-CSRF-Token": "wrong"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"


async def test_refresh_rotation_and_reuse_detection(world):
    c = await login(world.alice)
    old = c.cookies.get(REFRESH_COOKIE)
    r = await c.post("/api/auth/refresh")
    assert r.status_code == 200
    new = c.cookies.get(REFRESH_COOKIE)
    assert new and new != old
    # Replaying the rotated token revokes the whole family.
    thief = client()
    r = await thief.post("/api/auth/refresh",
                         headers={"Cookie": f"{REFRESH_COOKIE}={old}; cl_csrf=t", "X-CSRF-Token": "t"})
    assert r.status_code == 401
    r = await c.post("/api/auth/refresh")
    assert r.status_code == 401  # family revoked


async def test_self_registration_disabled_by_default():
    r = await client().post("/api/auth/register", json={"email": "x@y.edu", "name": "X",
                                                        "password": "long-enough-password"})
    assert r.status_code == 403


async def test_demo_accounts_refused_when_demo_mode_off(world):
    from app.auth.routes import create_user
    from app.db import sessionmaker
    from app.models import Role
    async with sessionmaker()() as db:
        await create_user(db, "demo-student9@cloudlabs.demo", "D", Role.student, PASSWORD, is_demo=True)
        await db.commit()
    r = await client().post("/api/auth/login", json={"email": "demo-student9@cloudlabs.demo",
                                                     "password": PASSWORD})
    assert r.status_code == 401


# ------------------------------------------------------------------------------ authz matrix
async def test_role_matrix(world):
    alice, inst, admin = await login(world.alice), await login(world.instructor), await login(world.admin)
    aid = world.assignment.id
    # students can't see class results or admin status
    assert (await alice.get(f"/api/instructor/assignments/{aid}/results")).status_code == 403
    assert (await alice.get("/api/admin/runtime-status")).status_code == 403
    # instructors/admins can't start student sessions
    assert (await inst.post(f"/api/assignments/{aid}/sessions")).status_code == 403
    assert (await admin.post(f"/api/assignments/{aid}/sessions")).status_code == 403
    # staff of the course see results; admin sees everything
    assert (await inst.get(f"/api/instructor/assignments/{aid}/results")).status_code == 200
    assert (await admin.get(f"/api/instructor/assignments/{aid}/results")).status_code == 200
    assert (await admin.get("/api/admin/runtime-status")).status_code == 200
    assert (await inst.get("/api/admin/runtime-status")).status_code == 403


async def test_other_courses_are_404_not_403(world):
    other = await login(world.other_instructor)
    r = await other.get(f"/api/instructor/assignments/{world.assignment.id}/results")
    assert r.status_code == 404
    # a student not enrolled can't see the assignment either
    from app.auth.routes import create_user
    from app.db import sessionmaker
    from app.models import Role
    async with sessionmaker()() as db:
        await create_user(db, "carol@x.edu", "Carol", Role.student, PASSWORD)
        await db.commit()
    carol = await login("carol@x.edu")
    assert (await carol.get(f"/api/assignments/{world.assignment.id}")).status_code == 404
    assert (await carol.post(f"/api/assignments/{world.assignment.id}/sessions")).status_code == 404


async def test_password_hashing_does_not_block_the_event_loop(world):
    """A class signing in at once must not freeze everyone else: argon2 runs in bounded worker threads."""
    import asyncio
    import time

    from app.auth.routes import create_user
    from app.db import sessionmaker
    from app.models import Role
    from tests.conftest import PASSWORD, client
    async with sessionmaker()() as db:
        for i in range(8):
            await create_user(db, f"burst{i}@x.edu", f"Burst {i}", Role.student, PASSWORD)
        await db.commit()
    worst = 0.0
    done = asyncio.Event()

    async def probe() -> None:
        nonlocal worst
        while not done.is_set():
            t = time.monotonic()
            await asyncio.sleep(0.01)
            worst = max(worst, time.monotonic() - t - 0.01)

    async def sign_in(i: int) -> int:
        return (await client().post("/api/auth/login", json={"email": f"burst{i}@x.edu", "password": PASSWORD})).status_code
    import threading

    from app.auth import security
    loop_thread, hashing_threads = threading.get_ident(), set()
    real_verify = security._verify

    def spy(pw, hashed):
        hashing_threads.add(threading.get_ident())
        return real_verify(pw, hashed)
    security._verify = spy
    try:
        watcher = asyncio.create_task(probe())
        codes = await asyncio.gather(*(sign_in(i) for i in range(8)))
        done.set()
        await watcher
    finally:
        security._verify = real_verify
    assert codes == [200] * 8
    assert hashing_threads and loop_thread not in hashing_threads  # argon2 never runs on the event loop
    from app.auth.security import _ph, needs_rehash
    old = __import__("argon2").PasswordHasher().hash("x")  # library defaults (pre phase 7)
    assert needs_rehash(old) and not needs_rehash(_ph.hash("x")) and _ph.verify(old, "x")
    assert worst < 2.0, f"event loop stalled for {worst:.2f}s during sign-ins"  # loose: CI machines can be busy
