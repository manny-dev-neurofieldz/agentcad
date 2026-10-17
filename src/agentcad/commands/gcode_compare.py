"""``agentcad gcode compare``: two sliced files side by side."""

import json
import sys

from agentcad.gcode import compare, sliced, supports


def cmd_gcode_compare(args):
    """Compare two sliced files: time, filament, layers, supports, objects and the settings that differ.

    Exit status 0 whenever both files were read (a comparison gives no verdict), 1 when one could not be."""
    loaded = []
    for label, name in (("A", args.a), ("B", args.b)):
        try:
            s = sliced.load(name)
            supports.contact_distance_from(s.config)     # a contact distance that is not one: cannot be read
            loaded.append(s)
        except (OSError, ValueError) as e:        # BGCodeError is a ValueError
            reason = e.strerror if isinstance(e, OSError) and e.strerror else e
            print(f"Error: cannot read {label} ({name}): {reason}", file=sys.stderr)
    if len(loaded) < 2:
        return 1
    for label, s in zip("AB", loaded):
        if not s.model.paths:
            print(f"Warning: {label} ({s.path}) has no extrusion in it; is it a sliced file?", file=sys.stderr)
    rec = compare.compare(loaded[0], loaded[1], min_area=args.min_area)
    if args.json:
        print(json.dumps(rec, indent=2))
    else:
        print("\n".join(compare.render_text(rec, all_settings=args.all_settings)))
    return 0


def register(subparsers, groups):
    from agentcad.cli import SLICED_FILE_HELP

    pg = groups["gcode"].add_parser(
        "compare", help="Two sliced files side by side: time, filament, layers, supports, objects, settings that differ")
    pg.add_argument("a", help=SLICED_FILE_HELP + " (the baseline)")
    pg.add_argument("b", help=SLICED_FILE_HELP + " (the one compared with A; every difference is B minus A)")
    pg.add_argument("--json", action="store_true",
                    help="Print the comparison record (schema agentcad.gcode.compare/1), every differing setting included")
    pg.add_argument("--all-settings", action="store_true",
                    help=f"List every differing setting, not the first {compare.SETTINGS_SHOWN}")
    pg.add_argument("--min-area", type=float, default=compare.DEFAULT_MIN_AREA,
                    help="Count only contact bands of at least this area in mm2 (default 1, as gcode supports; "
                         "smaller ones are reported apart)")
    pg.set_defaults(func=cmd_gcode_compare)
