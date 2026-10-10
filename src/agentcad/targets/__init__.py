"""Output targets: what a part becomes on its way to a machine.

A target turns finished parts (meshes, their placement on the plate, the print intent) into what
one slicer, printer host or machine takes, and reads back what that tool produced. Targets
register under a short lower-case name, as engines do. Each declares the capabilities it has:

* ``write_job``: write a project or package for a job (``write_job(job, out_dir)``);
* ``slice``: slice headless (``slice(project_file, out_dir)``);
* ``read_output``: read the target's outputs and the settings they carry (``read_settings(path)``);
* ``map_intent``: map neutral print intent to native settings (``map_intent(intent)``);
* ``printer_config``: describe a printer from the target's printer configuration (``printer(path)``).

A capability a target does not declare raises :class:`NotSupported` naming the target, never a
silent no-op, so adding the next target changes no command: the commands ask the registry what
each target can do.
"""

from abc import ABC
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Tuple, Type

CAPABILITIES = ("write_job", "slice", "read_output", "map_intent", "printer_config")

IDENTITY = ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0))


class NotSupported(Exception):
    """A target was asked for a capability it does not declare."""


@dataclass
class JobPart:
    """One part of a job: its mesh, how many, and where it sits: the model-to-bed transform as a
    row-major 4x4 acting on column vectors (p_bed = T p_model), translation in the last column."""
    name: str
    stl: Path
    copies: int = 1
    transform: Sequence[Sequence[float]] = IDENTITY


@dataclass
class Job:
    """What a target is asked to stage: named parts, the neutral print intent ([print]), and the
    target's own native settings ([slice.<target>])."""
    name: str
    parts: List[JobPart]
    intent: Dict[str, Any] = field(default_factory=dict)
    native: Dict[str, Any] = field(default_factory=dict)


class OutputTarget(ABC):
    """An output target; subclasses set ``name`` and ``capabilities`` and implement those methods."""

    name: str = ""
    capabilities: FrozenSet[str] = frozenset()

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


# imported last: the generic target subclasses OutputTarget, defined above
from agentcad.targets import generic as _generic  # noqa: E402

register_target("generic", _generic.GenericTarget)
