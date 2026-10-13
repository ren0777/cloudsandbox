#!/usr/bin/env python3
"""CloudLabs API-audit proxy (PLAN architecture, "audit proxy"; docs/NEXT.md milestone 50).

Runs as the sandbox's `audit` container (terminal image, own uid) inside the emulator's network namespace. The
student terminal and the console reach the emulator through it; it forwards each request unchanged and records
what was asked and how it ended:

    {seq, t, method, path, query, target, action, service, headers, status, source}

It records raw request facts only. Turning them into `service:Operation` names is the control plane's job (it has
botocore's service models), so this file stays small and never needs to know an AWS API.

    GET /_cloudlabs/audit   the log as JSON (never logged itself; refused to the student terminal)

Source: `cli` unless the request carries `X-CloudLabs-Source: console` AND provably does not come from the
terminal container (its address is resolved through the sandbox network's DNS); an unknown terminal address
fails closed to `cli`, so a student can never make a call look like a console call.

Standard library only (Python 3.11 in the terminal image). Bodies are streamed, never buffered, except small
form-encoded bodies (Query protocol), which are read to find their `Action`.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import sys
import threading
import time
import urllib.parse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

LOG_PATH = "/_cloudlabs/audit"
SOURCE_HEADER = "x-cloudlabs-source"
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "proxy-connection", "te",
       "trailer", "trailers", "transfer-encoding", "upgrade", "expect", SOURCE_HEADER}
MAX_EVENTS = 5000
FORM_PEEK = 1024 * 1024
CHUNK = 64 * 1024
MAX_FIELD = 1024
MAX_HEADER_NAMES = 40
TERMINAL_TTL_S = 5.0


class AuditLog:
    """Bounded, thread-safe event log. When full, the oldest events go and `dropped` counts them."""

    def __init__(self, max_events: int = MAX_EVENTS):
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._lock = threading.Lock()
        self._seq = 0
        self.dropped = 0

    def add(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._seq += 1
            if len(self._events) == self._events.maxlen:
                self.dropped += 1
            self._events.append({"seq": self._seq, **event})

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"version": 1, "dropped": self.dropped, "events": list(self._events)}


class TerminalAddress:
    """The terminal container's address(es) on the sandbox network, re-resolved every few seconds (the terminal
    is recreated on Reset). `is_terminal` answers None when the name can't be resolved."""

    def __init__(self, host: str):
        self.host = host
        self._ips: set[str] | None = None
        self._at = 0.0
        self._lock = threading.Lock()

    def _resolve(self) -> set[str] | None:
        try:
            return {ai[4][0] for ai in socket.getaddrinfo(self.host, None, proto=socket.IPPROTO_TCP)}
        except OSError:
            return None

    def is_terminal(self, ip: str) -> bool | None:
        with self._lock:
            if time.monotonic() - self._at > TERMINAL_TTL_S or self._ips is None:
                self._ips, self._at = self._resolve(), time.monotonic()
            ips = self._ips
        return None if ips is None else ip in ips


def sigv4_service(headers: Any, query: dict[str, list[str]]) -> str:
    """The signing service from a SigV4 credential scope (`<key>/<date>/<region>/<service>/aws4_request`), from
    the Authorization header or a presigned URL's X-Amz-Credential. '' when the request isn't SigV4-signed."""
    auth = headers.get("Authorization") or ""
    cred = ""
    if "Credential=" in auth:
        cred = auth.split("Credential=", 1)[1].split(",", 1)[0].strip()
    elif query.get("X-Amz-Credential"):
        cred = query["X-Amz-Credential"][0]
    parts = cred.split("/")
    return parts[3] if len(parts) >= 5 else ""


def form_action(body: bytes) -> str:
    try:
        return urllib.parse.parse_qs(body.decode("utf-8", "replace")).get("Action", [""])[0][:128]
    except ValueError:
        return ""


