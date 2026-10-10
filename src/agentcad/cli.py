"""AgentCAD command-line interface."""

import argparse
import importlib
import json
import pkgutil
import sys
from pathlib import Path

from agentcad import __version__
from agentcad.camera import MULTI_VIEW_DEFAULT, STANDARD_PRESETS


def _parse_defines(define_list):
    """Parse ['-D', 'key=value', ...] into a dict."""
    defines = {}
    for d in define_list:
        if "=" in d:
            k, v = d.split("=", 1)
            defines[k] = v
    return defines


def _engine_for(engine_name, cfg):
    """Resolve the engine: explicit flag, else the project config, else openscad.

    Settings come from the config's ``[engine.<name>]`` table when a config is
    present, so a project's tuning reaches the engine on every command path.
    """
    from agentcad.engines import get_engine

    name = engine_name or (cfg.engine if cfg else None) or "openscad"
    settings = cfg.engine_settings(name) if cfg else None
    return get_engine(name, settings=settings)


def cmd_render(args):
    """Render a CAD source file to PNG images."""
    from agentcad.config import ProjectConfig

    source = Path(args.source_file)
    if not source.exists():
        print(f"Error: File not found: {source}", file=sys.stderr)
        sys.exit(1)

    cfg = ProjectConfig.discover(source.parent)
    engine = _engine_for(args.engine, cfg)
    if not engine.available():
        print(f"Error: {engine.name} is not available.", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir) if args.output_dir else source.parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    views = args.views if args.views else MULTI_VIEW_DEFAULT
    defines = _parse_defines(args.define) if args.define else None
    result = engine.render(source, output_dir, views=views, image_size=args.size, defines=defines)

    for warn in result.warnings:
        print(f"Warning: {warn}", file=sys.stderr)
    for err in result.errors:
        print(f"Error: {err}", file=sys.stderr)

    for view_name, img_path in result.images.items():
        print(f"  {view_name}: {img_path}")
    if getattr(args, "report", False):
        from agentcad.report import feature_effect, render_lines
        rep = feature_effect(None, result.metadata,
                             expected_solids=int(engine.setting("expected_solids")),
                             short_edge_mm=float(engine.setting("short_edge_mm")))
        print("Report:")
        for line in render_lines(rep):
            print(line, file=sys.stderr if line.lstrip().startswith("warning:") else sys.stdout)
    else:
        for key, value in result.metadata.items():
            print(f"  {key}: {value}")

    if result.success:
        print(f"\nRendered {len(result.images)} view(s) in {result.render_time_ms:.0f}ms")
    else:
        sys.exit(1)


def cmd_export(args):
    """Export a CAD source file to a geometry file (STL by default)."""
    from agentcad.config import ProjectConfig

    source = Path(args.source_file)
    if not source.exists():
        print(f"Error: File not found: {source}", file=sys.stderr)
        sys.exit(1)

    cfg = ProjectConfig.discover(source.parent)
    engine = _engine_for(args.engine, cfg)
    fmt = args.format.lower()
    output = Path(args.output) if args.output else source.with_suffix(f".{fmt}")

    defines = _parse_defines(args.define) if args.define else {}
    if getattr(args, "variants", None):
        # One knob, several values, one file each with the value in its name:
        # a print plate that measures the material's clearance tax in one go.
        knob, _, values = args.variants.partition("=")
        values = [v for v in values.split(",") if v]
        if not knob or not values:
            print("Error: --variants expects KNOB=v1,v2,...", file=sys.stderr)
            sys.exit(2)
        failed = False
        for value in values:
            per = dict(defines); per[knob] = value
            out = output.with_name(f"{output.stem}_{knob}-{value.replace('.', 'p')}{output.suffix}")
            result = engine.export(source, out, fmt=fmt, defines=per)
            for warn in result.warnings:
                print(f"Warning: {warn}", file=sys.stderr)
            if result.success:
                vol = result.metadata.get("volume")
                print(f"Exported: {result.output_path} ({knob}={value}" + (f", volume {vol:.4g}" if vol else "") + ")")
            else:
                failed = True
                for err in result.errors:
                    print(f"Error ({knob}={value}): {err}", file=sys.stderr)
        if failed:
            sys.exit(1)
        return
    result = engine.export(source, output, fmt=fmt, defines=defines or None)
    for warn in result.warnings:
        print(f"Warning: {warn}", file=sys.stderr)
    if result.success:
        facets = f", {result.facet_count} facets" if result.facet_count else ""
        print(f"Exported: {result.output_path} ({fmt}{facets}, {result.render_time_ms:.0f}ms)")
    else:
        for err in result.errors:
            print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)


def cmd_info(args):
    """Show engine and environment info."""
    from agentcad.engines import list_engines, get_engine

    print(f"AgentCAD v{__version__}")
    print(f"Registered engines: {list_engines()}")
    for name in list_engines():
        eng = get_engine(name)
        if eng.available():
            status = f"available (version {eng.version() or 'unknown'})"
        else:
            status = "not found"
        formats = ", ".join(eng.supported_export_formats)
        print(f"  {name}: {eng.name} - {status}; sources {eng.file_extension}; exports {formats}")
    print(f"\nCamera presets: {list(STANDARD_PRESETS.keys())}")


def cmd_new_project(args):
    """Create a new design project folder structure with agentcad.toml."""
    from agentcad.output import DesignProject
    from agentcad.config import OutputConfig, generate_config_template, CONFIG_FILENAME

    config = OutputConfig()
    if args.base_dir:
        config.base_dir = args.base_dir

    project = DesignProject(args.name, config)
    path = project.setup()

    # Generate agentcad.toml inside the project
    engine_name = args.engine if args.engine else "openscad"
    config_path = path / CONFIG_FILENAME
    if not config_path.exists():
        desc = args.description if args.description else ""
        config_path.write_text(generate_config_template(args.name, desc, engine_name))

    from agentcad.engines import engine_extensions
    ext = engine_extensions().get(engine_name, "")
    print(f"Created project: {path}")
    print(f"  agentcad.toml - project config (engine: {engine_name})")
    print(f"  source/       - {ext or 'engine'} source files")
    print(f"  renders/      - multi-view PNGs")
    print(f"  exports/      - geometry exports (STL, ...)")


def cmd_projects(args):
    """List all AgentCAD projects."""
    from agentcad.config import list_projects

    projects = list_projects()
    if not projects:
        print("No AgentCAD projects found.")
        return

    print(f"{'Project':<30} {'Engine':<12} {'Description'}")
    print("-" * 70)
    for cfg in projects:
        label = cfg.name or cfg.project_dir.name
        if cfg.parent_name:
            label = f"  \u2514 {label}"
        print(f"{label:<30} {cfg.engine:<12} {cfg.description[:40]}")


def cmd_status(args):
    """Show project status."""
    from agentcad.config import find_project, OutputConfig
    from pathlib import Path

    # Try to find project by name in designs dir
    designs = OutputConfig().designs_dir
    project_path = designs / args.project
    if not project_path.exists():
        project_path = Path(args.project)

    cfg = find_project(project_path)
    if cfg:
        print(cfg.show())
    else:
        print(f"No agentcad.toml found in {project_path}")
        print("Run: agentcad new-project <name> to create one")
        return

    # File counts
    source_dir = project_path / "source"
    renders_dir = project_path / "renders"
    exports_dir = project_path / "exports"
    print(f"\nFiles:")
    if source_dir.exists():
        sources = list(source_dir.glob("*.*"))
        print(f"  source/  : {len(sources)} files")
    if renders_dir.exists():
        renders = list(renders_dir.glob("*.png"))
        print(f"  renders/ : {len(renders)} PNGs")
    if exports_dir.exists():
        stls = list(exports_dir.glob("*.stl"))
        jsons = list(exports_dir.glob("*.json"))
        print(f"  exports/ : {len(stls)} STLs, {len(jsons)} manifests")
    if (project_path / "index.html").exists():
        print(f"  index.html : present")


def cmd_open(args):
    """Print project path for shell integration."""
    from agentcad.config import OutputConfig

    designs = OutputConfig().designs_dir
    project_path = designs / args.project
    print(project_path)


def cmd_config_init(args):
    """Create agentcad.toml in current directory."""
    from agentcad.config import generate_config_template, CONFIG_FILENAME

    path = Path.cwd() / CONFIG_FILENAME
    if path.exists() and not args.force:
        print(f"{CONFIG_FILENAME} already exists. Use --force to overwrite.")
        sys.exit(1)

    name = args.name or Path.cwd().name
    path.write_text(generate_config_template(name, args.description or ""))
    print(f"Created {path}")


