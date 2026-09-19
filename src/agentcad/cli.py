"""AgentCAD command-line interface."""

import argparse
import json
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


def cmd_probe_fillet(args):
    """Why a fillet fails: the selected chain on the live part at the step it is applied."""
    from agentcad import probe

    radii = [float(v) for v in args.radii.split(",")] if args.radii else (1.0, 0.6, 0.4, 0.25)
    res = probe.fillet_probe(Path(args.source), at=args.at, index=args.index, radii=radii, short_mm=args.short,
                             defines=_parse_defines(args.define) if args.define else None)
    print("\n".join(probe.render_fillet_probe(res)))
    if args.output:
        print(f"fillet.json: {probe.write_json(res, Path(args.output))}")


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
    """Pose two parts and measure interference, clearance, windows and insertion."""
    from agentcad import fit as fitmod

    windows = {}
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
    offset = [float(v) for v in args.offset.split(",")] if args.offset else (0, 0, 0)
    res = fitmod.fit(Path(args.a), Path(args.b),
                     a_defines=a_defs or None, b_defines=b_defs or None,
                     offset=offset, spin_deg=args.spin, spin_axis=args.spin_axis, windows=windows or None,
                     sweep_axis=args.sweep, sweep_travel=args.travel,
                     out_dir=Path(args.output_dir) if args.output_dir else None)
    print(f"interference {res['interference_mm3']:.4g} mm^3; clearance {res['clearance_mm']:.4g} mm")
    for name, w in (res.get("windows") or {}).items():
        if "min_mm" in w:
            print(f"  window {name}: min {w['min_mm']:.4g} mm (p05 {w['p05_mm']:.4g})")
        else:
            print(f"  window {name}: {w.get('note')}")
    for row in res.get("insertion") or []:
        print(f"  insertion at {row['offset_mm']:.3g} mm out: interference {row['interference_mm3']:.4g} mm^3")
    for name, path in (res.get("renders") or {}).items():
        print(f"  render {name}: {path}")
    if args.output_dir:
        print(f"fit.json: {fitmod.write_json(res, Path(args.output_dir) / 'fit.json')}")
    if args.record:
        from agentcad.manifest import PrintManifest
        manifests = sorted(Path(args.record).glob("exports/*.print.json"))
        if manifests:
            m = PrintManifest.load(manifests[0])
            key = (res["a"], res["b"], json.dumps(res["a_defines"], sort_keys=True), json.dumps(res["b_defines"], sort_keys=True))
            m.fit = [f for f in m.fit if (f.get("a"), f.get("b"), json.dumps(f.get("a_defines") or {}, sort_keys=True),
                                          json.dumps(f.get("b_defines") or {}, sort_keys=True)) != key]
            m.fit.append({k: res[k] for k in ("a", "b", "a_defines", "b_defines", "pose", "interference_mm3", "clearance_mm") if k in res}
                         | ({"windows": res["windows"]} if res.get("windows") else {}))
            m.save(manifests[0])
            print(f"recorded in {manifests[0]}")
        else:
            print(f"Warning: no print manifest under {args.record}/exports to record into", file=sys.stderr)
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


