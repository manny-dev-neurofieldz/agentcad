"""The prusaslicer output target: a PrusaSlicer 3MF project from a job, and what PrusaSlicer wrote back.

Capabilities: ``write_job`` (a project 3MF and the placement sidecar), ``read_output`` (the settings a
``.bgcode``, a ``.gcode`` or a project 3MF carries), ``map_intent`` (the neutral ``[print]`` keys that
have a PrusaSlicer setting) and ``printer_config`` (the bed and height of a configuration). It does not
slice: headless slicing is a later capability.

The settings a project carries are layered, and each layer can only change what the one below has:

1. the base configuration the user supplies (``job.options["base_config"]``, else ``base_config`` under
   ``[prusaslicer]`` in ``targets.toml`` in the agentcad user config folder);
2. the neutral intent, mapped (``map_intent``);
3. the native settings (``job.native``, from ``[slice]`` and ``[slice.prusaslicer]``), which win.

A key that layers 2 and 3 name and the base configuration does not carry is refused by name: a mistyped key
would otherwise be written as a setting nothing reads, and the project would silently not say what the designer
wrote. ``post_process`` is always written empty and the print-host family (credentials, addresses) is never
written. A job whose placement leaves the bed or the build height is refused before a file is written.
"""

import difflib
import json
import struct
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from agentcad import printers
from agentcad.targets import Job, OutputTarget, TargetError, Written, canonical, generic, layer_native
from agentcad.targets import prusaslicer_3mf as project
from agentcad.targets import prusaslicer_config as pconfig

USER_FILE = "targets.toml"
USER_KEYS = ("base_config",)

#: The neutral intent keys this target maps, and the PrusaSlicer settings each one sets.
MAPPED = {
    "layer_height": ("layer_height",),
    "walls": ("perimeters",),
    "infill_percent": ("fill_density",),
    "supports": ("support_material", "support_material_auto"),
}

#: Neutral keys that are not settings of the slicer, and why each is reported as not mapped.
NOT_MAPPED = {
    "material": "the filament profile in the base configuration carries the material",
    "print_orientation": "orientation is the placement's job: the print pose and the build item transforms",
    "printer_profile": "names a printer profile; the base configuration is the printer",
    "filament_profile": "names a filament profile; the base configuration is the filament",
    "target": "names the output target; it is not a setting",
    "notes": "prose, not a setting",
}

#: The settings PrusaSlicer lets one object override (its Add settings menu for an object). A key outside
#: this list in a part's settings is refused: PrusaSlicer reads an object's keys against its own list.
PER_OBJECT_KEYS = frozenset({
    "layer_height", "perimeters", "top_solid_layers", "bottom_solid_layers", "fill_density", "fill_pattern",
    "support_material", "support_material_auto", "support_material_buildplate_only", "support_material_threshold",
    "support_material_style", "support_material_contact_distance",
})

#: How far outside the bed, or below it, a posed part may reach and still be on it (floating-point noise), in mm.
BED_TOLERANCE = 1e-3
#: At most this many offending instances are named in a refusal.
NAMED_IN_REFUSAL = 4


# --- the neutral intent, mapped ---------------------------------------------------------------------------

def _number(key: str, value: Any, low: float, high: Optional[float] = None, above: bool = False) -> float:
    ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    if ok and ((value > low) if above else (value >= low)) and (high is None or value <= high):
        return float(value)
    bounds = (f"over {low:g}" if above else f"at least {low:g}") + (f" and at most {high:g}" if high is not None else "")
    raise TargetError(f"[print] {key} must be a number {bounds}, not {value!r}")


def map_intent(intent: Dict[str, Any]) -> Tuple[Dict[str, str], List[str]]:
    """PrusaSlicer settings (in the form a configuration file spells them) for the neutral intent, and one note
    ``key: reason`` for every stated key that has no setting. TargetError for a value that is not usable."""
    settings: Dict[str, str] = {}
    if "layer_height" in intent:
        settings["layer_height"] = canonical(_number("layer_height", intent["layer_height"], 0, above=True))
    if "walls" in intent:
        walls = _number("walls", intent["walls"], 0)
        if walls != int(walls):
            raise TargetError(f"[print] walls must be a whole number, not {intent['walls']!r}")
        settings["perimeters"] = str(int(walls))
    if "infill_percent" in intent:
        settings["fill_density"] = canonical(_number("infill_percent", intent["infill_percent"], 0, 100)) + "%"
    if "supports" in intent:
        if not isinstance(intent["supports"], bool):
            raise TargetError(f"[print] supports must be true or false, not {intent['supports']!r}")
        settings["support_material"] = "1" if intent["supports"] else "0"
        if intent["supports"]:
            settings["support_material_auto"] = "1"      # generated where needed, not only for enforcers
    notes = [f"{key}: {NOT_MAPPED.get(key, 'this target has no setting for it')}"
             for key in sorted(intent) if key not in MAPPED]
    return settings, notes


