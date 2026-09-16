"""CAD engine registry.

Engines register under a short lower-case name (the value of
``[project] engine`` in ``agentcad.toml`` and of the CLI's ``-e`` flag).
Import failures keep an engine out of the registry; a registered engine
whose backend is missing still constructs, and reports ``available() ==
False`` so callers can say why rather than crash.
"""

import logging
from typing import Any, Dict, List, Mapping, Optional, Type

from agentcad.engine import CADEngine

_REGISTRY: Dict[str, Type[CADEngine]] = {}
_log = logging.getLogger(__name__)


def register_engine(name: str, engine_cls: Type[CADEngine]) -> None:
    """Register a CAD engine class by name."""
    _REGISTRY[name] = engine_cls


def get_engine(name: str, settings: Optional[Mapping[str, Any]] = None, **overrides) -> CADEngine:
    """Instantiate a registered engine with its settings table and overrides."""
    if name not in _REGISTRY:
        raise ValueError(
            f"Unknown engine '{name}'. "
            f"Available: {list(_REGISTRY.keys())}"
        )
    return _REGISTRY[name](settings, **overrides)


def list_engines() -> List[str]:
    """Registered engine names."""
    return list(_REGISTRY.keys())


def engine_extensions() -> Dict[str, str]:
    """Registered engine name -> source file extension (with dot)."""
    return {name: cls.FILE_EXTENSION for name, cls in _REGISTRY.items()}


def all_export_formats() -> List[str]:
    """Union of export formats across registered engines, sorted."""
    formats = set()
    for cls in _REGISTRY.values():
        formats.update(cls.EXPORT_FORMATS)
    return sorted(formats)


# Auto-register engines that are importable
try:
    from agentcad.engines.openscad import OpenSCADEngine
    register_engine("openscad", OpenSCADEngine)
except ImportError as e:
    _log.debug("OpenSCAD engine not available: %s", e)

try:
    from agentcad.engines.voxelcad import VoxelCADEngine
    register_engine("voxelcad", VoxelCADEngine)
except ImportError as e:
    _log.debug("VoxelCAD engine not available: %s", e)

try:
    from agentcad.engines.build123d import Build123dEngine
    register_engine("build123d", Build123dEngine)
except ImportError as e:
    _log.debug("build123d engine not available: %s", e)
