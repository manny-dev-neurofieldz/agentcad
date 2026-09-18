"""Design project output management.

Organizes renders, STLs, and source code into structured project folders.
Filename conventions are documented in the CAD Knowledge Web (cad_agentcad_config.md)
and applied by the agent, not enforced by code.
"""

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from agentcad.config import OutputConfig


@dataclass
class MeshRef:
    """One mesh of a variant: a single part, or one body of an assembly."""
    name: str
    path: Path
    quantity: int = 1
    color: Optional[str] = None


class DesignVariant:
    """A single parametric variant within a project.

    A variant carries a list of meshes: one for a single part, one per part
    for an assembly whose parent gathered its subprojects' exports. The
    ``stl_path`` property keeps the single-mesh API working: reading it
    gives the first mesh, assigning it replaces the list with one entry.
    """

    def __init__(self, name: str, params: Optional[Dict[str, Any]] = None,
                 source_code: str = "", source_path: Optional[Path] = None):
        self.name = name
        self.params = params or {}
        self.source_code = source_code
        self.source_path = source_path
        self.renders: Dict[str, Path] = {}
        self.meshes: List[MeshRef] = []

    @property
    def stl_path(self) -> Optional[Path]:
        return self.meshes[0].path if self.meshes else None

    @stl_path.setter
    def stl_path(self, value: Optional[Path]) -> None:
        self.meshes = [MeshRef(self.name, Path(value))] if value else []

    def add_mesh(self, name: str, path: Path, quantity: int = 1, color: Optional[str] = None) -> MeshRef:
        ref = MeshRef(name, Path(path), quantity, color)
        self.meshes.append(ref)
        return ref


class DesignProject:
    """Manages output for a design project.

    Creates structured folder:
        {designs_dir}/{project_name}/
        |-- source/           # engine source files (extension from the engine)
        |-- renders/          # multi-view PNGs
        |-- exports/          # mesh/geometry exports (.stl, .step, ...)
        `-- index.html        # interactive viewer

    ``source_extension`` and ``syntax_language`` come from the engine the
    project is designed with; the session sets them, and the viewer reads
    them, so no file extension is assumed anywhere in between.
    """

    def __init__(self, name: str, config: Optional[OutputConfig] = None,
                 source_extension: str = "", syntax_language: str = "plaintext"):
        self.name = name
        self.config = config or OutputConfig()
        self.variants: List[DesignVariant] = []
        self.source_extension = source_extension
        self.syntax_language = syntax_language
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
        """Save source code for a variant.

        Without ``filename`` the name is ``{variant.name}{source_extension}``,
        which needs the project's engine extension to be set.
        """
        self.setup()
        if filename is None:
            if not self.source_extension:
                raise ValueError(
                    "save_source needs a filename or a project source_extension "
                    "(set from the engine's file_extension)"
                )
            filename = f"{variant.name}{self.source_extension}"
        out = self.source_dir / filename
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