# --- the settings a job writes ---------------------------------------------------------------------------

@dataclass
class Resolved:
    settings: Dict[str, str]                    # every setting of the project, as written
    objects: List[Dict[str, str]]               # per part, in job order: its own settings, as written
    conflicts: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def _text(key: str, spec: Any, base: Dict[str, str], notes: List[str]) -> Optional[str]:
    """The text to write for a setting, or None when it states no value. TargetError for a key the project must
    never carry or the base configuration does not have."""
    if pconfig.is_private(key):
        raise TargetError(f"{key} is never written: " + (
            "it names a program that runs on the machine that slices (post_process is always written empty)"
            if key == "post_process" else "it holds a credential or an address"))
    if key not in base:
        close = difflib.get_close_matches(key, list(base), n=3)
        raise TargetError(f"{key} is not a setting of the base configuration"
                          + (f" (did you mean {', '.join(close)}?)" if close else "")
                          + "; a native or mapped setting must name a key the base configuration carries")
    value = spec.get("value") if isinstance(spec, dict) else spec
    if value is None:
        notes.append(f"{key}: a range or a reason without a value is a check for gcode check, not a setting; not written")
        return None
    return canonical(value)


def resolve(job: Job, base: Dict[str, str]) -> Resolved:
    """The settings of the project a job writes over ``base``: the mapped intent, then the native settings, the
    print-host family removed and ``post_process`` empty; each part's own settings. TargetError names what is wrong."""
    notes: List[str] = []
    mapped, _ = map_intent(job.intent)
    layered, conflicts = layer_native(mapped, job.native)
    settings = dict(base)
    for key, spec in layered.items():
        text = _text(key, spec, base, notes)
        if text is not None:
            settings[key] = text
    withheld = pconfig.left_out(base)
    for key in withheld:
        settings.pop(key, None)
    for key in pconfig.NOT_IN_PROJECT:
        settings.pop(key, None)
    settings["post_process"] = ""
    if base.get("post_process", "").strip():
        notes.append("post_process: set in the base configuration; written empty")
    hosts = [k for k in withheld if k != "post_process"]
    if hosts:
        notes.append("left out of the project (credentials and addresses are never written): " + ", ".join(hosts))
    material, kind = job.intent.get("material"), base.get("filament_type", "").split(";")[0].split(",")[0].strip('" ')
    if material not in (None, "") and kind and str(material).strip().lower() != kind.lower():
        notes.append(f"material: [print] says {material}, the base configuration's filament_type is {kind}; "
                     f"the project carries the base configuration's filament")
    objects: List[Dict[str, str]] = []
    for part in job.parts:
        chosen: Dict[str, str] = {}
        for key in sorted(part.settings):
            if key not in PER_OBJECT_KEYS:
                raise TargetError(f"{part.name}: {key} cannot be set for one object in PrusaSlicer "
                                  f"(it can for: {', '.join(sorted(PER_OBJECT_KEYS))}); set it for the whole job")
            text = _text(key, part.settings[key], base, notes)
            if text is not None:
                chosen[key] = text
        objects.append(chosen)
    return Resolved(settings, objects, conflicts, notes)


# --- the bed -------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Bed:
    outline: Tuple[Tuple[float, float], ...]    # the bed's polygon, in the frame a 3MF build item places in
    height: float                               # the build height, mm
    label: str