def cmd_config_show(args):
    """Show resolved project config."""
    from agentcad.config import ProjectConfig

    cfg = ProjectConfig.discover()
    if cfg:
        print(cfg.show())
    else:
        print("No agentcad.toml found in current directory or parents.")


def _resolve_project(project_arg):
    """Resolve project name/path -> (ProjectConfig, project_dir, project_name).

    Returns (cfg, project_dir, project_name). Exits if project not found.
    """
    from agentcad.config import OutputConfig, find_project

    designs = OutputConfig().designs_dir
    project_path = designs / project_arg
    if not project_path.exists():
        project_path = Path(project_arg)
    if not project_path.exists():
        # a part subproject named on its own: look under every parent's parts
        for parent in sorted(designs.iterdir()) if designs.exists() else []:
            parent_cfg = find_project(parent) if parent.is_dir() else None
            for folder, _ in (parent_cfg.part_projects() if parent_cfg else []):
                if folder.name == project_arg:
                    project_path = folder
                    break
            if project_path.exists():
                break
    if not project_path.exists():
        print(f"Error: project not found: {project_arg}", file=sys.stderr)
        sys.exit(1)

    cfg = find_project(project_path)
    if cfg is None:
        print(f"Error: no agentcad.toml in {project_path}. "
              f"Run `agentcad config-init` inside the project folder.", file=sys.stderr)
        sys.exit(1)
    return cfg, project_path, project_path.name


def cmd_session_start(args):
    """Start a new design session."""
    from agentcad.session import DesignSession

    cfg, project_dir, project_name = _resolve_project(args.project)
    engine = _engine_for(args.engine, cfg)
    if not engine.available():
        print(f"Error: engine '{engine.name}' is not available.", file=sys.stderr)
        sys.exit(1)

    session = DesignSession(
        name=project_name,
        engine=engine,
        config=cfg,
        max_iterations=args.max_iter,
        defines=_parse_defines(args.define) if args.define else None,
    )

    # An existing record is never overwritten. Without --force an active
    # session refuses the start; with it the record and its working files
    # move to _work/archive_<stamp>/ (or are discarded with --no-archive).
    if session.state_file.exists():
        try:
            prior = json.loads(session.state_file.read_text())
        except (OSError, json.JSONDecodeError) as e:
            print(f"Warning: existing session state unreadable: {e}", file=sys.stderr)
            prior = {}
        active = not prior.get("finalized", False) and prior.get("iterations")
        if active and not args.force:
            print(f"Error: active session exists at {session.state_file} "
                  f"with {len(prior['iterations'])} iteration(s). "
                  f"Use --force to archive it and start over, `agentcad session finalize` "
                  f"to close it, or `agentcad session reopen` to continue it.",
                  file=sys.stderr)
            sys.exit(1)
        if getattr(args, "no_archive", False):
            print(f"Warning: --no-archive: discarding the previous session record at {session.state_file}",
                  file=sys.stderr)
            session.state_file.unlink()
        else:
            archive = DesignSession.archive_previous(
                project_name, config=cfg,
                reason=f"session start{' --force' if args.force else ''} with {len(prior.get('iterations', []))} prior iteration(s)",
            )
            if archive:
                print(f"  Archived previous session to {archive}")

    state_path = session.save_state()
    print(f"Session started for project '{project_name}' (engine: {engine.name})")
    print(f"  Project dir: {project_dir}")
    print(f"  State file:  {state_path}")
    print(f"  Max iter:    {session.max_iterations}")


def cmd_session_iterate(args):
    """Add an iteration to the active session."""
    from agentcad.session import DesignSession

    cfg, project_dir, project_name = _resolve_project(args.project)
    engine = _engine_for(None, cfg)

    try:
        session = DesignSession.load_state(project_name, engine=engine, config=cfg)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    source = Path(args.source_file)
    if not source.exists():
        print(f"Error: source file not found: {source}", file=sys.stderr)
        sys.exit(1)

    code = source.read_text()
    if getattr(args, "all", False):
        _iterate_parts(cfg, source, code, args)
    try:
        it = session.iterate(code, defines=_parse_defines(args.define) if getattr(args, "define", None) else None)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    session.save_state()
    print(f"Iteration v{it.number} recorded")
    if it.render_result:
        for warn in it.render_result.warnings:
            print(f"  Warning: {warn}", file=sys.stderr)
    if it.render_result and it.render_result.success:
        print(f"  Rendered {len(it.image_paths)} view(s) in {it.render_result.render_time_ms:.0f}ms")
        for view, path in it.image_paths.items():
            print(f"    {view}: {path}")
        if it.report:
            from agentcad.report import render_lines
            print(f"  Report v{it.number}" + (f" vs v{it.number - 1}" if it.number > 1 else "") + ":")
            for line in render_lines(it.report, indent="    "):
                print(line, file=sys.stderr if line.lstrip().startswith("warning:") else sys.stdout)
    else:
        errors = it.render_result.errors if it.render_result else ["no render result"]
        for err in errors:
            print(f"  Render error: {err}", file=sys.stderr)
        sys.exit(1)


def _iterate_parts(cfg, source, code, args):
    """Run the iteration in every declared part subproject with the same source."""
    from agentcad.session import DesignSession
    from agentcad.report import render_lines

    parts = cfg.part_projects()
    if not parts:
        print("Warning: --all given but the project declares no parts ([project] parts = [...])", file=sys.stderr)
        return
    for folder, part_cfg in parts:
        engine = _engine_for(None, part_cfg)
        try:
            part_session = DesignSession.load_state(folder.name, engine=engine, config=part_cfg)
        except (FileNotFoundError, ValueError) as e:
            print(f"  part {folder.name}: skipped ({e})", file=sys.stderr)
            continue
        if part_session._finalized:
            # the parent is being iterated, so its parts continue too
            part_session.reopen()
        try:
            it = part_session.iterate(code, defines=_parse_defines(args.define) if getattr(args, "define", None) else None)
        except RuntimeError as e:
            print(f"  part {folder.name}: {e}", file=sys.stderr)
            continue
        part_session.save_state()
        ok = it.render_result is not None and it.render_result.success
        line = f"  part {folder.name}: v{it.number} {'rendered' if ok else 'FAILED'}"
        if it.report:
            counts = it.metadata.get("counts") or {}
            line += f"; volume {it.metadata.get('volume', 'n/a')}, solids {counts.get('solids', 'n/a')}"
        print(line)
        if it.report:
            for w in it.report.warnings:
                print(f"    warning: {w}", file=sys.stderr)


def cmd_session_reopen(args):
    """Continue a finalized session."""
    from agentcad.session import DesignSession

    cfg, _, project_name = _resolve_project(args.project)
    engine = _engine_for(None, cfg)
    try:
        session = DesignSession.load_state(project_name, engine=engine, config=cfg)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    if not session._finalized:
        print(f"Session for '{project_name}' is already open ({session.iteration_count} iteration(s)).")
        return
    session.reopen()
    session.save_state()
    print(f"Session reopened for '{project_name}'; the next iteration is v{session.iteration_count + 1}.")


def cmd_session_tag(args):
    """Freeze the latest iteration under tags/<name>/ for a review round."""
    from agentcad.session import DesignSession

    cfg, _, project_name = _resolve_project(args.project)
    engine = _engine_for(None, cfg)
    try:
        session = DesignSession.load_state(project_name, engine=engine, config=cfg)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    try:
        dest = session.tag(args.tag, note=args.note)
    except (RuntimeError, ValueError, FileExistsError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    session.save_state()
    print(f"Tagged v{session.current.number} as '{args.tag}': {dest}")


def cmd_session_note(args):
    """Add an analysis note to the current iteration."""
    from agentcad.session import DesignSession

    cfg, _, project_name = _resolve_project(args.project)
    engine = _engine_for(None, cfg)
    try:
        session = DesignSession.load_state(project_name, engine=engine, config=cfg)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    try:
        session.note(args.text)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    session.save_state()
    print(f"Note added to v{session.current.number}: {args.text}")


def cmd_session_finalize(args):
    """Finalize the session: STL exports, HTML viewer, print manifest."""
    from agentcad.session import DesignSession

    cfg, _, project_name = _resolve_project(args.project)
    engine = _engine_for(None, cfg)
    try:
        session = DesignSession.load_state(project_name, engine=engine, config=cfg)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "all", False):
        gathered = []
        for folder, part_cfg in cfg.part_projects():
            part_engine = _engine_for(None, part_cfg)
            try:
                part_session = DesignSession.load_state(folder.name, engine=part_engine, config=part_cfg)
                part_html = part_session.finalize(export_all=getattr(args, "export_all", False))
                part_session.save_state()
                print(f"  part {folder.name}: finalized ({part_session.iteration_count} iteration(s)) {part_html}")
                latest = part_session.project.variants[0] if part_session.project.variants else None
                if latest is not None and latest.stl_path and latest.stl_path.exists():
                    gathered.append((folder.name, latest.stl_path, part_cfg.quantity))
            except (FileNotFoundError, ValueError, RuntimeError) as e:
                print(f"  part {folder.name}: {e}", file=sys.stderr)
        session.part_meshes = gathered
        if gathered:
            print(f"  assembly viewer: {len(gathered)} part mesh(es) gathered")

    already = session._finalized
    html_path = session.finalize(export_all=getattr(args, "export_all", False))
    session.save_state()
    print("Session finalized." + (" (again: variants rebuilt, existing exports reused)" if already else ""))
    print(f"  HTML viewer: {html_path}")
    print(f"  Iterations:  {session.iteration_count}")
    _finalize_fits(cfg, session)


