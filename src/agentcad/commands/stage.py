"""``agentcad stage``: a finalized project's parts, posed and placed on the bed, written by an
output target."""

import sys
from pathlib import Path

GAP_MM = 10.0          # between parts of an assembly, laid out along y


def bed_transform(points, pose, bed_centre):
    """The model-to-bed transform: the print pose, then the part centred on the bed in x and y with
    its lowest point at z = 0. Returns (row-major 4x4, posed extent)."""
    import numpy as np
    from agentcad import qc as qcmod
    R = qcmod.pose_rotation(pose)
    P = np.asarray(points, dtype=float) @ R.T
    lo, hi = P.min(axis=0), P.max(axis=0)
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = [bed_centre[0] - (lo[0] + hi[0]) / 2.0, bed_centre[1] - (lo[1] + hi[1]) / 2.0, -lo[2]]
    return T.tolist(), (hi - lo)


def _refuse(message):
    print(f"Error: {message}", file=sys.stderr)
    return 2


def _size(printer):
    return " x ".join(f"{v:g}" for v in printer.build_volume) + " mm"


def _differs(printer, other):
    """Which of the build volume's dimensions differ between two printers, as the note prints them."""
    names = [n for n, a, b in zip(("width", "depth", "height"), printer.build_volume, other.build_volume)
             if f"{a:g}" != f"{b:g}"]
    said = ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else "".join(names)
    return f"whose {said} {'differ' if len(names) > 1 else 'differs'}"


def cmd_stage(args):
    from agentcad import qc as qcmod
    from agentcad import targets
    from agentcad.cli import _engine_for, _resolve_project
    from agentcad.meshmeasure import read_stl
    from agentcad.session import DesignSession

    cfg, _, name = _resolve_project(args.project)
    try:
        target = targets.get_target(args.target)
    except ValueError as e:
        return _refuse(e)
    if "write_job" not in target.capabilities:
        return _refuse(f"target {target.name!r} does not write a job (its capabilities: "
                       f"{', '.join(sorted(target.capabilities)) or 'none'})")
    if args.slice and "slice" not in target.capabilities:
        return _refuse(f"target {target.name!r} does not slice (its capabilities: "
                       f"{', '.join(sorted(target.capabilities))}); stage without --slice and slice the project "
                       f"in the slicer")
    if args.slice and not target.available():
        return _refuse(f"{target.unavailable_reason()}; nothing was staged (stage without --slice to write the "
                       f"project alone)")
    if args.base_config and "base_config" not in target.job_options:
        return _refuse(f"target {target.name!r} takes no base configuration (--base-config); it starts from "
                       f"nothing the user supplies")
    intent = dict(cfg.print_intent)
    mapped, unmapped = {}, []
    if "map_intent" in target.capabilities:
        try:
            mapped, unmapped = target.map_intent(intent)
        except targets.TargetError as e:
            return _refuse(e)
    qs = qcmod.settings(cfg) or qcmod.QCSettings()
    qc_printer = qcmod.printer_for(cfg, qs)
    options = {"base_config": Path(args.base_config)} if args.base_config else {}
    folders = cfg.part_projects() or [(Path(cfg.project_dir), cfg)]
    finalized = []                                  # the parts first: "finalize it first" before any target setting
    for folder, part_cfg in folders:
        try:
            session = DesignSession.load_state(Path(folder).name, engine=_engine_for(None, part_cfg), config=part_cfg)
        except (FileNotFoundError, ValueError) as e:
            return _refuse(e)
        it = session.iterations[-1] if session.iterations else None
        stl = session.project.exports_dir / f"{session.name}_v{it.number}.stl" if it else None
        if stl is None or not stl.is_file():
            return _refuse(f"{session.name} has no export of its latest iteration: finalize it first")
        finalized.append((session.name, stl, part_cfg))
    try:
        printer = target.job_printer(options)       # the bed the target will check, when it has one of its own
    except targets.TargetError as e:
        return _refuse(e)
    bed_from = f"its bed from {printer.source}" if printer else "the QC printer's bed"
    printer = printer or qc_printer
    centre = printer.bed_centre()
    parts, y_next = [], None
    for part_name, stl, part_cfg in finalized:
        part_qc = qcmod.settings(part_cfg) or qs
        V, _ = read_stl(stl)
        T, extent = bed_transform(V, part_qc.pose if part_qc.pose is not None else qs.pose, centre)
        if y_next is not None:                       # the next part in a row along y
            T[1][3] += y_next
        y_next = (y_next or 0.0) + float(extent[1]) + GAP_MM
        copies = args.copies if args.copies else int(part_cfg.quantity or 1)
        parts.append(targets.JobPart(part_name, stl, copies=copies, transform=T))
    native = targets.native_tables(cfg, target.name)
    _, conflicts = targets.layer_native(mapped, native)
    job = targets.Job(name, parts, intent=intent, native=native, options=options)
    out_dir = Path(args.output) if args.output else Path(cfg.project_dir) / "exports" / f"stage_{target.name}"
    try:
        written = target.write_job(job, out_dir)
    except targets.TargetError as e:
        return _refuse(e)
    print(f"staged {name} for {target.name} on {printer.label} ({bed_from}): {len(parts)} part(s), "
          f"{sum(p.copies for p in parts)} instance(s)")
    for path in written:
        print(f"  {path}")
    for note in getattr(written, "notes", ()):
        print(f"  note: {note}")
    if printer is not qc_printer and _size(printer) != _size(qc_printer):
        print(f"  note: QC judged the parts against {qc_printer.label} ({_size(qc_printer)}); they are placed on "
              f"{printer.label} ({_size(printer)}), {_differs(printer, qc_printer)}")
    for c in conflicts:
        print(f"  conflict: {c}")
    for u in unmapped:
        print(f"  not mapped: {u}")
    if args.slice:
        return _slice_and_read(target, written, out_dir, cfg)
    return 0


