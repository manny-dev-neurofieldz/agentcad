"""Lightweight HTML templating engine for AgentCAD.

Provides a Pythonic API for building HTML pages from components.
Uses stdlib string.Template for page-level layout and a component
builder pattern for structured content assembly.

Usage:
    page = Page("My Design", template="viewer.html")
    page.metadata("engine", "OpenSCAD")

    with page.variant("Bracket v1") as v:
        v.param("width", 40, "mm")
        v.render("iso", "renders/bracket_iso.png")
        v.render("front", "renders/bracket_front.png")
        v.stl("exports/bracket.stl")
        v.source("bracket source", code, language="openscad")

    html = page.build()
"""

import html as _html
from pathlib import Path
from string import Template
from typing import Any, List, Optional, Tuple

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _esc(text: Any) -> str:
    """HTML-escape any value."""
    return _html.escape(str(text))


class Table:
    """HTML table builder."""

    def __init__(self, headers: Optional[List[str]] = None, css_class: str = "params"):
        self.headers = headers
        self.rows: List[Tuple[str, ...]] = []
        self.css_class = css_class

    def row(self, *cells: Any) -> "Table":
        self.rows.append(tuple(str(c) for c in cells))
        return self

    def build(self) -> str:
        if not self.rows:
            return ""
        parts = [f'<table class="{_esc(self.css_class)}">']
        if self.headers:
            parts.append("<thead><tr>")
            parts.extend(f"<th>{_esc(h)}</th>" for h in self.headers)
            parts.append("</tr></thead>")
        parts.append("<tbody>")
        for row in self.rows:
            parts.append("<tr>")
            parts.extend(f"<td>{_esc(c)}</td>" for c in row)
            parts.append("</tr>")
        parts.append("</tbody></table>")
        return "".join(parts)


class Details:
    """Collapsible details/summary block."""

    def __init__(self, summary: str, open_: bool = False):
        self.summary = summary
        self.open = open_
        self.content = ""

    def body(self, html_content: str) -> "Details":
        self.content = html_content
        return self

    def build(self) -> str:
        if not self.content:
            return ""
        attr = " open" if self.open else ""
        return (
            f"<details{attr}><summary>{_esc(self.summary)}</summary>"
            f"{self.content}</details>"
        )


class Gallery:
    """Image gallery with labeled views."""

    def __init__(self):
        self.items: List[Tuple[str, str]] = []  # (label, src_path)

    def image(self, label: str, src: str) -> "Gallery":
        self.items.append((label, src))
        return self

    def build(self) -> str:
        if not self.items:
            return "<p>No renders available</p>"
        parts = []
        for label, src in self.items:
            parts.append(
                f'<div class="render-item">'
                f'<img src="{_esc(src)}" alt="{_esc(label)}" loading="lazy">'
                f'<span class="view-label">{_esc(label)}</span></div>'
            )
        return "\n".join(parts)


class CodeBlock:
    """Syntax-highlighted source code in a details block."""

    def __init__(self, title: str, code: str, language: str = "plaintext"):
        self.title = title
        self.code = code
        self.language = language

    def build(self) -> str:
        if not self.code:
            return ""
        return Details(f"Source Code — {self.title}").body(
            f'<pre><code class="language-{_esc(self.language)}">'
            f'{_esc(self.code)}</code></pre>'
        ).build()


class Button:
    """Action button or download link."""

    @staticmethod
    def download(label: str, href: str) -> str:
        return f'<a href="{_esc(href)}" download class="stl-download">{_esc(label)}</a>'

    @staticmethod
    def action(label: str, onclick: str, css_class: str = "stl-view") -> str:
        # onclick is trusted internal JS — don't HTML-escape it
        return f'<button onclick="{onclick}" class="{css_class}">{_esc(label)}</button>'