def _finalize_fits(cfg, session):
    """Fit every mate the project declares and record each fit in both parts' manifests."""
    from agentcad import fit as fitmod
    from agentcad import mates
    from agentcad.session import DesignSession

    project_dir = cfg.project_dir
    try:
        declared = mates.load_all(project_dir) if project_dir else {}
    except mates.MateError as e:
        print(f"  Mates: not read ({e})", file=sys.stderr)
        return
    if not declared:
        return

    def latest(sess, folder):
        it = sess.iterations[-1]
        return (Path(it.source_path), dict(it.defines or sess.defines or {}), Path(folder))

    sources = {session.name: latest(session, project_dir)}
    parts = cfg.part_projects()
    for folder, part_cfg in parts:
        try:
            part_session = DesignSession.load_state(folder.name, engine=_engine_for(None, part_cfg), config=part_cfg)
        except (FileNotFoundError, ValueError, RuntimeError):
            continue
        if part_session.iterations:
            sources[folder.name] = latest(part_session, folder)
    print(f"  Mates:       {len(declared)} declared")
    for r in fitmod.declared_fits(project_dir, session.name, sources, assembly=bool(parts)):
        if "skipped" in r:
            print(f"    {r['mate']}: not fitted ({r['skipped']})")
            continue
        rec = r["record"]
        line = (f"    {r['mate']} ({r['pair'][0]} / {r['pair'][1]}): {rec['verdict'].upper()}; interference "
                f"{rec['interference_mm3']:.4g} mm^3, clearance {rec['clearance_mm']:.4g} mm")
        for v in (rec.get("verdicts") or {}).values():
            if "min_mm" in v:
                line += f", window {v['min_mm']:.3g} mm against {v['nominal_mm']:.3g} +/- {v['tol_mm']:.3g}"
        print(line + f"; {rec.get('contact_regions', 0)} contact region(s)")
        for note in rec.get("pose", {}).get("notes") or []:
            print(f"      pose: {note}")
        print(f"      recorded in {len(r['written'])} manifest(s)")


def cmd_session_status(args):
    """Show current session state."""
    from agentcad.session import DesignSession

    cfg, _, project_name = _resolve_project(args.project)
    engine = _engine_for(None, cfg)
    try:
        session = DesignSession.load_state(project_name, engine=engine, config=cfg)
    except FileNotFoundError:
        print(f"No active session in project '{project_name}'.")
        print(f"Start one with: agentcad session start {project_name}")
        sys.exit(1)
    print(session.summary())


def cmd_viewer(args):
    """Regenerate the HTML viewer for a project from files on disk."""
    from agentcad.viewer import regenerate_from_project_dir

    cfg, project_dir, _ = _resolve_project(args.project)
    if getattr(args, "tag", None):
        tag_dir = project_dir / "tags" / args.tag
        if not (tag_dir / "TAG.json").exists():
            print(f"Error: no tag '{args.tag}' under {project_dir / 'tags'}", file=sys.stderr)
            sys.exit(1)
        project_dir = tag_dir
    try:
        html_path = regenerate_from_project_dir(project_dir, cfg=cfg,
                                                artifact_dir=Path(args.artifact) if getattr(args, "artifact", None) else None,
                                                title=getattr(args, "title", None))
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    if getattr(args, "artifact", None):
        print(f"Artifact fragment: {html_path} (files map: {html_path.parent / 'files.json'})")
    else:
        print(f"Regenerated: {html_path}")


def _windows_arg(items):
    out = {}
    for item in items or []:
        name, _, nums = item.partition("=")
        vals = [float(v) for v in nums.split(",")]
        if len(vals) != 4:
            print(f"Error: window {item!r}: expected name=x0,y0,x1,y1", file=sys.stderr)
            sys.exit(2)
        out[name] = vals
    return out


def cmd_probe_section(args):
    """Section loops of a shape on named planes, as loops.json."""
    from agentcad import probe

    shape = probe.load_shape(Path(args.source), defines=_parse_defines(args.define) if args.define else None)
    planes = args.planes or ["z=mid"]
    data = {"source": str(args.source), "planes": []}
    for spec in planes:
        plane, coord = probe.parse_plane(spec, shape)
        loops = probe.section_loops(shape, plane, max_loops=args.max_loops)
        for L in loops:
            L["fit"] = probe.fit_polyline_loop(L)
        total = loops[0]["total_on_plane"] if loops else 0
        print(f"{spec} (at {coord:.4g}): {total} loop(s)" + (f", {len(loops)} kept" if len(loops) != total else ""))
        for i, L in enumerate(loops[: args.show]):
            kinds = {}
            for e in L["edges"]:
                kinds[e["type"]] = kinds.get(e["type"], 0) + 1
            desc = ", ".join(f"{n} {k}" for k, n in sorted(kinds.items()))
            fit = f"; fits a circle r {L['fit']['radius']:.4g} (rms {L['fit']['rms']:.2g})" if L.get("fit") else ""
            print(f"  loop {i + 1}: length {L['length']:.4g}, {desc}{fit}")
        data["planes"].append({"plane": spec, "coordinate": coord, "n_loops": total, "loops": loops})
    if args.output:
        print(f"loops.json: {probe.write_json(data, Path(args.output))}")


def cmd_probe_inventory(args):
    """bbox, volume, census, cylinder axes and section loops of a shape."""
    from agentcad import probe

    shape = probe.load_shape(Path(args.source), defines=_parse_defines(args.define) if args.define else None)
    inv = probe.inventory(shape, planes=args.planes or [], max_loops=args.max_loops)
    print(f"bbox_min {inv.get('bbox_min')}  bbox_size {inv.get('bbox_size')}")
    print(f"volume {inv.get('volume')}  area {inv.get('area')}  counts {inv.get('counts')}  valid {inv.get('is_valid')}")
    print(f"census {inv.get('face_census')}")
    cyl = inv.get("cylinders") or []
    print(f"{len(cyl)} cylindrical/conical face(s) with axes:")
    for c in cyl[: args.show]:
        if "axis_direction" in c:
            o, d = c["axis_origin"], c["axis_direction"]
            print(f"  {c['type']} r {c.get('radius')}: axis through ({o[0]:.4g}, {o[1]:.4g}, {o[2]:.4g}) along ({d[0]:.3g}, {d[1]:.3g}, {d[2]:.3g})")
        else:
            print(f"  {c['type']}: no axis ({c.get('axis_error')})")
    for p in inv.get("planes") or []:
        print(f"{p['plane']}: {p['n_loops']} loop(s)")
    if args.output:
        print(f"inventory.json: {probe.write_json(inv, Path(args.output))}")


def cmd_probe_draft(args):
    """Will the part leave its mold: draft per face against a pull direction, with an optional gate."""
    from agentcad import probe

    shape = probe.load_shape(Path(args.source), defines=_parse_defines(args.define) if args.define else None)
    pull = [float(v) for v in args.pull.split(",")] if args.pull else [0.0, 0.0, 1.0]
    res = probe.draft_analysis(shape, pull=pull, samples=args.samples)
    print("\n".join(probe.render_draft(res, args.min_draft, show=args.show)))
    if args.output:
        print(f"draft.json: {probe.write_json(res, Path(args.output))}")
    if args.min_draft is not None and probe.draft_failures(res, args.min_draft):
        sys.exit(1)


def cmd_probe_fillet(args):
    """Why a fillet fails: the selected chain on the live part at the step it is applied."""
    from agentcad import probe

    radii = [float(v) for v in args.radii.split(",")] if args.radii else (1.0, 0.6, 0.4, 0.25)
    res = probe.fillet_probe(Path(args.source), at=args.at, index=args.index, radii=radii, short_mm=args.short,
                             defines=_parse_defines(args.define) if args.define else None)
    print("\n".join(probe.render_fillet_probe(res)))
    if args.output:
        print(f"fillet.json: {probe.write_json(res, Path(args.output))}")


