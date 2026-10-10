"""``agentcad probe sketches``: the sketches, parameters and timeline of a design dump, in millimetres,
every dimension labelled DRAWN and, against a part, APPLIED where the part's section carries it.

Registered as a command module under the ``probe`` group, so cli.py is not edited. The dump is read with
the standard library alone; ``--against`` needs the build123d backend and says so when it is missing.
"""

import sys
from pathlib import Path

DEFAULT_TOL = 0.01      # mm


def cmd_probe_sketches(args):
    """Print a design dump's sketches in mm with their labels; with --against, also what the part applies."""
    from agentcad import probe, sketches

    try:
        record = sketches.describe(sketches.load_dump(Path(args.dump)), args.sketch)
        if args.against:
            sketches.apply_part(record, Path(args.against), args.tol)
    except sketches.DumpError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print("\n".join(sketches.render(record)))
    for note in record["notes"]:
        print(f"note: {note}", file=sys.stderr)
    if args.output:
        print(f"sketches.json: {probe.write_json(record, Path(args.output))}")


def register(subparsers, groups):
    p = groups["probe"].add_parser(
        "sketches", help="DRAWN vs APPLIED: a design dump's sketches in mm with construction flags, parameters, timeline")
    p.add_argument("dump", help="Design dump (JSON with sketches, parameters and timeline; geometry in cm)")
    p.add_argument("--sketch", default=None, metavar="NAME",
                   help="Only the sketches whose name contains NAME (ignoring case)")
    p.add_argument("--against", default=None, metavar="PART",
                   help="STEP file or build123d program: label a dimension APPLIED when its section on the sketch plane carries it "
                        "(needs the build123d backend)")
    p.add_argument("--tol", type=float, default=DEFAULT_TOL, metavar="MM",
                   help="With --against: how close a section's radius or length must be to a drawn one (default 0.01)")
    p.add_argument("-o", "--output", default=None, help="Write the record (all dimensions and labels) here as JSON")
    p.set_defaults(func=cmd_probe_sketches)