def bed_of(config: Dict[str, str]) -> Bed:
    """The bed polygon (``bed_shape``), build height (``max_print_height``) and name a configuration describes.
    TargetError for a value that is not understood."""
    try:
        points = tuple((float(x), float(y)) for x, y in
                       (p.strip().split("x") for p in str(config["bed_shape"]).split(",")))
        if len(points) < 3:
            raise ValueError("fewer than three points")
        height = float(config["max_print_height"])
        printer = printers.from_slicer_config(config)
    except KeyError as e:
        raise TargetError(f"the configuration has no {e.args[0]}, which the bed check reads") from None
    except ValueError as e:
        raise TargetError(f"bed_shape ({config.get('bed_shape')}) or max_print_height "
                          f"({config.get('max_print_height')}) is not understood: {e}") from None
    return Bed(points, height, printer.label)


def _area(poly: Sequence[Tuple[float, float]]) -> float:
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(poly, list(poly[1:]) + [poly[0]]))) / 2.0


def _hull(points) -> List[Tuple[float, float]]:
    """The convex hull of 2D points (Andrew's monotone chain), counter-clockwise."""
    pts = sorted(set(map(tuple, points)))
    if len(pts) <= 2:
        return pts

    def half(seq):
        chain: List[Tuple[float, float]] = []
        for p in seq:
            while len(chain) >= 2 and ((chain[-1][0] - chain[-2][0]) * (p[1] - chain[-2][1])
                                       - (chain[-1][1] - chain[-2][1]) * (p[0] - chain[-2][0])) <= 0:
                chain.pop()
            chain.append(p)
        return chain[:-1]
    return half(pts) + half(reversed(pts))


def _inside(poly: Sequence[Tuple[float, float]], x: float, y: float, eps: float) -> bool:
    """Whether a point is in the polygon or within ``eps`` of its edge."""
    inside = False
    n = len(poly)
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        length2 = dx * dx + dy * dy
        t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / length2))
        if (x - (x0 + t * dx)) ** 2 + (y - (y0 + t * dy)) ** 2 <= eps * eps:
            return True
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * dx / dy:
            inside = not inside
    return inside


def check_bed(instances: Sequence[Dict[str, Any]], meshes: Dict[str, Tuple[Any, Any]], bed: Bed) -> None:
    """Refuse a placement whose posed part is below the bed, higher than the printer prints or outside the
    bed's outline: TargetError naming the instances and how far they reach."""
    import numpy as np
    xs, ys = [p[0] for p in bed.outline], [p[1] for p in bed.outline]
    lo, hi = (min(xs), min(ys)), (max(xs), max(ys))
    rectangle = abs(_area(bed.outline) - (hi[0] - lo[0]) * (hi[1] - lo[1])) <= 1e-9 * max(1.0, _area(bed.outline))
    copies = Counter(inst["part"] for inst in instances)
    eps = BED_TOLERANCE
    problems: List[str] = []
    for inst in instances:
        T = np.asarray(inst["transform"], dtype=float)
        P = meshes[inst["part"]][0] @ T[:3, :3].T + T[:3, 3]
        a, b = P.min(axis=0), P.max(axis=0)
        who = inst["part"] if copies[inst["part"]] == 1 else f"{inst['part']} (copy {inst['copy']})"
        if a[2] < -eps:
            problems.append(f"{who} reaches {-a[2]:.2f} mm below the bed")
        if b[2] > bed.height + eps:
            problems.append(f"{who} is {b[2]:.1f} mm high in its pose, over the {bed.height:g} mm the printer prints")
        if rectangle:
            off = a[0] < lo[0] - eps or b[0] > hi[0] + eps or a[1] < lo[1] - eps or b[1] > hi[1] + eps
        else:                                    # a footprint is inside a bed outline when its hull corners are
            off = not all(_inside(bed.outline, x, y, eps) for x, y in _hull(P[:, :2]))
        if off:
            problems.append(f"{who} covers x {a[0]:.1f} to {b[0]:.1f} and y {a[1]:.1f} to {b[1]:.1f} mm, off the bed "
                            f"(x {lo[0]:g} to {hi[0]:g}, y {lo[1]:g} to {hi[1]:g})")
    if problems:
        more = f"; and {len(problems) - NAMED_IN_REFUSAL} more" if len(problems) > NAMED_IN_REFUSAL else ""
        raise TargetError(f"the placement does not fit the bed of {bed.label}: "
                          + "; ".join(problems[:NAMED_IN_REFUSAL]) + more
                          + " (fewer copies, another pose, or a base configuration for a larger printer)")


# --- the base configuration the user supplies -------------------------------------------------------------

