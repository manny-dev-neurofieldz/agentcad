"""The read-only host contract as checks.

``tests/test_host_contract.py`` runs these over every registered host, and runs them again over hosts
written to break the contract (the controls), which must fail. Each check raises AssertionError
naming what it found; none of them contacts anything but the fake server on the loopback address.

1. ``check_refuses_writes``: the host's one network function refuses every method but GET and HEAD,
   before any connection is attempted.
2. ``check_source``: in the host's module, no network or process library is used outside that function,
   the function opens with ``require_read_only``, and no write method is spelled out in it.
3. ``check_wire``: every declared capability, run against the fake server, connects only from inside
   the network function, and
4. the fake saw nothing but GET and HEAD.
"""

import ast
import inspect
import io
import socket
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

from agentcad.hosts import CAPABILITIES, NotSupported, ReadOnlyViolation

WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT", "get", "head", "Get", "",
                 "GET /x HTTP/1.1\r\nPOST", "GET ", "GETS")
WRITE_LITERALS = {"POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"}
DENIED_MODULES = ("socket", "ssl", "http.client", "http.server", "urllib.request", "urllib3", "requests", "httpx",
                  "aiohttp", "ftplib", "smtplib", "telnetlib", "xmlrpc", "asyncio", "selectors", "subprocess",
                  "pycurl", "paramiko", "websocket", "websockets")
DENIED_CALLS = {"__import__", "import_module", "eval", "exec", "system", "popen"}


def _denied(dotted: str) -> bool:
    return any(dotted == m or dotted.startswith(m + ".") for m in DENIED_MODULES)


def _dotted(node) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def network_method(host):
    return getattr(host, host.network_function)


# ---- 1. refuses writes -------------------------------------------------------------------------

def check_refuses_writes(host, monkeypatch) -> None:
    attempts: List[Any] = []
    real_connect = socket.socket.connect

    def connect(self, address):
        attempts.append(address)
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    send = network_method(host)
    for method in WRITE_METHODS:
        try:
            send(method, "/api/v1/status")
        except ReadOnlyViolation:
            continue
        except BaseException as e:                       # refused for another reason is not refused as a write
            raise AssertionError(f"{host.name}: {method!r} raised {type(e).__name__}, not ReadOnlyViolation") from None
        raise AssertionError(f"{host.name}: {host.network_function} sent or accepted the method {method!r}")
    assert not attempts, f"{host.name}: a connection was attempted for a refused method: {attempts}"


# ---- 2. source ----------------------------------------------------------------------------------

def _problems_outside(tree, path: Path, inside) -> List[str]:
    problems: List[str] = []
    for node in ast.walk(tree):
        if id(node) in inside:
            continue
        where = f"{path.name}:{getattr(node, 'lineno', '?')}"
        if isinstance(node, ast.Import):
            problems += [f"{where} imports {a.name}" for a in node.names if _denied(a.name)]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            problems += [f"{where} imports {module}.{a.name}" for a in node.names
                         if _denied(module) or _denied(f"{module}.{a.name}")]
        elif isinstance(node, ast.Attribute) and _denied(_dotted(node)):
            problems.append(f"{where} uses {_dotted(node)}")
        elif isinstance(node, ast.Name) and _denied(node.id):
            problems.append(f"{where} uses {node.id}")
        elif isinstance(node, ast.Call) and _dotted(node.func).split(".")[-1] in DENIED_CALLS:
            problems.append(f"{where} calls {_dotted(node.func)}")
    return problems


def check_module_is_network_free(path: Path) -> None:
    """A module that is not a host's (the contract, the credentials, the Digest maths) uses no network or process library."""
    path = Path(path)
    problems = _problems_outside(ast.parse(path.read_text(), filename=str(path)), path, set())
    assert not problems, "network or process use in a shared module: " + "; ".join(problems)


def check_source(host_cls) -> None:
    """The host's own modules (its class and the host classes it inherits from, not the base contract)."""
    from agentcad.hosts import PrinterHost
    name = host_cls.network_function
    classes = [c for c in host_cls.__mro__ if c not in (PrinterHost, object) and issubclass(c, PrinterHost)]
    owners = [c for c in classes if name in vars(c)]
    assert owners, f"{host_cls.__name__}: no class defines the network function {name!r}"
    owner_path = Path(inspect.getsourcefile(sys.modules[owners[0].__module__]))
    seen = set()
    for cls in classes:
        path = Path(inspect.getsourcefile(sys.modules[cls.__module__]))
        if path in seen:
            continue
        seen.add(path)
        tree = ast.parse(path.read_text(), filename=str(path))
        functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
        inside = {id(n) for fn in functions for n in ast.walk(fn)}      # an overridden base version stays allowed
        if path == owner_path:                                            # the effective one is checked closely
            assert len(functions) == 1, f"{path.name}: expected one function named {name!r}, found {len(functions)}"
            fn = functions[0]
            body = [st for st in fn.body if not (isinstance(st, ast.Expr) and isinstance(getattr(st, "value", None), ast.Constant))]
            first = body[0] if body else None
            guard = _dotted(first.value.func) if isinstance(first, (ast.Expr, ast.Assign)) and isinstance(first.value, ast.Call) else None
            assert guard and guard.split(".")[-1] == "require_read_only", \
                f"{name} does not open with require_read_only (opens with {guard!r})"
            literals = sorted({n.value for n in ast.walk(fn) if isinstance(n, ast.Constant) and n.value in WRITE_LITERALS})
            assert not literals, f"{name} spells out write methods: {literals}"
        problems = _problems_outside(tree, path, inside)
        assert not problems, f"network or process use outside {name}: " + "; ".join(problems)


# ---- 3 and 4. the wire --------------------------------------------------------------------------

def exercise(host, fake) -> Dict[str, Any]:
    """Every declared capability, once, against ``fake``; returns the results and any errors."""
    sink = io.BytesIO()
    calls = {"list_printers": lambda: host.list_printers(),
             "list_files": lambda: host.list_files(),
             "download_file": lambda: host.download_file(fake.sample_file, lambda entry: sink),
             "job_status": lambda: host.job_status()}
    results: Dict[str, Any] = {}
    errors: List[str] = []
    for capability in CAPABILITIES:
        if capability not in host.capabilities:
            with pytest.raises(NotSupported, match=host.name):
                calls[capability]()
            continue
        try:
            results[capability] = calls[capability]()
        except Exception as e:
            errors.append(f"{capability}: {type(e).__name__}: {e}")
    return {"results": results, "errors": errors, "downloaded": sink.getvalue()}


def check_wire(host, fake, monkeypatch) -> Dict[str, Any]:
    seen: List[Any] = []
    real_connect = socket.socket.connect

    def connect(self, address):
        frames, frame = [], sys._getframe(1)
        while frame is not None:
            frames.append(frame.f_code.co_name)
            frame = frame.f_back
        seen.append((address, frames))
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    ran = exercise(host, fake)
    name = host.network_function
    outside = [address for address, frames in seen if name not in frames]
    assert seen, f"{host.name}: no capability reached the network at all"
    assert not outside, f"{host.name}: connected from outside {name}: {outside}"
    writes = sorted(fake.methods_seen() - {"GET", "HEAD"})
    assert not writes, f"{host.name}: the server saw {writes}"
    return ran
