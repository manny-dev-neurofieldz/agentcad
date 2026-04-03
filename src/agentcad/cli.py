"""AgentCAD command-line interface."""

import argparse
import sys
from pathlib import Path

from agentcad import __version__
from agentcad.camera import MULTI_VIEW_DEFAULT, STANDARD_PRESETS


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
    result = engine.render(source, output_dir, views=views, image_size=args.size)

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

    result = engine.export_stl(source, output)
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
    p_render.set_defaults(func=cmd_render)

    # export
    p_export = sub.add_parser("export", help="Export CAD source to STL")
    p_export.add_argument("source_file", help="Path to CAD source file")
    p_export.add_argument("-o", "--output", help="Output STL path")
    p_export.add_argument("-e", "--engine", default="openscad", help="CAD engine (default: openscad)")
    p_export.set_defaults(func=cmd_export)

    # info
    p_info = sub.add_parser("info", help="Show engine and environment info")
    p_info.set_defaults(func=cmd_info)

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
