"""The ``prusalink`` host: a printer's own PrusaLink service (v1 HTTP API, HTTP Digest authentication).

Everything it reads, it reads with GET:

* ``/api/v1/info``: the printer's name, nozzle and serial number (``list_printers``);
* ``/api/v1/files/<storage>/<folder>/``: a folder's entries, each with a short (8.3) ``name``, a
  ``display_name`` and, in ``refs.download``, the path the file is served from (``list_files``,
  ``download_file``);
* ``/api/v1/status`` and ``/api/v1/job``: the printer's state, temperatures and the running job
  (``job_status``).

A file is found by either of its names, the short name the printer stores or the display name a
slicer gave it; the download goes to the path the printer itself names. The one method that touches
the network is :meth:`PrusaLinkHost._http`: it refuses anything but GET and HEAD first, speaks Digest
(a first request, the printer's challenge, the same request answered), streams a download into the
caller's file, and never follows a redirect, so a credential only ever goes where it was configured.
Network libraries are imported inside that method and nowhere else in this module.
"""

import difflib
import json
import logging
import re
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import quote, urlsplit

from agentcad.hosts import (CAPABILITIES, HostAuthError, HostError, HostNotFound, HostResponse, HostServerError,
                            HostUnreachable, OpenSink, PrinterHost, require_read_only)
from agentcad.hosts import digest

_log = logging.getLogger(__name__)

DEFAULT_STORAGE = "usb"
MAX_JSON = 16 * 1024 * 1024          # a folder listing is far smaller; this only stops a runaway reply
CHUNK = 64 * 1024
ATTEMPTS = 3                         # the first request, the answered challenge, one retry for a stale nonce
USER_AGENT = "agentcad-printer-host"
_SAFE_PATH = re.compile(r"/[!-~]*")  # a request path: printable ASCII, no space, so nothing can end the request line
_SAFE_ROUTE = re.compile(r"/[A-Za-z0-9._~/!#$&'()@^`{}+,;=%-]*")
_PRINTER_FIELDS = ("state", "temp_nozzle", "target_nozzle", "temp_bed", "target_bed", "axis_x", "axis_y", "axis_z",
                   "flow", "speed", "fan_hotend", "fan_print")


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def split_name(name: str) -> List[str]:
    """The parts of a file name given relative to the storage root (``folder/file``); empty parts dropped."""
    return [p for p in str(name).replace("\\", "/").split("/") if p and p != "."]


def safe_route(route: Any) -> Optional[str]:
    """A server-relative path the printer named, or None when it is anything else (a full URL, a path
    with ``..``, odd characters): a download is only ever fetched from the host that was configured."""
    if not isinstance(route, str) or not _SAFE_ROUTE.fullmatch(route) or route.startswith("//"):
        return None
    if ".." in route.split("/") or len(route) > 1024:
        return None
    return route


def entry_from(raw: Dict[str, Any], folder: Sequence[str]) -> Dict[str, Any]:
    """One folder entry in the shape every host uses."""
    name = str(raw.get("name") or "")
    ftype = str(raw.get("type") or "")
    refs = raw.get("refs") if isinstance(raw.get("refs"), dict) else {}
    return {"name": name, "display_name": str(raw.get("display_name") or name),
            "kind": "folder" if ftype.upper() == "FOLDER" or "children" in raw else "file",
            "type": ftype or None, "size": _int_or_none(raw.get("size")),
            "modified": _int_or_none(raw.get("m_timestamp")), "path": "/".join(list(folder) + [name]),
            "download": safe_route(refs.get("download"))}


