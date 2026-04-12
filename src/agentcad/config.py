"""AgentCAD configuration system.

Project-centric config: each project folder contains agentcad.toml.
Discovery: agentcad finds projects by locating agentcad.toml in folder structure.
Layered: package defaults → project agentcad.toml → env vars → CLI flags.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

AGENTCAD_VERSION = "0.2.0"
CONFIG_FILENAME = "agentcad.toml"
_DEFAULT_DROPBOX = "/shared_workspace/Dropbox_NEUro_DataScienceTeam_MannyMacEff"


@dataclass
class OpenSCADConfig:
    """OpenSCAD engine defaults."""
    fa: float = 1.0
    fs: float = 0.5
    backend: str = "Manifold"
    colorscheme: str = "Cornfield"
    library_path: str = "/opt/openscad-libraries"


@dataclass
class PrintConfig:
    """Suggested print settings."""
    material: str = "PLA"
    layer_height: float = 0.2
    infill_percent: int = 20
    supports: bool = False
    printer_profile: str = "Original Prusa MK4"
    filament_profile: str = ""
    print_orientation: str = ""
    notes: str = ""


@dataclass
class OutputConfig:
    """Output directory and rendering defaults."""
    base_dir: str = _DEFAULT_DROPBOX
    sub_dir: str = "mechanical_designs"
    image_size: int = 1024
    default_views: List[str] = field(
        default_factory=lambda: ["iso", "front", "top", "right", "back"]
    )

    @property
    def designs_dir(self) -> Path:
        return Path(self.base_dir) / self.sub_dir


@dataclass
class ProjectConfig:
    """Full project configuration loaded from agentcad.toml."""
    # Metadata
    version: str = AGENTCAD_VERSION
    name: str = ""
    engine: str = "openscad"
    description: str = ""

    # Sub-configs
    output: OutputConfig = field(default_factory=OutputConfig)
    print: PrintConfig = field(default_factory=PrintConfig)
    engine_configs: Dict[str, object] = field(default_factory=dict)

    # Source path (where agentcad.toml was loaded from)
    _project_dir: Optional[Path] = field(default=None, repr=False)

    @property
    def project_dir(self) -> Optional[Path]:
        return self._project_dir

    def get_openscad_config(self) -> OpenSCADConfig:
        return self.engine_configs.get("openscad", OpenSCADConfig())

    @classmethod
    def discover(cls, start_path: Optional[Path] = None) -> Optional["ProjectConfig"]:
        """Walk up from start_path looking for agentcad.toml."""
        path = Path(start_path or Path.cwd())
        for parent in [path] + list(path.parents):
            config_file = parent / CONFIG_FILENAME
            if config_file.exists():
                return cls.load(config_file)
        return None

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "ProjectConfig":
        """Load config from agentcad.toml, falling back to defaults."""
        config = cls()

        if path is None:
            path = Path.cwd() / CONFIG_FILENAME

        path = Path(path)
        if not path.exists():
            return config

        config._project_dir = path.parent

        if tomllib is None:
            return config

        with open(path, "rb") as f:
            data = tomllib.load(f)

        # AgentCAD section (version)
        ac = data.get("agentcad", {})
        if "version" in ac:
            config.version = ac["version"]

        # Project section
        proj = data.get("project", {})
        for k in ("name", "engine", "description"):
            if k in proj:
                setattr(config, k, proj[k])

        # Output section
        out = data.get("output", {})
        for k in ("base_dir", "sub_dir", "image_size"):
            if k in out:
                setattr(config.output, k, out[k])
        if "default_views" in out:
            config.output.default_views = out["default_views"]

        # Print section
        pr = data.get("print", {})
        for k in ("material", "layer_height", "infill_percent", "supports",
                   "printer_profile", "filament_profile", "print_orientation", "notes"):
            if k in pr:
                setattr(config.print, k, pr[k])

        # Engine configs
        engines = data.get("engine", {})
        if "openscad" in engines:
            osc = engines["openscad"]
            cfg = OpenSCADConfig()
            for k in ("fa", "fs", "backend", "colorscheme", "library_path"):
                if k in osc:
                    setattr(cfg, k, osc[k])
            config.engine_configs["openscad"] = cfg

        return config

    def show(self) -> str:
        """Display resolved config as readable text."""
        lines = [f"AgentCAD Config (v{self.version})"]
        if self._project_dir:
            lines.append(f"  Project dir: {self._project_dir}")
        lines.append(f"  Name: {self.name or '(unnamed)'}")
        lines.append(f"  Engine: {self.engine}")
        lines.append(f"  Description: {self.description or '(none)'}")
        lines.append(f"  Output dir: {self.output.designs_dir}")
        lines.append(f"  Image size: {self.output.image_size}")
        lines.append(f"  Views: {self.output.default_views}")
        lines.append(f"  Material: {self.print.material}")
        lines.append(f"  Layer height: {self.print.layer_height}mm")
        lines.append(f"  Infill: {self.print.infill_percent}%")
        lines.append(f"  Printer: {self.print.printer_profile}")
        osc = self.get_openscad_config()
        lines.append(f"  OpenSCAD: $fa={osc.fa} $fs={osc.fs} backend={osc.backend}")
        return "\n".join(lines)


def generate_config_template(name: str = "", description: str = "",
                              engine: str = "openscad") -> str:
    """Generate a well-commented agentcad.toml template."""
    return f'''# AgentCAD Project Configuration
# This file identifies a folder as an AgentCAD project.
# agentcad discovers projects by finding this file.

[agentcad]
version = "{AGENTCAD_VERSION}"          # config format version (for compat)

[project]
name = "{name}"
engine = "{engine}"                     # "openscad" or "voxelcad"
description = "{description}"

[engine.openscad]
fa = 1.0                               # fragment angle (smooth curves)
fs = 0.5                               # fragment size (mm)
# backend = "Manifold"                 # "Manifold" (fast) or "CGAL" (legacy)
# colorscheme = "Cornfield"            # render color scheme

[output]
image_size = 1024                       # render resolution
default_views = ["iso", "front", "top", "right", "back"]

[print]
material = "PLA"                        # filament type
layer_height = 0.2                      # mm
infill_percent = 20                     # %
supports = false
printer_profile = "Original Prusa MK4"
# filament_profile = "PolyLite PLA Pro"
# print_orientation = "flat on bed"
# notes = ""
'''


def find_project(project_path: Path) -> Optional[ProjectConfig]:
    """Load project config from a project directory."""
    config_file = Path(project_path) / CONFIG_FILENAME
    if config_file.exists():
        return ProjectConfig.load(config_file)
    return None


def list_projects(designs_dir: Optional[Path] = None) -> List[ProjectConfig]:
    """Find all AgentCAD projects under the designs directory."""
    if designs_dir is None:
        designs_dir = OutputConfig().designs_dir
    designs_dir = Path(designs_dir)
    projects = []
    if designs_dir.exists():
        for d in sorted(designs_dir.iterdir()):
            if d.is_dir():
                cfg = find_project(d)
                if cfg:
                    projects.append(cfg)
    return projects
