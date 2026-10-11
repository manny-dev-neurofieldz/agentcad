"""``agentcad duties``: the work a library's or a project's records say is owed."""

import json
import sys
from datetime import date


def cmd_duties(args):
    from agentcad import duties as dutymod
    from agentcad import records as recmod

    try:
        as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    except ValueError:
        print(f"Error: --as-of {args.as_of!r} is not a date (YYYY-MM-DD)", file=sys.stderr)
        return 2
    try:
        found = recmod.load(args.path)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    if not (found.parts or found.jobs or found.fits):
        print(f"Error: no part, job or fit records under {args.path}", file=sys.stderr)
        return 2
    if found.errors():
        print(f"agentcad duties: {len(found.errors())} record error(s); what is owed is read from fields that do "
              f"not all read as their contract says (agentcad records check {args.path} lists them)", file=sys.stderr)
    owed = dutymod.derive(found, as_of)
    if args.json:
        print(json.dumps(dutymod.to_dict(owed, found, as_of), indent=2))
    else:
        print("\n".join(dutymod.summary(owed, found, as_of)))
    return 0


def register(subparsers, groups):
    p = subparsers.add_parser("duties", help="The work the records say is owed: verdicts to record, plans past "
                                             "their day, fits to re-run")
    p.add_argument("path", help="A library or project folder, or one part.toml, job.toml or *.print.json manifest")
    p.add_argument("--as-of", default=None, metavar="DATE",
                   help="Judge planned days against this date, YYYY-MM-DD (default: today)")
    p.add_argument("--json", action="store_true", help="Print the duties as JSON (schema agentcad.duties/1)")
    p.set_defaults(func=cmd_duties)