def main():
    parser = argparse.ArgumentParser(
        prog="agentcad",
        description="Agentic feedback loop for parametric 3D CAD design",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    # render
    p_render = sub.add_parser("render", help="Render CAD source to PNG images")
    p_render.add_argument("source_file", help="Path to CAD source file")
    p_render.add_argument("-o", "--output-dir", help="Output directory (default: ./output)")
    p_render.add_argument("-v", "--views", nargs="+", choices=list(STANDARD_PRESETS.keys()))
    p_render.add_argument("-s", "--size", type=int, default=1024, help="Image size (default: 1024)")
    p_render.add_argument("-e", "--engine", default=None,
                          help="CAD engine (default: the project's agentcad.toml, else openscad)")
    p_render.add_argument("--report", action="store_true",
                          help="Print the measured report (the tray) instead of raw metadata")
    p_render.add_argument("-D", "--define", action="append", metavar="VAR=VAL",
                          help="Override a model parameter (repeatable)")
    p_render.set_defaults(func=cmd_render)

    # export
    p_export = sub.add_parser("export", help="Export CAD source to STL or another format")
    p_export.add_argument("source_file", help="Path to CAD source file")
    p_export.add_argument("-o", "--output", help="Output path (default: source name with the format's extension)")
    p_export.add_argument("-f", "--format", default="stl",
                          help="Export format (default: stl; see `agentcad info` for each engine's list)")
    p_export.add_argument("-e", "--engine", default=None,
                          help="CAD engine (default: the project's agentcad.toml, else openscad)")
    p_export.add_argument("--variants", metavar="KNOB=v1,v2,...", default=None,
                          help="Export one file per value of KNOB, the value in each filename (a clearance plate)")
    p_export.add_argument("-D", "--define", action="append", metavar="VAR=VAL",
                          help="Override a model parameter (repeatable)")
    p_export.set_defaults(func=cmd_export)

    # info
    p_info = sub.add_parser("info", help="Show engine and environment info")
    p_info.set_defaults(func=cmd_info)

    # new-project
    p_newproj = sub.add_parser("new-project", help="Create a design project folder")
    p_newproj.add_argument("name", help="Project name")
    p_newproj.add_argument("-b", "--base-dir", help="Override output base directory")
    p_newproj.add_argument("-d", "--description", default="", help="Project description")
    p_newproj.add_argument("-e", "--engine", default="openscad", help="CAD engine")
    p_newproj.set_defaults(func=cmd_new_project)

    # projects
    p_projects = sub.add_parser("projects", help="List all AgentCAD projects")
    p_projects.set_defaults(func=cmd_projects)

    # status
    p_status = sub.add_parser("status", help="Show project status")
    p_status.add_argument("project", help="Project name or path")
    p_status.set_defaults(func=cmd_status)

    # open
    p_open = sub.add_parser("open", help="Print project path")
    p_open.add_argument("project", help="Project name")
    p_open.set_defaults(func=cmd_open)

    # config init
    p_cinit = sub.add_parser("config-init", help="Create agentcad.toml in current dir")
    p_cinit.add_argument("-n", "--name", help="Project name (default: dir name)")
    p_cinit.add_argument("-d", "--description", default="", help="Description")
    p_cinit.add_argument("-f", "--force", action="store_true", help="Overwrite existing")
    p_cinit.set_defaults(func=cmd_config_init)

    # config show
    p_cshow = sub.add_parser("config-show", help="Show resolved project config")
    p_cshow.set_defaults(func=cmd_config_show)

    # viewer (regenerate HTML from existing files)
    p_probe = sub.add_parser("probe", help="RECOVER: section loops, arc fits and an inventory of a STEP or build123d source")
    sub_probe = p_probe.add_subparsers(dest="probe_cmd", required=True)
    for name, func, hlp in (("section", cmd_probe_section, "Closed loops of exact edges on named planes (loops.json)"),
                            ("inventory", cmd_probe_inventory, "bbox, volume, census, cylinder axes, loops on planes")):
        pp = sub_probe.add_parser(name, help=hlp)
        pp.add_argument("source", help="STEP file or build123d program")
        pp.add_argument("--planes", nargs="*", default=None, help="x=|y=|z= followed by a number or mid")
        pp.add_argument("--max-loops", type=int, default=None, help="Keep at most N loops per plane (printed when applied; default none)")
        pp.add_argument("--show", type=int, default=12, help="Lines to print per plane or face list (default 12)")
        pp.add_argument("-o", "--output", default=None, help="Write the JSON record here")
        pp.add_argument("-D", "--define", action="append", metavar="VAR=VAL")
        pp.set_defaults(func=func)

    pf = sub_probe.add_parser("fillet", help="Why a fillet fails: the selected chain on the LIVE part at the call, steps under 0.2 mm, sizes each edge takes")
    pf.add_argument("source", help="build123d program")
    pf.add_argument("--at", default="fillet", help="fillet or chamfer (default fillet)")
    pf.add_argument("--index", type=int, default=0, help="Which call of --at to stop at, counting from 0")
    pf.add_argument("--radii", default=None, help="Comma-separated sizes to try (default 1.0,0.6,0.4,0.25)")
    pf.add_argument("--short", type=float, default=0.2, help="Edges and steps shorter than this are flagged (mm)")
    pf.add_argument("-o", "--output", default=None, help="Write the JSON record here")
    pf.add_argument("-D", "--define", action="append", metavar="VAR=VAL")
    pf.set_defaults(func=cmd_probe_fillet)

    p_cmp = sub.add_parser("compare", help="COMPARE: loop counts per plane (a gate), sampled deviation, overlays")
    p_cmp.add_argument("original")
    p_cmp.add_argument("candidate")
    p_cmp.add_argument("--planes", nargs="*", default=None)
    p_cmp.add_argument("--window", action="append", metavar="NAME=x0,y0,x1,y1", help="Per-window distances on the section plane (repeatable)")
    p_cmp.add_argument("-o", "--output-dir", default=None, help="Overlay PNGs and compare.json go here")
    p_cmp.add_argument("--max-loops", type=int, default=None)
    p_cmp.add_argument("-D", "--define", action="append", metavar="VAR=VAL")
    p_cmp.set_defaults(func=cmd_compare)

    p_fit = sub.add_parser("fit", help="Pose two parts and measure interference, clearance, mate windows, insertion")
    p_fit.add_argument("a", help="First part (STEP or build123d source); the fixed one")
    p_fit.add_argument("b", help="Second part, posed by --offset/--spin")
    p_fit.add_argument("--offset", default=None, metavar="X,Y,Z")
    p_fit.add_argument("--spin", type=float, default=0.0, help="Rotation of B in degrees about --spin-axis")
    p_fit.add_argument("--spin-axis", default="z", choices=["x", "y", "z"])
    p_fit.add_argument("--window", action="append", metavar="NAME=x0,y0,z0,x1,y1,z1", help="Mate window (repeatable)")
    p_fit.add_argument("--mates-from", default=None, metavar="PROJECT", help="Read [mates] windows from a project's agentcad.toml")
    p_fit.add_argument("--sweep", default=None, choices=["x", "y", "z"], help="Insertion sweep axis")
    p_fit.add_argument("--travel", type=float, default=10.0, help="Insertion sweep travel in mm")
    p_fit.add_argument("--allow", type=float, default=0.0, help="Interference tolerated before the command fails (mm^3)")
    p_fit.add_argument("-o", "--output-dir", default=None, help="Renders and fit.json go here")
    p_fit.add_argument("--record", metavar="PROJECT", default=None, help="Record the result in the project's print manifest fit table")
    p_fit.add_argument("--a-define", action="append", metavar="VAR=VAL")
    p_fit.add_argument("--b-define", action="append", metavar="VAR=VAL")
    p_fit.set_defaults(func=cmd_fit)

    p_gallery = sub.add_parser("gallery", help="Build or check a static gallery of project viewers")
    sub_gallery = p_gallery.add_subparsers(dest="gallery_cmd", required=True)
    p_gb = sub_gallery.add_parser("build", help="Build the gallery page and copy the viewers under it")
    p_gb.add_argument("-o", "--output", default="site", help="Gallery folder (default: site)")
    p_gb.add_argument("--projects", nargs="*", default=None, help="Project folder globs (default: every project under designs_dir)")
    p_gb.add_argument("--designs-dir", default=None, help="Designs directory to scan when --projects is not given")
    p_gb.add_argument("--title", default="agentcad gallery")
    p_gb.add_argument("--no-copy", action="store_true", help="Link the viewers in place instead of copying them")
    p_gb.add_argument("--max-mb", type=float, default=200.0, help="Size budget for copied viewers (default 200)")
    p_gb.set_defaults(func=cmd_gallery_build)
    p_gc = sub_gallery.add_parser("check", help="Verify every link and thumbnail of a built gallery")
    p_gc.add_argument("gallery_dir")
    p_gc.set_defaults(func=cmd_gallery_check)

    p_viewer = sub.add_parser("viewer", help="Regenerate HTML viewer from project files")
    p_viewer.add_argument("project", help="Project name (folder under designs_dir) or path")
    p_viewer.add_argument("--tag", default=None, help="Regenerate the viewer of a frozen tag (tags/<tag>/index.html)")
    p_viewer.add_argument("--artifact", metavar="DIR", default=None,
                          help="Write a page fragment plus its files and files.json into DIR for an artifact host that supplies the document shell")
    p_viewer.add_argument("--title", default=None, help="Artifact title (default: the project name)")
    p_viewer.set_defaults(func=cmd_viewer)

    # check
    p_check = sub.add_parser("check", help="Check HTML viewer for JS errors")
    p_check.add_argument("html_file", help="Path to index.html")
    p_check.add_argument("-t", "--timeout", type=int, default=10000, help="Timeout in ms (default: 10000)")
    p_check.set_defaults(func=cmd_check)

    # session (nested subcommands)
    p_session = sub.add_parser("session", help="Manage design sessions (iterative feedback loop)")
    sub_session = p_session.add_subparsers(dest="session_command")

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

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)
    if args.command == "session" and not getattr(args, "session_command", None):
        p_session.print_help()
        sys.exit(0)
    args.func(args)