class _Limited:
    """File-like view of exactly n bytes of a stream (http.client reads a body object block by block)."""

    def __init__(self, stream: Any, n: int):
        self.stream, self.left = stream, n

    def read(self, size: int = CHUNK) -> bytes:
        if self.left <= 0:
            return b""
        data = self.stream.read(min(size if size and size > 0 else CHUNK, self.left))
        if not data:
            raise ConnectionError("client closed the connection mid-body")
        self.left -= len(data)
        return data


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive with the client; Expect: 100-continue is answered here
    timeout = 120  # idle client connections don't hold a thread forever
    server: "AuditServer"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002  (quiet: the audit log is the record)
        pass

    def do_GET(self) -> None:  # noqa: N802
        self._handle()

    do_POST = do_PUT = do_DELETE = do_HEAD = do_PATCH = do_OPTIONS = do_GET  # noqa: N815

    # ------------------------------------------------------------------ helpers
    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response_only(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_chunked(self):
        while True:
            line = self.rfile.readline(1024)
            size = int(line.split(b";", 1)[0].strip() or b"0", 16)
            if size == 0:
                while self.rfile.readline(1024) not in (b"\r\n", b"\n", b""):
                    pass  # trailers
                return
            data = self.rfile.read(size)
            self.rfile.readline(8)  # CRLF after the chunk
            yield data

    # ------------------------------------------------------------------ request
    def _handle(self) -> None:
        peer = self.client_address[0]
        split = urllib.parse.urlsplit(self.path)
        if split.path == LOG_PATH:
            if self.server.terminal.is_terminal(peer) is True:
                self._send_json(403, {"error": "forbidden"})
            else:
                self._send_json(200, self.server.log.snapshot())
            return
        query = urllib.parse.parse_qs(split.query, keep_blank_values=True)
        chunked = "chunked" in (self.headers.get("Transfer-Encoding") or "").lower()
        length = 0 if chunked else int(self.headers.get("Content-Length") or 0)
        ctype = (self.headers.get("Content-Type") or "").lower()
        peeked: bytes | None = None
        if (not chunked and self.command == "POST" and ctype.startswith("application/x-www-form-urlencoded")
                and length <= FORM_PEEK):
            peeked = self.rfile.read(length)
        claimed_console = (self.headers.get(SOURCE_HEADER) or "").strip().lower() == "console"
        source = "console" if claimed_console and self.server.terminal.is_terminal(peer) is False else "cli"
        event: dict[str, Any] = {
            "t": int(time.time() * 1000), "method": self.command, "path": split.path[:MAX_FIELD],
            "query": split.query[:MAX_FIELD], "target": (self.headers.get("X-Amz-Target") or "")[:128],
            "action": form_action(peeked) if peeked else "", "service": sigv4_service(self.headers, query),
            "headers": sorted({k.lower() for k in self.headers.keys()})[:MAX_HEADER_NAMES],
            "status": 0, "source": source,
        }
        try:
            self._forward(event, chunked, length, peeked)
        except (ConnectionError, OSError, http.client.HTTPException, ValueError):
            self.close_connection = True
        finally:
            if event["status"] == 0:  # never answered by the emulator (client gone mid-body, bad framing)
                event["status"] = 502
                self.server.log.add(event)

    def _forward(self, event: dict[str, Any], chunked: bool, length: int, peeked: bytes | None) -> None:
        host, port = self.server.upstream
        conn = http.client.HTTPConnection(host, port, timeout=300)
        try:
            try:
                conn.putrequest(self.command, self.path, skip_host=True, skip_accept_encoding=True)
                for k, v in self.headers.items():
                    if k.lower() not in HOP:
                        conn.putheader(k, v)
                if chunked:
                    conn.putheader("Transfer-Encoding", "chunked")
                conn.endheaders()
                if peeked is not None:
                    conn.send(peeked)
                elif chunked:
                    for data in self._read_chunked():
                        conn.send(f"{len(data):x}\r\n".encode() + data + b"\r\n")
                    conn.send(b"0\r\n\r\n")
                elif length:
                    body = _Limited(self.rfile, length)
                    while data := body.read(CHUNK):
                        conn.send(data)
                resp = conn.getresponse()
            except (ConnectionRefusedError, socket.timeout, http.client.HTTPException, OSError) as e:
                if isinstance(e, ConnectionError) and "mid-body" in str(e):
                    raise
                event["status"] = 502
                self.server.log.add(event)
                self._send_json(502, {"error": "emulator unreachable"})
                return
            # Recorded before the response is relayed: once a client has its answer, the call is in the log
            # (a grade taken right after a CLI command must see it), even if the client goes away mid-body.
            event["status"] = resp.status
            self.server.log.add(event)
            self._relay(resp)
        finally:
            conn.close()

    def _relay(self, resp: http.client.HTTPResponse) -> None:
        status = resp.status
        self.send_response_only(status, resp.reason)
        no_body = self.command == "HEAD" or status in (204, 304) or 100 <= status < 200
        has_length = resp.getheader("Content-Length") is not None
        for k, v in resp.getheaders():
            if k.lower() not in HOP:
                self.send_header(k, v)
        if not no_body and not has_length:
            self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        if no_body:
            return
        while data := resp.read(CHUNK):
            if has_length:
                self.wfile.write(data)
            else:
                self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
        if not has_length:
            self.wfile.write(b"0\r\n\r\n")


class AuditServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, listen: tuple[str, int], upstream: tuple[str, int], terminal_host: str = "terminal",
                 max_events: int = MAX_EVENTS):
        super().__init__(listen, Handler)
        self.upstream = upstream
        self.log = AuditLog(max_events)
        self.terminal = TerminalAddress(terminal_host)


def main() -> int:
    port = int(os.environ.get("AUDIT_PORT", "7690"))
    up_host, _, up_port = os.environ.get("AUDIT_UPSTREAM", "127.0.0.1:4566").rpartition(":")
    server = AuditServer(("0.0.0.0", port), (up_host or "127.0.0.1", int(up_port)),
                         os.environ.get("AUDIT_TERMINAL_HOST", "terminal"))
    print(f"audit proxy :{port} -> {up_host}:{up_port}", file=sys.stderr, flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
