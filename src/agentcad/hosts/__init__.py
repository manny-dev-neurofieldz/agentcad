"""Printer hosts: where a printer can be asked what it holds and what it is doing.

A host is a service in front of printers: a printer's own web interface, a farm server, a cloud
queue. Hosts register under a short lower-case name, as output targets and engines do. Each
declares the capabilities it has, and each capability is a method of the same name:

* ``list_printers``: the printers the host knows (``list_printers()``);
* ``list_files``: the files a printer keeps (``list_files(path, storage)``);
* ``download_file``: fetch one file by name (``download_file(name, open_sink, storage)``);
* ``job_status``: what the printer is doing now (``job_status()``).

A capability a host does not declare raises :class:`NotSupported` naming the host, never a silent
no-op, so adding the next host changes no command: the commands ask the registry what each host
can do.

Read-only is part of the contract. In every host exactly one method performs network I/O; the
class attribute ``network_function`` names it. Its first statement is ``require_read_only(method)``,
which refuses any method but GET and HEAD before a connection is opened, and no network library
is imported or used anywhere else in the host's module. The contract test runs over every
registered host and holds each one to that, on the wire as well as in the source.
"""

from abc import ABC
from dataclasses import dataclass, field
from typing import Any, BinaryIO, Callable, Dict, FrozenSet, List, Optional, Type

CAPABILITIES = ("list_printers", "list_files", "download_file", "job_status")

#: The only HTTP methods any host may send.
READ_ONLY_METHODS = ("GET", "HEAD")


class HostError(Exception):
    """A host could not do what was asked; the message says why and never carries a credential."""


class HostConfigError(HostError):
    """The host is not configured (no address or credentials) or its configuration is unsafe."""


class NotSupported(HostError):
    """A host was asked for a capability it does not declare."""


class HostUnreachable(HostError):
    """The host could not be reached (refused, timed out, no route, a broken reply)."""


class HostAuthError(HostError):
    """The host refused the credentials, or asked for authentication agentcad cannot answer."""


class HostNotFound(HostError):
    """The host has no such file or route."""


class HostServerError(HostError):
    """The host answered with a server error or something unexpected."""


class ReadOnlyViolation(RuntimeError):
    """Something tried to send a request that is not GET or HEAD. A defect in the caller, not a host failure."""


def require_read_only(method: str) -> str:
    """The method itself when it is GET or HEAD; anything else raises before anything is sent."""
    if method not in READ_ONLY_METHODS:
        raise ReadOnlyViolation(f"{method!r} refused: printer hosts are read-only (only "
                                f"{' and '.join(READ_ONLY_METHODS)} may be sent)")
    return method


@dataclass
class HostResponse:
    """What a host's network function returns: the status line, the headers (names lower-cased,
    repeated ones joined by ``, ``), the body when it was held in memory, and the bytes read."""
    status: int
    reason: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    bytes_read: int = 0


#: ``open_sink(entry)`` returns the binary file object a download is written to; the host calls it
#: once, after it has found the file and before the first byte is written.
OpenSink = Callable[[Dict[str, Any]], BinaryIO]


class PrinterHost(ABC):
    """A printer host; subclasses set ``name``, ``capabilities`` and ``network_function`` and
    implement exactly the capabilities they declare."""

    name: str = ""
    capabilities: FrozenSet[str] = frozenset()
    #: The one method that performs network I/O (checked by the contract test).
    network_function: str = "_http"
    #: Values a host fills in when the configuration leaves them out (for example the user name).
    setting_defaults: Dict[str, Any] = {}

    def __init__(self, settings=None):
        self._settings = settings

    @property
    def settings(self):
        """Address and credentials: those the host was built with, else those the environment and
        the user configuration file give (read on first use, so listing hosts needs none)."""
        if self._settings is None:
            from agentcad.hosts.credentials import load_settings
            self._settings = load_settings(self.name, defaults=self.setting_defaults)
        return self._settings

    def _unsupported(self, capability: str) -> NotSupported:
        return NotSupported(f"host {self.name!r} does not {capability.replace('_', ' ')} "
                            f"(its capabilities: {', '.join(sorted(self.capabilities)) or 'none'})")

    def require(self, capability: str) -> None:
        """Raise :class:`NotSupported` unless the host declares ``capability``."""
        if capability not in self.capabilities:
            raise self._unsupported(capability)

    def list_printers(self) -> List[Dict[str, Any]]:
        raise self._unsupported("list_printers")

    def list_files(self, path: str = "", storage: Optional[str] = None) -> Dict[str, Any]:
        raise self._unsupported("list_files")

    def download_file(self, name: str, open_sink: OpenSink, storage: Optional[str] = None) -> Dict[str, Any]:
        raise self._unsupported("download_file")

    def job_status(self) -> Dict[str, Any]:
        raise self._unsupported("job_status")


_REGISTRY: Dict[str, Type[PrinterHost]] = {}


def register_host(name: str, host_cls: Type[PrinterHost]) -> None:
    """Register a printer host class by name."""
    _REGISTRY[name] = host_cls


def unregister_host(name: str) -> None:
    _REGISTRY.pop(name, None)


def get_host(name: str, settings=None) -> PrinterHost:
    """An instance of a registered host; an error names the registered ones."""
    if name not in _REGISTRY:
        raise ValueError(f"unknown printer host {name!r}; registered: {', '.join(sorted(_REGISTRY)) or 'none'}")
    return _REGISTRY[name](settings)


def list_hosts() -> List[str]:
    return sorted(_REGISTRY)


def describe() -> List[Dict[str, Any]]:
    """Every registered host: its name and the capabilities it declares, in contract order."""
    out = []
    for name in list_hosts():
        host = _REGISTRY[name]
        out.append({"name": name, "capabilities": [c for c in CAPABILITIES if c in host.capabilities]})
    return out


# imported last: the hosts subclass PrinterHost, defined above
from agentcad.hosts import prusalink as _prusalink  # noqa: E402

register_host("prusalink", _prusalink.PrusaLinkHost)
