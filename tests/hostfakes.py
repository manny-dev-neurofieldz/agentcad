"""A PrusaLink look-alike for the tests: a real HTTP server on 127.0.0.1 (an ephemeral port) that
asks for HTTP Digest authentication and checks the answer.

The challenge carries a realm, a fresh nonce, ``qop="auth"``, an opaque value and an algorithm. The
reply is checked with an implementation of RFC 7616 written here, separate from the client's: the
user, the realm, the nonce (one this server issued, not expired), the request URI as sent, a ``qop``
and an ``nc`` that only goes up, and the response hash itself. A wrong password gets a new challenge,
as a real server gives it.

It serves the routes the host reads (info, status, job, folder listings, and the files themselves at
the path a listing names) and records every request that reaches it, so a test can say exactly which
methods and paths went over the wire. Options switch on the misbehaviour the host must survive: an
expired nonce, a redirect, a server error, a truncated download, a server that never answers, a
server that only offers Basic.

Every host in the registry needs an entry in ``FAKES`` (the contract suite fails for one without it).
"""

import hashlib
import hmac
import json
import re
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

import pytest

from agentcad.hosts.credentials import HostSettings

USER = "agent-u-4821"
PASSWORD = "p4ss-W0rd-ZZ91"
REALM = "Printer API"
LOOPBACK = ("127.0.0.1", "::1", "localhost")

_HASH = {"MD5": "md5", "SHA-256": "sha256", "SHA-512-256": "sha512_256"}


# ---- the network guard every host test runs under --------------------------------------------

@pytest.fixture
def loopback_only(monkeypatch):
    """Tests reach the fake on 127.0.0.1 and nothing else: any other address or name fails the test."""
    real_connect, real_getaddrinfo = socket.socket.connect, socket.getaddrinfo

    def connect(self, address):
        if not (isinstance(address, tuple) and address[0] in LOOPBACK):
            raise AssertionError(f"a test tried to connect to {address!r}; tests stay on the loopback")
        return real_connect(self, address)

    def getaddrinfo(host, *args, **kwargs):
        if host not in LOOPBACK:
            raise AssertionError(f"a test tried to resolve {host!r}; tests stay on the loopback")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


# ---- a small file tree ------------------------------------------------------------------------

