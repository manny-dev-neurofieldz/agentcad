"""Design project output management.

Organizes renders, STLs, and source code into structured project folders.
Filename conventions are documented in the CAD Knowledge Web (cad_agentcad_config.md)
and applied by the agent, not enforced by code.
"""

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from agentcad.config import OutputConfig


class DesignVariant:
    """A single parametric variant within a project."""

    def __init__(self, name: str, params: Optional[Dict[str, Any]] = None,
                 source_code: str = "", source_path: Optional[Path] = None):
        self.name = name
        self.params = params or {}
        self.source_code = source_code
        self.source_path = source_path
        self.renders: Dict[str, Path] = {}
        self.stl_path: Optional[Path] = None


class DesignProject:
    """Manages output for a design project.

    Creates structured folder:
        {designs_dir}/{project_name}/
        ├── source/           # .scad source files
        ├── renders/          # multi-view PNGs
        ├── exports/          # STL files
        └── index.html        # interactive viewer
    """

    def __init__(self, name: str, config: Optional[OutputConfig] = None):
        self.name = name
        self.config = config or OutputConfig()
        self.variants: List[DesignVariant] = []
        self.metadata: Dict[str, Any] = {
            "created": datetime.now().isoformat(),
            "engine": "",
        }
        self._project_dir = self.config.designs_dir / self.name

    @property
    def project_dir(self) -> Path:
        return self._project_dir

    @property
    def source_dir(self) -> Path:
        return self._project_dir / "source"

    @property
    def renders_dir(self) -> Path:
        return self._project_dir / "renders"

    @property
    def exports_dir(self) -> Path:
        return self._project_dir / "exports"

    def setup(self) -> Path:
        """Create project directory structure."""
        for d in [self.source_dir, self.renders_dir, self.exports_dir]:
            d.mkdir(parents=True, exist_ok=True)
        return self._project_dir

    def add_variant(self, name: str, params: Optional[Dict[str, Any]] = None,
                    source_code: str = "", source_path: Optional[Path] = None) -> DesignVariant:
        """Register a parametric variant."""
        v = DesignVariant(name, params, source_code, source_path)
        self.variants.append(v)
        return v

    def save_source(self, variant: DesignVariant, code: str,
                    filename: Optional[str] = None) -> Path:
        """Save source code for a variant."""
        self.setup()
        fname = filename or f"{variant.name}.scad"
        out = self.source_dir / fname
        out.write_text(code)
        variant.source_code = code
        variant.source_path = out
        return out

    def register_render(self, variant: DesignVariant, view: str,
                        image_path: Path, filename: Optional[str] = None) -> Path:
        """Copy a rendered image into the project renders dir."""
        self.setup()
        fname = filename or f"{variant.name}_{view}.png"
        dest = self.renders_dir / fname
        if image_path.resolve() != dest.resolve():
            shutil.copy2(image_path, dest)
        variant.renders[view] = dest
        return dest

    def register_stl(self, variant: DesignVariant, stl_path: Path,
                     filename: Optional[str] = None) -> Path:
        """Copy an STL export into the project exports dir."""
        self.setup()
        fname = filename or f"{variant.name}.stl"
        dest = self.exports_dir / fname
        if stl_path.resolve() != dest.resolve():
            shutil.copy2(stl_path, dest)
        variant.stl_path = dest
        return dest

    def generate_viewer(self) -> Path:
        """Generate index.html with interactive STL viewer and galleries."""
        from agentcad.viewer import generate_html
        self.setup()
        html_path = self._project_dir / "index.html"
        html = generate_html(self)
        html_path.write_text(html)
        return html_path
