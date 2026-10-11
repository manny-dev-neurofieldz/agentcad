"""``agentcad qc`` and ``agentcad printers``: design rules judged before a print, and the
printers they are judged against."""

import json
import sys
from pathlib import Path


def _print_report(name, report):
    p = report["printer"]
    pose = report["pose"]
    stated = f"matrix {pose['matrix']}" if pose.get("matrix") else f"up {pose.get('up', [0, 0, 1])}, spin {pose.get('spin_deg', 0)}"
    print(f"{name} v{report['iteration']} against {p['label']} ({p['name']}, {p['process']}, "
          f"{' x '.join(f'{v:g}' for v in p['build_volume'])} mm; {p['source']}); "
          f"pose {stated} ({report.get('pose_from', '[qc] pose')})")
    for f in report["findings"]:
        print(f"  {f['severity'].upper() if f['severity'] == 'error' else f['severity']}: {f['rule']}: "
              f"{f['sentence']} (limit: {f['layer']})")
    for s in report.get("suppressed", []):
        print(f"  suppressed: {s['rule']} at {s['source']}, because {s['why']}: {s['finding']}")
    for item in report.get("loosened", []):
        print(f"  loosened: {item['limit']} {item['value']:g} (from {item['below']:g}) for {item['feature']!r} at "
              f"{item['source']}" + (f", because {item['why']}" if item["why"] else ", with no reason given"))
    print("  limits: " + ", ".join(f"{k} {v['value']:g} ({v['layer']})" for k, v in report["limits"].items()))
    if report.get("resolution"):
        from agentcad.qc import mm_text
        r = report["resolution"]
        made = [f"voxel {r['voxel_mm']:g} mm"] if r.get("voxel_mm") is not None else []
        made += [f"stride {r['stride']}"] if r.get("stride") is not None else []
        print(f"  mesh resolution: {mm_text(r['mm'])}" + (f" ({' x '.join(made)})" if made else "") +
              "; a width is read only where the mesh resolves at most half its limit")
    if report["not_measured"]:
        print("  not measured: " + "; ".join(f"{k} ({why})" for k, why in report["not_measured"].items()))
    errors = sum(f["severity"] == "error" for f in report["findings"])
    warnings = sum(f["severity"] == "warning" for f in report["findings"])
    print(f"qc: {errors} error(s), {warnings} warning(s)" + ("; the gate is on" if report.get("gate") else ""))


def cmd_qc(args):
    from agentcad import qc as qcmod
    from agentcad.cli import _engine_for, _resolve_project
    from agentcad.session import DesignSession

    cfg, _, project_name = _resolve_project(args.project)
    try:
        qs = qcmod.settings(cfg) or qcmod.QCSettings()
        session = DesignSession.load_state(project_name, engine=_engine_for(None, cfg), config=cfg)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    if not session.iterations:
        print(f"Error: {project_name} has no iteration to judge", file=sys.stderr)
        return 2
    it = session.iterations[-1]
    stl = session.project.exports_dir / f"{session.name}_v{it.number}.stl"
    mesh_md = it.metadata           # what the engine said about the mesh judged: the iteration's, or the fresh export's
    if not stl.is_file():           # not finalized yet: export the latest iteration for QC alone
        stl = Path(it.source_path).parent / f"{session.name}_v{it.number}_qc.stl"
        result = session.engine.export(it.source_path, stl, fmt="stl", defines=it.defines or session.defines or None)
        if not result.success:
            print(f"agentcad qc: no mesh of v{it.number} ({'; '.join(result.errors)}); nothing measured", file=sys.stderr)
            stl = None
        else:
            mesh_md = result.metadata       # made now, with today's settings: its resolution is the one to judge by
    try:
        report = qcmod.run(cfg, stl, qs, printer_override=args.printer, annotations=it.metadata.get("qc_annotations"),
                           origin_of={str(it.source_path): it.origin} if it.origin else None,
                           resolution_mm=mesh_md.get("resolution_mm"), grid=qcmod.mesh_facts(mesh_md))
    except (KeyError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    report.update(iteration=it.number, mesh=str(stl) if stl else None)
    if getattr(args, "fixes", False):
        src = Path(it.source_path) if it.source_path else None
        if session.engine.name != "build123d":
            # a VoxelCAD program is a .py file too, and the sweep would rebuild it with build123d
            print(f"agentcad qc: --fixes turns the knobs of a build123d program; this project's engine is "
                  f"{session.engine.name}", file=sys.stderr)
        elif src is None or src.suffix.lower() != ".py":
            print("agentcad qc: --fixes turns the knobs of a build123d program; this iteration has none", file=sys.stderr)
        else:
            layer = float(getattr(getattr(cfg, "print", None), "layer_height", 0.2) or 0.2)
            try:
                runs = getattr(args, "max_runs", None)
                report["sensitivity"] = qcmod.sensitivity(report, src, it.defines or session.defines or None,
                                                          max_runs=16 if runs is None else runs, layer=layer)
            except (ValueError, RuntimeError) as e:
                print(f"agentcad qc: no fixes measured: {e}", file=sys.stderr)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_report(session.name, report)
    return 1 if qcmod.errors(report) else 0


def cmd_printers(args):
    from agentcad import printers
    from agentcad.config import ProjectConfig

    cfg = ProjectConfig.discover(Path.cwd())
    reg = printers.registry(cfg)
    if args.json:
        print(json.dumps([p.to_dict() for p in reg.values()], indent=2))
        return 0
    for p in reg.values():
        nozzle = f", {p.nozzle_mm:g} mm nozzle" if p.nozzle_mm else ""
        print(f"{p.name:<10} {p.label} ({p.process}{nozzle}), {' x '.join(f'{v:g}' for v in p.build_volume)} mm; "
              f"{p.source}")
    return 0


def register(subparsers, groups):
    from agentcad.cli import _requires        # here, not at import: the CLI imports this module

    pq = subparsers.add_parser("qc", help="Judge a project's latest iteration against its printer's design rules")
    pq.add_argument("project", help="Project name (folder under designs_dir) or path")
    pq.add_argument("--printer", default=None, help="Judge against this printer instead of the project's")
    pq.add_argument("--json", action="store_true", help="Print the report as JSON")
    pq.add_argument("--fixes", action="store_true",
                    help="For each error a feature claims, turn the knobs the feature names and say what each does "
                         "(build123d projects only)")
    pq.add_argument("--max-runs", type=int, default=None, metavar="N",
                    help="Rebuilds --fixes may make, the base included (default 16)")
    _requires(pq, "--max-runs", "--fixes")      # None until given, so the default never counts as given
    pq.set_defaults(func=cmd_qc)

    pp = subparsers.add_parser("printers", help="The printers QC knows: process, build volume, nozzle, defaults")
    pp.add_argument("--json", action="store_true", help="Print the registry as JSON, with each printer's defaults")
    pp.set_defaults(func=cmd_printers)
