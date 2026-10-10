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
        print(f"Error: {e}", file=sys.stderr)
        return 2
    if "write_job" not in target.capabilities:
        print(f"Error: target {target.name!r} does not write a job (its capabilities: "
              f"{', '.join(sorted(target.capabilities)) or 'none'})", file=sys.stderr)
        return 2
    qs = qcmod.settings(cfg) or qcmod.QCSettings()
    printer = qcmod.printer_for(cfg, qs)
    centre = (printer.build_volume[0] / 2.0, printer.build_volume[1] / 2.0)
    folders = cfg.part_projects() or [(Path(cfg.project_dir), cfg)]
    parts, y_next = [], None
    for folder, part_cfg in folders:
        try:
            session = DesignSession.load_state(Path(folder).name, engine=_engine_for(None, part_cfg), config=part_cfg)
        except (FileNotFoundError, ValueError) as e:
            print(f"Error: {e}", file=sys.stderr)
            return 2
        it = session.iterations[-1] if session.iterations else None
        stl = session.project.exports_dir / f"{session.name}_v{it.number}.stl" if it else None
        if stl is None or not stl.is_file():
            print(f"Error: {session.name} has no export of its latest iteration: finalize it first", file=sys.stderr)
            return 2
        part_qc = qcmod.settings(part_cfg) or qs
        V, _ = read_stl(stl)
        T, extent = bed_transform(V, part_qc.pose if part_qc.pose is not None else qs.pose, centre)
        if y_next is not None:                       # the next part in a row along y
            T[1][3] += y_next
        y_next = (y_next or 0.0) + float(extent[1]) + GAP_MM
        copies = args.copies if args.copies else int(part_cfg.quantity or 1)
        parts.append(targets.JobPart(session.name, stl, copies=copies, transform=T))
    native, conflicts = targets.native_settings(cfg, target.name)
    job = targets.Job(name, parts, intent=dict(cfg.print_intent), native=native)
    out_dir = Path(args.output) if args.output else Path(cfg.project_dir) / "exports" / f"stage_{target.name}"
    written = target.write_job(job, out_dir)
    print(f"staged {name} for {target.name} on {printer.label}: {len(parts)} part(s), "
          f"{sum(p.copies for p in parts)} instance(s)")
    for path in written:
        print(f"  {path}")
    for c in conflicts:
        print(f"  conflict: {c}")
    return 0


def register(subparsers, groups):
    p = subparsers.add_parser("stage", help="Write a finalized project's parts, posed and placed, for an output target")
    p.add_argument("project", help="Project name (folder under designs_dir) or path; an assembly stages its parts")
    p.add_argument("--target", required=True, help="Output target name (see agentcad targets)")
    p.add_argument("-o", "--output", default=None, help="Folder for the staged files (default: exports/stage_<target>)")
    p.add_argument("--copies", type=int, default=None,
                   help="Copies of each part (default: each part's [project] quantity)")
    p.set_defaults(func=cmd_stage)