def cmd_gcode_decode(args):
    """A sliced file as plain G-code text (a .bgcode is decoded; a plain file passes through)."""
    from agentcad.gcode import bgcode

    if args.no_verify:
        print("warning: CRC checks skipped (--no-verify)", file=sys.stderr)
    text = bgcode.gcode_text(Path(args.file), verify=not args.no_verify)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"{args.output}: {len(text.splitlines())} lines")
    else:
        sys.stdout.write(text)


def cmd_gcode_info(args):
    """The file header, the block table and the metadata of a .bgcode."""
    from agentcad.gcode import bgcode

    g = bgcode.read(Path(args.file), verify=not args.no_verify)
    print(f"bgcode version {g.version}, checksums {'CRC32' if g.checksum_type == 1 else 'none'}, {len(g.blocks)} blocks")
    counts = {}
    for b in g.blocks:
        counts[b.name] = counts.get(b.name, 0) + 1
    print("  " + ", ".join(f"{n} x{k}" for n, k in counts.items()))
    for t in g.thumbnails():
        print(f"  thumbnail {t.format} {t.width}x{t.height} ({len(t.data)} bytes)")
    for section in ("printer_metadata", "print_metadata"):
        for k, v in g.metadata.get(section, {}).items():
            print(f"  {k} = {v}")
    print(f"  slicer settings: {len(g.metadata.get('slicer_metadata', {}))} keys (gcode check reads them)")


def cmd_gcode_thumbnails(args):
    """Write the thumbnails a .bgcode carries."""
    from agentcad.gcode import bgcode

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(args.file).stem
    for i, t in enumerate(bgcode.read(Path(args.file)).thumbnails()):
        f = out / f"{stem}_{t.width}x{t.height}_{i}.{t.format}"
        f.write_bytes(t.data)
        print(f)


def cmd_gcode_summary(args):
    """Layers, filament, and extrusion by object and feature of a sliced file."""
    from agentcad.gcode import bgcode, model

    path = Path(args.file)
    meta = bgcode.read(path).metadata if bgcode.is_bgcode(path) else {}
    slicer = meta.get("slicer_metadata", {})
    density = float(slicer.get("filament_density", "0").split(",")[0] or 0) or None
    diameter = float(slicer.get("filament_diameter", "1.75").split(",")[0] or 1.75)
    s = model.summary(model.parse(bgcode.gcode_text(path)), diameter, density)
    stated = meta.get("print_metadata", {}).get("filament used [mm]")
    if stated:
        s["filament_used_stated_mm"] = float(stated)
    if args.json:
        print(json.dumps(s, indent=2))
        return
    fu = s["filament_used"]
    print(f"{path.name}: {s['layers']} layers to z {s['top_z']}; filament {fu['filament_mm']} mm"
          + (f" ({fu['mass_g']} g)" if "mass_g" in fu else "")
          + (f"; the file states {stated} mm" if stated else ""))
    if not s["features_known"]:
        print("  features unknown: the file carries no feature comments; totals only")
    for obj, o in s["by_object"].items():
        print(f"  {obj}: {o['filament_mm']} mm, support {100 * o['support_share']:.1f}%")
        for feat, f in sorted(o["features"].items(), key=lambda kv: -kv[1]["filament_mm"]):
            print(f"      {feat}: {f['filament_mm']} mm")
    sp = s["support"]
    if sp["first_layer"] is not None:
        print(f"  supports: {100 * sp['share']:.1f}% of extrusion, layers {sp['first_layer']}-{sp['last_layer']}"
              f" (z {sp['first_z']}-{sp['last_z']})")
    else:
        print("  supports: none")
    if s["unknown_features"]:
        print(f"  unclassified feature types: {s['unknown_features']}")


def cmd_gcode_check(args):
    """Compare the settings a sliced file carries with the [slice] intent of a project, a job or a TOML file."""
    from agentcad.gcode import check

    cfg = check.embedded_config(Path(args.file))
    source_path = None
    if args.project:
        source_path = Path(args.project)
        source_path = source_path / "agentcad.toml" if source_path.is_dir() else source_path
    elif args.intent:
        source_path = Path(args.intent)
    intent = check.load_intent(source_path) if source_path else {}
    label = f"{source_path.name} [slice]" if source_path else ""
    if not intent:
        print(f"{Path(args.file).name}: no [slice] intent declared" + (f" in {source_path}" if source_path else "")
              + "; the file's key settings, without a verdict:")
        for k in check.KEY_SETTINGS:
            if k in cfg:
                print(f"  {k} = {cfg[k]}")
        return 0
    findings = check.check(cfg, intent, label)
    if args.json:
        print(json.dumps([f.__dict__ | {"sentence": f.sentence()} for f in findings], indent=2))
    else:
        for f in findings:
            mark = {"error": "ERROR", "warning": "warning", "ok": "ok"}[f.severity]
            print(f"  {mark}: {f.sentence()}")
        n_err = sum(f.severity == "error" for f in findings)
        n_warn = sum(f.severity == "warning" for f in findings)
        print(f"{Path(args.file).name}: {len(findings)} intended settings, {n_err} error(s), {n_warn} warning(s)")
    return 1 if any(f.severity == "error" for f in findings) else 0


def _supports_png(out, bands, placement, meshes, stl_root):
    """Parts (translucent, placed on the bed) with contact cells: green on an outer surface, red in a cavity."""
    import numpy as np
    import pyvista as pv
    from agentcad.gcode import supports

    pl = pv.Plotter(off_screen=True, window_size=(1000, 800))
    placed = set()
    for b in bands:
        p = placement.get(b.object or "")
        cells = np.array(b.cells or [], float)
        if not len(cells):
            continue
        colour = "seagreen"
        if p and stl_root is not None and (stl_root / p["stl"]).exists():
            mesh = meshes.setdefault(str(stl_root / p["stl"]), pv.read(str(stl_root / p["stl"])))
            if b.object not in placed:
                pl.add_mesh(mesh.translate(p["bed_offset"], inplace=False), color="lightsteelblue", opacity=0.35)
                placed.add(b.object)
            votes = supports.band_enclosure(b, placement, mesh) or {}
            if votes and max(votes, key=votes.get) == "cavity":
                colour = "red"
        pl.add_points(cells, color=colour, point_size=6, render_points_as_spheres=True)
    pl.add_axes()
    pl.camera_position = "iso"
    pl.screenshot(str(out))


def cmd_gcode_supports(args):
    """Where supports touch each object, as contact bands in the bed frame."""
    from agentcad.gcode import bgcode, model, supports
    from agentcad.gcode.check import embedded_config

    path = Path(args.file)
    cfg = embedded_config(path)
    cd = args.contact_distance
    if cd is None:
        cd = float(cfg.get("support_material_contact_distance", "0.25").split(",")[0] or 0.25)
    bands = [b for b in supports.find_contacts(model.parse(bgcode.gcode_text(path)), contact_distance=cd)
             if b.area_mm2 >= args.min_area]
    placement = supports.load_placement(Path(args.placement)) if args.placement else {}
    if args.json:
        print(json.dumps([dict(b.__dict__, object_frame=supports.in_object_frame(b, placement)) for b in bands],
                         indent=2))
        return
    if not bands:
        print(f"{path.name}: no support touches a part (contact distance {cd} mm)")
        return
    print(f"{path.name}: {len(bands)} contact band(s), about {sum(b.area_mm2 for b in bands):.0f} mm2 in all "
          f"(contact distance {cd} mm; bed frame)")
    meshes, in_cavity = {}, 0
    for b in sorted(bands, key=lambda b: -b.area_mm2):
        print(f"  {b.sentence()}")
        if args.placement:
            o = supports.in_object_frame(b, placement)
            print("      in its STL frame: " + (f"x {o['x'][0]:.1f}..{o['x'][1]:.1f}, y {o['y'][0]:.1f}..{o['y'][1]:.1f}, "
                                                 f"z {o['z'][0]:.1f}..{o['z'][1]:.1f}" if o else "placement unknown"))
            stl = Path(args.stl_root or Path(args.placement).parent) / o["stl"] if o and o.get("stl") else None
            if stl is not None and stl.exists():
                import pyvista as pv
                votes = supports.band_enclosure(b, placement, meshes.setdefault(str(stl), pv.read(str(stl))))
                where = max(votes, key=votes.get) if votes else None
                if where == "cavity":
                    in_cavity += 1
                    print(f"      ERROR: walled in on every side (a bore or pocket): supports here are hard to remove "
                          f"and foul the fit; block them (a support blocker volume) or re-orient. Votes {votes}")
                elif where:
                    print(f"      on an outer surface. Votes {votes}")
            elif o:
                print(f"      (STL not found under {stl.parent if stl else '?'}: no region check; pass --stl-root)")
    if args.png:
        _supports_png(Path(args.png), bands, placement, meshes, Path(args.stl_root or Path(args.placement).parent)
                      if args.placement else None)
        print(f"render: {args.png}")
    if in_cavity:
        return 1


