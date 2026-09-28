"""Route coverage for the authorization matrix (PLAN §9) — the guard named in `app/main.py` and
`app/auth/policy.py`.

Every route must either
  * depend on `Authz(action)` / `AuthzAny(...)` (so the role matrix and CSRF checks run), or
  * be listed in the *expected* public allowlist below — which lives in the test on purpose, so opening a
    route to anonymous callers is a deliberate, reviewable diff rather than a one-line edit to `main.py`.

Three independent failure modes are covered:
  1. a protected route added with no `Authz` dependency;
  2. a route added to `PUBLIC_ROUTES` to make (1) go away;
  3. an `Authz` whose action is missing from `MATRIX` (a `KeyError` at request time = 500, not a 403).

Behavioural check: every protected route answers 401 to an anonymous caller. Cross-resource access keeps
answering 404 rather than 403 so IDs cannot be enumerated — that is asserted here too, because it is the
half of the contract most likely to be broken by a refactor.
"""

from __future__ import annotations

import re
import uuid

import httpx
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.routing import Route as StarletteRoute

from app.auth.policy import MATRIX, Action, Authz, AuthzAny
from app.auth.routes import PUBLIC_ROUTES as AUTH_PUBLIC
from app.main import PUBLIC_ROUTES, app
from app.models import User
from tests.conftest import login

