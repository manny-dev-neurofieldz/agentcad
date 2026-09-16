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

    defines = _parse_defines(args.define) if args.define else None
    result = engine.export(source, output, fmt=fmt, defines=defines)
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
        print(f"{cfg.name or cfg.project_dir.name:<30} {cfg.engine:<12} {cfg.description[:40]}")


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

    # Refuse to overwrite an active (non-finalized) session unless --force.
    if session.state_file.exists() and not args.force:
        try:
            prior = json.loads(session.state_file.read_text())
        except (OSError, json.JSONDecodeError) as e:
            print(f"Warning: existing session state unreadable, starting fresh: {e}", file=sys.stderr)
            prior = {}
        if not prior.get("finalized", False) and prior.get("iterations"):
            print(f"Error: active session exists at {session.state_file} "
                  f"with {len(prior['iterations'])} iteration(s). "
                  f"Use --force to overwrite or `agentcad session finalize` first.",
                  file=sys.stderr)
            sys.exit(1)

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
    try:
        it = session.iterate(code)
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
        for key, value in it.render_result.metadata.items():
            print(f"    {key}: {value}")
    else:
        errors = it.render_result.errors if it.render_result else ["no render result"]
        for err in errors:
            print(f"  Render error: {err}", file=sys.stderr)
        sys.exit(1)


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

    if session._finalized:
        print(f"Session already finalized. Project: {session.project.project_dir}")
        return

    html_path = session.finalize()
    session.save_state()
    print(f"Session finalized.")
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
    try:
        html_path = regenerate_from_project_dir(project_dir, cfg=cfg)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Regenerated: {html_path}")


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
    p_viewer = sub.add_parser("viewer", help="Regenerate HTML viewer from project files")
    p_viewer.add_argument("project", help="Project name (folder under designs_dir) or path")
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
    p_ss.add_argument("-f", "--force", action="store_true",
                      help="Overwrite an existing un-finalized session")
    p_ss.set_defaults(func=cmd_session_start)

    p_si = sub_session.add_parser("iterate", help="Add iteration: render source file, record")
    p_si.add_argument("project", help="Project name or path")
    p_si.add_argument("source_file", help="Path to CAD source file for this iteration")
    p_si.set_defaults(func=cmd_session_iterate)

    p_sn = sub_session.add_parser("note", help="Add analysis note to current iteration")
    p_sn.add_argument("project", help="Project name or path")
    p_sn.add_argument("text", help="Note text")
    p_sn.set_defaults(func=cmd_session_note)

    p_sf = sub_session.add_parser("finalize", help="Finalize session: STL exports + HTML viewer")
    p_sf.add_argument("project", help="Project name or path")
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
