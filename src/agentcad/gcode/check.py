"""Settings check: what a sliced file was sliced with, against what the project intended.

Intent is read from a TOML file (a project's ``agentcad.toml``, a print job's ``job.toml``, or any other) as the
slicer's target sees it: the neutral ``[print]`` table as the target maps it (``layer_height``, ``walls``,
``infill_percent``, ``supports``), then the bare ``[slice]`` table when the target is the file's default, then
``[slice.<target>]``, keyed by the slicer's own setting names. A native value that differs from the mapped one wins
and is reported as a conflict. A value is either the intended value, or a table with ``value`` or ``min``/``max``
and an optional ``why``::

    [print]
    layer_height = 0.2                  # checked as layer_height, why "[print] layer_height"
    [slice]
    temperature = { min = 270, max = 285, why = "layer bond in ASA-CF" }
    support_material_buildplate_only = { value = 1, why = "supports must not grow inside the bores" }

The file's configuration comes from the slicer metadata block of a .bgcode, the ``; key = value`` comment
block a plain G-code export carries, or the configuration a PrusaSlicer 3MF project keeps in
``Metadata/Slic3r_PE.config`` (the same ``; key = value`` lines). Each finding is a sentence: the key, both
values, where the intent was declared, why it matters, and the usual fix.
"""

import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from agentcad.config import tomllib
from agentcad.findings import FIX_DIFFERS, FIX_MISSING, Finding   # Finding: callers import it from here too
from agentcad.gcode import bgcode

#: Settings worth printing when a project declares no intent.
KEY_SETTINGS = (
    "printer_settings_id", "print_settings_id", "filament_settings_id", "layer_height", "temperature",
    "bed_temperature", "fill_density", "perimeters", "support_material", "support_material_buildplate_only",
    "support_material_threshold", "support_material_style", "support_material_contact_distance", "brim_width",
)

#: Never echoed: credentials and machine paths a slicer may store in its configuration.
PRIVATE_KEYS = ("printhost_apikey", "printhost_password", "printhost_user", "printhost_cafile", "post_process")


#: Where PrusaSlicer keeps a project's configuration inside a 3MF.
THREEMF_CONFIG = "Metadata/Slic3r_PE.config"


def is_3mf(path: Union[str, Path]) -> bool:
    """Whether the file is a 3MF (a zip archive), by its first bytes, not its name."""
    with open(path, "rb") as f:
        return f.read(4) == b"PK\x03\x04"


def config_from_3mf(path: Union[str, Path]) -> Dict[str, str]:
    """The configuration a PrusaSlicer 3MF project carries. A 3MF written by another tool has none: ValueError."""
    path = Path(path)
    try:
        with zipfile.ZipFile(path) as z:
            data = z.read(THREEMF_CONFIG)
    except zipfile.BadZipFile as e:
        raise ValueError(f"{path.name} is not a readable 3MF: {e}") from None
    except KeyError:
        raise ValueError(f"{path.name} is a 3MF without {THREEMF_CONFIG}: it carries no PrusaSlicer "
                         f"configuration (save the project from PrusaSlicer, or stage it with the prusaslicer "
                         f"target)") from None
    return config_from_text(data.decode("utf-8", errors="replace"))


def embedded_config(path: Union[str, Path]) -> Dict[str, str]:
    """The slicer configuration a file carries: a .bgcode's metadata, a 3MF project's configuration, or a
    plain G-code file's comment block."""
    path = Path(path)
    if bgcode.is_bgcode(path):
        return dict(bgcode.read(path).metadata.get("slicer_metadata", {}))
    if is_3mf(path):
        return config_from_3mf(path)
    return config_from_text(path.read_text(encoding="utf-8", errors="replace"))


def _comments(text: str):
    """(key, value, state) of every ``; key = value`` comment in plain G-code text. ``state`` is None before any
    configuration block, True inside one and False after it; the block's own begin and end lines are not yielded."""
    in_block = None
    for line in text.splitlines():
        if not line.startswith(";") or " = " not in line:
            continue
        k, v = line[1:].split(" = ", 1)
        k, v = k.strip(), v.strip()
        if k.endswith("_config") and v in ("begin", "end"):
            in_block = v == "begin"
            continue
        yield k, v, in_block


def config_from_text(text: str, whole: bool = False) -> Dict[str, str]:
    """Every ``; key = value`` comment of plain G-code text, up to the end of the configuration block.

    Lines before the block count too: a slicer writes its statistics (filament used, estimated printing time)
    there, and a file without a block is all comments. Telling statistics from settings is the caller's job
    (a setting's name has no spaces). Nothing after the block's end is read unless ``whole`` is set, which
    reads the statistics a file writes after its block."""
    return {k: v for k, v, state in _comments(text) if whole or state is None or state}


