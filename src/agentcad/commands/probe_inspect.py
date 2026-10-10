"""``agentcad probe rays`` and ``agentcad probe knobs``: what a part is made of along lines, and which
parameters of its program matter.

The commands here sit under the ``probe`` group beside the recover probes and
share their conventions: a source (build123d program, STEP file, or for rays an
STL mesh), ``-D VAR=VAL`` parameter overrides, ``-o`` for the JSON record, and
every cap an instrument applies printed with its value.
"""

import sys
from pathlib import Path


def cmd_probe_rays(args):
    """Intervals of material and void along lines and fans through a solid."""
    from agentcad import probe, rays
    from agentcad.cli import _parse_defines

    lines = []
    try:
        for n, spec in enumerate(args.line or [], 1):
            lines.append(rays.parse_line(spec, label=f"L{n}"))
        for n, spec in enumerate(args.fan or [], 1):
            lines.extend(rays.parse_fan(spec, label=f"F{n}"))
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    if not lines:
        print("Error: give at least one --line or --fan (agentcad policy read probe-inspect shows the forms)", file=sys.stderr)
        return 2
    try:
        res = rays.probe_rays(Path(args.source), lines, defines=_parse_defines(args.define) if args.define else None,
                              length=args.length)
    except (ValueError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print("\n".join(rays.render_rays(res, show=args.show)))
    if args.output:
        print(f"rays.json: {probe.write_json(res, Path(args.output))}")
    return 0


def cmd_probe_knobs(args):
    """Which parameters of a program change the part: base, plus and minus a delta per knob."""
    from agentcad import knobs, probe
    from agentcad.cli import _parse_defines

    if not args.knob:
        print("Error: give at least one --knob NAME=DELTA (agentcad policy read probe-inspect shows the forms)", file=sys.stderr)
        return 2
    try:
        res = knobs.knob_sweep(Path(args.source), args.knob, defines=_parse_defines(args.define) if args.define else None)
    except (ValueError, RuntimeError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2 if isinstance(e, ValueError) else 1
    print("\n".join(knobs.render_knobs(res)))
    if args.output:
        print(f"knobs.json: {probe.write_json(res, Path(args.output))}")
    return 0


def register(subparsers, groups):
    from agentcad.cli import DEFINE_HELP, SIGNED_NUMBER_LIST

    sub = groups["probe"]
    pr = sub.add_parser("rays", help="Material and void intervals along lines and radial fans: wall thickness, bore depth, gaps")
    pr._negative_number_matcher = SIGNED_NUMBER_LIST      # --line -30,0,0:1,0,0 and --fan -5,0,0:0,0,1:30
    pr.add_argument("source", help="build123d program, STEP file (exact) or STL mesh (to its tessellation)")
    pr.add_argument("--line", action="append", metavar="X,Y,Z:DX,DY,DZ[:LEN]",
                    help="A line from a start point along a direction, optionally LEN mm long (repeatable)")
    pr.add_argument("--fan", action="append", metavar="X,Y,Z:AX,AY,AZ:STEP[:FROM[:TO]]",
                    help="Lines leaving the point X,Y,Z on the axis along AX,AY,AZ, square to it, every STEP degrees "
                         "(from FROM to TO; default a full turn) (repeatable)")
    pr.add_argument("--length", type=float, default=None,
                    help="Follow each line this far from its start (default: through the part's bounding box)")
    pr.add_argument("--show", type=int, default=12, help="Intervals to print per line (default 12; the JSON has all)")
    pr.add_argument("-o", "--output", default=None, help="Write the JSON record here (schema agentcad.probe.rays/1)")
    pr.add_argument("-D", "--define", action="append", metavar="VAR=VAL", help=DEFINE_HELP)
    pr.set_defaults(func=cmd_probe_rays)

    pk = sub.add_parser("knobs", help="Which parameters of a program matter: base, plus and minus a delta per knob; flags saturated and dead knobs")
    pk.add_argument("source", help="build123d program defining build(**params)")
    pk.add_argument("--knob", action="append", metavar="NAME=DELTA", help="A parameter to move by DELTA, or by NAME=P%% of its base (repeatable; two builds each)")
    pk.add_argument("-o", "--output", default=None, help="Write the JSON record here (schema agentcad.probe.knobs/1)")
    pk.add_argument("-D", "--define", action="append", metavar="VAR=VAL", help="Move the base: override a parameter before the sweep (repeatable)")
    pk.set_defaults(func=cmd_probe_knobs)
