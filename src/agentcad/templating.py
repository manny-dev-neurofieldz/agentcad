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
        v.source("source/bracket.scad")

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

    def __init__(self, title: str, code: str, language: str = "openscad"):
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

    def __init__(self, name: str):
        self.name = name
        self._params = Table(["Parameter", "Value"])
        self._gallery = Gallery()
        self._stl_path: Optional[str] = None
        self._stl_data: Optional[bytes] = None
        self._source_title = ""
        self._source_code = ""

    def param(self, key: str, value: Any, unit: str = "") -> "VariantBuilder":
        display = f"{value} {unit}".strip() if unit else str(value)
        self._params.row(key, display)
        return self

    def render(self, view: str, path: str) -> "VariantBuilder":
        self._gallery.image(view, path)
        return self

    def stl(self, path: str, data: Optional[bytes] = None) -> "VariantBuilder":
        self._stl_path = path
        self._stl_data = data
        return self

    def source(self, title: str, code: str, language: str = "openscad") -> "VariantBuilder":
        self._source_title = title
        self._source_code = code
        return self

    def build(self, variant_template: Template) -> str:
        import base64

        stl_buttons = ""
        stl_embed = ""
        if self._stl_path:
            stl_buttons = Button.download("Download STL", self._stl_path)
            if self._stl_data:
                stl_id = self.name.replace(" ", "_").replace("-", "_")
                b64 = base64.b64encode(self._stl_data).decode("ascii")
                stl_buttons += " " + Button.action("View 3D", f"loadSTLData('{stl_id}')")
                stl_embed = f'<script id="stl-data-{stl_id}" type="application/octet-stream">{b64}</script>'

        params_html = ""
        if self._params.rows:
            params_html = Details("Parameters", open_=True).body(
                self._params.build()
            ).build()

        return variant_template.substitute(
            variant_name=_esc(self.name),
            stl_buttons=stl_buttons + stl_embed,
            params_table=params_html,
            gallery_items=self._gallery.build(),
            source_block=CodeBlock(self._source_title, self._source_code).build(),
        )


class Page:
    """Top-level HTML page builder."""

    def __init__(self, title: str, template: str = "viewer.html"):
        self.title = title
        self._template_name = template
        self._metadata = Table(css_class="meta")
        self._variants: List[VariantBuilder] = []

    def metadata(self, key: str, value: Any) -> "Page":
        self._metadata.row(key, value)
        return self

    def variant(self, name: str) -> VariantBuilder:
        v = VariantBuilder(name)
        self._variants.append(v)
        return v

    def _load_vendor_scripts(self) -> str:
        """Read vendor JS files and return inline <script> tags."""
        vendor_dir = _TEMPLATES_DIR / "vendor"
        scripts = []
        for name in ["three.min.js", "OrbitControls.js", "STLLoader.js"]:
            path = vendor_dir / name
            if path.exists():
                scripts.append(f"<script>/* {name} */\n{path.read_text()}</script>")
        return "\n".join(scripts)

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
        )
