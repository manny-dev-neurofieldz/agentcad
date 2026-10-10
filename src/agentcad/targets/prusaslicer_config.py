"""PrusaSlicer's configuration, as the prusaslicer target reads and writes it.

A project starts from a *base configuration*: the complete flat configuration of one printer, one
filament and one print profile, which agentcad never ships. It is read from any of:

* an exported ``.ini`` (File, Export, Export Config in PrusaSlicer): ``key = value`` lines and ``#``
  comments, no sections;
* a project 3MF: the ``Metadata/Slic3r_PE.config`` member, ``; key = value`` lines;
* a sliced file: the configuration a ``.gcode`` (the comment block) or a ``.bgcode`` (its slicer
  metadata) carries.

The kind is told from the file's first bytes, not its name. A config bundle (``[print:name]``
sections, many presets) is not one configuration and is refused.

PrusaSlicer reads a 3MF's configuration as it reads a G-code file's: line by line from the end of the
text upward, each line ``; key = value``, and it stops at the first line that is not one. The text
written here is therefore one header line, a blank line, and nothing but settings after it.
"""

import re
from pathlib import Path
from typing import Dict, Iterable, List, Union

from agentcad.gcode import bgcode, check
from agentcad.gcode.compare import is_private      # the print-host family and post-processing (also used by the target)
from agentcad.targets import TargetError

#: A slicer setting is named in lower case with underscores (a statistic written beside the settings has spaces).
SETTING_KEY = re.compile(r"[a-z][a-z0-9_]*")

#: Settings every configuration PrusaSlicer exports carries and a project cannot do without: the bed and the
#: height the bed check reads, the start and end G-code a print needs, and the profile's basic values. A
#: configuration that lacks one is a fragment, and PrusaSlicer would fill the gap with its own default
#: (an empty start G-code, for one) without a word.
COMPLETE_KEYS = ("printer_technology", "bed_shape", "max_print_height", "nozzle_diameter", "gcode_flavor",
                 "start_gcode", "end_gcode", "layer_height", "perimeters", "fill_density", "support_material",
                 "temperature", "bed_temperature", "filament_diameter")

#: PrusaSlicer leaves these out of the configuration a project carries (they belong to presets).
NOT_IN_PROJECT = ("compatible_printers", "compatible_prints")


def parse_ini(text: str) -> Dict[str, str]:
    """The settings of a flat PrusaSlicer ``.ini``: ``key = value`` lines, ``#`` and ``;`` comments and blank
    lines skipped. A ``[section]`` header means a config bundle: TargetError."""
    out: Dict[str, str] = {}
    for number, raw in enumerate(text.lstrip("\ufeff").splitlines(), start=1):
        line = raw.strip()
        if not line or line[0] in "#;":
            continue
        if line.startswith("["):
            raise TargetError(f"line {number} opens a section ({line[:40]}): that is a config bundle of many "
                              f"presets, not one configuration; export one (File, Export, Export Config), "
                              f"save a project, or give a file PrusaSlicer sliced")
        key, sep, value = line.partition("=")
        key = key.strip()
        if sep and SETTING_KEY.fullmatch(key):
            out[key] = value.strip()
    return out


def format_config(settings: Dict[str, str], header: str) -> str:
    """The text of a 3MF's ``Metadata/Slic3r_PE.config``: a header line, a blank line, then every setting as
    ``; key = value`` in key order (an empty value keeps its trailing space, as PrusaSlicer writes it). A value
    or a header with a line break would end the configuration early; TargetError names the key."""
    for key, value in settings.items():
        if "\n" in value or "\r" in value:
            raise TargetError(f"the value of {key} has a line break: a configuration value is one line "
                              f"(PrusaSlicer writes a break inside a value as the two characters \\n)")
    lines: List[str] = [f"; {header}", ""]
    lines += [f"; {key} = {settings[key]}" for key in sorted(settings)]
    return "\n".join(lines) + "\n"


def _settings_only(config: Dict[str, str]) -> Dict[str, str]:
    from agentcad.gcode.sliced import is_setting_key
    return {k: v for k, v in config.items() if is_setting_key(k)}


def load(path: Union[str, Path]) -> Dict[str, str]:
    """The configuration a file carries, statistics left out. TargetError for a file that cannot be read,
    that carries no PrusaSlicer configuration, or is a config bundle: one line saying what to supply."""
    path = Path(path)
    try:
        if bgcode.is_bgcode(path):
            config = dict(bgcode.read(path).metadata.get("slicer_metadata", {}))
        elif check.is_3mf(path):
            config = check.config_from_3mf(path)
        else:
            text = path.read_text(encoding="utf-8", errors="replace")
            block = check.config_block(text)
            config = block if block is not None else (parse_ini(text) or check.config_from_text(text))
    except OSError as e:
        raise TargetError(f"cannot read {path}: {e.strerror or e}") from None
    except ValueError as e:                   # a bundle, a damaged .bgcode, a 3MF with no configuration
        said = str(e)
        raise TargetError(said if said.startswith(path.name) else f"{path.name}: {said}") from None
    config = _settings_only(config)
    if not config:
        raise TargetError(f"{path.name} carries no PrusaSlicer settings: give an exported .ini (File, Export, "
                          f"Export Config), a project 3MF saved from PrusaSlicer, or a .gcode or .bgcode it sliced")
    return config


def check_complete(config: Dict[str, str], source: str) -> None:
    """Refuse a configuration that is a fragment or is not for filament printing (TargetError)."""
    missing = [k for k in COMPLETE_KEYS if k not in config]
    if missing:
        raise TargetError(f"{source} is not a complete PrusaSlicer configuration (it lacks {', '.join(missing)}); "
                          f"supply one exported from PrusaSlicer, a project saved from it, or a file it sliced")
    technology = config["printer_technology"].strip().strip('"')
    if technology != "FFF":
        raise TargetError(f"{source} is a configuration for {technology} printing; this target writes projects "
                          f"for filament (FFF) printers")


def left_out(config: Iterable[str]) -> List[str]:
    """The keys of a configuration that a project never carries because they hold a credential, an address or a
    program to run (the print-host family and post-processing), in key order. ``post_process`` is among
    them: the target writes it empty rather than leaving it out."""
    return sorted(k for k in config if is_private(k))
