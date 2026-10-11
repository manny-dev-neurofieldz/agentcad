"""Output targets: what a part becomes on its way to a machine.

A target turns finished parts (meshes, their placement on the plate, the print intent) into what
one slicer, printer host or machine takes, and reads back what that tool produced. Targets
register under a short lower-case name, as engines do. Each declares the capabilities it has:

* ``write_job``: write a project or package for a job (``write_job(job, out_dir)``, returning the files
  written; a :class:`Written` list also carries ``notes`` for what the target left out or changed);
* ``slice``: slice headless (``slice(project_file, out_dir)``);
* ``read_output``: read the target's outputs and the settings they carry (``read_settings(path)``);
* ``map_intent``: map neutral print intent to native settings (``map_intent(intent)``, returning the
  settings and one note per stated key that has no setting, with the reason);
* ``printer_config``: describe a printer from the target's printer configuration (``printer(path)``), and
  the printer a job is placed on (``job_printer(options)``; None when the target uses no configuration).

A capability a target does not declare raises :class:`NotSupported` naming the target, never a
silent no-op, so adding the next target changes no command: the commands ask the registry what
each target can do.

A target that cannot work from the job alone names the inputs it takes in ``job_options`` (the
slicer targets take ``base_config``, the complete configuration their projects start from); the
command line passes them in ``Job.options``, and refuses one the target does not name. An input
that is missing or unusable raises :class:`TargetError`, a message that says what to change, which
commands print as one line.
"""

from abc import ABC
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple, Type

CAPABILITIES = ("write_job", "slice", "read_output", "map_intent", "printer_config")

IDENTITY = ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0))


class NotSupported(Exception):
    """A target was asked for a capability it does not declare."""


class TargetError(ValueError):
    """A target cannot do what it was asked with the inputs it was given. The message says what to change."""


@dataclass
class JobPart:
    """One part of a job: its mesh, how many, and where it sits: the model-to-bed transform as a
    row-major 4x4 acting on column vectors (p_bed = T p_model), translation in the last column.
    ``settings`` are native settings for this part alone (a target that has per-object settings
    writes them; the others ignore them)."""
    name: str
    stl: Path
    copies: int = 1
    transform: Sequence[Sequence[float]] = IDENTITY
    settings: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Job:
    """What a target is asked to stage: named parts, the neutral print intent ([print]), the
    target's own native settings ([slice.<target>]) and the inputs the command line gave it
    (``options``, limited to the names in the target's ``job_options``)."""
    name: str
    parts: List[JobPart]
    intent: Dict[str, Any] = field(default_factory=dict)
    native: Dict[str, Any] = field(default_factory=dict)
    options: Dict[str, Any] = field(default_factory=dict)


class Written(list):
    """The files a target wrote (a list of paths) and what it has to say about the job: ``notes``,
    one line each, for what it left out or changed and why. A command prints them."""

    def __init__(self, paths: Iterable[Path] = (), notes: Iterable[str] = ()):
        super().__init__(paths)
        self.notes: List[str] = list(notes)


