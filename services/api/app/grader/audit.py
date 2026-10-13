"""API-call audit (PLAN "Audit"; docs/NEXT.md milestone 50).

A sandbox whose lab uses `audit.*` checks runs an audit proxy in front of its emulator. The student terminal
and the console reach the emulator through it; setup jobs, grading collectors and probes don't, so the log holds
only what the student did. The proxy records raw request facts; this module turns them into AWS operation names
(`s3:PutObject`) with botocore's own service models — the same models the AWS CLI serialises from — and the
`audit` collector stores only the resolved events, so grading stays a pure function of stored evidence.

Evidence shape (collector 'audit'):
    {"available": bool, "dropped": int, "events": [{"seq", "action", "source", "status"}]}
`action` is "<service>:<Operation>" ("<service>:?" when the request matched no operation, "unknown" when it
wasn't SigV4-signed); `source` is "cli" or "console"; `status` is the emulator's HTTP status (502: unreachable).
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx
from botocore.exceptions import UnknownServiceError
from botocore.session import get_session

LOG_PATH = "/_cloudlabs/audit"
SOURCE_HEADER = "X-CloudLabs-Source"
MAX_STORED_EVENTS = 2000  # most recent; older ones are counted in `dropped`
X_ID = "x-id"  # some SDK/model versions add `?x-id=<Operation>` to REST URIs; tolerated both ways


# ------------------------------------------------------------------------------------ resolution
@dataclass(frozen=True)
class _Route:
    operation: str
    method: str
    segments: tuple[str, ...]          # "{Bucket}", "{Key+}" or literals
    literal_query: tuple[tuple[str, str | None], ...]  # from requestUri ("versioning", None) / ("list-type", "2")
    required_query: frozenset[str]
    required_headers: frozenset[str]

    @property
    def literals(self) -> int:
        return sum(1 for s in self.segments if not s.startswith("{"))


def _segments(path: str) -> tuple[str, ...]:
    return tuple(p for p in path.strip("/").split("/") if p != "")


@lru_cache(maxsize=32)
def _model(service: str) -> Any:
    try:
        return get_session().get_service_model(service)
    except UnknownServiceError:
        return None


@lru_cache(maxsize=32)
def _routes(service: str) -> tuple[_Route, ...]:
    model = _model(service)
    if model is None or model.protocol not in ("rest-xml", "rest-json"):
        return ()
    out = []
    for name in model.operation_names:
        op = model.operation_model(name)
        uri = op.http.get("requestUri", "/")
        path, _, q = uri.partition("?")
        literal_query = tuple((k, v if sep else None) for k, sep, v in (p.partition("=") for p in q.split("&") if p))
        req_q, req_h = set(), set()
        shape = op.input_shape
        if shape is not None:
            for member in shape.required_members:
                ser = shape.members[member].serialization
                if ser.get("location") == "querystring":
                    req_q.add(ser.get("name", member))
                elif ser.get("location") == "header":
                    req_h.add(ser.get("name", member).lower())
        out.append(_Route(name, op.http.get("method", "POST"), _segments(path), literal_query,
                          frozenset(req_q), frozenset(req_h)))
    return tuple(out)


def _path_matches(template: tuple[str, ...], actual: tuple[str, ...]) -> bool:
    for i, seg in enumerate(template):
        if seg.endswith("+}"):  # greedy label: the rest of the path (at least one segment)
            return len(actual) > i
        if i >= len(actual):
            return False
        if not seg.startswith("{") and seg != actual[i]:
            return False
    return len(actual) == len(template)


def match_rest(service: str, method: str, path: str, query: str, headers: list[str]) -> str | None:
    """The REST operation a request serialises: same method and path template, every literal query key of the
    requestUri and every required query/header member present. The most specific candidate wins."""
    q = urllib.parse.parse_qs(query, keep_blank_values=True)
    if q.get(X_ID) and q[X_ID][0] in (_model(service).operation_names if _model(service) else ()):
        return q[X_ID][0]  # newer SDKs name the operation in the query (`?x-id=PutObject`)
    names = {h.lower() for h in headers}
    actual = tuple(urllib.parse.unquote(s) for s in _segments(path))
    best: tuple[tuple[int, int, int], str] | None = None
    for r in _routes(service):
        if r.method != method.upper() or not _path_matches(r.segments, actual):
            continue
        if any((k not in q and k != X_ID) or (k in q and v is not None and v not in q[k])
               for k, v in r.literal_query):
            continue
        if not r.required_query <= q.keys() or not r.required_headers <= names:
            continue
        score = (len(r.literal_query) + len(r.required_query) + len(r.required_headers), r.literals,
                 -len(r.segments))
        if best is None or score > best[0] or (score == best[0] and r.operation < best[1]):
            best = (score, r.operation)
    return best[1] if best else None


def resolve(event: dict[str, Any]) -> str:
    """`<service>:<Operation>` for one raw proxy event."""
    service = event.get("service") or ""
    if not service:
        return "unknown"
    op: str | None
    if event.get("target"):  # JSON protocols: X-Amz-Target "<Prefix>.<Operation>"
        op = str(event["target"]).rsplit(".", 1)[-1]
    elif event.get("action"):  # Query protocol: form field Action
        op = str(event["action"])
    else:
        op = match_rest(service, str(event.get("method", "")), str(event.get("path", "/")),
                        str(event.get("query", "")), list(event.get("headers") or []))
    return f"{service}:{op or '?'}"


# ------------------------------------------------------------------------------------ collector
def fetch_log(audit_endpoint: str) -> dict[str, Any]:
    """The proxy's raw log. Raises on any infrastructure error (grading must not silently see an empty log)."""
    r = httpx.get(audit_endpoint.rstrip("/") + LOG_PATH, timeout=10)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        raise ValueError("malformed audit log")
    return data


def collect_audit(audit_endpoint: str | None) -> dict[str, Any]:
    if not audit_endpoint:
        return {"available": False, "dropped": 0, "events": []}
    raw = fetch_log(audit_endpoint)
    events = [{"seq": int(e.get("seq", 0)), "action": resolve(e),
               "source": "console" if e.get("source") == "console" else "cli", "status": int(e.get("status", 0))}
              for e in raw["events"]]
    events.sort(key=lambda e: e["seq"])
    cut = max(0, len(events) - MAX_STORED_EVENTS)
    return {"available": True, "dropped": int(raw.get("dropped", 0)) + cut, "events": events[cut:]}


def console_headers() -> dict[str, str]:
    """Marks console calls; the proxy honours it only from outside the student terminal."""
    return {SOURCE_HEADER: "console"}
