"""The ``[mates]`` contract: how a part declares the features it mates through.

A mate is declared in a project's ``agentcad.toml``, a ``part.toml`` or a
``job.toml`` under ``[mates.<name>]``. The window-only form (a box where the
clearance is measured, an optional nominal clearance, and the parts involved)
keeps working; a mate may also declare the datums that pose its two bodies
without a hand-written transform:

- ``axis``: a point and a direction, the shared axis of a bore and its pin;
- ``rim_plane``: a point and a normal, the face the parts seat against;
- ``key_line``: a point and a direction fixing rotation about the axis;
- ``insertion``: the direction one body travels to assemble;
- ``dimensions``: named sizes, each with the datum it counts from.

Each vector is three numbers. Directions and normals are normalised on load,
and a zero vector is an error that names the mate and the key.
"""

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

Vec = Tuple[float, float, float]
_FILES = ("agentcad.toml", "job.toml", "part.toml")


class MateError(ValueError):
    """A [mates] entry that cannot be read as declared."""


@dataclass
class Datum:
    point: Vec
    direction: Vec


@dataclass
class Mate:
    name: str
    window: Optional[List[float]] = None
    nominal_mm: Optional[float] = None
    tol_mm: Optional[float] = None
    parts: Optional[List[str]] = None
    counterpart: Optional[str] = None
    axis: Optional[Datum] = None
    rim_plane: Optional[Datum] = None
    key_line: Optional[Datum] = None
    insertion: Optional[Vec] = None
    dimensions: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    @property
    def has_datums(self) -> bool:
        return self.axis is not None


def _vector(name: str, key: str, value, unit: bool) -> Vec:
    try:
        x, y, z = (float(v) for v in value)
    except (TypeError, ValueError):
        raise MateError(f"mate {name}: {key} must be three numbers, got {value!r}")
    if not unit:
        return (x, y, z)
    length = math.sqrt(x * x + y * y + z * z)
    if length == 0.0:
        raise MateError(f"mate {name}: {key} is a zero vector")
    return (x / length, y / length, z / length)


def _datum(name: str, key: str, value) -> Datum:
    if not isinstance(value, dict) or "point" not in value or not ({"direction", "normal"} & set(value)):
        raise MateError(f"mate {name}: {key} needs a point and a direction (or normal)")
    direction = value.get("direction", value.get("normal"))
    return Datum(_vector(name, f"{key}.point", value["point"], unit=False),
                 _vector(name, f"{key}.direction", direction, unit=True))


def parse(name: str, entry: Dict[str, Any]) -> Mate:
    """One ``[mates.<name>]`` table as a Mate."""
    mate = Mate(name=name,
                window=[float(v) for v in entry["window"]] if "window" in entry else None,
                nominal_mm=float(entry["nominal_mm"]) if "nominal_mm" in entry else None,
                tol_mm=float(entry["tol_mm"]) if "tol_mm" in entry else None,
                parts=list(entry["parts"]) if "parts" in entry else None,
                counterpart=entry.get("counterpart"),
                dimensions=dict(entry.get("dimensions") or {}))
    if mate.window is not None and len(mate.window) != 6:
        raise MateError(f"mate {name}: window must be x0,y0,z0,x1,y1,z1")
    for key in ("axis", "rim_plane", "key_line"):
        if key in entry:
            setattr(mate, key, _datum(name, key, entry[key]))
    if "insertion" in entry:
        mate.insertion = _vector(name, "insertion", entry["insertion"], unit=True)
    if (mate.rim_plane or mate.key_line) and mate.axis is None:
        raise MateError(f"mate {name}: rim_plane and key_line pose a body only with an axis")
    return mate


def read_table(where: Path) -> Dict[str, Any]:
    """The raw ``[mates]`` table of a toml file, or of the first agentcad.toml, job.toml
    or part.toml in a folder; empty, with a note on stderr, when there is none."""
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore
        except ImportError:
            return {}
    given = Path(where)
    candidates = [given] if given.is_file() else [given / n for n in _FILES]
    path = next((c for c in candidates if c.exists()), None)
    if path is None:
        print(f"agentcad: no {', '.join(_FILES)} under {given}; no mates read", file=sys.stderr)
        return {}
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return dict(data.get("mates") or {})


def load(where: Path) -> Dict[str, Mate]:
    """Every mate declared at ``where``, parsed."""
    return {name: parse(name, entry) for name, entry in read_table(where).items()}


# --- posing a body from declared datums ---------------------------------------------

def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(v):
    n = math.sqrt(_dot(v, v))
    return (v[0] / n, v[1] / n, v[2] / n)


def _frame(mate: Mate) -> Tuple[Vec, Vec, Vec, Vec, bool]:
    """(origin, x, y, z) of a mate's datum frame: z along the axis, x toward the key line
    (or a fixed perpendicular when none is declared, and the spin is then free)."""
    z = mate.axis.direction
    if mate.key_line is not None:
        k = mate.key_line.direction
        x = _sub(k, tuple(_dot(k, z) * c for c in z))
        if _dot(x, x) < 1e-12:
            raise MateError(f"mate {mate.name}: key_line is parallel to the axis")
        spin_fixed = True
    else:
        helper = (1.0, 0.0, 0.0) if abs(z[0]) < 0.9 else (0.0, 1.0, 0.0)
        x = _cross(helper, z)
        spin_fixed = False
    x = _unit(x)
    y = _cross(z, x)
    return mate.axis.point, x, y, z, spin_fixed


def pose_from_datums(a: Mate, b: Mate) -> Tuple[List[List[float]], List[str]]:
    """A 4x4 transform (row-major) that places body B so its mate's datums meet A's:
    axis onto axis, key line onto key line about it, rim plane onto rim plane along it."""
    if not (a.has_datums and b.has_datums):
        raise MateError(f"mates {a.name}/{b.name}: both need an axis to pose from datums")
    oa, xa, ya, za, fixed_a = _frame(a)
    ob, xb, yb, zb, fixed_b = _frame(b)
    # rotation R = Fa * Fb^T (columns are the frame axes)
    fa = (xa, ya, za)
    fb = (xb, yb, zb)
    rot = [[sum(fa[k][i] * fb[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    det = (rot[0][0] * (rot[1][1] * rot[2][2] - rot[1][2] * rot[2][1])
           - rot[0][1] * (rot[1][0] * rot[2][2] - rot[1][2] * rot[2][0])
           + rot[0][2] * (rot[1][0] * rot[2][1] - rot[1][1] * rot[2][0]))
    if abs(det - 1.0) > 1e-9:
        raise MateError(f"mates {a.name}/{b.name}: the datum frames give an improper rotation (det {det:.6g})")

    def apply(p):
        return tuple(sum(rot[i][j] * p[j] for j in range(3)) for i in range(3))

    rb = apply(ob)
    t = _sub(oa, rb)
    notes = []
    if a.rim_plane is not None and b.rim_plane is not None:
        rim_b = tuple(c + d for c, d in zip(apply(b.rim_plane.point), t))
        shift = _dot(_sub(a.rim_plane.point, rim_b), za)
        t = tuple(c + shift * d for c, d in zip(t, za))
    else:
        notes.append("no rim planes on both sides: the position along the axis is the axis points'")
    if not (fixed_a and fixed_b):
        notes.append("no key line on both sides: the spin about the axis is free (a fixed choice was made)")
    matrix = [rot[0] + [t[0]], rot[1] + [t[1]], rot[2] + [t[2]], [0.0, 0.0, 0.0, 1.0]]
    return matrix, notes