def blob(n: int = 200_003, seed: int = 0) -> bytes:
    """Deterministic bytes that span several read chunks and end off a chunk boundary."""
    return (bytes((i + seed) % 256 for i in range(256)) * (n // 256 + 1))[:n]


def file_node(name, display, mtime, data=None, size=False):
    data = blob() if data is None else data
    return {"name": name, "display_name": display, "type": "PRINT_FILE", "m_timestamp": mtime, "data": data,
            "with_size": size}


def folder_node(name, display, mtime, children):
    return {"name": name, "display_name": display, "type": "FOLDER", "m_timestamp": mtime, "children": children}


def default_tree() -> List[Dict[str, Any]]:
    return [
        file_node("BRACKE~2.BGC", "bracket_v1_x1_PETG_MK4_0.4n_0.2mm_PETG_MK4IS_41m.bgcode", 1790000100,
                  blob(seed=1)),
        file_node("BRACKE~1.BGC", "bracket_v2_x1_PETG_MK4_0.4n_0.2mm_PETG_MK4IS_44m.bgcode", 1790000300,
                  blob(seed=2), size=True),
        file_node("LID~1.BGC", "lid.bgcode", 1789999000, blob(5000, seed=3)),
        folder_node("OLD", "old", 1780000000, [
            file_node("SPARE~1.BGC", "spare_part_0.15mm.bgcode", 1780000100, blob(3000, seed=4)),
        ]),
    ]


# ---- the server -------------------------------------------------------------------------------

def _parse_authorization(value: str) -> Dict[str, str]:
    """The fields of a Digest Authorization header (quoted or bare)."""
    if not value.lower().startswith("digest "):
        return {}
    return {k.lower(): (v[1:-1].replace('\\"', '"') if v.startswith('"') else v)
            for k, v in re.findall(r'(\w+)=("(?:[^"\\]|\\.)*"|[^,\s]*)', value[7:])}


class FakePrusaLink:
    """Start with ``FakePrusaLink(...)``, stop with ``close()`` (or use it as a context manager)."""

    def __init__(self, tree=None, user: str = USER, password: str = PASSWORD, algorithms=("MD5",), qop: Optional[str] = "auth",
                 keep_alive: bool = True, stale_first: bool = False, basic_only: bool = False,
                 redirect_to: Optional[str] = None, fail: Optional[Dict[str, int]] = None, truncate: bool = False,
                 hang: bool = False, job: Optional[Dict[str, Any]] = None, prefix: str = "", timeout: float = 2.0,
                 printer_state: str = "IDLE", refs: str = "normal", always_stale: bool = False, garbage: bool = False,
                 raw: Optional[Dict[str, bytes]] = None, chunked: bool = False):
        self.tree = default_tree() if tree is None else tree
        self.user, self.password, self.algorithms, self.qop = user, password, list(algorithms), qop
        self.keep_alive, self.stale_first, self.basic_only = keep_alive, stale_first, basic_only
        self.redirect_to, self.fail, self.truncate, self.hang = redirect_to, dict(fail or {}), truncate, hang
        self.job, self.prefix, self.timeout, self.printer_state = job, prefix, timeout, printer_state
        self.refs = refs                                  # "normal", "none" (no refs at all) or a literal download ref
        self.always_stale, self.garbage, self.raw, self.chunked = always_stale, garbage, dict(raw or {}), chunked
        self.requests: List[Dict[str, Any]] = []          # every request that arrived, in order
        self.algorithm_used: Optional[str] = None         # the algorithm the last good Authorization named
        self._nonces: Dict[str, int] = {}                 # issued nonce -> highest nc seen
        self._expire_next = stale_first
        self._lock = threading.Lock()
        self._release = threading.Event()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):                 # keep test output quiet
                pass

            def handle_any(self):
                fake._handle(self)

            do_GET = do_HEAD = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = handle_any

        class Server(ThreadingHTTPServer):
            daemon_threads = True

        self._server = Server(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self._thread.start()

    # -- lifecycle
    def close(self):
        self._release.set()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- what the tests read
    @property
    def settings(self) -> HostSettings:
        return HostSettings(url=self.url + self.prefix, user=self.user, password=self.password,
                            timeout=self.timeout, source="test")

    @property
    def sample_file(self) -> str:
        return self.tree[0]["display_name"]

    def methods_seen(self):
        return {r["method"] for r in self.requests}

    def derived_secrets(self):
        """Values the client computed from the password and sent: each response hash, cnonce and the nonce."""
        found = set()
        for r in self.requests:
            found.update(v for k, v in _parse_authorization(r["authorization"] or "").items() if k in ("response", "cnonce", "nonce"))
        return found

    # -- digest
    def _challenge_headers(self, stale: bool = False) -> List[str]:
        if self.basic_only:
            return [f'Basic realm="{REALM}"']
        nonce = secrets.token_hex(16)
        with self._lock:
            self._nonces[nonce] = 0
        headers = []
        for algorithm in self.algorithms:
            parts = [f'realm="{REALM}"', f'nonce="{nonce}"']
            if self.qop:
                parts.append(f'qop="{self.qop}"')
            parts += ['opaque="5ccc069c403ebaf9"', f"algorithm={algorithm}"]
            if stale:
                parts.append("stale=true")
            headers.append("Digest " + ", ".join(parts))
        return headers

    def _expected(self, algorithm: str, method: str, uri: str, nonce: str, nc: str, cnonce: str) -> str:
        H = lambda text: hashlib.new(_HASH[algorithm], text.encode()).hexdigest()
        ha1 = H(f"{self.user}:{REALM}:{self.password}")
        ha2 = H(f"{method}:{uri}")
        if self.qop:
            return H(f"{ha1}:{nonce}:{nc}:{cnonce}:{self.qop}:{ha2}")
        return H(f"{ha1}:{nonce}:{ha2}")

    def _authorized(self, h) -> Optional[bool]:
        """True when the request carries a good Digest answer, False for a bad one, None when it
        carries none (or an expired nonce, which gets the stale flag)."""
        fields = _parse_authorization(h.headers.get("Authorization", ""))
        if not fields:
            return None
        algorithm = fields.get("algorithm", "MD5").upper()
        if algorithm not in self.algorithms or fields.get("username") != self.user or fields.get("realm") != REALM:
            return False
        if fields.get("uri") != h.path:                   # the URI as the request line sent it
            return False
        nonce = fields.get("nonce", "")
        with self._lock:
            known = nonce in self._nonces
            last_nc = self._nonces.get(nonce, 0)
        if not known or self._expire_next or self.always_stale:
            self._expire_next = False
            return None
        if self.qop:
            if fields.get("qop") != self.qop or not fields.get("cnonce") or not re.fullmatch(r"[0-9a-f]{8}", fields.get("nc", "")):
                return False
            if int(fields["nc"], 16) <= last_nc:          # a replay
                return False
        good = hmac.compare_digest(
            fields.get("response", ""), self._expected(algorithm, h.command, h.path, nonce, fields.get("nc", ""), fields.get("cnonce", "")))
        if good:
            with self._lock:
                if self.qop:
                    self._nonces[nonce] = int(fields["nc"], 16)
            self.algorithm_used = algorithm
        return good

    # -- http
    def _send(self, h, status, body=b"", headers=None, ctype="application/json", head=False, cut=None, chunked=False):
        h.send_response(status)
        for key, value in (headers or []):
            h.send_header(key, value)
        chunked = chunked and not head and status == 200
        if status != 204:
            h.send_header("Content-Type", ctype)
            h.send_header("Transfer-Encoding", "chunked") if chunked else h.send_header("Content-Length", str(len(body)))
        h.send_header("Connection", "keep-alive" if self.keep_alive else "close")
        h.end_headers()
        if chunked:
            allowed, sent, step = len(body) if cut is None else cut, 0, max(1, len(body) // 4)
            for i in range(0, len(body), step):
                piece = body[i:i + step]
                if sent + len(piece) > allowed:               # announce the whole chunk, deliver part of it, hang up
                    h.wfile.write(f"{len(piece):x}\r\n".encode() + piece[:allowed - sent])
                    h.wfile.flush()
                    h.close_connection = True
                    return
                h.wfile.write(f"{len(piece):x}\r\n".encode() + piece + b"\r\n")
                sent += len(piece)
            h.wfile.write(b"0\r\n\r\n")
            h.wfile.flush()
            return
        if not head and status != 204 and body:
            h.wfile.write(body if cut is None else body[:cut])
            h.wfile.flush()
        if cut is not None or not self.keep_alive:
            h.close_connection = True

    def _json(self, h, status, obj, head=False):
        self._send(h, status, json.dumps(obj).encode(), head=head)

    def _handle(self, h):
        head = h.command == "HEAD"
        record = {"method": h.command, "target": h.path, "authorized": False,
                  "authorization": h.headers.get("Authorization")}       # kept so tests can look for it in output
        self.requests.append(record)
        length = int(h.headers.get("Content-Length") or 0)
        if length:                                        # a request body would be a write; read it so the log is complete
            h.rfile.read(length)
        if self.hang:
            self._release.wait(self.timeout * 4)
            return
        if self.garbage:                                  # an answer that is not HTTP at all
            h.wfile.write(b"this is not http\r\n\r\n")
            h.wfile.flush()
            h.close_connection = True
            return
        if self.redirect_to:
            self._send(h, 301, headers=[("Location", self.redirect_to + h.path)])
            return
        auth = self._authorized(h)
        if auth is not True:
            stale = auth is None and bool(h.headers.get("Authorization"))
            self._send(h, 401, json.dumps({"message": "Unauthorized"}).encode(),
                       headers=[("WWW-Authenticate", c) for c in self._challenge_headers(stale)], head=head)
            return
        record["authorized"] = True
        if h.command not in ("GET", "HEAD"):              # the fake has no write routes at all
            self._json(h, 405, {"message": "Method Not Allowed"})
            return
        path = h.path
        if self.prefix:
            if not path.startswith(self.prefix + "/"):
                self._json(h, 404, {"message": "Not Found"}, head)
                return
            path = path[len(self.prefix):]
        for prefix, status in self.fail.items():
            if path.startswith(prefix):
                self._json(h, status, {"message": "the printer is having a bad day"}, head)
                return
        for prefix, body in self.raw.items():             # a fixed 200 reply that is not what the host expects
            if path.startswith(prefix):
                self._send(h, 200, body, ctype="text/html", head=head)
                return
        self._route(h, path, head)

    def _route(self, h, path, head):
        if path == "/api/v1/info":
            self._json(h, 200, {"name": "bench-printer", "hostname": "bench-mk4", "serial": "CZPX0000X000X00000",
                                "nozzle_diameter": 0.4, "mmu": False, "min_extrusion_temp": 170}, head)
        elif path == "/api/v1/status":
            body = {"storage": {"path": "/usb/", "name": "usb", "read_only": False},
                    "printer": {"state": self.printer_state, "temp_bed": 31.3, "target_bed": 0.0, "temp_nozzle": 30.9,
                                "target_nozzle": 0.0, "axis_z": 73.5, "flow": 100, "speed": 100, "fan_hotend": 0,
                                "fan_print": 0}}
            if self.job:
                body["job"] = {k: self.job[k] for k in ("id", "progress", "time_remaining", "time_printing") if k in self.job}
            self._json(h, 200, body, head)
        elif path == "/api/v1/job":
            if self.job:
                self._json(h, 200, self.job, head)
            else:
                self._send(h, 204)
        elif path.startswith("/api/v1/files/"):
            self._listing(h, [unquote(p) for p in path[len("/api/v1/files/"):].split("/") if p], head)
        else:
            self._download(h, [unquote(p) for p in path.split("/") if p], head)

    def _node(self, storage_and_path):
        storage, rest = storage_and_path[0], storage_and_path[1:]
        if storage != "usb":
            return None
        children = self.tree
        node = {"children": children, "type": "FOLDER"}
        for part in rest:
            node = next((c for c in node.get("children", []) if c["name"] == part), None)
            if node is None:
                return None
        return node

    def _listing(self, h, parts, head):
        node = self._node(parts) if parts else None
        if node is None or node["type"] != "FOLDER":
            self._json(h, 404, {"message": "Not Found"}, head)
            return
        base = "/" + "/".join(parts)
        children = []
        for c in node["children"]:
            entry = {"name": c["name"], "display_name": c["display_name"], "type": c["type"],
                     "m_timestamp": c["m_timestamp"]}
            if c["type"] != "FOLDER":
                if c.get("with_size"):
                    entry["size"] = len(c["data"])
                if self.refs != "none":
                    entry["refs"] = {"icon": f"/thumb/s{base}/{c['name']}", "thumbnail": f"/thumb/l{base}/{c['name']}",
                                     "download": f"{base}/{c['name']}" if self.refs == "normal" else self.refs}
            children.append(entry)
        self._json(h, 200, {"type": "FOLDER", "name": parts[-1], "path": "/", "read_only": False, "children": children}, head)

    def _download(self, h, parts, head):
        node = self._node(parts) if len(parts) >= 2 else None
        if node is None or node["type"] == "FOLDER":
            self._json(h, 404, {"message": "Not Found"}, head)
            return
        data = node["data"]
        self._send(h, 200, data, ctype="application/octet-stream", head=head,
                   cut=len(data) // 2 if self.truncate else None, chunked=self.chunked)


FAKES = {"prusalink": FakePrusaLink}