class VariantBuilder:
    """Builder for a single design variant section."""

    _id_counter = 0

    def __init__(self, name: str):
        VariantBuilder._id_counter += 1
        self._id = VariantBuilder._id_counter
        self.name = name
        self._params = Table(["Parameter", "Value"])
        self._gallery = Gallery()
        self._stl_path: Optional[str] = None
        self._stl_data: Optional[bytes] = None
        #: (name, relative path, bytes or None, quantity) per mesh of the variant
        self._meshes: List[tuple] = []
        self._mesh_note: str = ""
        self._source_title = ""
        self._source_code = ""
        self._source_language = "plaintext"
        self._notes: List[str] = []
        self._print_manifest: Optional[dict] = None

    def param(self, key: str, value: Any, unit: str = "") -> "VariantBuilder":
        display = f"{value} {unit}".strip() if unit else str(value)
        self._params.row(key, display)
        return self

    def render(self, view: str, path: str) -> "VariantBuilder":
        self._gallery.image(view, path)
        return self

    def stl(self, path: str, data: Optional[bytes] = None) -> "VariantBuilder":
        """Single-mesh compatibility: one mesh named after the variant."""
        self._stl_path = path
        self._stl_data = data
        return self.mesh(self.name, path, data)

    def mesh(self, name: str, path: str, data: Optional[bytes] = None, quantity: int = 1) -> "VariantBuilder":
        """Add one mesh; ``data`` inline when given, else loaded from ``path`` beside the page."""
        self._meshes.append((name, path, data, quantity))
        return self

    def mesh_note(self, text: str) -> "VariantBuilder":
        """A badge shown on the 3D tab (why a mesh is linked rather than embedded)."""
        self._mesh_note = text
        return self

    def notes(self, text: str) -> "VariantBuilder":
        self._notes.append(text)
        return self

    def print_settings(self, manifest_dict: dict) -> "VariantBuilder":
        self._print_manifest = manifest_dict
        return self

    def source(self, title: str, code: str, language: str = "plaintext") -> "VariantBuilder":
        self._source_title = title
        self._source_code = code
        self._source_language = language
        return self

    def build(self, variant_template: Template) -> str:
        import base64

        stl_buttons = ""
        stl_embed = ""
        if self._meshes:
            blocks = []
            for name, path, data, quantity in self._meshes:
                label = _esc(name) + (f" x{quantity}" if quantity and quantity > 1 else "")
                stl_buttons += Button.download(f"Download {label}", path) + " "
                if data is not None:
                    b64 = base64.b64encode(data).decode("ascii")
                    blocks.append(f'<script class="mesh-data" type="application/octet-stream" '
                                  f'data-variant="{self._id}" data-name="{_esc(name)}">{b64}</script>')
                else:
                    blocks.append(f'<script class="mesh-data" type="application/octet-stream" '
                                  f'data-variant="{self._id}" data-name="{_esc(name)}" data-src="{_esc(path)}"></script>')
            stl_buttons += Button.action("View 3D", f"loadVariantMeshes('{self._id}')")
            stl_embed = "\n".join(blocks)
        if self._mesh_note:
            stl_buttons += f' <span class="mesh-badge">{_esc(self._mesh_note)}</span>'

        params_html = ""
        if self._params.rows:
            params_html = Details("Parameters", open_=True).body(
                self._params.build()
            ).build()

        notes_html = ""
        if self._notes:
            notes_content = "\n".join(self._notes)
            notes_html = f'<div class="notes-raw">{notes_content}</div>'

        # Print manifest table
        print_html = "<p>No print settings available</p>"
        if self._print_manifest:
            pt = Table(["Setting", "Value"], css_class="print-table")
            skip = {"custom", "agent_notes", "stl_filename", "created"}
            for k, v in self._print_manifest.items():
                if k in skip or not v:
                    continue
                label = k.replace("_", " ").title()
                val = str(v)
                pt.row(label, val)
            print_html = pt.build()

        return variant_template.substitute(
            variant_id=self._id,
            variant_name=_esc(self.name),
            stl_buttons=stl_buttons + stl_embed,
            params_table=params_html,
            print_manifest=print_html,
            notes_block=notes_html,
            gallery_items=self._gallery.build(),
            source_block=CodeBlock(self._source_title, self._source_code, self._source_language).build(),
        )


class Page:
    """Top-level HTML page builder."""

    #: Pinned CDN builds used when a page must not carry vendored scripts
    #: (an artifact fragment loads scripts only from the allowed hosts).
    CDN_SCRIPTS = (
        "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js",
        "https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js",
        "https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/STLLoader.js",
    )

    def __init__(self, title: str, template: str = "viewer.html", cdn: bool = False):
        self.title = title
        self._template_name = template
        self._metadata = Table(css_class="meta")
        self._variants: List[VariantBuilder] = []
        self._cdn = cdn

    def metadata(self, key: str, value: Any) -> "Page":
        self._metadata.row(key, value)
        return self

    def variant(self, name: str) -> VariantBuilder:
        v = VariantBuilder(name)
        self._variants.append(v)
        return v

    def _load_vendor_scripts(self) -> str:
        """Inline vendor JS (offline page), or pinned CDN tags in cdn mode."""
        vendor_dir = _TEMPLATES_DIR / "vendor"
        if self._cdn:
            tags = [f'<script src="{url}"></script>' for url in self.CDN_SCRIPTS]
            hl = vendor_dir / "hljs-openscad.min.js"
            if hl.exists():
                tags.append(f"<script>/* hljs-openscad.min.js */\n{hl.read_text()}</script>")
            return "\n".join(tags)
        scripts = []
        for name in ["three.min.js", "OrbitControls.js", "STLLoader.js", "hljs-openscad.min.js"]:
            path = vendor_dir / name
            if path.exists():
                scripts.append(f"<script>/* {name} */\n{path.read_text()}</script>")
        return "\n".join(scripts)

    @staticmethod
    def _camera_presets_json() -> str:
        import json
        from agentcad.camera import STANDARD_PRESETS
        return json.dumps({name: {"eye": list(p.eye), "up": list(p.up)} for name, p in STANDARD_PRESETS.items()})

    @staticmethod
    def _view_buttons() -> str:
        from agentcad.camera import STANDARD_PRESETS
        return " ".join(f'<button onclick="setView(\'{name}\')">{name}</button>' for name in STANDARD_PRESETS)

    def build(self) -> str:
        page_tmpl = Template((_TEMPLATES_DIR / self._template_name).read_text())
        variant_tmpl = Template((_TEMPLATES_DIR / "variant.html").read_text())

        variants_html = "\n".join(
            v.build(variant_tmpl) for v in self._variants
        )

        return page_tmpl.substitute(
            project_name=_esc(self.title),
            metadata_rows=self._metadata.build(),
            variants_html=variants_html,
            threejs_scripts=self._load_vendor_scripts(),
            camera_presets_json=self._camera_presets_json(),
            view_buttons=self._view_buttons(),
        )