def config_block(text: str) -> Optional[Dict[str, str]]:
    """The settings inside the configuration block of plain G-code text, and nothing else; None when the text
    carries no block."""
    block: Dict[str, str] = {}
    seen = False
    for k, v, state in _comments(text):
        if state is not None:
            seen = True
        if state:
            block[k] = v
    return block if seen else None


#: The target whose sliced files this check reads.
READER_TARGET = "prusaslicer"


def intent_for(path: Union[str, Path], target_name: str = READER_TARGET) -> Tuple[Dict[str, Any], List[str], List[str]]:
    """The settings a file sliced by ``target_name`` is checked against, from a TOML file: its ``[print]`` intent as
    the target maps it (each mapped setting's ``why`` names the ``[print]`` key it came from), then the bare
    ``[slice]`` table when the target is the file's default (``[print] target``, else prusaslicer), then
    ``[slice.<target>]``. Returns the settings, a note for each ``[print]`` key the target has no setting for, and
    each conflict where a native value overrides a mapped one. TargetError for a ``[print]`` value the target
    cannot use."""
    from agentcad import targets
    from agentcad.config import split_slice
    if tomllib is None:
        raise RuntimeError("reading intent needs tomllib (Python 3.11+) or the tomli package")
    with open(path, "rb") as f:
        data = tomllib.load(f)
    neutral = dict(data.get("print") or {})
    bare, per_target = split_slice(data.get("slice") or {})
    native = dict(bare) if target_name == str(neutral.get("target") or READER_TARGET) else {}
    native.update(per_target.get(target_name, {}))
    mapped: Dict[str, Any] = {}
    notes: List[str] = []
    origin: Dict[str, str] = {}
    stated = {k: v for k, v in neutral.items() if k != "target"}
    if stated:
        target = targets.get_target(target_name)
        mapped, notes = target.map_intent(stated)
        for key, value in stated.items():                 # which [print] key each mapped setting came from
            try:
                for setting in target.map_intent({key: value})[0]:
                    origin.setdefault(setting, key)
            except targets.TargetError:
                pass
    settings, conflicts = targets.layer_native(mapped, native)
    for key in mapped:
        if key not in native:
            settings[key] = {"value": settings[key], "why": f"[print] {origin.get(key, key)}"}
    return settings, notes, conflicts


def load_intent(path: Union[str, Path]) -> Dict[str, Any]:
    """The settings a sliced file is checked against, from a TOML file (``intent_for``); empty when the file states
    no print or slice intent."""
    return intent_for(path)[0]


def _num(v: Any) -> Optional[float]:
    try:
        return float(str(v).strip().rstrip("%").split(",")[0])
    except ValueError:
        return None


_ESCAPES = {"n": "\n", "r": "\r", "t": "\t"}


def _unescape(s: str) -> str:
    out, chars = [], iter(s)
    for c in chars:
        if c == "\\":
            nxt = next(chars, "")
            out.append(_ESCAPES.get(nxt, nxt))
        else:
            out.append(c)
    return "".join(out)


def _quoted(s: str) -> bool:
    return len(s) >= 2 and s[0] == '"' and s[-1] == '"'


def _text(value: Any, written: bool = False) -> str:
    """A value as text the way the slicer means it. The slicer escapes every string setting it writes: a list of
    strings value-quoted (``filament_notes = "say \\"hi\\""``), a single string bare (``start_gcode = M17\\nG28``),
    so a value read from a file (``written``) has its escapes read either way. A value asked for is plain text: it
    loses one pair of quotes, and their escapes, only when it carries them."""
    s = str(value).strip()
    if _quoted(s):
        return _unescape(s[1:-1])
    return _unescape(s) if written else s


def _same(found: str, want: Any) -> bool:
    if isinstance(want, bool):
        want = int(want)
    a, b = _num(found), _num(want)
    if a is not None and b is not None:
        return abs(a - b) <= 1e-6 * max(1.0, abs(b))
    return _text(found, written=True) == _text(want)


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
            severity, fix = "warning", FIX_MISSING
        elif want is not None:
            severity = "ok" if _same(found, want) else "error"
            fix = "" if severity == "ok" else FIX_DIFFERS
        else:
            v = _num(found)
            inside = v is not None and (lo is None or v >= float(lo)) and (hi is None or v <= float(hi))
            severity, fix = ("ok", "") if inside else ("warning", FIX_DIFFERS)
        findings.append(Finding(key, severity, found, intended, why, source,
                                rule="slice_setting", layer=source, fix=fix))
    return findings