# The complete, intentional anonymous surface. Adding an entry here is a security decision.
EXPECTED_PUBLIC = {
    ("GET", "/healthz"),
    ("GET", "/metrics"),
    ("GET", "/api/docs"),
    ("GET", "/api/openapi.json"),
    ("GET", "/docs/oauth2-redirect"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/refresh"),
    ("POST", "/api/auth/logout"),
    ("POST", "/api/auth/register"),
    ("GET", "/api/auth/demo-accounts"),
    ("WS", "/ws/terminal"),
}

# Prefixes that always belong to an authenticated, resource-scoped area. Nothing under them may be public.
PROTECTED_PREFIXES = ("/api/sessions", "/api/instructor", "/api/admin", "/api/console",
                      "/api/me", "/api/assignments", "/api/attempts", "/api/courses",
                      "/api/labs", "/api/drafts", "/api/preview")


def _iter_routes():
    """Every route the app serves — including the plain Starlette ones FastAPI adds for `/api/docs` and
    friends. Those have no `dependant` at all, so they can only ever be on the public allowlist."""
    for r in app.routes:
        if isinstance(r, APIRoute):
            for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
                yield m, r.path, r
        elif isinstance(r, APIWebSocketRoute):
            yield "WS", r.path, r
        elif isinstance(r, StarletteRoute):
            for m in sorted((r.methods or set()) - {"HEAD", "OPTIONS"}):
                yield m, r.path, r


def _authz_dependencies(dependant) -> list[Authz]:
    found: list[Authz] = []
    for d in dependant.dependencies:
        if isinstance(d.call, Authz):  # AuthzAny subclasses Authz
            found.append(d.call)
        found.extend(_authz_dependencies(d))
    return found


def _has_authz(route) -> bool:
    """False for a Starlette route (no `dependant`), which is exactly why they must be allowlisted."""
    dependant = getattr(route, "dependant", None)
    return bool(dependant) and bool(_authz_dependencies(dependant))


def _actions_of(az: Authz) -> tuple[Action, ...]:
    return tuple(az.actions) if isinstance(az, AuthzAny) else (az.action,)


def _sample_path(path: str) -> str:
    """A plausible value for every path parameter: UUIDs for `{id}`, small ints for page-ish params."""
    def sub(m: re.Match[str]) -> str:
        name = m.group(1)
        if name.endswith(("_no", "limit", "offset", "page")):
            return "1"
        return str(uuid.uuid4())
    return re.sub(r"\{([^}]+)\}", sub, path)


# ------------------------------------------------------------------------------- static coverage
def test_every_route_is_authorized_or_explicitly_public():
    """PLAN §9: a new protected route with no Authz dependency fails here."""
    public = PUBLIC_ROUTES | AUTH_PUBLIC
    missing = [f"{m} {path}" for m, path, r in _iter_routes()
               if (m, path) not in public and not _has_authz(r)]
    assert not missing, f"routes without Authz(action): {missing}"


def test_public_allowlist_is_the_reviewed_one():
    """Opening a route to anonymous callers must mean editing this file, not just `main.py`."""
    actual = PUBLIC_ROUTES | AUTH_PUBLIC
    added = sorted(actual - EXPECTED_PUBLIC)
    removed = sorted(EXPECTED_PUBLIC - actual)
    assert not added, f"newly public routes — review them, then add to EXPECTED_PUBLIC: {added}"
    assert not removed, f"public routes that no longer exist: {removed}"


def _registered() -> tuple[set[tuple[str, str]], set[str]]:
    """Every route FastAPI actually serves, including the ones Starlette adds itself (`/api/docs`, the
    OAuth2 redirect, …) — `APIRoute` alone would miss them. Routes declared without a method set (the
    OAuth2 redirect) match any method, so their paths come back separately."""
    pairs: set[tuple[str, str]] = set()
    any_method: set[str] = set()
    for r in app.routes:
        path = getattr(r, "path", None)
        if not path:
            continue
        methods = getattr(r, "methods", None)
        if methods:
            for m in methods:
                pairs.add((m, path))
        else:
            any_method.add(path)
    return pairs, any_method


def test_public_allowlist_entries_are_real_routes():
    pairs, any_method = _registered()
    for entry in sorted(PUBLIC_ROUTES | AUTH_PUBLIC):
        assert entry in pairs or entry[1] in any_method, \
            f"PUBLIC_ROUTES names a route that is not registered: {entry}"


def test_no_resource_scoped_route_is_public():
    """Anonymous access must never be reachable through a path that reads someone else's data."""
    public = PUBLIC_ROUTES | AUTH_PUBLIC
    offenders = []
    for m, path, _ in _iter_routes():
        if (m, path) not in public:
            continue
        for prefix in PROTECTED_PREFIXES:
            if path.startswith(prefix):
                offenders.append(f"{m} {path} (under {prefix})")
        if "{" in path and path != "/ws/terminal":
            offenders.append(f"{m} {path} (public route with a path parameter)")
    assert not offenders, f"resource-scoped routes exposed anonymously: {offenders}"


def test_every_authz_action_is_declared_in_the_matrix():
    """An action missing from MATRIX raises KeyError inside the dependency → 500 instead of 403."""
    assert set(MATRIX) == set(Action), (
        f"Action members without a MATRIX row: {sorted(set(Action) - set(MATRIX))}; "
        f"MATRIX rows without an Action: {sorted(set(MATRIX) - set(Action))}"
    )
    undeclared = []
    for m, path, r in _iter_routes():
        if not isinstance(r, APIRoute):
            continue
        for az in _authz_dependencies(r.dependant):
            for act in _actions_of(az):
                if act not in MATRIX:
                    undeclared.append(f"{m} {path} → {act.value}")
    assert not undeclared, f"Authz(...) with an action missing from MATRIX: {undeclared}"


def test_no_route_is_both_public_and_protected():
    """A route listed in PUBLIC_ROUTES *and* carrying Authz is a contradiction (and a review trap)."""
    contradictions = []
    for m, path, r in _iter_routes():
        if not isinstance(r, APIRoute):
            continue
        is_public = (m, path) in (PUBLIC_ROUTES | AUTH_PUBLIC)
        has_authz = bool(_authz_dependencies(r.dependant))
        if is_public and has_authz:
            contradictions.append(f"{m} {path}: listed public but still depends on Authz")
    assert not contradictions, contradictions


def test_the_guard_itself_is_not_vacuous():
    """A coverage test that can never fail is worthless: prove the checker flags a newly added route that
    forgot `Authz`, and stays silent once the dependency is there."""
    def flagged(app: FastAPI) -> set[str]:
        out = set()
        for r in app.routes:
            if not isinstance(r, APIRoute):
                continue
            for m in r.methods - {"HEAD", "OPTIONS"}:
                if not _authz_dependencies(r.dependant):
                    out.add(f"{m} {r.path}")
        return out

    probe = FastAPI()

    @probe.get("/api/widgets")
    async def list_widgets() -> None:  # reads every teacher's data with no policy check
        ...

    @probe.post("/api/widgets")
    async def create_widget() -> None:
        ...

    assert flagged(probe) == {"GET /api/widgets", "POST /api/widgets"}

    covered = FastAPI()

    @covered.get("/api/widgets")
    async def list_widgets_ok(user: User = Depends(Authz(Action.results_view))) -> None:
        ...

    assert flagged(covered) == set()


# --------------------------------------------------------------------------- behavioural coverage
async def test_anonymous_requests_are_rejected_on_every_protected_route():
    """A route whose Authz dependency is wired up in theory but never runs in practice (for example
    dropped from a router's dependencies) would answer something other than 401 here."""
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")
    public = PUBLIC_ROUTES | AUTH_PUBLIC
    bad = []
    try:
        for m, path, r in _iter_routes():
            if (m, path) in public:
                continue
            body = {} if m in {"POST", "PUT", "PATCH"} else None
            try:
                resp = await c.request(m, _sample_path(path), json=body)
            except Exception as e:  # pragma: no cover - a crash here is itself the failure
                bad.append(f"{m} {path}: raised {e!r}")
                continue
            if resp.status_code != 401:
                bad.append(f"{m} {path} → {resp.status_code} {resp.text[:160]}")
    finally:
        await c.aclose()
    assert not bad, "protected routes that did not answer 401 to an anonymous caller:\n" + "\n".join(bad)


async def test_cross_resource_access_stays_404_not_403(world):
    """PLAN §9: IDs must not be enumerable — a resource that exists but belongs to someone else is 404;
    a wrong *role* is 403. (Student-to-student session ownership is covered in `test_sessions.py`.)"""
    # an instructor who does not teach the course: role allows it, ownership does not → 404
    other = await login(world.other_instructor)
    assert (await other.get(f"/api/instructor/courses/{world.course.id}/gradebook")).status_code == 404
    # a student hitting the same instructor route: the role matrix refuses first → 403
    student = await login(world.alice)
    assert (await student.get(f"/api/instructor/courses/{world.course.id}/gradebook")).status_code == 403
    assert (await student.get(f"/api/instructor/assignments/{world.assignment.id}/results")).status_code == 403
