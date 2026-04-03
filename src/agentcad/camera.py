"""Engine-agnostic camera preset system for multi-view rendering."""

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class CameraPreset:
    """A camera viewpoint for rendering.

    Coordinates follow OpenSCAD convention:
    - translate: (x, y, z) camera target offset
    - rotate: (x, y, z) rotation angles in degrees
    - distance: camera distance (0 = auto-fit)
    """
    name: str
    translate: Tuple[float, float, float] = (0, 0, 0)
    rotate: Tuple[float, float, float] = (0, 0, 0)
    distance: float = 0
    orthographic: bool = False

    @property
    def camera_string(self) -> str:
        """Format as OpenSCAD --camera argument value."""
        tx, ty, tz = self.translate
        rx, ry, rz = self.rotate
        return f"{tx},{ty},{tz},{rx},{ry},{rz},{self.distance}"


STANDARD_PRESETS: Dict[str, CameraPreset] = {
    "iso": CameraPreset(
        name="iso",
        rotate=(55, 0, 45),
    ),
    "front": CameraPreset(
        name="front",
        rotate=(90, 0, 0),
        orthographic=True,
    ),
    "top": CameraPreset(
        name="top",
        rotate=(0, 0, 0),
        orthographic=True,
    ),
    "right": CameraPreset(
        name="right",
        rotate=(90, 0, 90),
        orthographic=True,
    ),
    "back": CameraPreset(
        name="back",
        rotate=(90, 0, 180),
        orthographic=True,
    ),
}

MULTI_VIEW_DEFAULT = ["iso", "front", "top", "right"]
