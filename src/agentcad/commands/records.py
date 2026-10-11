"""``agentcad records check``: read a library's or a project's records and check their structured fields."""

import sys


def _fail(message, status):
    print(f"Error: {message}", file=sys.stderr)
    return status


def cmd_records_check(args):
    from agentcad import records as recmod

    try:
        found = recmod.load(args.path)
    except (FileNotFoundError, ValueError) as e:
        return _fail(str(e), 2)
    if not (found.parts or found.jobs or found.fits):
        return _fail(f"no part, job or fit records under {args.path}", 2)
    if args.json:
        print(found.to_json())
    else:
        print("\n".join(recmod.summary(found)))
    return 1 if found.errors() else 0


def register(subparsers, groups):
    group = subparsers.add_parser(
        "records", help="Part, job and fit records: read them and check their structured fields")
    group.set_defaults(func=lambda args: _fail("name a subcommand: check", 2))
    sub = group.add_subparsers(dest="records_command")
    groups["records"] = sub

    p = sub.add_parser("check", help="Check every record under a library or project folder, or one record file")
    p.add_argument("path", help="A library or project folder, or one part.toml, job.toml or *.print.json manifest")
    p.add_argument("--json", action="store_true",
                   help="Print what was read and every problem as JSON (schema agentcad.records/1)")
    p.set_defaults(func=cmd_records_check)