def user_base_config() -> Optional[Path]:
    """The base configuration named under ``[prusaslicer]`` in ``targets.toml`` in the agentcad user config
    folder, or None when the file or the key is absent. A relative path is relative to that folder."""
    path = printers.user_config_dir() / USER_FILE
    if not path.is_file():
        return None
    from agentcad.config import tomllib
    if tomllib is None:
        raise TargetError(f"{path} exists but this Python has no TOML reader (use Python 3.11 or install tomli); "
                          f"pass --base-config instead")
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except OSError as e:
        raise TargetError(f"cannot read {path}: {e.strerror or e}") from None
    except ValueError as e:
        raise TargetError(f"cannot parse {path}: {e}") from None
    table = data.get("prusaslicer", {})
    if not isinstance(table, dict):
        raise TargetError(f"{path}: [prusaslicer] must be a table")
    unknown = sorted(set(table) - set(USER_KEYS))
    if unknown:
        raise TargetError(f"{path}: unknown setting(s) in [prusaslicer]: {', '.join(unknown)} "
                          f"(known: {', '.join(USER_KEYS)})")
    value = table.get("base_config")
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise TargetError(f"{path}: base_config must be a path, in quotes")
    chosen = Path(value).expanduser()
    return chosen if chosen.is_absolute() else path.parent / chosen


def base_config_path(job: Job) -> Path:
    """The base configuration of a job: the option the command line gave, else the user's default."""
    given = job.options.get("base_config")
    if given:
        return Path(given)
    default = user_base_config()
    if default is None:
        raise TargetError(
            "no base configuration: pass --base-config PATH (a PrusaSlicer .ini export, a project 3MF, or a "
            f".gcode or .bgcode it sliced), or set base_config under [prusaslicer] in {USER_FILE} in "
            f"{printers.user_config_dir()}")
    return default


# --- the target -------------------------------------------------------------------------------------------

class PrusaSlicerTarget(OutputTarget):
    name = "prusaslicer"
    capabilities = frozenset({"write_job", "read_output", "map_intent", "printer_config"})
    job_options = ("base_config",)

    def write_job(self, job: Job, out_dir: Path) -> List[Path]:
        if not job.parts:
            raise TargetError("the job has no parts")
        names = Counter(part.name for part in job.parts)
        twice = sorted(n for n, k in names.items() if k > 1)
        if twice:
            raise TargetError(f"two parts are named {', '.join(twice)}: a project names its objects apart")
        base_path = base_config_path(job)
        base = pconfig.load(base_path)
        pconfig.check_complete(base, base_path.name)
        resolved = resolve(job, base)
        meshes = {}
        for part in job.parts:
            try:
                meshes[part.name] = generic.mesh_of(part.stl)
            except (OSError, ValueError, struct.error) as e:    # a truncated binary STL raises struct.error
                raise TargetError(f"cannot read the mesh of {part.name} ({Path(part.stl).name}): {e}") from None
            if not len(meshes[part.name][1]):
                raise TargetError(f"the mesh of {part.name} ({Path(part.stl).name}) has no triangles")
        insts = generic.instances(job, meshes)
        check_bed(insts, meshes, bed_of(resolved.settings))
        out_dir = Path(out_dir)
        sidecar = out_dir / f"{job.name}.placement.json"
        try:
            written = project.write_project(out_dir / f"{job.name}.3mf", job, insts, meshes, resolved.settings,
                                            resolved.objects)
            sidecar.write_text(json.dumps(generic.placement(job, self.name, insts), indent=1) + "\n")
        except OSError as e:
            raise TargetError(f"cannot write the project to {out_dir}: {e.strerror or e}") from None
        return Written([written, sidecar],
                       [f"base configuration: {base_path.name} ({len(base)} settings)"] + resolved.notes)

    def read_settings(self, path: Path) -> Dict[str, str]:
        from agentcad.gcode.check import embedded_config
        return embedded_config(Path(path))

    def map_intent(self, intent: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
        return map_intent(intent)

    def printer(self, config_path: Path):
        config = pconfig.load(config_path)
        try:
            return printers.from_slicer_config(config, name=Path(config_path).stem)
        except KeyError as e:
            raise TargetError(f"{Path(config_path).name} has no {e.args[0]}, which a printer is described by") from None
        except ValueError as e:
            raise TargetError(f"{Path(config_path).name}: bed_shape or max_print_height is not understood: {e}") from None