class OutputTarget(ABC):
    """An output target; subclasses set ``name`` and ``capabilities`` and implement those methods."""

    name: str = ""
    capabilities: FrozenSet[str] = frozenset()
    job_options: Tuple[str, ...] = ()

    def version(self) -> Optional[str]:
        """The target tool's version, when it has one and it can be read."""
        return None

    def available(self) -> bool:
        """Whether the target can work here (a slicer installed, say); declared capabilities still
        describe the target when it cannot."""
        return True

    def _unsupported(self, capability: str):
        return NotSupported(f"target {self.name!r} does not {capability.replace('_', ' ')} "
                            f"(its capabilities: {', '.join(sorted(self.capabilities)) or 'none'})")

    def write_job(self, job: Job, out_dir: Path) -> List[Path]:
        raise self._unsupported("write_job")

    def slice(self, project_file: Path, out_dir: Path) -> Path:
        raise self._unsupported("slice")

    def read_settings(self, path: Path) -> Dict[str, str]:
        raise self._unsupported("read_output")

    def map_intent(self, intent: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
        raise self._unsupported("map_intent")

    def printer(self, config_path: Path):
        raise self._unsupported("printer_config")

    def job_printer(self, options: Dict[str, Any]):
        """The printer a job with these options is placed on, as the target's own configuration describes it, or
        None when the target has none. ``agentcad stage`` centres the parts on this printer's bed, else on the QC
        printer's, so the bed the parts are centred on is the bed the target checks. A target that answers
        declares ``printer_config``."""
        return None


_REGISTRY: Dict[str, Type[OutputTarget]] = {}


def register_target(name: str, target_cls: Type[OutputTarget]) -> None:
    """Register an output target class by name."""
    _REGISTRY[name] = target_cls


def unregister_target(name: str) -> None:
    _REGISTRY.pop(name, None)


def get_target(name: str) -> OutputTarget:
    """An instance of a registered target; an error names the registered ones."""
    if name not in _REGISTRY:
        raise ValueError(f"unknown output target {name!r}; registered: {', '.join(sorted(_REGISTRY)) or 'none'}")
    return _REGISTRY[name]()


def list_targets() -> List[str]:
    return sorted(_REGISTRY)


def describe() -> List[Dict[str, Any]]:
    """Every registered target: name, version, availability and declared capabilities."""
    out = []
    for name in list_targets():
        t = get_target(name)
        out.append({"name": name, "version": t.version(), "available": bool(t.available()),
                    "capabilities": [c for c in CAPABILITIES if c in t.capabilities]})
    return out


def default_target(cfg) -> str:
    """The project's target: ``[print] target``, else prusaslicer (whose keys a bare [slice] holds)."""
    return str((getattr(cfg, "print_intent", None) or {}).get("target") or "prusaslicer")


def canonical(value: Any) -> str:
    """A setting's value as a slicer's configuration file spells it: a boolean as 1 or 0, a float
    without a needless point or tail, a list joined with commas, anything else as text. Two
    statements of one setting are compared in this form, so ``True``, ``1`` and ``"1"`` agree."""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return format(value, ".10g")
    if isinstance(value, (list, tuple)):
        return ",".join(canonical(v) for v in value)
    return str(value)


def native_tables(cfg, target_name: str) -> Dict[str, Any]:
    """A target's native settings as the project states them: the bare ``[slice]`` table when the
    target is the project's default, then ``[slice.<target>]`` over it."""
    native: Dict[str, Any] = {}
    if target_name == default_target(cfg):
        native.update(getattr(cfg, "slice_intent", {}) or {})
    native.update((getattr(cfg, "slice_targets", {}) or {}).get(target_name, {}))
    return native


def layer_native(mapped: Optional[Dict[str, Any]], native: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """The mapped intent with the native settings over it. A native value that differs from the
    mapped one wins and is reported as a conflict naming the key and both values; a native value
    that states a range only (no ``value``) is a check for ``gcode check``, not a setting, and
    conflicts with nothing."""
    settings = dict(mapped or {})
    conflicts = []
    for key, value in native.items():
        wanted = value.get("value") if isinstance(value, dict) else value
        if key in settings and wanted is not None and canonical(settings[key]).strip() != canonical(wanted).strip():
            conflicts.append(f"{key}: [print] maps to {settings[key]!r}, the native table says {wanted!r} (native kept)")
        settings[key] = value
    return settings, conflicts


def native_settings(cfg, target_name: str, mapped: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], List[str]]:
    """A target's native settings: the neutral intent as the target mapped it (``mapped``), then the
    bare ``[slice]`` table when the target is the project's default, then ``[slice.<target>]``. A
    native value that differs from the mapped one wins and is reported as a conflict."""
    return layer_native(mapped, native_tables(cfg, target_name))


# imported last: the targets subclass OutputTarget and use the helpers, defined above
from agentcad.targets import generic as _generic  # noqa: E402
from agentcad.targets import prusaslicer as _prusaslicer  # noqa: E402

register_target("generic", _generic.GenericTarget)
register_target("prusaslicer", _prusaslicer.PrusaSlicerTarget)
