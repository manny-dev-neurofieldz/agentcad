"""``agentcad printer``: read-only access to a printer host (printers, files, downloads, job status).

Every subcommand asks the host registry what the chosen host can do, so a new host needs no new
command. Exit status: 0 on success, 1 when the host could not be reached or refused the request,
2 for a request or configuration the command cannot act on (no credentials, an unsafe credentials
file, an unknown host or a capability the host lacks, a file that would be overwritten).
"""

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

DEFAULT_HOST = "prusalink"


class _Refused(Exception):
    """The destination cannot be written (it exists and --force was not given, or the folder is not writable)."""


def _fail(message, status):
    print(f"Error: {message}", file=sys.stderr)
    return status


def _run(args, capability, action):
    """Open the chosen host, check that it declares ``capability`` and run ``action(host)``. A host
    failure is one line on stderr and an exit status, never a traceback."""
    from agentcad import hosts

    try:
        host = hosts.get_host(getattr(args, "host", None) or DEFAULT_HOST)
    except ValueError as e:                       # an unknown host name
        return _fail(e, 2)
    try:
        host.require(capability)
        return action(host)
    except (hosts.NotSupported, hosts.HostConfigError, _Refused) as e:
        return _fail(e, 2)
    except hosts.HostError as e:
        return _fail(e, 1)


def _emit(args, schema, host, record, lines):
    """Print ``record`` as JSON (with its schema and host) or the text lines ``lines()`` builds."""
    if args.json:
        print(json.dumps(dict(schema=schema, host=host.name, **record), indent=2))
    else:
        for line in lines():
            print(line)
    return 0


def _clock(epoch):
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(epoch)) if epoch else "-"


def _size(n):
    if n is None:
        return "-"
    if n < 1024:
        return f"{n} B"
    for unit in ("KiB", "MiB", "GiB"):
        n /= 1024.0
        if n < 1024 or unit == "GiB":
            return f"{n:.1f} {unit}"


def cmd_printer_list(args):
    def lines(printers, host):
        yield f"{host.name}: {len(printers)} printer(s)"
        for p in printers:
            nozzle = f"  nozzle {p['nozzle_mm']:g} mm" if isinstance(p.get("nozzle_mm"), (int, float)) else ""
            yield f"  {p['id']}  {p.get('state') or 'state unknown'}{nozzle}  {p.get('url') or ''}".rstrip()

    def action(host):
        printers = host.list_printers()
        return _emit(args, "agentcad.printer.list/1", host, {"printers": printers}, lambda: lines(printers, host))
    return _run(args, "list_printers", action)


def cmd_printer_files(args):
    def lines(listing, shown):
        more = f", showing {len(shown)}" if len(shown) < len(listing["entries"]) else ""
        yield f"{listing['storage']}:/{listing['path']}: {len(listing['entries'])} item(s), newest first{more}"
        for e in shown:
            short = f"  [{e['name']}]" if e["name"] != e["display_name"] else ""
            yield f"  {_clock(e['modified'])}  {e['display_name']}{short}  " + (
                "(folder)" if e["kind"] == "folder" else _size(e["size"]))

    def action(host):
        listing = host.list_files(args.path or "", storage=args.storage)
        shown = listing["entries"][:args.limit] if args.limit and args.limit > 0 else listing["entries"]
        record = dict(listing, entries=shown, total=len(listing["entries"]))
        return _emit(args, "agentcad.printer.files/1", host, record, lambda: lines(listing, shown))
    return _run(args, "list_files", action)


class _HashingFile:
    """A file that keeps a SHA-256 of what is written to it."""

    def __init__(self, handle):
        self.handle, self.digest = handle, hashlib.sha256()

    def write(self, data):
        self.digest.update(data)
        return self.handle.write(data)


def _local_name(display_name, fallback):
    """A safe file name for a name the printer chose: its last path component, no control characters."""
    name = os.path.basename(str(display_name).replace("\\", "/"))
    name = "".join(c for c in name if c >= " " and c != "\x7f").strip()
    return name if name not in ("", ".", "..") else fallback


