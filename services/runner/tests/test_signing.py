import json
import time

from fastapi.testclient import TestClient

from app.config import Settings
from app.driver import Capacity
from app.main import create_app
from app.signing import SIGNATURE_HEADER, TIMESTAMP_HEADER, compute, verify

KNOWN = "fa636268028634194c8034692c7170927406acdd5caf029f11dd608934c1571a"
SECRET = "runner-test-signing-secret-0123456789abcdef"  # >= 32 chars: config refuses dev-length secrets


def test_known_answer_vector():
    assert compute("test-secret", "POST", "/v1/sandboxes", b'{"a":1}', "1700000000") == KNOWN


def test_verify_window_and_tamper():
    ts = "1700000000"
    sig = compute("s", "GET", "/x", b"", ts)
    assert verify("s", "GET", "/x", b"", ts, sig, 30, now=1700000010)
    assert not verify("s", "GET", "/x", b"", ts, sig, 30, now=1700000031)  # outside window
    assert not verify("s", "GET", "/y", b"", ts, sig, 30, now=1700000000)  # path tampered
    assert not verify("s", "GET", "/x", b"1", ts, sig, 30, now=1700000000)  # body tampered
    assert not verify("other", "GET", "/x", b"", ts, sig, 30, now=1700000000)
    assert not verify("s", "GET", "/x", b"", None, sig, 30)


class FakeDriver:
    def capacity(self):
        return Capacity(runner_id="r", version="t", max_sandboxes=4, active=0, docker_ok=True)


def _client():
    return TestClient(create_app(Settings(secret=SECRET, reattach_interval_s=0), FakeDriver()))


def signed(method, path, body=b""):
    ts = str(int(time.time()))
    return {TIMESTAMP_HEADER: ts, SIGNATURE_HEADER: compute(SECRET, method, path, body, ts)}


def test_unsigned_rejected():
    c = _client()
    r = c.get("/v1/capacity")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


def test_signed_ok_and_replay_of_other_path_rejected():
    c = _client()
    h = signed("GET", "/v1/capacity")
    assert c.get("/v1/capacity", headers=h).status_code == 200
    assert c.get("/v1/sandboxes", headers=h).status_code == 401


def test_no_exec_endpoint():
    app = create_app(Settings(secret=SECRET, reattach_interval_s=0), FakeDriver())
    paths = {r.path for r in app.routes}
    assert not any("exec" in p for p in paths)
    assert paths >= {"/v1/capacity", "/v1/sandboxes", "/v1/sandboxes/{sandbox_id}",
                     "/v1/sandboxes/{sandbox_id}/reset", "/v1/sandboxes/{sandbox_id}/jobs"}
