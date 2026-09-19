"""Engine-neutral camera presets for multi-view rendering.

A preset is a viewing direction, not an engine command line. It is stored as
the unit vector from the target toward the camera (``eye``), a ``target``
point, an ``up`` vector and a projection flag. Every engine derives what it
needs from that: the OpenSCAD engine asks for the gimbal rotation the
``--camera`` flag wants, a PyVista-based engine asks for a camera position
around a bounding sphere. Presets therefore describe the same view on every
engine, which is what makes cross-engine renders comparable.

The OpenSCAD gimbal convention is the historical reference for the presets:
``rotate=(rx, 0, rz)`` means the camera looks down the +Z axis, is tilted by
``rx`` about X, then swung by ``rz`` about Z. ``from_rotation`` and
``rotate`` convert both ways so the presets keep their familiar numbers.
"""

import math
from dataclasses import dataclass
from typing import Dict, Tuple

Vec3 = Tuple[float, float, float]


def _normalize(v: Vec3) -> Vec3:
    length = math.sqrt(sum(c * c for c in v))
    if length == 0.0:
        raise ValueError("camera eye direction must not be the zero vector")
    return (v[0] / length, v[1] / length, v[2] / length)


def _rotation_to_eye(rot_x: float, rot_z: float) -> Vec3:
    """OpenSCAD gimbal angles (degrees) -> unit eye direction."""
    rx = math.radians(rot_x)
    rz = math.radians(rot_z)
    # Rz(rz) * Rx(rx) * (0, 0, 1)
    return (
        math.sin(rx) * math.sin(rz),
        -math.sin(rx) * math.cos(rz),
        math.cos(rx),
    )


def _eye_to_rotation(eye: Vec3) -> Tuple[float, float]:
    """Unit eye direction -> OpenSCAD gimbal angles (rot_x, rot_z) in degrees."""
    x, y, z = eye
    rot_x = math.degrees(math.acos(max(-1.0, min(1.0, z))))
    rot_z = math.degrees(math.atan2(x, -y)) % 360.0 if rot_x > 1e-9 else 0.0
    return (round(rot_x, 6), round(rot_z, 6))


def _fmt(value: float) -> str:
    """Format a float the way the legacy camera string did (no trailing .0)."""
    return f"{value:g}"


@dataclass(frozen=True)
class CameraPreset:
    """A named viewpoint.

    Attributes:
        name: Preset name used in view lists and output filenames.
        eye: Unit vector from ``target`` toward the camera.
        target: Point the camera looks at (engine may recentre on the model).
        up: Screen-up direction.
        orthographic: Parallel projection when True, perspective otherwise.
        distance: Camera distance from target; 0 means "fit the model".
    """
    name: str
    eye: Vec3 = (0.0, 0.0, 1.0)
    target: Vec3 = (0.0, 0.0, 0.0)
    up: Vec3 = (0.0, 0.0, 1.0)
    orthographic: bool = False
    distance: float = 0.0

    def __post_init__(self):
        object.__setattr__(self, "eye", _normalize(self.eye))
        object.__setattr__(self, "up", _normalize(self.up))

    @classmethod
    def from_rotation(cls, name: str, rot_x: float, rot_z: float, **kwargs) -> "CameraPreset":
        """Build a preset from OpenSCAD gimbal angles (degrees)."""
        return cls(name=name, eye=_rotation_to_eye(rot_x, rot_z), **kwargs)

    @property
    def rotate(self) -> Vec3:
        """OpenSCAD gimbal rotation (rx, ry, rz) in degrees; ry is always 0."""
        rot_x, rot_z = _eye_to_rotation(self.eye)
        return (rot_x, 0.0, rot_z)

    @property
    def translate(self) -> Vec3:
        """OpenSCAD camera target offset."""
        return self.target

    @property
    def camera_string(self) -> str:
        """Value for OpenSCAD's ``--camera`` flag: tx,ty,tz,rx,ry,rz,distance."""
        tx, ty, tz = self.translate
        rx, ry, rz = self.rotate
        return ",".join(_fmt(v) for v in (tx, ty, tz, rx, ry, rz, self.distance))

    def eye_position(self, center: Vec3, radius: float, factor: float = 2.5) -> Vec3:
        """Camera location for a scene bounded by a sphere.

        Args:
            center: Bounding-sphere centre (becomes the look-at point).
            radius: Bounding-sphere radius.
            factor: Distance multiplier used when ``distance`` is 0 (fit).
        """
        d = self.distance if self.distance > 0 else max(radius, 1e-9) * factor
        return (
            center[0] + self.eye[0] * d,
            center[1] + self.eye[1] * d,
            center[2] + self.eye[2] * d,
        )


STANDARD_PRESETS: Dict[str, CameraPreset] = {
    "iso": CameraPreset.from_rotation("iso", 55, 45),
    "front": CameraPreset.from_rotation("front", 90, 0, orthographic=True),
    "top": CameraPreset.from_rotation("top", 0, 0, up=(0.0, 1.0, 0.0), orthographic=True),
    "right": CameraPreset.from_rotation("right", 90, 90, orthographic=True),
    "back": CameraPreset.from_rotation("back", 90, 180, orthographic=True),
    "left": CameraPreset.from_rotation("left", 90, 270, orthographic=True),
    # Looking up at the underside: counterbores and chamfers cut from below
    # are invisible in every other preset.
    "bottom": CameraPreset.from_rotation("bottom", 180, 0, up=(0.0, -1.0, 0.0), orthographic=True),
}

#: The views a render or session produces when none are named. The output
#: config's default is this same list, so the two cannot drift apart.
MULTI_VIEW_DEFAULT = ["iso", "front", "top", "right"]