def cmd_gcode_view(args):
    """Write a standalone page showing a sliced file's toolpaths."""
    from agentcad.gcode import bgcode, model, view

    path = Path(args.file)
    out = (Path(args.artifact) / "index.html" if getattr(args, "artifact", None)
           else Path(args.output) if args.output else path.with_suffix(".toolpaths.html"))
    m = model.parse(bgcode.gcode_text(path))
    contacts = []
    if args.placement:
        import pyvista as pv
        from agentcad.gcode import supports
        from agentcad.gcode.check import embedded_config
        cd = float(embedded_config(path).get("support_material_contact_distance", "0.25").split(",")[0] or 0.25)
        placement = supports.load_placement(Path(args.placement))
        root = Path(args.stl_root or Path(args.placement).parent)
        for b in supports.find_contacts(m, contact_distance=cd):
            p = placement.get(b.object or "")
            stl = root / p["stl"] if p and p.get("stl") else None
            votes = supports.band_enclosure(b, placement, pv.read(str(stl))) if stl is not None and stl.exists() else None
            kind = "cavity" if votes and max(votes, key=votes.get) == "cavity" else "outside"
            contacts += [(x, y, z, kind) for x, y, z in (b.cells or [])]
    meshes = []
    if args.placement:
        import numpy as np
        for label, p in placement.items():
            stl = root / p["stl"] if p.get("stl") else None
            if stl is not None and stl.exists():
                mesh = pv.read(str(stl)).triangulate()
                meshes.append((np.asarray(mesh.points) + np.asarray(p["bed_offset"]), mesh.faces.reshape(-1, 4)[:, 1:]))
    view.write_page(m, out, title=path.stem, budget_mb=args.budget_mb, contacts=contacts, meshes=meshes,
                    fragment=bool(getattr(args, "artifact", None)))
    print(f"toolpaths: {out}")


def cmd_compare(args):
    """Loop-count gate per plane, sampled deviation both ways, overlay PNGs."""
    from agentcad import probe

    res = probe.compare(Path(args.original), Path(args.candidate), planes=args.planes or [],
                        windows=_windows_arg(args.window) or None,
                        out_dir=Path(args.output_dir) if args.output_dir else None,
                        defines=_parse_defines(args.define) if args.define else None, max_loops=args.max_loops)
    for p in res.get("planes", []):
        mark = "ok" if p["equal"] else "DIFFERENT"
        print(f"{p['plane']}: loops {p['loops_original']} vs {p['loops_candidate']} {mark}")
        for name, w in (p.get("windows") or {}).items():
            if "p95" in w:
                print(f"  window {name}: p95 {w['p95']:.4g}, max {w['max']:.4g}")
            else:
                print(f"  window {name}: {w.get('note')}")
        if p.get("overlay"):
            print(f"  overlay: {p['overlay']}")
    if res.get("planes_note"):
        print(f"note: {res['planes_note']}")
    dev = res.get("deviation")
    if dev:
        a, b = dev["candidate_to_original"], dev["original_to_candidate"]
        print(f"deviation candidate->original p95 {a['p95']:.4g} max {a['max']:.4g}; original->candidate p95 {b['p95']:.4g} max {b['max']:.4g}")
    elif res.get("deviation_error"):
        print(f"deviation: {res['deviation_error']}", file=sys.stderr)
    if args.output_dir:
        print(f"compare.json: {probe.write_json(res, Path(args.output_dir) / 'compare.json')}")
    if res.get("gate") is False:
        print("loop-count gate: FAILED (a plane's loop counts differ)", file=sys.stderr)
        sys.exit(1)


def cmd_fit(args):
    """Pose two parts and measure interference, clearance, windows, contacts and insertion."""
    from agentcad import fit as fitmod
    from agentcad import mates

    windows = {}
    nominals = {}
    for item in args.window or []:
        name, _, nums = item.partition("=")
        vals = [float(v) for v in nums.split(",")]
        if len(vals) != 6:
            print(f"Error: window {item!r}: expected name=x0,y0,z0,x1,y1,z1", file=sys.stderr)
            sys.exit(2)
        windows[name] = vals
    a_defs = _parse_defines(args.a_define) if args.a_define else {}
    b_defs = _parse_defines(args.b_define) if args.b_define else {}
    if args.mates_from:
        sides = {str(a_defs.get("part", "")), str(b_defs.get("part", ""))} - {""}
        for name, m in fitmod.load_mates(Path(args.mates_from)).items():
            if not (isinstance(m, dict) and "window" in m and len(m["window"]) == 6):
                continue
            # a mate that names its parts (or its counterpart) is checked only on that pair;
            # a window for another pair would just read empty and say nothing
            pair = {str(x) for x in (m.get("parts") or [])}
            cp = str(m.get("counterpart", "") or "")
            if sides and ((pair and pair != sides) or (not pair and cp and cp not in sides)):
                continue
            windows.setdefault(name, [float(v) for v in m["window"]])
            nominals.setdefault(name, (m.get("nominal_mm"), m.get("tol_mm")))
    offset = [float(v) for v in args.offset.split(",")] if args.offset else (0, 0, 0)
    transform = None
    frame = None
    pose_info = {}
    if args.mate:
        if args.map or args.offset or args.spin:
            print("Error: --mate poses B from declared datums; drop --map, --offset and --spin", file=sys.stderr)
            sys.exit(2)
        posed = []
        for name in args.mate:
            try:
                posed.append(mates.pose_for(name, Path(args.a_mates or args.a), Path(args.b_mates or args.b)))
            except mates.MateError as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(2)
        first = posed[0]
        transform = first["matrix"]
        a_side = first["a"]
        frame = (a_side.axis.point, a_side.key_line.direction if a_side.key_line else (1.0, 0.0, 0.0),
                 a_side.axis.direction)
        pose_info = {"mate": args.mate[0], "a_declared_in": str(first["a_path"]),
                     "b_declared_in": str(first["b_path"]), "notes": first["notes"]}
        for name, p in zip(args.mate, posed):
            if p is not first:
                diff = max(abs(p["matrix"][i][j] - transform[i][j]) for i in range(3) for j in range(4))
                if diff > 1e-6:
                    print(f"Warning: mate {name} poses B differently from {args.mate[0]} (largest entry "
                          f"difference {diff:.3g}); the pose of {args.mate[0]} is used", file=sys.stderr)
            # the window and nominal are A's side's, or else the enclosing assembly's (in A's frame)
            above = mates.enclosing(name, p["a_path"])
            side = p["a"] if p["a"].window else (above[0] if above and above[0].window else None)
            if side is not None:
                windows.setdefault(name, side.window)
            stated = [m for m in (p["a"], side, p["b"]) if m is not None and m.nominal_mm is not None]
            if side is not None and stated:
                nominals.setdefault(name, (stated[0].nominal_mm, stated[0].tol_mm))
        for note in first["notes"]:
            print(f"  pose: {note}")
    elif args.map:
        if args.offset or args.spin:
            print("Error: --map replaces --offset and --spin; give one or the other", file=sys.stderr)
            sys.exit(2)
        fields = dict(item.partition("=")[::2] for item in args.map)
        unknown = set(fields) - {"axis", "spin", "offset"}
        if unknown:
            print(f"Error: --map takes axis=, spin= and offset=, not {', '.join(sorted(unknown))}", file=sys.stderr)
            sys.exit(2)
        try:
            transform = mates.map_transform(fields.get("axis", "z"), float(fields.get("spin", 0)),
                                            [float(v) for v in fields.get("offset", "0,0,0").split(",")])
        except (ValueError, mates.MateError) as e:
            print(f"Error: --map: {e}", file=sys.stderr)
            sys.exit(2)
    res = fitmod.fit(Path(args.a), Path(args.b), transform=transform,
                     a_defines=a_defs or None, b_defines=b_defs or None,
                     offset=offset, spin_deg=args.spin, spin_axis=args.spin_axis, windows=windows or None,
                     sweep_axis=args.sweep, sweep_travel=args.travel,
                     out_dir=Path(args.output_dir) if args.output_dir else None,
                     sweep_steps=args.sweep_steps, sample_step=args.step,
                     contact_mm=None if args.contact_mm < 0 else args.contact_mm, frame=frame)
    res["pose"].update(pose_info)
    if nominals and res.get("windows"):
        res["verdicts"] = fitmod.judge_windows(res["windows"], nominals)
    print(f"interference {res['interference_mm3']:.4g} mm^3; clearance {res['clearance_mm']:.4g} mm")
    if "contacts" in res:
        regions = res["contacts"]
        print(f"  contacts within {res['contact_mm']:.3g} mm: {len(regions) or 'none'}"
              + (" region(s)" if regions else ""))
        for r in regions[:8]:
            c, lo, hi = r["centroid"], r["min"], r["max"]
            print(f"    at ({c[0]:.2f}, {c[1]:.2f}, {c[2]:.2f}), box ({lo[0]:.2f}, {lo[1]:.2f}, {lo[2]:.2f})"
                  f" to ({hi[0]:.2f}, {hi[1]:.2f}, {hi[2]:.2f}), closest {r['min_mm']:.3g} mm")
        if len(regions) > 8:
            print(f"    ... {len(regions) - 8} more in fit.json")
    for name, w in (res.get("windows") or {}).items():
        if "min_mm" in w:
            print(f"  window {name}: min {w['min_mm']:.4g} mm (p05 {w['p05_mm']:.4g})")
        else:
            print(f"  window {name}: {w.get('note')}")
    failed_windows = []
    for name, v in (res.get("verdicts") or {}).items():
        measured = f"{v['min_mm']:.3g} mm" if "min_mm" in v else "not measured"
        print(f"  window {name}: {v['verdict'].upper()} (clearance {measured}; nominal {v['nominal_mm']:.3g} "
              f"+/- {v['tol_mm']:.3g} mm)")
        if v["verdict"] == "fail":
            failed_windows.append(name)
    for row in res.get("insertion") or []:
        print(f"  insertion at {row['offset_mm']:.3g} mm out: interference {row['interference_mm3']:.4g} mm^3")
    for name, path in (res.get("renders") or {}).items():
        print(f"  render {name}: {path}")
    if args.output_dir:
        print(f"fit.json: {fitmod.write_json(res, Path(args.output_dir) / 'fit.json')}")
    if args.record is not None:
        record = fitmod.fit_record(res, allow_mm3=args.allow or 0.0)
        # each part's record goes where the part is declared: the folder of its side of the mate,
        # or else the project holding its source
        homes = ((pose_info["a_declared_in"], pose_info["b_declared_in"]) if pose_info else (args.a, args.b))
        projects = [Path(p) for p in args.record] or [q for q in (fitmod.project_of(Path(h)) for h in homes) if q]
        if not projects:
            print("Warning: --record found no project (agentcad.toml) above either part; name one", file=sys.stderr)
        for project in dict.fromkeys(p.resolve() for p in projects):
            written = fitmod.record_fit(project, record)
            if written:
                print(f"recorded ({record['verdict']}) in {written}")
            else:
                print(f"Warning: no print manifest under {project}/exports to record into (finalize it first)",
                      file=sys.stderr)
    if failed_windows:
        print(f"fit: BELOW NOMINAL CLEARANCE in {', '.join(failed_windows)}", file=sys.stderr)
        sys.exit(1)
    if res["interference_mm3"] and res["interference_mm3"] > (args.allow or 0.0):
        print("fit: INTERFERENCE (the bodies overlap)", file=sys.stderr)
        sys.exit(1)