def match_entry(entries: Sequence[Dict[str, Any]], wanted: str, kind: str) -> Dict[str, Any]:
    """The one entry of ``kind`` that ``wanted`` names: its short name or its display name, exactly,
    then ignoring case. Several matches, or none, are an error that lists what could be meant."""
    pool = [e for e in entries if e["kind"] == kind]
    for tier in (lambda e, w: w in (e["name"], e["display_name"]),
                 lambda e, w: w.lower() in (e["name"].lower(), e["display_name"].lower())):
        hits = [e for e in pool if tier(e, wanted)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise HostError(f"{wanted!r} names {len(hits)} {kind}s here; use a short name: "
                            + ", ".join(e["name"] for e in hits))
    near = difflib.get_close_matches(wanted, [n for e in pool for n in (e["display_name"], e["name"])], n=3, cutoff=0.5)
    raise HostNotFound(f"no {kind} named {wanted!r} on the printer" + (f"; did you mean: {', '.join(near)}" if near else ""))


class PrusaLinkHost(PrinterHost):
    name = "prusalink"
    capabilities = frozenset(CAPABILITIES)
    network_function = "_http"
    setting_defaults = {"user": "maker"}

    # ---- the one network function ---------------------------------------------------------

    def _http(self, method: str, path: str, *, sink=None, accept: str = "application/json",
              limit: int = MAX_JSON) -> HostResponse:
        """Send one request and return the reply. This is the only method of the host that touches the
        network, and it only sends GET or HEAD: the check runs before anything is opened. A 200 reply
        is streamed into ``sink`` when one is given; any other body is read into memory (up to ``limit``)."""
        require_read_only(method)
        import http.client
        import socket
        import ssl
        if not _SAFE_PATH.fullmatch(path):
            raise HostError("refusing a request path with spaces or control characters")
        cfg = self.settings
        parts = urlsplit(cfg.url)
        target = parts.path + path
        if parts.scheme == "https":
            conn = http.client.HTTPSConnection(parts.hostname, parts.port, timeout=cfg.timeout,
                                               context=ssl.create_default_context())
        else:
            conn = http.client.HTTPConnection(parts.hostname, parts.port, timeout=cfg.timeout)
        where = f"{parts.hostname}:{parts.port or (443 if parts.scheme == 'https' else 80)}"

        def receive(resp, into, cap: int) -> HostResponse:
            """Read one reply: its headers, and its body into ``into`` (a 200 only) or into memory."""
            headers: Dict[str, str] = {}
            for key, value in resp.getheaders():
                key = key.lower()
                headers[key] = f"{headers[key]}, {value}" if key in headers else value
            out = HostResponse(resp.status, resp.reason or "", headers)
            if method == "HEAD":
                resp.read()                                  # no body, but the reply must be closed for the next request
                return out
            stream = into is not None and resp.status == 200
            chunks: List[bytes] = []
            total = 0
            while True:
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if stream:
                    try:
                        into.write(chunk)
                    except OSError as e:
                        raise HostError(f"cannot write the download: {e.strerror or e}") from None
                else:
                    if total > cap:
                        raise HostError(f"the reply is larger than {cap} bytes; not reading it")
                    chunks.append(chunk)
            declared = _int_or_none(headers.get("content-length"))
            if declared is not None and declared != total:
                raise HostError(f"incomplete reply: {total} of {declared} bytes arrived")
            out.body, out.bytes_read = b"".join(chunks), total
            return out

        headers = {"Accept": accept, "User-Agent": USER_AGENT}
        authorization = None
        try:
            for _ in range(ATTEMPTS):
                sent = dict(headers)
                if authorization:
                    sent["Authorization"] = authorization
                conn.request(method, target, headers=sent)
                resp = conn.getresponse()
                _log.debug("%s %s -> %s%s", method, path, resp.status, " (authenticated)" if authorization else "")
                if resp.status != 401:
                    return receive(resp, sink, limit)
                offered = resp.msg.get_all("WWW-Authenticate") or []
                receive(resp, None, CHUNK)                                  # drain it, so the connection can be reused
                challenges = digest.parse_challenges(offered)
                if authorization and not any(c.stale for c in challenges):
                    raise HostAuthError(f"the host rejected the credentials (from {cfg.source}); check the user "
                                        f"and password")
                if not challenges:
                    schemes = digest.offered_schemes(offered)
                    raise HostAuthError("the host asks for " + (", ".join(schemes) + " authentication"
                                                                if schemes else "authentication without naming a scheme")
                                        + "; agentcad speaks Digest only")
                try:
                    challenge = digest.choose(challenges)
                except digest.DigestError as e:
                    raise HostAuthError(str(e)) from None
                authorization = digest.authorization(challenge, method, target, cfg.user, cfg.password)
            raise HostAuthError("the host kept asking for authentication (stale nonces); try again")
        except (socket.timeout, TimeoutError):
            raise HostUnreachable(f"timed out after {cfg.timeout:g} s talking to {where}") from None
        except ssl.SSLError as e:
            raise HostUnreachable(f"TLS to {where} failed: {e.reason or e}") from None
        except OSError as e:
            raise HostUnreachable(f"cannot reach {where}: {e.strerror or type(e).__name__}") from None
        except http.client.IncompleteRead:
            raise HostError("incomplete reply: the connection closed before the end of the reply") from None
        except http.client.HTTPException as e:
            raise HostUnreachable(f"{where} sent a reply that is not HTTP ({type(e).__name__})") from None
        finally:
            conn.close()

    # ---- helpers that use it ---------------------------------------------------------------

    def _check(self, resp: HostResponse, path: str) -> None:
        if 200 <= resp.status < 300:
            return
        detail = f"HTTP {resp.status} {resp.reason}".strip()
        try:
            message = json.loads(resp.body.decode("utf-8")).get("message")
            if isinstance(message, str) and message.strip():
                detail += f": {re.sub(r'[^ -~]', '', message)[:200]}"
        except (ValueError, AttributeError, UnicodeDecodeError):
            pass
        if resp.status in (401, 403):
            raise HostAuthError(f"{path}: {detail}")
        if resp.status == 404:
            raise HostNotFound(f"{path}: {detail}")
        raise HostServerError(f"{path}: {detail}")

    def _get_json(self, path: str) -> Optional[Any]:
        resp = self._http("GET", path)
        self._check(resp, path)
        if resp.status == 204 or not resp.body.strip():
            return None
        try:
            return json.loads(resp.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise HostServerError(f"{path}: the reply is not JSON") from None

    def _folder(self, storage: str, folder: Sequence[str]) -> List[Dict[str, Any]]:
        """The entries of a folder, named by short names from the storage root."""
        route = "/api/v1/files/" + "/".join(quote(p, safe="~") for p in [storage] + list(folder)) + "/"
        data = self._get_json(route)
        children = data.get("children") if isinstance(data, dict) else None
        if not isinstance(children, list):
            raise HostServerError(f"{route}: the reply is not a folder listing")
        return [entry_from(c, folder) for c in children if isinstance(c, dict) and c.get("name")]

    def _walk(self, storage: str, parts: Sequence[str]) -> List[str]:
        """The short names of the folders ``parts`` name (each given by either of its names)."""
        short: List[str] = []
        for part in parts:
            short.append(match_entry(self._folder(storage, short), part, "folder")["name"])
        return short

    def _storage(self, storage: Optional[str]) -> str:
        return storage or self.settings.storage or DEFAULT_STORAGE

    # ---- capabilities ----------------------------------------------------------------------

    def list_printers(self) -> List[Dict[str, Any]]:
        try:
            info = self._get_json("/api/v1/info")
        except HostNotFound:                                  # an older firmware: the status still names the state
            info = None
        status = self._get_json("/api/v1/status")
        info = info if isinstance(info, dict) else {}
        printer = (status or {}).get("printer") if isinstance(status, dict) else None
        label = info.get("hostname") or info.get("name") or info.get("serial") or "printer"
        return [{"id": str(label), "name": str(info.get("name") or label), "host": self.name, "url": self.settings.url,
                 "state": (printer or {}).get("state"), "nozzle_mm": info.get("nozzle_diameter"),
                 "mmu": info.get("mmu"), "serial": info.get("serial")}]

    def list_files(self, path: str = "", storage: Optional[str] = None) -> Dict[str, Any]:
        storage = self._storage(storage)
        short = self._walk(storage, split_name(path))
        entries = self._folder(storage, short)
        entries.sort(key=lambda e: (-(e["modified"] or 0), e["name"]))
        return {"storage": storage, "path": "/".join(short), "entries": entries}

    def download_file(self, name: str, open_sink: OpenSink, storage: Optional[str] = None) -> Dict[str, Any]:
        storage = self._storage(storage)
        parts = split_name(name)
        if not parts:
            raise HostError("no file name given")
        folder = self._walk(storage, parts[:-1])
        entry = match_entry(self._folder(storage, folder), parts[-1], "file")
        route = entry["download"] or "/" + "/".join(quote(p, safe="~") for p in [storage] + folder + [entry["name"]])
        sink = open_sink(dict(entry, storage=storage))
        resp = self._http("GET", route, sink=sink, accept="*/*")
        self._check(resp, route)
        return {"storage": storage, "name": entry["name"], "display_name": entry["display_name"],
                "path": entry["path"], "download": route, "bytes": resp.bytes_read}

    def job_status(self) -> Dict[str, Any]:
        status = self._get_json("/api/v1/status")
        status = status if isinstance(status, dict) else {}
        try:
            job = self._get_json("/api/v1/job")
        except HostNotFound:                                  # no job route: the status may still carry the job
            job = None
        job = job if isinstance(job, dict) else (status.get("job") if isinstance(status.get("job"), dict) else None)
        printer = status.get("printer") if isinstance(status.get("printer"), dict) else {}
        record: Dict[str, Any] = {"host": self.name, "printer": {k: printer[k] for k in _PRINTER_FIELDS if k in printer},
                                  "job": None}
        if job:
            file = job.get("file") if isinstance(job.get("file"), dict) else {}
            record["job"] = {"id": job.get("id"), "state": job.get("state"), "progress": job.get("progress"),
                             "time_remaining": job.get("time_remaining"), "time_printing": job.get("time_printing"),
                             "file": {"name": file.get("name"), "display_name": file.get("display_name"),
                                      "path": file.get("path")} if file else None}
        storage = status.get("storage")
        if isinstance(storage, dict):
            record["storage"] = {k: storage[k] for k in ("name", "path", "read_only") if k in storage}
        return record
