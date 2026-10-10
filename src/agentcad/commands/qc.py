"""``agentcad qc`` and ``agentcad printers``: design rules judged before a print, and the
printers they are judged against."""

import json
import sys
from pathlib import Path


def _print_report(name, report):
    p = report["printer"]
    pose = report["pose"]
    print(f"{name} v{report['iteration']} against {p['label']} ({p['name']}, {p['process']}, "
          f"{' x '.join(f'{v:g}' for v in p['build_volume'])} mm; {p['source']}); "
          f"pose up {pose.get('up', [0, 0, 1])}, spin {pose.get('spin_deg', 0)}")
    for f in report["findings"]:
        print(f"  {f['severity'].upper() if f['severity'] == 'error' else f['severity']}: {f['rule']}: "
              f"{f['sentence']} (limit: {f['layer']})")
    print("  limits: " + ", ".join(f"{k} {v['value']:g} ({v['layer']})" for k, v in report["limits"].items()))
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
    if not stl.is_file():           # not finalized yet: export the latest iteration for QC alone
        stl = Path(it.source_path).parent / f"{session.name}_v{it.number}_qc.stl"
        result = session.engine.export(it.source_path, stl, fmt="stl", defines=it.defines or session.defines or None)
        if not result.success:
            print(f"agentcad qc: no mesh of v{it.number} ({'; '.join(result.errors)}); nothing measured", file=sys.stderr)
            stl = None
    try:
        report = qcmod.run(cfg, stl, qs, printer_override=args.printer)
    except (KeyError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    report.update(iteration=it.number, mesh=str(stl) if stl else None)
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
    pq = subparsers.add_parser("qc", help="Judge a project's latest iteration against its printer's design rules")
    pq.add_argument("project", help="Project name (folder under designs_dir) or path")
    pq.add_argument("--printer", default=None, help="Judge against this printer instead of the project's")
    pq.add_argument("--json", action="store_true", help="Print the report as JSON")
    pq.set_defaults(func=cmd_qc)

    pp = subparsers.add_parser("printers", help="The printers QC knows: process, build volume, nozzle, defaults")
    pp.add_argument("--json", action="store_true", help="Print the registry as JSON, with each printer's defaults")
    pp.set_defaults(func=cmd_printers)
