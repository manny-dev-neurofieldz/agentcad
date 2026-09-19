"""AgentCAD configuration system.

Project-centric config: each project folder contains agentcad.toml.
Discovery: agentcad finds projects by locating agentcad.toml in folder structure.
Layered: package defaults -> project agentcad.toml -> env vars -> CLI flags.
"""

import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Tuple, Any, Dict, List, Optional

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
    #: Globs (relative to the project folder) of part subprojects, each a
    #: folder with its own agentcad.toml: ``parts = ["parts/*"]``. A parent
    #: that declares parts can iterate and finalize them all in one call.
    parts: List[str] = field(default_factory=list)
    #: Name of the enclosing project when this config was found through a
    #: parent's ``parts`` globs (set by discovery, never by the file).
    parent_name: Optional[str] = field(default=None, repr=False)

    # Sub-configs
    output: OutputConfig = field(default_factory=OutputConfig)
    print: PrintConfig = field(default_factory=PrintConfig)
    #: Raw ``[engine.<name>]`` tables, keyed by engine name. Kept as plain
    #: dicts so any registered engine can read its own keys; the engine
    #: decides which keys it knows and reports the rest.
    engine_configs: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Source path (where agentcad.toml was loaded from)
    _project_dir: Optional[Path] = field(default=None, repr=False)

    @property
    def project_dir(self) -> Optional[Path]:
        return self._project_dir

    def engine_settings(self, name: str) -> Dict[str, Any]:
        """Settings table for engine ``name`` (a copy; empty when absent)."""
        return dict(self.engine_configs.get(name, {}))

    def part_projects(self) -> List[Tuple[Path, "ProjectConfig"]]:
        """The part subprojects this project declares, sorted by path.

        Each entry is the part folder and its loaded config with
        ``parent_name`` set. A project with no ``parts`` yields nothing.
        """
        found: List[Tuple[Path, "ProjectConfig"]] = []
        if not self.parts or self._project_dir is None:
            return found
        for pattern in self.parts:
            for folder in sorted(Path(self._project_dir).glob(pattern)):
                if not folder.is_dir() or folder.resolve() == Path(self._project_dir).resolve():
                    continue
                cfg = find_project(folder)
                if cfg is not None:
                    cfg.parent_name = self.name or Path(self._project_dir).name
                    found.append((folder, cfg))
        return found

    def get_openscad_config(self) -> OpenSCADConfig:
        """OpenSCAD settings as the legacy dataclass (known keys only)."""
        cfg = OpenSCADConfig()
        table = self.engine_settings("openscad")
        for f in fields(OpenSCADConfig):
            if f.name in table:
                setattr(cfg, f.name, table[f.name])
        return cfg

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
        if "parts" in proj:
            parts = proj["parts"]
            config.parts = [parts] if isinstance(parts, str) else list(parts)

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

        # Engine configs: every [engine.<name>] table, verbatim
        engines = data.get("engine", {})
        for engine_name, table in engines.items():
            if isinstance(table, dict):
                config.engine_configs[engine_name] = dict(table)
            else:
                print(
                    f"agentcad warning: [engine.{engine_name}] in {path} is not a table (ignored)",
                    file=sys.stderr,
                )

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
        for engine_name, table in sorted(self.engine_configs.items()):
            settings = " ".join(f"{k}={v}" for k, v in table.items())
            lines.append(f"  [engine.{engine_name}] {settings}")
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
engine = "{engine}"                     # "openscad", "voxelcad" or "build123d"
description = "{description}"

# Per-engine settings live in [engine.<name>] tables. Only the table for the
# project's engine is used; unknown keys are reported, not silently ignored.

[engine.openscad]
fa = 1.0                               # fragment angle (smooth curves)
fs = 0.5                               # fragment size (mm)
# backend = "Manifold"                 # "Manifold" (fast) or "CGAL" (legacy)
# colorscheme = "Cornfield"            # render color scheme

# [engine.voxelcad]
# voxel_size = 0.2                     # mm per voxel
# color = "steelblue"                  # render colour
# background = "white"

# [engine.build123d]
# tolerance = 0.01                     # tessellation tolerance (mm)
# timeout = 120                        # seconds per render
# shading = "smooth"                   # "flat" shows the tessellation on curved faces

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
                    # declared part subprojects follow their parent
                    for _, part in cfg.part_projects():
                        projects.append(part)
    return projects
