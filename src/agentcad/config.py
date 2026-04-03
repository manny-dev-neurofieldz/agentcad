"""AgentCAD configuration system.

Layered config: package defaults → agentcad.toml → env vars → CLI flags.
Engine-specific configs with project-level overrides.
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
class OutputConfig:
    """Output directory and rendering defaults."""
    base_dir: str = _DEFAULT_DROPBOX
    sub_dir: str = "mechanical_designs"
    image_size: int = 1024
    default_views: List[str] = field(default_factory=lambda: ["iso", "front", "top", "right"])

    @property
    def designs_dir(self) -> Path:
        return Path(self.base_dir) / self.sub_dir


@dataclass
class ProjectConfig:
    """Full project configuration."""
    name: str = ""
    engines: List[str] = field(default_factory=lambda: ["openscad"])
    output: OutputConfig = field(default_factory=OutputConfig)
    engine_configs: Dict[str, object] = field(default_factory=dict)

    def get_openscad_config(self) -> OpenSCADConfig:
        return self.engine_configs.get("openscad", OpenSCADConfig())

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "ProjectConfig":
        """Load config from agentcad.toml, falling back to defaults."""
        config = cls()

        if path is None:
            path = Path.cwd() / "agentcad.toml"

        if not path.exists():
            return config

        if tomllib is None:
            return config

        with open(path, "rb") as f:
            data = tomllib.load(f)

        # Project section
        proj = data.get("project", {})
        if "name" in proj:
            config.name = proj["name"]
        if "engines" in proj:
            config.engines = proj["engines"]

        # Output section
        out = data.get("output", {})
        if "base_dir" in out:
            config.output.base_dir = out["base_dir"]
        if "sub_dir" in out:
            config.output.sub_dir = out["sub_dir"]
        if "image_size" in out:
            config.output.image_size = out["image_size"]
        if "default_views" in out:
            config.output.default_views = out["default_views"]

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
