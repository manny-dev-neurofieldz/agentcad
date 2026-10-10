"""One sliced file, read once: its model, its embedded configuration and what it states about itself.

``gcode summary`` and ``gcode compare`` both start here, so the two commands report the same numbers for the
same file. A .bgcode is decoded a single time (the pure-Python decoder is the slow part of reading one) and
gives its statistics from the print and printer metadata blocks. A plain file gives them from the comments a
slicer writes after the G-code (``; estimated printing time (normal mode) = 1h 2m 3s``). Nothing here
computes a time: a duration is read from the file or it is unknown.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Union

from agentcad.gcode import bgcode, check
from agentcad.gcode import model as gm
from agentcad.gcode.model import DEFAULT_FILAMENT_DIAMETER

TIME_KEY = "estimated printing time (normal mode)"
FILAMENT_KEY = "filament used [mm]"
MASS_KEY = "filament used [g]"

#: A slicer setting is named in lower case with underscores. A statistic a plain file writes beside its
#: configuration ("filament used [mm]", "estimated printing time (normal mode)", "total layers count") has
#: spaces in its name, which is what tells the two apart.
_SETTING_KEY = re.compile(r"[a-z][a-z0-9_]*")
#: Written like a setting, but a result of the slice (where the objects sit, how high it goes), not an input to it.
#: A plain file with a configuration block gets its settings from the block alone; these names matter for one without.
NOT_SETTINGS = ("objects_info", "max_layer_z")

_DURATION = re.compile(r"\s*(?:(\d+)\s*d)?\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+)\s*s)?\s*")


@dataclass
class Sliced:
    path: Path
    kind: str                                   # "bgcode" or "gcode"
    model: gm.GCodeModel
    config: Dict[str, str]                      # the embedded slicer configuration as written (credentials included)
    metadata: Dict[str, Dict[str, str]]         # a .bgcode's metadata blocks by name; empty for plain G-code
    stated: Dict[str, str]                      # the statistics the file states about itself, by name


def is_setting_key(key: str) -> bool:
    """Whether a configuration key names a slicer setting, rather than a statistic written beside the settings."""
    return bool(_SETTING_KEY.fullmatch(key)) and key not in NOT_SETTINGS


def load(path: Union[str, Path]) -> Sliced:
    """Read a .bgcode or plain G-code file once: parse its model and collect its configuration and statistics.
    Raises OSError for a file that cannot be opened and ValueError (BGCodeError among them) for one that cannot
    be read."""
    path = Path(path)
    if bgcode.is_bgcode(path):
        g = bgcode.read(path)
        meta = g.metadata
        stated = dict(meta.get("printer_metadata", {}))
        stated.update(meta.get("print_metadata", {}))
        return Sliced(path, "bgcode", gm.parse(g.gcode()), dict(meta.get("slicer_metadata", {})), meta, stated)
    text = path.read_text(encoding="utf-8", errors="replace")
    block = check.config_block(text)
    config = block if block is not None else check.config_from_text(text)
    # statistics are read from the whole file: a slicer writes them before its configuration block, but a file
    # that writes them after it states them just as much
    stated = {k: v for k, v in check.config_from_text(text, whole=True).items() if not is_setting_key(k)}
    return Sliced(path, "gcode", gm.parse(text), config, {}, stated)


def parse_duration(text: Optional[str]) -> Optional[int]:
    """Seconds in a duration the way a slicer writes one ('1d 2h 3m 4s', '56m 22s', '4s'); None when it is not one."""
    m = _DURATION.fullmatch(text or "")
    if not m or not any(m.groups()):
        return None
    d, h, mi, s = (int(g) if g else 0 for g in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + s


def format_duration(seconds: int, signed: bool = False) -> str:
    """A duration in the slicer's own form: 3723 -> '1h 2m 3s'. ``signed`` puts a plus on a positive one."""
    sign = "-" if seconds < 0 else ("+" if signed and seconds > 0 else "")
    d, rest = divmod(abs(int(seconds)), 86400)
    h, rest = divmod(rest, 3600)
    m, s = divmod(rest, 60)
    body = (f"{d}d {h}h {m}m {s}s" if d else f"{h}h {m}m {s}s" if h else f"{m}m {s}s" if m else f"{s}s")
    return sign + body


def stated_time(stated: Dict[str, str]) -> Optional[Dict]:
    """The estimated printing time the file states ({"seconds", "text"}), or None when it states none.
    ``seconds`` is None when the text is not a duration this reader knows."""
    text = stated.get(TIME_KEY)
    if not text:
        return None
    return {"seconds": parse_duration(text), "text": text}


def stated_total(stated: Dict[str, str], key: str) -> Optional[float]:
    """A total the file states under ``key`` (FILAMENT_KEY: mm of filament, MASS_KEY: grams); several extruders'
    values are added up. None when the file does not state it, or states something that is not a number."""
    raw = stated.get(key)
    if not raw:
        return None
    try:
        return float(raw) if "," not in raw else round(sum(float(v) for v in raw.split(",")), 6)
    except ValueError:
        return None


def _first_number(value: str, default: float) -> float:
    """The first value of a comma-separated setting as a number; ``default`` when there is none or it is not a
    number (a per-extruder 'nil')."""
    try:
        return float(value.split(",")[0])
    except ValueError:
        return default


def summary_record(s: Sliced) -> Dict:
    """The record ``gcode summary --json`` prints (schema agentcad.gcode.summary/1).

    The slicer's density and diameter come from a .bgcode's slicer metadata, and the stated filament total from
    its print metadata; a plain file has neither here, as before. ``estimated_time`` is the one field added
    to the record: the time the file states, or null."""
    slicer = s.metadata.get("slicer_metadata", {})
    density = _first_number(slicer.get("filament_density", ""), 0.0) or None
    diameter = _first_number(slicer.get("filament_diameter", ""), DEFAULT_FILAMENT_DIAMETER)
    rec = gm.summary(s.model, diameter, density)
    stated = stated_total(s.metadata.get("print_metadata", {}), FILAMENT_KEY)
    if stated is not None:
        rec["filament_used_stated_mm"] = stated
    rec["estimated_time"] = stated_time(s.stated)
    return rec
