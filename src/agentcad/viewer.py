"""HTML design viewer generator.

Uses the agentcad.templating API to build interactive project viewer pages.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from agentcad.templating import Page

if TYPE_CHECKING:
    from agentcad.output import DesignProject


def _relative(base: Path, target: Path) -> str:
    try:
        return str(target.relative_to(base))
    except ValueError:
        return str(target)


def generate_html(project: "DesignProject") -> str:
    """Generate complete HTML viewer for a design project."""
    base = project.project_dir

    page = Page(project.name)
    for key, value in project.metadata.items():
        page.metadata(key, value)

    for v in project.variants:
        vb = page.variant(v.name)

        for key, value in v.params.items():
            # Notes are rendered separately, not as a param row
            if key == "notes":
                vb.notes(str(value))
            else:
                vb.param(key, value)

        for view_name, img_path in sorted(v.renders.items()):
            vb.render(view_name, _relative(base, img_path))

        if v.stl_path and v.stl_path.exists():
            stl_data = v.stl_path.read_bytes()
            vb.stl(_relative(base, v.stl_path), data=stl_data)

        code = v.source_code
        if not code and v.source_path and v.source_path.exists():
            code = v.source_path.read_text()
        if code:
            name = v.source_path.name if v.source_path else f"{v.name}.scad"
            vb.source(name, code)

        # Print manifest (if available on project)
        manifest = getattr(project, '_manifest', None)
        if manifest:
            from dataclasses import asdict
            vb.print_settings(asdict(manifest))

    return page.build()