def cmd_gallery_build(args):
    """Build a static gallery of project viewers."""
    from agentcad.config import OutputConfig
    from agentcad.gallery import build

    folders = []
    if args.projects:
        import glob as _glob
        for pattern in args.projects:
            folders += [Path(p) for p in sorted(_glob.glob(pattern)) if (Path(p) / "agentcad.toml").exists()]
    else:
        designs = Path(args.designs_dir) if args.designs_dir else OutputConfig().designs_dir
        folders = [p for p in sorted(designs.iterdir()) if (p / "agentcad.toml").exists()] if designs.exists() else []
    if not folders:
        print("Error: no projects found", file=sys.stderr)
        sys.exit(1)
    page = build(folders, Path(args.output), title=args.title, copy=not args.no_copy, max_mb=args.max_mb)
    print(f"Gallery: {page} ({len(folders)} project(s))")


def cmd_gallery_check(args):
    """Verify a built gallery's links and images."""
    from agentcad.gallery import check

    problems = check(Path(args.gallery_dir))
    if problems:
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        print(f"Gallery check: {len(problems)} problem(s)", file=sys.stderr)
        sys.exit(1)
    print("Gallery check: clean")


def cmd_check(args):
    """Check an HTML viewer page for JS console errors."""
    from agentcad.webdebug import check_html

    html_path = Path(args.html_file)
    if not html_path.exists():
        print(f"Error: File not found: {html_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Checking {html_path} with headless Chromium...")
    result = check_html(html_path, timeout_ms=args.timeout)
    print(result.summary())
    sys.exit(0 if result.success else 1)


# --- the command tree -----------------------------------------------------------
#
# Each command group registers its own subparsers in a function below, and
# command modules in ``agentcad.commands`` register more without editing this
# file. ``build_parser()`` returns the whole tree so other code (tests, the
# policy contract, exporters) can walk it.

DEFINE_HELP = "Override a model parameter (repeatable)"
SLICED_FILE_HELP = "Sliced file: Prusa binary G-code (.bgcode) or plain G-code"


def _register_render_export(sub, groups):
    p_render = sub.add_parser("render", help="Render CAD source to PNG images")
    p_render.add_argument("source_file", help="Path to CAD source file")
    p_render.add_argument("-o", "--output-dir", help="Output directory (default: ./output)")
    p_render.add_argument("-v", "--views", nargs="+", choices=list(STANDARD_PRESETS.keys()),
                          help="Camera presets to render (default: the standard multi-view set)")
    p_render.add_argument("-s", "--size", type=int, default=1024, help="Image size (default: 1024)")
    p_render.add_argument("-e", "--engine", default=None,
                          help="CAD engine (default: the project's agentcad.toml, else openscad)")
    p_render.add_argument("--report", action="store_true",
                          help="Print the measured report (the tray) instead of raw metadata")
    p_render.add_argument("-D", "--define", action="append", metavar="VAR=VAL", help=DEFINE_HELP)
    p_render.set_defaults(func=cmd_render)

    p_export = sub.add_parser("export", help="Export CAD source to STL or another format")
    p_export.add_argument("source_file", help="Path to CAD source file")
    p_export.add_argument("-o", "--output", help="Output path (default: source name with the format's extension)")
    p_export.add_argument("-f", "--format", default="stl",
                          help="Export format (default: stl; see `agentcad info` for each engine's list)")
    p_export.add_argument("-e", "--engine", default=None,
                          help="CAD engine (default: the project's agentcad.toml, else openscad)")
    p_export.add_argument("--variants", metavar="KNOB=v1,v2,...", default=None,
                          help="Export one file per value of KNOB, the value in each filename (a clearance plate)")
    p_export.add_argument("-D", "--define", action="append", metavar="VAR=VAL", help=DEFINE_HELP)
    p_export.set_defaults(func=cmd_export)


def _register_projects(sub, groups):
    p_info = sub.add_parser("info", help="Show engine and environment info")
    p_info.set_defaults(func=cmd_info)

    p_newproj = sub.add_parser("new-project", help="Create a design project folder")
    p_newproj.add_argument("name", help="Project name")
    p_newproj.add_argument("-b", "--base-dir", help="Override output base directory")
    p_newproj.add_argument("-d", "--description", default="", help="Project description")
    p_newproj.add_argument("-e", "--engine", default="openscad", help="CAD engine")
    p_newproj.set_defaults(func=cmd_new_project)

    p_projects = sub.add_parser("projects", help="List all AgentCAD projects")
    p_projects.set_defaults(func=cmd_projects)

    p_status = sub.add_parser("status", help="Show project status")
    p_status.add_argument("project", help="Project name or path")
    p_status.set_defaults(func=cmd_status)

    p_open = sub.add_parser("open", help="Print project path")
    p_open.add_argument("project", help="Project name")
    p_open.set_defaults(func=cmd_open)

    p_cinit = sub.add_parser("config-init", help="Create agentcad.toml in current dir")
    p_cinit.add_argument("-n", "--name", help="Project name (default: dir name)")
    p_cinit.add_argument("-d", "--description", default="", help="Description")
    p_cinit.add_argument("-f", "--force", action="store_true", help="Overwrite existing")
    p_cinit.set_defaults(func=cmd_config_init)

    p_cshow = sub.add_parser("config-show", help="Show resolved project config")
    p_cshow.set_defaults(func=cmd_config_show)


