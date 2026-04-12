"""AgentCAD command-line interface."""

import argparse
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


def cmd_render(args):
    """Render a CAD source file to PNG images."""
    from agentcad.engines import get_engine

    engine = get_engine(args.engine)
    if not engine.available():
        print(f"Error: {engine.name} is not available.", file=sys.stderr)
        sys.exit(1)

    source = Path(args.source_file)
    if not source.exists():
        print(f"Error: File not found: {source}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir) if args.output_dir else source.parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    views = args.views if args.views else MULTI_VIEW_DEFAULT
    defines = _parse_defines(args.define) if args.define else None
    result = engine.render(source, output_dir, views=views, image_size=args.size, defines=defines)

    if result.errors:
        for err in result.errors:
            print(f"Error: {err}", file=sys.stderr)

    for view_name, img_path in result.images.items():
        print(f"  {view_name}: {img_path}")

    if result.success:
        print(f"\nRendered {len(result.images)} view(s) in {result.render_time_ms:.0f}ms")
    else:
        sys.exit(1)


def cmd_export(args):
    """Export a CAD source file to STL."""
    from agentcad.engines import get_engine

    engine = get_engine(args.engine)
    source = Path(args.source_file)
    output = Path(args.output) if args.output else source.with_suffix(".stl")

    defines = _parse_defines(args.define) if args.define else None
    result = engine.export_stl(source, output, defines=defines)
    if result.success:
        print(f"Exported: {result.stl_path} ({result.facet_count} facets, {result.render_time_ms:.0f}ms)")
    else:
        for err in result.errors:
            print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)


def cmd_info(args):
    """Show engine and environment info."""
    from agentcad.engines import list_engines, get_engine

    print(f"AgentCAD v{__version__}")
    print(f"Available engines: {list_engines()}")
    for name in list_engines():
        eng = get_engine(name)
        status = "available" if eng.available() else "not found"
        print(f"  {eng.name}: {status}")
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
    config_path = path / CONFIG_FILENAME
    if not config_path.exists():
        desc = args.description if args.description else ""
        engine = args.engine if args.engine else "openscad"
        config_path.write_text(generate_config_template(args.name, desc, engine))

    print(f"Created project: {path}")
    print(f"  agentcad.toml — project config")
    print(f"  source/       — .scad source files")
    print(f"  renders/      — multi-view PNGs")
    print(f"  exports/      — STL files")


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
    p_render.add_argument("-e", "--engine", default="openscad", help="CAD engine (default: openscad)")
    p_render.add_argument("-D", "--define", action="append", metavar="VAR=VAL",
                          help="Override OpenSCAD variable (repeatable)")
    p_render.set_defaults(func=cmd_render)

    # export
    p_export = sub.add_parser("export", help="Export CAD source to STL")
    p_export.add_argument("source_file", help="Path to CAD source file")
    p_export.add_argument("-o", "--output", help="Output STL path")
    p_export.add_argument("-e", "--engine", default="openscad", help="CAD engine (default: openscad)")
    p_export.add_argument("-D", "--define", action="append", metavar="VAR=VAL",
                          help="Override OpenSCAD variable (repeatable)")
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

    # check
    p_check = sub.add_parser("check", help="Check HTML viewer for JS errors")
    p_check.add_argument("html_file", help="Path to index.html")
    p_check.add_argument("-t", "--timeout", type=int, default=10000, help="Timeout in ms (default: 10000)")
    p_check.set_defaults(func=cmd_check)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)
    args.func(args)
