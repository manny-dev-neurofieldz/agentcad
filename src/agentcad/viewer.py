"""HTML design viewer generator.

Uses the agentcad.templating API to build interactive project viewer pages.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

from agentcad.templating import Page

if TYPE_CHECKING:
    from agentcad.config import ProjectConfig
    from agentcad.output import DesignProject


# {prefix}_v{N}{_view}.{ext} — capture name, version number, optional view suffix, extension
_VERSION_RE = re.compile(
    r"^(?P<name>.+)_v(?P<ver>\d+)(?P<rest>(?:_[A-Za-z0-9]+)?)\.(?P<ext>scad|py|stl|png)$",
    re.IGNORECASE,
)


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


def _scan_versioned_files(directory: Path, ext: str) -> Dict[int, Dict[str, Path]]:
    """Scan a directory for files matching {name}_v{N}{_view}.{ext}.

    Returns: {version_number: {"name": str, "files": {key: path}}}
    where key is "" for the base file (no _view suffix) or the view name.
    """
    result: Dict[int, Dict] = {}
    if not directory.exists():
        return result
    for f in sorted(directory.iterdir()):
        if not f.is_file():
            continue
        m = _VERSION_RE.match(f.name)
        if not m:
            continue
        if m.group("ext").lower() != ext.lower():
            continue
        n = int(m.group("ver"))
        key = m.group("rest").lstrip("_") if m.group("rest") else ""
        entry = result.setdefault(n, {"name": m.group("name"), "files": {}})
        entry["files"][key] = f
    return result


def regenerate_from_project_dir(
    project_dir: Path,
    cfg: Optional["ProjectConfig"] = None,
) -> Path:
    """Scan a project directory and regenerate index.html from files on disk.

    Sources:
      - source/{name}_vN.scad (or .py)
      - renders/{name}_vN_{view}.png
      - exports/{name}_vN.stl
      - exports/{name}.print.json (optional)
      - _work/session.json (optional — sources iteration notes)

    Returns path to generated index.html.

    Raises:
        RuntimeError if no versioned files are found.
    """
    from agentcad.config import find_project, ProjectConfig
    from agentcad.output import DesignProject

    project_dir = Path(project_dir)
    if cfg is None:
        cfg = find_project(project_dir) or ProjectConfig()

    source_dir = project_dir / "source"
    renders_dir = project_dir / "renders"
    exports_dir = project_dir / "exports"

    source_versions = _scan_versioned_files(source_dir, "scad")
    py_versions = _scan_versioned_files(source_dir, "py")
    render_versions = _scan_versioned_files(renders_dir, "png")
    stl_versions = _scan_versioned_files(exports_dir, "stl")

    # Merge source: prefer .scad, fall back to .py
    src_versions: Dict[int, Dict] = {}
    for n, v in source_versions.items():
        src_versions[n] = v
    for n, v in py_versions.items():
        src_versions.setdefault(n, v)

    all_versions = set(src_versions) | set(render_versions) | set(stl_versions)
    if not all_versions:
        raise RuntimeError(
            f"No versioned files found in {project_dir}. "
            f"Expected files matching pattern {{name}}_v{{N}}[_view].(scad|py|stl|png) in "
            f"source/, renders/, or exports/."
        )

    # Try to load session notes (preserves iteration history)
    notes_by_version: Dict[int, List[str]] = {}
    state_file = project_dir / "_work" / "session.json"
    if state_file.exists():
        try:
            data = json.loads(state_file.read_text())
            for it in data.get("iterations", []):
                if it.get("notes"):
                    notes_by_version[int(it["number"])] = list(it["notes"])
        except Exception:
            pass

    # Set up the DesignProject (sharing the same dir)
    config_output = cfg.output if cfg else None
    project = DesignProject(project_dir.name, config_output)
    project.metadata["regenerated"] = datetime.now().isoformat()
    project.metadata["engine"] = (cfg.engine if cfg and cfg.engine else "")
    project.metadata["regenerated_from"] = str(project_dir)

    # Add variants in REVERSE order (latest first), matching session.finalize()
    sorted_versions = sorted(all_versions, reverse=True)
    is_latest = True
    for n in sorted_versions:
        label = f"v{n}"
        if is_latest:
            label += " (latest)"
            is_latest = False
        params: Dict[str, object] = {"iteration": n}
        if notes_by_version.get(n):
            params["notes"] = "\n".join(notes_by_version[n])

        variant = project.add_variant(label, params)

        # Source
        if n in src_versions and "" in src_versions[n]["files"]:
            src_path = src_versions[n]["files"][""]
            variant.source_path = src_path
            variant.source_code = src_path.read_text()

        # Renders
        if n in render_versions:
            for view, path in render_versions[n]["files"].items():
                view_key = view or "default"
                variant.renders[view_key] = path

        # STL
        if n in stl_versions and "" in stl_versions[n]["files"]:
            variant.stl_path = stl_versions[n]["files"][""]

    # Load print manifest if present
    if exports_dir.exists():
        manifest_files = list(exports_dir.glob("*.print.json"))
        if manifest_files:
            from agentcad.manifest import PrintManifest
            try:
                project._manifest = PrintManifest.load(manifest_files[0])
            except Exception:
                pass

    return project.generate_viewer()
