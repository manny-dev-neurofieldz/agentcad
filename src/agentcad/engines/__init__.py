"""CAD engine registry."""

from typing import Dict, Type

from agentcad.engine import CADEngine

_REGISTRY: Dict[str, Type[CADEngine]] = {}


def register_engine(name: str, engine_cls: Type[CADEngine]) -> None:
    """Register a CAD engine class by name."""
    _REGISTRY[name] = engine_cls


def get_engine(name: str, **kwargs) -> CADEngine:
    """Instantiate a registered engine by name."""
    if name not in _REGISTRY:
        raise ValueError(
            f"Unknown engine '{name}'. "
            f"Available: {list(_REGISTRY.keys())}"
        )
    return _REGISTRY[name](**kwargs)


def list_engines() -> list:
    """List registered engine names."""
    return list(_REGISTRY.keys())


# Auto-register engines that are importable
import logging as _logging

_log = _logging.getLogger(__name__)

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