def cmd_printer_get(args):
    got = {}

    def open_sink(entry):
        local = _local_name(entry["display_name"], entry["name"])
        asked = args.output
        if asked is None:
            dest = Path.cwd() / local
        elif asked.endswith(("/", os.sep)) or Path(asked).is_dir():
            dest = Path(asked) / local
        else:
            dest = Path(asked)
        dest = dest.absolute()
        if dest.exists() and not args.force:
            raise _Refused(f"{dest} exists; use --force to replace it")
        part = dest.with_name(dest.name + ".part")
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            handle = open(part, "wb")
        except OSError as e:
            raise _Refused(f"cannot write {dest}: {e.strerror or e}") from None
        got.update(dest=dest, part=part, handle=handle, hashing=_HashingFile(handle))
        return got["hashing"]

    def discard():
        """Never leave a truncated file that looks finished."""
        if "handle" in got:
            got["handle"].close()
            got["part"].unlink(missing_ok=True)

    def action(host):
        try:
            info = host.download_file(args.name, open_sink, storage=args.storage)
            got["handle"].close()
            os.replace(got["part"], got["dest"])
        except OSError as e:
            discard()
            raise _Refused(f"cannot write {got.get('dest', args.output)}: {e.strerror or e}") from None
        except BaseException:
            discard()
            raise
        record = dict(info, output=str(got["dest"]), sha256=got["hashing"].digest.hexdigest())
        return _emit(args, "agentcad.printer.get/1", host, record, lambda: [
            f"downloaded {info['display_name']} [{info['name']}] -> {got['dest']}: "
            f"{info['bytes']} bytes, sha256 {record['sha256']}"])
    return _run(args, "download_file", action)


def cmd_printer_status(args):
    def lines(status, host):
        p = status.get("printer", {})
        yield f"{host.name}: {p.get('state', 'state unknown')}"
        temps = [f"{label} {p[key]:g}/{p[target]:g} C" for label, key, target in
                 (("nozzle", "temp_nozzle", "target_nozzle"), ("bed", "temp_bed", "target_bed"))
                 if isinstance(p.get(key), (int, float)) and isinstance(p.get(target), (int, float))]
        if temps:
            yield "  " + ", ".join(temps)
        job = status.get("job")
        if not job:
            yield "  no job"
            return
        file = job.get("file") or {}
        bits = [f"{job['progress']:g}%"] if isinstance(job.get("progress"), (int, float)) else []
        if isinstance(job.get("time_remaining"), (int, float)):
            bits.append(f"{int(job['time_remaining'] // 60)} min left")
        yield f"  job {job.get('id', '?')}: {file.get('display_name') or file.get('name') or 'unnamed'}" + (
            f", {', '.join(bits)}" if bits else "")

    def action(host):
        status = host.job_status()
        record = {k: v for k, v in status.items() if k != "host"}
        return _emit(args, "agentcad.printer.status/1", host, record, lambda: lines(status, host))
    return _run(args, "job_status", action)


def register(subparsers, groups):
    from agentcad import hosts

    def add_host(parser, default):
        parser.add_argument("--host", metavar="NAME", default=default,
                            help=f"Printer host to use (registered: {', '.join(hosts.list_hosts()) or 'none'}; "
                                 f"default {DEFAULT_HOST})")

    group = subparsers.add_parser(
        "printer", help="Read-only access to a printer host: printers, files, downloads, job status "
                        "(machine specifications are under 'printers')")
    add_host(group, None)
    group.set_defaults(func=lambda args: _fail("name a subcommand: list, files, get or status", 2))
    sub = group.add_subparsers(dest="printer_command")
    groups["printer"] = sub

    p = sub.add_parser("list", help="The printers the host knows, with their state")
    add_host(p, argparse.SUPPRESS)
    p.add_argument("--json", action="store_true", help="Print the printers as JSON (schema agentcad.printer.list/1)")
    p.set_defaults(func=cmd_printer_list)

    p = sub.add_parser("files", help="The files on the printer's storage, newest first, with both names")
    add_host(p, argparse.SUPPRESS)
    p.add_argument("path", nargs="?", default="", help="Folder to list, relative to the storage root (default: the root)")
    p.add_argument("--storage", default=None, help="Storage to read (default: the host's; usb on PrusaLink)")
    p.add_argument("--limit", type=int, default=0, metavar="N", help="Show only the newest N entries (default: all)")
    p.add_argument("--json", action="store_true", help="Print the listing as JSON (schema agentcad.printer.files/1)")
    p.set_defaults(func=cmd_printer_files)

    p = sub.add_parser("get", help="Download one file from the printer, found by its short name or its display name")
    add_host(p, argparse.SUPPRESS)
    p.add_argument("name", help="The file: its short (8.3) name or its display name, with folders as folder/file")
    p.add_argument("-o", "--output", default=None, metavar="PATH",
                   help="Where to write it: a file path, or a folder (an existing one, or a path ending in /) to keep "
                        "the display name (default: the display name in the current folder)")
    p.add_argument("--storage", default=None, help="Storage to read (default: the host's; usb on PrusaLink)")
    p.add_argument("--force", action="store_true", help="Replace the output file if it exists")
    p.add_argument("--json", action="store_true", help="Print the result as JSON (schema agentcad.printer.get/1)")
    p.set_defaults(func=cmd_printer_get)

    p = sub.add_parser("status", help="What the printer is doing: state, temperatures and the running job")
    add_host(p, argparse.SUPPRESS)
    p.add_argument("--json", action="store_true", help="Print the status as JSON (schema agentcad.printer.status/1)")
    p.set_defaults(func=cmd_printer_status)
