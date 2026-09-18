"""HTML design viewer generator.

Uses the agentcad.templating API to build interactive project viewer pages.
Nothing here assumes a source language: the extension and highlighting
language come from the project (set by the session from its engine), and the
on-disk scan in ``regenerate_from_project_dir`` builds its filename pattern
from the registered engines.
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional

from agentcad.templating import Page

if TYPE_CHECKING:
    from agentcad.config import ProjectConfig
    from agentcad.output import DesignProject


def _relative(base: Path, target: Path) -> str:
    try:
        return str(target.relative_to(base))
    except ValueError:
        return str(target)


def _preview_mesh(path: Path, target_bytes: int) -> Optional[Path]:
    """A decimated copy of ``path`` for display, or None when no decimator is available."""
    try:
        import pyvista as pv
    except ImportError:
        return None
    try:
        mesh = pv.read(str(path))
        size = path.stat().st_size
        reduction = max(0.0, min(0.95, 1.0 - target_bytes / max(size, 1)))
        preview = mesh.decimate_pro(reduction) if reduction > 0 else mesh
        out = path.with_name(path.stem + "_preview.stl")
        preview.save(str(out), binary=True)
        return out
    except Exception as e:  # any decimation failure means "link it"; the page still loads
        print(f"agentcad warning: mesh preview not built for {path.name} (linking instead): {e}", file=sys.stderr)
        return None


def generate_html(project: "DesignProject", embed_mb: Optional[float] = None, cdn: bool = False,
                  embed_only_latest: bool = False) -> str:
    """Generate complete HTML viewer for a design project.

    Meshes of a variant are embedded inline while their total stays under
    ``embed_mb`` (the output config's ``viewer_embed_mb`` by default); past
    it, a decimated preview is embedded when PyVista is available and the
    full file is linked, else the files are linked beside the page and a
    badge says so. Either way the page loads.
    """
    base = project.project_dir
    cap = int((embed_mb if embed_mb is not None else getattr(project.config, "viewer_embed_mb", 8.0)) * 1024 * 1024)

    page = Page(project.name, cdn=cdn)
    for key, value in project.metadata.items():
        page.metadata(key, value)

    for index, v in enumerate(project.variants):
        vb = page.variant(v.name)

        for key, value in v.params.items():
            # Notes are rendered separately, not as a param row
            if key == "notes":
                vb.notes(str(value))
            else:
                vb.param(key, value)

        for view_name, img_path in sorted(v.renders.items()):
            vb.render(view_name, _relative(base, img_path))

        meshes = [m for m in v.meshes if m.path.exists()]
        total = sum(m.path.stat().st_size for m in meshes)
        if meshes and embed_only_latest and index > 0:
            # an artifact serves no mesh files, so older versions carry none
            vb.mesh_note("older version: mesh not included in the artifact (see the renders)")
        elif meshes and total <= cap:
            for m in meshes:
                vb.mesh(m.name, _relative(base, m.path), data=m.path.read_bytes(), quantity=m.quantity)
        elif meshes:
            share = cap // max(len(meshes), 1)
            embedded = 0
            for m in meshes:
                preview = _preview_mesh(m.path, share)
                if preview is not None and preview.stat().st_size <= share:
                    vb.mesh(m.name, _relative(base, m.path), data=preview.read_bytes(), quantity=m.quantity)
                    embedded += 1
                else:
                    vb.mesh(m.name, _relative(base, m.path), data=None, quantity=m.quantity)
            mb = total / (1024 * 1024)
            vb.mesh_note(f"meshes total {mb:.1f} MB, over the {cap / (1024 * 1024):.0f} MB embed cap: "
                         + (f"{embedded} shown as decimated previews, " if embedded else "")
                         + "full files linked beside the page")

        code = v.source_code
        if not code and v.source_path and v.source_path.exists():
            code = v.source_path.read_text()
        if code:
            name = v.source_path.name if v.source_path else f"{v.name}{project.source_extension}"
            vb.source(name, code, language=project.syntax_language)

        # Print manifest (if available on project)
        manifest = getattr(project, '_manifest', None)
        if manifest:
            from dataclasses import asdict
            vb.print_settings(asdict(manifest))

    return page.build()


_ARTIFACT_STRIP = ('<!DOCTYPE html>', '<html lang="en">', '<head>', '</head>', '<body>', '</body>', '</html>',
                   '<meta charset="UTF-8">', '<meta name="viewport" content="width=device-width, initial-scale=1.0">')
_ARTIFACT_CODE_CSS = ('<style>pre code.hljs{display:block;overflow-x:auto;padding:1em;background:#0d1117;color:#c9d1d9}'
                      '.hljs-keyword,.hljs-built_in{color:#ff7b72}.hljs-string{color:#a5d6ff}.hljs-comment{color:#8b949e}'
                      '.hljs-number{color:#79c0ff}.hljs-title,.hljs-function{color:#d2a8ff}</style>')


def write_artifact(project: "DesignProject", out_dir: Path, title: Optional[str] = None) -> Path:
    """Write the viewer as a page fragment for publishing on an artifact host that supplies the document shell.

    The artifact host supplies doctype, head and body, blocks external
    stylesheets, serves supporting files only in web media types (images,
    scripts, styles, JSON: an STL is refused), and downloads started by the
    page are inert. So: the page becomes a fragment keeping its <title> and
    <style>; the highlight stylesheet is replaced by a small inline palette;
    the latest variant's meshes are embedded inline (base64) and older
    variants carry none; renders are copied beside the fragment and
    referenced relatively; download links become plain labels; and
    ``files.json`` maps every published image to its source so the publisher
    can pass the map straight through. The vendored scripts stay inline (an
    inline script is allowed; only external hosts are restricted).
    """
    import shutil

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = project.project_dir
    files: Dict[str, str] = {}

    html = generate_html(project, embed_only_latest=True)
    for tag in _ARTIFACT_STRIP:
        html = html.replace(tag, "", 1)
    if title:
        html = re.sub(r"<title>[^<]*</title>", f"<title>{title}</title>", html, count=1)
    html = re.sub(r'<link rel="stylesheet" href="https://cdnjs\.cloudflare\.com/ajax/libs/highlight\.js/[^"]+">',
                  _ARTIFACT_CODE_CSS, html, count=1)
    # copy the files the page references and rewrite download links to labels
    for v in project.variants:
        for view, img in v.renders.items():
            rel = _relative(base, img)
            if Path(img).exists():
                dest = out_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(img, dest)
                files[rel] = str(img)
    html = re.sub(r'<a href="([^"]+)" download class="stl-download">([^<]*)</a>',
                  r'<span class="stl-download" style="opacity:.6">\2: \1</span>', html)
    page = out_dir / "index.html"
    page.write_text(html)
    (out_dir / "files.json").write_text(json.dumps(files, indent=2))
    return page


def version_pattern(extensions: Iterable[str]) -> "re.Pattern[str]":
    """Regex for ``{name}_v{N}[_view].{ext}`` over the given extensions (no dots)."""
    alternatives = "|".join(re.escape(ext.lstrip(".").lower()) for ext in sorted(set(extensions)))
    return re.compile(
        r"^(?P<name>.+)_v(?P<ver>\d+)(?P<rest>(?:_[A-Za-z0-9]+)?)\.(?P<ext>" + alternatives + r")$",
        re.IGNORECASE,
    )


def _scan_versioned_files(directory: Path, ext: str) -> Dict[int, Dict]:
    """Scan a directory for files matching ``{name}_v{N}[_view].{ext}``.

    Returns: {version_number: {"name": str, "files": {key: path}}}
    where key is "" for the base file (no _view suffix) or the view name.
    """
    ext = ext.lstrip(".").lower()
    pattern = version_pattern([ext])
    result: Dict[int, Dict] = {}
    if not directory.exists():
        return result
    for f in sorted(directory.iterdir()):
        if not f.is_file():
            continue
        m = pattern.match(f.name)
        if not m:
            continue
        n = int(m.group("ver"))
        key = m.group("rest").lstrip("_") if m.group("rest") else ""
        entry = result.setdefault(n, {"name": m.group("name"), "files": {}})
        entry["files"][key] = f
    return result


def _load_session_notes(state_file: Path) -> Dict[int, List[str]]:
    """Iteration notes from a session state file, keyed by version number."""
    notes_by_version: Dict[int, List[str]] = {}
    if not state_file.exists():
        return notes_by_version
    try:
        data = json.loads(state_file.read_text())
        for it in data.get("iterations", []):
            if it.get("notes"):
                notes_by_version[int(it["number"])] = list(it["notes"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        print(f"agentcad warning: session notes unreadable (viewer built without them): {e}", file=sys.stderr)
    return notes_by_version


def regenerate_from_project_dir(
    project_dir: Path,
    cfg: Optional["ProjectConfig"] = None,
    artifact_dir: Optional[Path] = None,
    title: Optional[str] = None,
) -> Path:
    """Scan a project directory and regenerate index.html from files on disk.

    Sources:
      - source/{name}_vN{engine extension}
      - renders/{name}_vN_{view}.png
      - exports/{name}_vN.{stl|step|...}
      - exports/{name}.print.json (optional)
      - _work/session.json (optional - sources iteration notes)

    The engine named by the project config decides which source extension is
    scanned, so a ``.py`` project is never mistaken for another engine's.

    Returns path to generated index.html.

    Raises:
        RuntimeError if no versioned files are found.
    """
    from agentcad.config import find_project, ProjectConfig
    from agentcad.engines import get_engine, all_export_formats
    from agentcad.output import DesignProject

    project_dir = Path(project_dir)
    if cfg is None:
        cfg = find_project(project_dir) or ProjectConfig()

    engine = get_engine(cfg.engine, settings=cfg.engine_settings(cfg.engine))
    source_ext = engine.file_extension
    export_formats = all_export_formats()

    source_dir = project_dir / "source"
    renders_dir = project_dir / "renders"
    exports_dir = project_dir / "exports"

    src_versions = _scan_versioned_files(source_dir, source_ext)
    render_versions = _scan_versioned_files(renders_dir, "png")
    export_versions: Dict[str, Dict[int, Dict]] = {
        fmt: _scan_versioned_files(exports_dir, fmt) for fmt in export_formats
    }

    all_versions = set(src_versions) | set(render_versions)
    for versions in export_versions.values():
        all_versions |= set(versions)
    if not all_versions:
        raise RuntimeError(
            f"No versioned files found in {project_dir}. "
            f"Expected files matching {{name}}_v{{N}}[_view].({source_ext.lstrip('.')}|png|"
            f"{'|'.join(export_formats)}) in source/, renders/, or exports/."
        )

    notes_by_version = _load_session_notes(project_dir / "_work" / "session.json")

    # Set up the DesignProject (sharing the same dir)
    project = DesignProject(
        project_dir.name, cfg.output,
        source_extension=source_ext, syntax_language=engine.syntax_language,
    )
    # The scanned folder is the authority for where the page goes: a tag
    # folder or a project whose config points elsewhere must not have its
    # page written into designs_dir/<folder name>.
    project._project_dir = project_dir
    project.metadata["regenerated"] = datetime.now().isoformat()
    project.metadata["engine"] = engine.name
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

        # Mesh for the 3D view (STL is the only format the viewer can show)
        stl_versions = export_versions.get("stl", {})
        if n in stl_versions and "" in stl_versions[n]["files"]:
            variant.stl_path = stl_versions[n]["files"][""]

    # Load print manifest if present
    if exports_dir.exists():
        manifest_files = sorted(exports_dir.glob("*.print.json"))
        if manifest_files:
            from agentcad.manifest import PrintManifest
            try:
                project._manifest = PrintManifest.load(manifest_files[0])
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
                print(
                    f"agentcad warning: print manifest unreadable (viewer built without it): {e}",
                    file=sys.stderr,
                )

    # An assembly that declares parts shows their latest meshes with toggles
    if project.variants and cfg.parts:
        parts = []
        for folder, part_cfg in cfg.part_projects():
            exports = sorted((folder / "exports").glob("*_v*.stl"),
                             key=lambda p: int(re.search(r"_v(\d+)", p.stem).group(1)) if re.search(r"_v(\d+)", p.stem) else 0)
            if exports:
                parts.append((folder.name, exports[-1], part_cfg.quantity))
        if parts:
            project.variants[0].meshes = []
            for name, path, quantity in parts:
                project.variants[0].add_mesh(name, path, quantity=quantity)

    if artifact_dir is not None:
        return write_artifact(project, artifact_dir, title=title)
    return project.generate_viewer()
