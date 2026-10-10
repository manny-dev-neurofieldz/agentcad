"""Settings check: what a sliced file was sliced with, against what the project intended.

Intent is a ``[slice]`` table (in a project's ``agentcad.toml``, a print job's ``job.toml``, or any TOML file),
keyed by the slicer's own setting names. A value is either the intended value, or a table with ``value`` or
``min``/``max`` and an optional ``why``::

    [slice]
    layer_height = 0.2
    temperature = { min = 270, max = 285, why = "layer bond in ASA-CF" }
    support_material_buildplate_only = { value = 1, why = "supports must not grow inside the bores" }

The file's configuration comes from the slicer metadata block of a .bgcode, or the ``; key = value`` comment
block a plain G-code export carries. Each finding is a sentence: the key, both values, where the intent was
declared, why it matters, and the usual fix.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from agentcad.config import tomllib
from agentcad.gcode import bgcode

#: Settings worth printing when a project declares no intent.
KEY_SETTINGS = (
    "printer_settings_id", "print_settings_id", "filament_settings_id", "layer_height", "temperature",
    "bed_temperature", "fill_density", "perimeters", "support_material", "support_material_buildplate_only",
    "support_material_threshold", "support_material_style", "support_material_contact_distance", "brim_width",
)

#: Never echoed: credentials and machine paths a slicer may store in its configuration.
PRIVATE_KEYS = ("printhost_apikey", "printhost_password", "printhost_user", "printhost_cafile", "post_process")


@dataclass
class Finding:
    key: str
    severity: str            # "error" | "warning" | "ok"
    found: Optional[str]
    intended: str
    why: str
    source: str

    def sentence(self) -> str:
        why = f" Why: {self.why}." if self.why else ""
        if self.severity == "ok":
            return f"{self.key} = {self.found}, as {self.source} asks."
        if self.found is None:
            return (f"{self.key} is not in the file's configuration; {self.source} asks for {self.intended}.{why} "
                    f"Fix: check the slicer version writes this setting, or drop it from the intent.")
        return (f"{self.key} is {self.found} in the file; {self.source} asks for {self.intended}.{why} "
                f"Fix: re-load the project file in the slicer and re-slice; a preset selected afterwards can "
                f"override a project's settings.")


def embedded_config(path: Union[str, Path]) -> Dict[str, str]:
    """The slicer configuration a sliced file carries (.bgcode metadata, or a plain file's comment block)."""
    path = Path(path)
    if bgcode.is_bgcode(path):
        return dict(bgcode.read(path).metadata.get("slicer_metadata", {}))
    out: Dict[str, str] = {}
    in_block = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith(";") or " = " not in line:
            continue
        k, v = line[1:].split(" = ", 1)
        k, v = k.strip(), v.strip()
        if k.endswith("_config") and v in ("begin", "end"):
            in_block = v == "begin"
            continue
        if in_block is None or in_block:
            out[k] = v
    return out


def load_intent(path: Union[str, Path]) -> Dict[str, Any]:
    """The ``[slice]`` table of a TOML file (empty when the file declares none)."""
    if tomllib is None:
        raise RuntimeError("reading a [slice] table needs tomllib (Python 3.11+) or the tomli package")
    with open(path, "rb") as f:
        return dict(tomllib.load(f).get("slice", {}))


def _num(v: Any) -> Optional[float]:
    try:
        return float(str(v).strip().rstrip("%").split(",")[0])
    except ValueError:
        return None


def _same(found: str, want: Any) -> bool:
    if isinstance(want, bool):
        want = int(want)
    a, b = _num(found), _num(want)
    if a is not None and b is not None:
        return abs(a - b) <= 1e-6 * max(1.0, abs(b))
    return str(found).strip().strip('"') == str(want).strip().strip('"')


def check(config: Dict[str, str], intent: Dict[str, Any], source: str) -> List[Finding]:
    """One finding per intended key: error when a stated value differs, warning when a range is left or the key
    is missing, ok otherwise."""
    findings = []
    for key, spec in intent.items():
        if key in PRIVATE_KEYS:
            continue
        why = ""
        lo = hi = None
        want: Any = spec
        if isinstance(spec, dict):
            why = str(spec.get("why", ""))
            want = spec.get("value")
            lo, hi = spec.get("min"), spec.get("max")
        found = config.get(key)
        if want is not None:
            intended = str(int(want) if isinstance(want, bool) else want)
        else:
            intended = "between " + " and ".join(str(x) for x in (lo, hi) if x is not None) if lo is not None and hi is not None \
                else (f"at least {lo}" if lo is not None else f"at most {hi}")
        if found is None:
            findings.append(Finding(key, "warning", None, intended, why, source))
        elif want is not None:
            findings.append(Finding(key, "ok" if _same(found, want) else "error", found, intended, why, source))
        else:
            v = _num(found)
            inside = v is not None and (lo is None or v >= float(lo)) and (hi is None or v <= float(hi))
            findings.append(Finding(key, "ok" if inside else "warning", found, intended, why, source))
    return findings