def _register_probe(sub, groups):
    p_probe = sub.add_parser("probe", help="RECOVER: section loops, arc fits and an inventory of a STEP or build123d source")
    sub_probe = p_probe.add_subparsers(dest="probe_cmd", required=True)
    groups["probe"] = sub_probe
    for name, func, hlp in (("section", cmd_probe_section, "Closed loops of exact edges on named planes (loops.json)"),
                            ("inventory", cmd_probe_inventory, "bbox, volume, census, cylinder axes, loops on planes")):
        pp = sub_probe.add_parser(name, help=hlp)
        pp.add_argument("source", help="STEP file or build123d program")
        pp.add_argument("--planes", nargs="*", default=None, help="x=|y=|z= followed by a number or mid")
        pp.add_argument("--max-loops", type=int, default=None, help="Keep at most N loops per plane (printed when applied; default none)")
        pp.add_argument("--show", type=int, default=12, help="Lines to print per plane or face list (default 12)")
        pp.add_argument("-o", "--output", default=None, help="Write the JSON record here")
        pp.add_argument("-D", "--define", action="append", metavar="VAR=VAL", help=DEFINE_HELP)
        pp.set_defaults(func=func)

    pf = sub_probe.add_parser("fillet", help="Why a fillet fails: the selected chain on the LIVE part at the call, steps under 0.2 mm, sizes each edge takes")
    pf.add_argument("source", help="build123d program")
    pf.add_argument("--at", default="fillet", help="fillet or chamfer (default fillet)")
    pf.add_argument("--index", type=int, default=0, help="Which call of --at to stop at, counting from 0")
    pf.add_argument("--radii", default=None, help="Comma-separated sizes to try (default 1.0,0.6,0.4,0.25)")
    pf.add_argument("--short", type=float, default=0.2, help="Edges and steps shorter than this are flagged (mm)")
    pf.add_argument("-o", "--output", default=None, help="Write the JSON record here")
    pf.add_argument("-D", "--define", action="append", metavar="VAR=VAL", help=DEFINE_HELP)
    pf.set_defaults(func=cmd_probe_fillet)

    pd = sub_probe.add_parser("draft", help="Draft per face against a pull direction: release, drag, undercut; faces along the pull reported, not judged")
    pd.add_argument("source", help="STEP file or build123d program")
    pd.add_argument("--pull", default=None, help="Pull direction x,y,z (default 0,0,1)")
    pd.add_argument("--min-draft", type=float, default=None, help="Fail (exit 1) when a side face has less draft than this, in degrees")
    pd.add_argument("--samples", type=int, default=7, help="Grid samples per face side (default 7)")
    pd.add_argument("--show", type=int, default=12, help="Failing faces to list (default 12)")
    pd.add_argument("-o", "--output", default=None, help="Write draft.json here")
    pd.add_argument("-D", "--define", action="append", metavar="VAR=VAL", help=DEFINE_HELP)
    pd.set_defaults(func=cmd_probe_draft)


def _register_gcode(sub, groups):
    p_gcode = sub.add_parser("gcode", help="READ what the slicer produced: decode .bgcode, block table, metadata, thumbnails")
    sub_gcode = p_gcode.add_subparsers(dest="gcode_cmd", required=True)
    groups["gcode"] = sub_gcode
    pg = sub_gcode.add_parser("decode", help="A .bgcode as plain G-code (plain files pass through)")
    pg.add_argument("file", help=SLICED_FILE_HELP)
    pg.add_argument("-o", "--output", default=None, help="Write here instead of stdout")
    pg.add_argument("--no-verify", action="store_true", help="Skip the CRC32 checks (says so on stderr)")
    pg.set_defaults(func=cmd_gcode_decode)
    pg = sub_gcode.add_parser("info", help="Header, block table, printer and print metadata, thumbnails")
    pg.add_argument("file", help=SLICED_FILE_HELP)
    pg.add_argument("--no-verify", action="store_true", help="Skip the CRC32 checks")
    pg.set_defaults(func=cmd_gcode_info)
    pg = sub_gcode.add_parser("summary", help="Layers, filament, extrusion by object and feature, where supports are")
    pg.add_argument("file", help=SLICED_FILE_HELP)
    pg.add_argument("--json", action="store_true", help="Print the summary record (schema agentcad.gcode.summary/1)")
    pg.set_defaults(func=cmd_gcode_summary)
    pg = sub_gcode.add_parser("check", help="Compare a sliced file's settings with the [slice] intent; exit 1 on an error")
    pg.add_argument("file", help=SLICED_FILE_HELP)
    pg.add_argument("--project", default=None, help="Project folder or agentcad.toml carrying the [slice] table")
    pg.add_argument("--intent", default=None, help="Any TOML file with a [slice] table (a job.toml, for one)")
    pg.add_argument("--json", action="store_true", help="Findings as JSON, each with its sentence")
    pg.set_defaults(func=cmd_gcode_check)
    pg = sub_gcode.add_parser("supports", help="Where supports touch each object: contact bands (bed frame)")
    pg.add_argument("file", help=SLICED_FILE_HELP)
    pg.add_argument("--contact-distance", type=float, default=None,
                    help="Support-to-part gap in mm (default: the file's support_material_contact_distance)")
    pg.add_argument("--min-area", type=float, default=1.0, help="Hide bands smaller than this (mm2, default 1)")
    pg.add_argument("--placement", default=None, help="Placement sidecar (agentcad.placement/1): bands in each STL's frame")
    pg.add_argument("--stl-root", default=None, help="Folder the sidecar's STL paths are relative to (default: the sidecar's)")
    pg.add_argument("--png", default=None, help="Render the parts with contact cells (green outside, red in a cavity)")
    pg.add_argument("--json", action="store_true", help="Bands as JSON")
    pg.set_defaults(func=cmd_gcode_supports)
    pg = sub_gcode.add_parser("view", help="A standalone page of the toolpaths: feature colours, toggles, layer range")
    pg.add_argument("file", help=SLICED_FILE_HELP)
    pg.add_argument("-o", "--output", default=None, help="Page path (default: <file>.toolpaths.html)")
    pg.add_argument("--budget-mb", type=float, default=8.0, help="Embedded toolpath budget; over it, every Nth layer")
    pg.add_argument("--placement", default=None, help="Placement sidecar: mark support contact cells (red in a cavity)")
    pg.add_argument("--stl-root", default=None, help="Folder the sidecar's STL paths are relative to")
    pg.add_argument("--artifact", metavar="DIR", default=None,
                    help="Write DIR/index.html as a page fragment (no document shell) plus files.json, for an artifact host")
    pg.set_defaults(func=cmd_gcode_view)
    pg = sub_gcode.add_parser("thumbnails", help="Write the thumbnails a .bgcode carries")
    pg.add_argument("file", help=SLICED_FILE_HELP)
    pg.add_argument("-o", "--output", required=True, help="Directory to write into")
    pg.set_defaults(func=cmd_gcode_thumbnails)


def _register_compare_fit(sub, groups):
    p_cmp = sub.add_parser("compare", help="COMPARE: loop counts per plane (a gate), sampled deviation, overlays")
    p_cmp.add_argument("original", help="The reference part: STEP file or build123d program")
    p_cmp.add_argument("candidate", help="The part compared with it: STEP file or build123d program")
    p_cmp.add_argument("--planes", nargs="*", default=None,
                       help="Section planes for the loop-count gate: x=|y=|z= followed by a number or mid "
                            "(default: none, so no gate)")
    p_cmp.add_argument("--window", action="append", metavar="NAME=x0,y0,x1,y1", help="Per-window distances on the section plane (repeatable)")
    p_cmp.add_argument("-o", "--output-dir", default=None, help="Overlay PNGs and compare.json go here")
    p_cmp.add_argument("--max-loops", type=int, default=None,
                       help="Keep at most N loops per plane (printed when applied; default none)")
    p_cmp.add_argument("-D", "--define", action="append", metavar="VAR=VAL",
                       help="Override a model parameter of a program input (repeatable)")
    p_cmp.set_defaults(func=cmd_compare)

    p_fit = sub.add_parser("fit", help="Pose two parts and measure interference, clearance, mate windows, insertion")
    p_fit.add_argument("a", help="First part (STEP or build123d source); the fixed one")
    p_fit.add_argument("b", help="Second part, posed by --mate, --map or --offset/--spin")
    p_fit.add_argument("--offset", default=None, metavar="X,Y,Z", help="Translation of B in mm (default 0,0,0)")
    p_fit.add_argument("--spin", type=float, default=0.0, help="Rotation of B in degrees about --spin-axis")
    p_fit.add_argument("--spin-axis", default="z", choices=["x", "y", "z"], help="Axis of the --spin rotation (default z)")
    p_fit.add_argument("--map", nargs="+", metavar="KEY=VALUE", default=None,
                       help="Pose B by axis=x|y|z spin=DEG offset=x,y,z: a turn about the axis, then the offset "
                            "(instead of --offset/--spin)")
    p_fit.add_argument("--mate", action="append", metavar="NAME", default=None,
                       help="Pose B from the datums both parts declare for this mate and measure its window "
                            "(repeatable; the first poses, the rest are checked against it)")
    p_fit.add_argument("--a-mates", default=None, metavar="PATH",
                       help="Where part A declares its mates (toml or folder; default: searched upward from A)")
    p_fit.add_argument("--b-mates", default=None, metavar="PATH",
                       help="Where part B declares its mates (toml or folder; default: searched upward from B)")
    p_fit.add_argument("--window", action="append", metavar="NAME=x0,y0,z0,x1,y1,z1", help="Mate window (repeatable)")
    p_fit.add_argument("--mates-from", default=None, metavar="PROJECT", help="Read [mates] windows from a project's agentcad.toml")
    p_fit.add_argument("--sweep", default=None, choices=["x", "y", "z"], help="Insertion sweep axis")
    p_fit.add_argument("--travel", type=float, default=10.0, help="Insertion sweep travel in mm")
    p_fit.add_argument("--sweep-steps", type=int, default=10, help="Positions along the insertion sweep (default 10)")
    p_fit.add_argument("--step", type=float, default=None,
                       help="Surface sampling spacing in mm for window clearances and contacts "
                            "(default: part A's diagonal / 100)")
    p_fit.add_argument("--contact-mm", type=float, default=0.05,
                       help="Report where the surfaces come within this distance, as regions "
                            "(default 0.05; a negative value skips it)")
    p_fit.add_argument("--allow", type=float, default=0.0, help="Interference tolerated before the command fails (mm^3)")
    p_fit.add_argument("-o", "--output-dir", default=None, help="Renders and fit.json go here")
    p_fit.add_argument("--record", metavar="PROJECT", nargs="*", default=None,
                       help="Record the fit (time, both parts' parameters, verdict) in the print manifest of each "
                            "PROJECT; with no PROJECT, in both parts' own projects")
    p_fit.add_argument("--a-define", action="append", metavar="VAR=VAL", help="Override a parameter of part A (repeatable)")
    p_fit.add_argument("--b-define", action="append", metavar="VAR=VAL", help="Override a parameter of part B (repeatable)")
    p_fit.set_defaults(func=cmd_fit)


