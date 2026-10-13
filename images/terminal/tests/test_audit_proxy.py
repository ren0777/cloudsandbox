"""Audit proxy unit tests: a fake upstream and the real proxy on loopback sockets (stdlib only).

    python -m unittest discover -s images/terminal/tests
"""

from __future__ import annotations

import hashlib
import http.client
import json
import socket
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import audit_proxy as ap  # noqa: E402

SIG = ("AWS4-HMAC-SHA256 Credential=testing/20261012/us-east-1/{svc}/aws4_request, "
       "SignedHeaders=host;x-amz-date, Signature=abc")


class Upstream(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _body(self) -> bytes:
        if "chunked" in (self.headers.get("Transfer-Encoding") or ""):
            out = b""
            while True:
                size = int(self.rfile.readline().strip(), 16)
                if size == 0:
                    self.rfile.readline()
                    return out
                out += self.rfile.read(size)
                self.rfile.readline()
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def do_GET(self):
        body = self._body()
        if self.path.startswith("/nocontent"):
            self.send_response(204)
            self.end_headers()
            return
        if self.path.startswith("/fail"):
            payload = b'{"error":"nope"}'
            self.send_response(400)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        echo = json.dumps({"method": self.command, "path": self.path,
                           "headers": {k.lower(): v for k, v in self.headers.items()},
                           "len": len(body), "sha": hashlib.sha256(body).hexdigest()}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        if self.path.startswith("/chunked"):
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for i in range(0, len(echo), 7):
                part = echo[i:i + 7]
                self.wfile.write(f"{len(part):x}\r\n".encode() + part + b"\r\n")
            self.wfile.write(b"0\r\n\r\n")
            return
        self.send_header("Content-Length", str(len(echo)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(echo)

    do_POST = do_PUT = do_DELETE = do_HEAD = do_GET


def serve(server: ThreadingHTTPServer) -> None:
    threading.Thread(target=server.serve_forever, daemon=True).start()


class ProxyTest(unittest.TestCase):
    terminal_host = "192.0.2.1"  # TEST-NET: never the loopback peer, so the test client is "not the terminal"

    def setUp(self):
        self.up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        self.up.daemon_threads = True
        serve(self.up)
        self.proxy = ap.AuditServer(("127.0.0.1", 0), ("127.0.0.1", self.up.server_address[1]),
                                    self.terminal_host, max_events=50)
        serve(self.proxy)
        self.port = self.proxy.server_address[1]

    def tearDown(self):
        for s in (self.proxy, self.up):
            s.shutdown()
            s.server_close()

    def request(self, method, path, body=None, headers=None, conn=None):
        c = conn or http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        data = r.read()
        if conn is None:
            c.close()
        return r, data

    def events(self):
        r, data = self.request("GET", ap.LOG_PATH)
        self.assertEqual(r.status, 200)
        return json.loads(data)

    # ----------------------------------------------------------------- forwarding
    def test_json_protocol_is_forwarded_and_logged(self):
        r, data = self.request("POST", "/", b'{"TableName":"t"}', {
            "X-Amz-Target": "DynamoDB_20120810.CreateTable", "Authorization": SIG.format(svc="dynamodb"),
            "Content-Type": "application/x-amz-json-1.0"})
        self.assertEqual(r.status, 200)
        echo = json.loads(data)
        self.assertEqual(echo["headers"]["x-amz-target"], "DynamoDB_20120810.CreateTable")
        self.assertEqual(echo["len"], len(b'{"TableName":"t"}'))
        (ev,) = self.events()["events"]
        self.assertEqual((ev["seq"], ev["target"], ev["service"], ev["status"], ev["source"]),
                         (1, "DynamoDB_20120810.CreateTable", "dynamodb", 200, "cli"))

    def test_query_protocol_action_is_read_and_body_forwarded_intact(self):
        body = b"Action=CreateUser&Version=2010-05-08&UserName=alice"
        r, data = self.request("POST", "/", body, {"Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                                                   "Authorization": SIG.format(svc="iam")})
        self.assertEqual(json.loads(data)["sha"], hashlib.sha256(body).hexdigest())
        (ev,) = self.events()["events"]
        self.assertEqual((ev["action"], ev["service"]), ("CreateUser", "iam"))

    def test_rest_request_records_path_query_and_header_names(self):
        self.request("PUT", "/bucket/key.txt?tagging", b"x", {"x-amz-copy-source": "a/b",
                                                               "Authorization": SIG.format(svc="s3")})
        (ev,) = self.events()["events"]
        self.assertEqual((ev["method"], ev["path"], ev["query"]), ("PUT", "/bucket/key.txt", "tagging"))
        self.assertIn("x-amz-copy-source", ev["headers"])

    def test_large_body_is_streamed(self):
        body = bytes(range(256)) * 12000  # ~3 MiB
        r, data = self.request("PUT", "/b/big", body, {"Authorization": SIG.format(svc="s3")})
        self.assertEqual(json.loads(data)["sha"], hashlib.sha256(body).hexdigest())

    def test_chunked_request_body(self):
        def gen():
            yield b"hello "
            yield b"world"
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("PUT", "/b/k", body=gen(), encode_chunked=True, headers={"Transfer-Encoding": "chunked"})
        echo = json.loads(c.getresponse().read())
        c.close()
        self.assertEqual(echo["sha"], hashlib.sha256(b"hello world").hexdigest())

    def test_expect_100_continue(self):
        s = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        s.sendall(b"PUT /b/k HTTP/1.1\r\nHost: x\r\nContent-Length: 4\r\nExpect: 100-continue\r\n\r\n")
        self.assertTrue(s.recv(64).startswith(b"HTTP/1.1 100"))
        s.sendall(b"data")
        buf = b""
        while b"sha" not in buf:
            buf += s.recv(4096)
        s.close()
        self.assertIn(b"200", buf.split(b"\r\n", 1)[0])

    def test_chunked_response_is_relayed(self):
        r, data = self.request("GET", "/chunked/x")
        self.assertEqual(json.loads(data)["path"], "/chunked/x")

    def test_head_and_no_content(self):
        r, data = self.request("HEAD", "/b/k")
        self.assertEqual((r.status, data), (200, b""))
        r, data = self.request("DELETE", "/nocontent")
        self.assertEqual((r.status, data), (204, b""))
        self.assertEqual([e["status"] for e in self.events()["events"]], [200, 204])

    def test_keep_alive_logs_every_request(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        for i in range(3):
            self.request("GET", f"/b?i={i}", conn=c)
        c.close()
        self.assertEqual([e["query"] for e in self.events()["events"]], ["i=0", "i=1", "i=2"])

    def test_error_status_is_recorded(self):
        r, _ = self.request("POST", "/fail")
        self.assertEqual(r.status, 400)
        self.assertEqual(self.events()["events"][0]["status"], 400)

    def test_presigned_credential(self):
        cred = "testing%2F20261012%2Fus-east-1%2Fs3%2Faws4_request"
        self.request("GET", f"/b/k?X-Amz-Credential={cred}&X-Amz-Signature=x")
        self.assertEqual(self.events()["events"][0]["service"], "s3")

    # ----------------------------------------------------------------- source + log
    def test_console_header_honoured_for_non_terminal_peer_and_not_forwarded(self):
        _, data = self.request("GET", "/b", headers={"X-CloudLabs-Source": "console"})
        self.assertNotIn("x-cloudlabs-source", json.loads(data)["headers"])
        self.assertEqual(self.events()["events"][0]["source"], "console")

    def test_log_endpoint_is_not_logged(self):
        self.events()
        self.events()
        self.assertEqual(self.events()["events"], [])

    def test_ring_buffer_counts_dropped_events(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        for _ in range(55):
            self.request("GET", "/b", conn=c)
        c.close()
        log = self.events()
        self.assertEqual((len(log["events"]), log["dropped"], log["events"][0]["seq"]), (50, 5, 6))


class TerminalPeerTest(ProxyTest.__base__):  # type: ignore[misc]
    """The test client IS the terminal (terminal name resolves to loopback)."""

    def setUp(self):
        ProxyTest.setUp(self)

    tearDown = ProxyTest.tearDown
    request = ProxyTest.request
    terminal_host = "localhost"

    def test_forged_console_header_from_terminal_is_cli(self):
        self.request("GET", "/b", headers={"X-CloudLabs-Source": "console"})
        log = self.proxy.log.snapshot()
        self.assertEqual(log["events"][0]["source"], "cli")

    def test_terminal_cannot_read_the_log(self):
        r, _ = self.request("GET", ap.LOG_PATH)
        self.assertEqual(r.status, 403)


class UnresolvableTerminalTest(TerminalPeerTest):
    terminal_host = "no-such-terminal.invalid"

    def test_forged_console_header_from_terminal_is_cli(self):
        """Unknown terminal address fails closed: the console claim is ignored."""
        super().test_forged_console_header_from_terminal_is_cli()

    def test_terminal_cannot_read_the_log(self):
        r, _ = self.request("GET", ap.LOG_PATH)  # unknown terminal: the control plane must still read it
        self.assertEqual(r.status, 200)


class UpstreamDownTest(unittest.TestCase):
    def test_unreachable_emulator_answers_502_and_is_logged(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        dead = s.getsockname()[1]
        s.close()
        proxy = ap.AuditServer(("127.0.0.1", 0), ("127.0.0.1", dead), "192.0.2.1")
        serve(proxy)
        try:
            c = http.client.HTTPConnection("127.0.0.1", proxy.server_address[1], timeout=10)
            c.request("GET", "/b")
            self.assertEqual(c.getresponse().status, 502)
            c.close()
            self.assertEqual(proxy.log.snapshot()["events"][0]["status"], 502)
        finally:
            proxy.shutdown()
            proxy.server_close()


if __name__ == "__main__":
    unittest.main()
