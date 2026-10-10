"""Printers: what each machine can make, by process.

A printer names its process (``fdm`` or ``resin``), its build volume (x, y, z in mm) and, for
FDM, its nozzle. Its process defaults are the limits QC applies when nothing closer to the part
sets one. Two printers are built in: the Original Prusa MK4 (FDM, 0.4 mm nozzle) and the
Formlabs Form 3 (resin). More come from a user file (``printers.toml`` in the agentcad user
config folder, ``$XDG_CONFIG_HOME/agentcad`` or ``~/.config/agentcad``) and from a project's
``[printers.<name>]`` tables; a later source replaces an earlier entry of the same name, and
every printer says where it was defined. A slicer's printer configuration (``bed_shape``,
``max_print_height``, ``nozzle_diameter``, as a sliced file carries it) describes a printer too.

Each table holds ``label``, ``process``, ``build_volume = [x, y, z]`` and, for FDM, ``nozzle_mm``.
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

PROCESSES = ("fdm", "resin")

#: The usual extrusion width as a multiple of the nozzle (a 0.4 mm nozzle lays 0.45 mm lines).
LINE_PER_NOZZLE = 1.125


@dataclass(frozen=True)
class Printer:
    name: str
    label: str
    process: str
    build_volume: Tuple[float, float, float]
    nozzle_mm: Optional[float] = None
    source: str = "built in"

    def defaults_layer(self) -> str:
        """How a finding names the layer these defaults come from."""
        if self.process == "fdm":
            return f"process default (fdm, {self.nozzle_mm or 0.4:g} mm nozzle)"
        return f"process default ({self.process})"

    def defaults(self) -> Dict[str, float]:
        """The process defaults: limits keyed by rule. FDM: a wall of two lines, a feature of one,
        overhangs to 45 degrees, bridges to 10 mm; resin: walls of 0.4 mm and features of 0.3 mm."""
        if self.process == "fdm":
            line = round((self.nozzle_mm or 0.4) * LINE_PER_NOZZLE, 4)
            return {"min_wall_mm": round(2 * line, 4), "min_feature_mm": line, "max_overhang_deg": 45.0,
                    "max_bridge_mm": 10.0}
        if self.process == "resin":
            return {"min_wall_mm": 0.4, "min_feature_mm": 0.3}
        return {}

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "label": self.label, "process": self.process,
                "build_volume": list(self.build_volume), "nozzle_mm": self.nozzle_mm, "source": self.source,
                "defaults": self.defaults()}


BUILT_IN: Dict[str, Printer] = {
    "mk4": Printer("mk4", "Original Prusa MK4", "fdm", (250.0, 210.0, 220.0), 0.4),
    "form3": Printer("form3", "Formlabs Form 3", "resin", (145.0, 145.0, 185.0)),
}


def user_config_dir() -> Path:
    """The agentcad user config folder: ``$XDG_CONFIG_HOME/agentcad`` or ``~/.config/agentcad``."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "agentcad"


def from_table(name: str, table: Mapping[str, Any], source: str) -> Printer:
    """A printer from a ``[printers.<name>]`` table; an error names the table and the key."""
    process = str(table.get("process", "")).lower()
    if process not in PROCESSES:
        raise ValueError(f"printer {name} ({source}): process must be one of {', '.join(PROCESSES)}, not {process!r}")
    try:
        x, y, z = (float(v) for v in table["build_volume"])
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"printer {name} ({source}): build_volume must be three numbers [x, y, z]")
    nozzle = table.get("nozzle_mm")
    return Printer(name, str(table.get("label", name)), process, (x, y, z),
                   float(nozzle) if nozzle is not None else None, source)


def _read_tables(path: Path) -> Dict[str, Dict[str, Any]]:
    from agentcad.config import tomllib
    if tomllib is None or not path.is_file():
        return {}
    with open(path, "rb") as f:
        return {k: dict(v) for k, v in (tomllib.load(f).get("printers") or {}).items() if isinstance(v, dict)}


def registry(cfg=None) -> Dict[str, Printer]:
    """Every known printer: the built-ins, then the user file's, then the project's (``cfg``)."""
    reg = dict(BUILT_IN)
    user_file = user_config_dir() / "printers.toml"
    sources = [(user_file, _read_tables(user_file))]
    if cfg is not None and getattr(cfg, "printer_tables", None):
        where = Path(cfg.project_dir) / "agentcad.toml" if cfg.project_dir else Path("agentcad.toml")
        sources.append((where, cfg.printer_tables))
    for path, tables in sources:
        for name, table in tables.items():
            try:
                reg[name] = from_table(name, table, str(path))
            except ValueError as e:
                print(f"agentcad warning: {e} (ignored)", file=sys.stderr)
    return reg


def get(name: str, cfg=None) -> Printer:
    """A printer by name; a KeyError names the known ones."""
    reg = registry(cfg)
    if name not in reg:
        raise KeyError(f"no printer named {name!r}; known: {', '.join(sorted(reg))}")
    return reg[name]


def by_label(label: str, cfg=None) -> Optional[Printer]:
    """The printer whose label matches a profile name (``[print] printer_profile``), if any."""
    wanted = (label or "").strip().lower()
    for p in registry(cfg).values():
        if wanted and p.label.lower() == wanted:
            return p
    return None


def from_slicer_config(config: Mapping[str, str], name: str = "sliced") -> Printer:
    """The printer a slicer configuration describes: bed from ``bed_shape``, height from
    ``max_print_height``, nozzle from ``nozzle_diameter`` (FDM; a sliced file carries all three)."""
    pts = [tuple(float(v) for v in p.split("x")) for p in str(config["bed_shape"]).split(",") if "x" in p]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    nozzle = config.get("nozzle_diameter")
    return Printer(name, str(config.get("printer_model") or config.get("printer_settings_id") or name), "fdm",
                   (max(xs) - min(xs), max(ys) - min(ys), float(config["max_print_height"])),
                   float(str(nozzle).split(",")[0]) if nozzle else None, "slicer configuration")