def _register_viewers(sub, groups):
    p_gallery = sub.add_parser("gallery", help="Build or check a static gallery of project viewers")
    sub_gallery = p_gallery.add_subparsers(dest="gallery_cmd", required=True)
    groups["gallery"] = sub_gallery
    p_gb = sub_gallery.add_parser("build", help="Build the gallery page and copy the viewers under it")
    p_gb.add_argument("-o", "--output", default="site", help="Gallery folder (default: site)")
    p_gb.add_argument("--projects", nargs="*", default=None, help="Project folder globs (default: every project under designs_dir)")
    p_gb.add_argument("--designs-dir", default=None, help="Designs directory to scan when --projects is not given")
    p_gb.add_argument("--title", default="agentcad gallery", help="Page title (default: agentcad gallery)")
    p_gb.add_argument("--no-copy", action="store_true", help="Link the viewers in place instead of copying them")
    p_gb.add_argument("--max-mb", type=float, default=200.0, help="Size budget for copied viewers (default 200)")
    p_gb.set_defaults(func=cmd_gallery_build)
    p_gc = sub_gallery.add_parser("check", help="Verify every link and thumbnail of a built gallery")
    p_gc.add_argument("gallery_dir", help="A gallery folder written by `agentcad gallery build`")
    p_gc.set_defaults(func=cmd_gallery_check)

    p_viewer = sub.add_parser("viewer", help="Regenerate HTML viewer from project files")
    p_viewer.add_argument("project", help="Project name (folder under designs_dir) or path")
    p_viewer.add_argument("--tag", default=None, help="Regenerate the viewer of a frozen tag (tags/<tag>/index.html)")
    p_viewer.add_argument("--artifact", metavar="DIR", default=None,
                          help="Write a page fragment plus its files and files.json into DIR for an artifact host that supplies the document shell")
    p_viewer.add_argument("--title", default=None, help="Artifact title (default: the project name)")
    p_viewer.set_defaults(func=cmd_viewer)

    p_check = sub.add_parser("check", help="Check HTML viewer for JS errors")
    p_check.add_argument("html_file", help="Path to index.html")
    p_check.add_argument("-t", "--timeout", type=int, default=10000, help="Timeout in ms (default: 10000)")
    p_check.set_defaults(func=cmd_check)


def _register_session(sub, groups):
    p_session = sub.add_parser("session", help="Manage design sessions (iterative feedback loop)")
    sub_session = p_session.add_subparsers(dest="session_command")
    groups["session"] = sub_session

    p_ss = sub_session.add_parser("start", help="Start a new design session")
    p_ss.add_argument("project", help="Project name (folder under designs_dir) or path")
    p_ss.add_argument("--engine", help="Override project's default engine")
    p_ss.add_argument("--max-iter", type=int, default=10, help="Max iterations (default: 10)")
    p_ss.add_argument("-D", "--define", action="append", metavar="VAR=VAL",
                      help="Model parameter override applied to every iteration (repeatable)")
    p_ss.add_argument("--no-archive", action="store_true",
                      help="With --force: discard the previous record instead of archiving it")
    p_ss.add_argument("-f", "--force", action="store_true",
                      help="Overwrite an existing un-finalized session")
    p_ss.set_defaults(func=cmd_session_start)

    p_si = sub_session.add_parser("iterate", help="Add iteration: render source file, record")
    p_si.add_argument("project", help="Project name or path")
    p_si.add_argument("source_file", help="Path to CAD source file for this iteration")
    p_si.add_argument("-D", "--define", action="append", metavar="VAR=VAL",
                      help="Override a model parameter for this iteration only (repeatable)")
    p_si.add_argument("--all", action="store_true",
                      help="Also iterate every part subproject the project declares, with the same source")
    p_si.set_defaults(func=cmd_session_iterate)

    p_sr = sub_session.add_parser("reopen", help="Continue a finalized session (numbering carries on)")
    p_sr.add_argument("project", help="Project name or path")
    p_sr.set_defaults(func=cmd_session_reopen)

    p_st = sub_session.add_parser("tag", help="Freeze the latest iteration under tags/<name>/ for a review")
    p_st.add_argument("project", help="Project name or path")
    p_st.add_argument("tag", help="Tag name (a plain folder name, e.g. draft1)")
    p_st.add_argument("--note", default=None, help="What the tag is for")
    p_st.set_defaults(func=cmd_session_tag)

    p_sn = sub_session.add_parser("note", help="Add analysis note to current iteration")
    p_sn.add_argument("project", help="Project name or path")
    p_sn.add_argument("text", help="Note text")
    p_sn.set_defaults(func=cmd_session_note)

    p_sf = sub_session.add_parser("finalize", help="Finalize session: STL exports + HTML viewer")
    p_sf.add_argument("project", help="Project name or path")
    p_sf.add_argument("--all", action="store_true", help="Also finalize every declared part subproject")
    p_sf.add_argument("--export-all", action="store_true",
                      help="Re-export every iteration instead of reusing exports already on disk")
    p_sf.set_defaults(func=cmd_session_finalize)

    p_sst = sub_session.add_parser("status", help="Show session state")
    p_sst.add_argument("project", help="Project name or path")
    p_sst.set_defaults(func=cmd_session_status)


_REGISTRARS = (
    _register_render_export,
    _register_projects,
    _register_probe,
    _register_gcode,
    _register_compare_fit,
    _register_viewers,
    _register_session,
)


def _register_command_modules(sub, groups, packages):
    """Let each module in ``packages`` add commands; report and skip a module that fails."""
    for package in packages:
        for info in sorted(pkgutil.iter_modules(package.__path__), key=lambda m: m.name):
            name = f"{package.__name__}.{info.name}"
            try:
                module = importlib.import_module(name)
                register = getattr(module, "register", None)
                if callable(register):
                    register(sub, groups)
            except Exception as e:  # a broken command module must not take the whole CLI down
                print(f"Warning: command module {name} was skipped: {type(e).__name__}: {e}", file=sys.stderr)


def build_parser(command_packages=None):
    """The whole command tree. ``command_packages`` defaults to ``agentcad.commands``."""
    parser = argparse.ArgumentParser(
        prog="agentcad",
        description="Agentic feedback loop for parametric 3D CAD design",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")
    groups = {}
    for register in _REGISTRARS:
        register(sub, groups)
    if command_packages is None:
        from agentcad import commands
        command_packages = [commands]
    _register_command_modules(sub, groups, command_packages)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        sys.exit(0)
    if args.command == "session" and not getattr(args, "session_command", None):
        parser.parse_args(["session", "--help"])
    rc = args.func(args)
    if isinstance(rc, int) and rc:     # a command may return an exit status (gcode check: 1 on an error)
        sys.exit(rc)