def _slice_and_read(target, written, out_dir, cfg):
    """Slice the staged project headless, then read what came out as gcode check and gcode supports would:
    the settings against the project's intent (exit 1 on an error), and where supports touch the parts."""
    from argparse import Namespace
    from agentcad import targets
    from agentcad.cli import _supports_read, _supports_report, cmd_gcode_check

    project = next((Path(p) for p in written if Path(p).suffix == ".3mf"), Path(written[0]))
    sidecar = next((Path(p) for p in written if str(p).endswith(".placement.json")), None)
    try:
        sliced = target.slice(project, out_dir)
    except targets.TargetError as e:
        return _refuse(e)
    print(f"sliced: {sliced}")
    checked = cmd_gcode_check(Namespace(file=str(sliced), project=str(cfg.project_dir), intent=None, json=False))
    # Where supports touch is advisory: a contact in a cavity is printed, not counted. A support map that cannot
    # be read at all is counted, so exit 0 still means everything that was sliced was read. Only the reading is
    # caught: a failure in the analysis after it is a bug, and surfaces as one.
    args = Namespace(file=str(sliced), contact_distance=None, min_area=1.0,
                     placement=str(sidecar) if sidecar else None, stl_root=None, png=None, json=False)
    try:
        read = _supports_read(args)
    except (OSError, ValueError) as e:              # a BGCodeError is a ValueError
        print(f"Error: the support map of {sliced} could not be read: {e}", file=sys.stderr)
        return 1
    _supports_report(args, read)
    return checked or 0


def register(subparsers, groups):
    p = subparsers.add_parser("stage", help="Write a finalized project's parts, posed and placed, for an output target")
    p.add_argument("project", help="Project name (folder under designs_dir) or path; an assembly stages its parts")
    p.add_argument("--target", required=True, help="Output target name (see agentcad targets)")
    p.add_argument("-o", "--output", default=None, help="Folder for the staged files (default: exports/stage_<target>)")
    p.add_argument("--copies", type=int, default=None,
                   help="Copies of each part (default: each part's [project] quantity)")
    p.add_argument("--base-config", default=None,
                   help="Complete configuration a slicer target starts from: an exported .ini, a project 3MF or a "
                        "sliced .gcode/.bgcode (default: the target's entry in targets.toml in the agentcad user "
                        "config folder)")
    p.add_argument("--slice", action="store_true",
                   help="Also slice the staged project headless (targets that slice; see agentcad targets), then "
                        "check its settings against the intent and map where supports touch; exit 1 on a settings "
                        "error")
    p.set_defaults(func=cmd_stage)
