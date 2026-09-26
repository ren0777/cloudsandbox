"""Control plane <-> runner request signing (PLAN §10).

signature = HMAC-SHA256(secret, "METHOD|PATH_WITH_QUERY|SHA256(BODY)|TIMESTAMP")

The same algorithm lives in services/runner/app/signing.py; both test suites assert the same
known-answer vector so the two copies can never drift apart.
"""

import hashlib
import hmac
import time

TIMESTAMP_HEADER = "X-Runner-Timestamp"
SIGNATURE_HEADER = "X-Runner-Signature"



def compute(secret: str, method: str, path: str, body: bytes, ts: str) -> str:
    body_hash = hashlib.sha256(body).hexdigest()
    msg = f"{method.upper()}|{path}|{body_hash}|{ts}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def verify(secret: str, method: str, path: str, body: bytes, ts: str | None, sig: str | None,
           window_s: int, now: float | None = None) -> bool:
    if not ts or not sig:
        return False
    try:
        ts_int = int(ts)
    except ValueError:
        return False
    now = time.time() if now is None else now
    if abs(now - ts_int) > window_s:
        return False
    return hmac.compare_digest(compute(secret, method, path, body, ts), sig)
