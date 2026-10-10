"""Annotations a program makes about its own features, for QC to judge them by.

A program can say what its features are, how each should be judged, which findings it accepts and
why, and how it prints::

    try:
        from agentcad.annotate import feature, suppress, print_pose
    except ImportError:                       # without agentcad the annotations do nothing
        def feature(*args, **kwargs):
            pass
        suppress = print_pose = feature

    def build(wall=1.2, height=12.0):
        ...
        feature("socket wall", box=(-6, -6, 0, 6, 6, height), kind="wall")
        feature("flexure", box=(10, -2, 0, 20, 2, 4), kind="wall", min_wall_mm=0.5,
                why="a thin beam is the spring")
        suppress("max_overhang", box=(0, 0, 20, 30, 10, 22), why="the lid's underside; supports are planned")
        print_pose(up=(0, -1, 0))
        return part

Boxes are ``(x0, y0, z0, x1, y1, z1)`` in the part's own frame, the frame the program builds in.
A finding QC makes inside a feature's box belongs to that feature: it names the feature and the
line that declared it, takes the feature's limits, and may be an error; a finding no feature claims
is never more than a warning. A limit a feature loosens, and every suppression, is listed in the
report with its reason. Each call records the file and line it was made from. The registry is
reset before every build, so building twice does not declare a feature twice.
"""

import math
import sys
from typing import Any, Dict, List, Optional, Sequence

#: The limits a feature may set, by the name QC reads them under.
LIMIT_KEYS = ("min_wall_mm", "min_feature_mm", "max_overhang_deg", "max_bridge_mm")
#: The rules a suppression may name.
RULES = ("build_volume", "min_feature", "min_wall", "max_overhang", "max_bridge")
#: The feature kinds QC knows how to describe; any other kind is kept as written.
KINDS = ("feature", "wall", "floor", "bridge", "overhang", "hole", "boss", "rib", "pin")

_REGISTRY: List[Dict[str, Any]] = []


def _where(depth: int = 2) -> Dict[str, Any]:
    frame = sys._getframe(depth)
    return {"file": frame.f_code.co_filename, "line": frame.f_lineno}


def _box(box: Sequence[float], what: str) -> List[float]:
    try:
        values = [float(v) for v in box]
    except (TypeError, ValueError):
        raise ValueError(f"{what}: box must be six numbers (x0, y0, z0, x1, y1, z1)") from None
    if len(values) != 6 or not all(math.isfinite(v) for v in values):
        raise ValueError(f"{what}: box must be six finite numbers (x0, y0, z0, x1, y1, z1), not {list(box)!r}")
    lo = [min(values[i], values[i + 3]) for i in range(3)]
    hi = [max(values[i], values[i + 3]) for i in range(3)]
    return lo + hi


def feature(name: str, box: Sequence[float], *, kind: str = "feature", why: str = "", **limits: float) -> None:
    """Declare a feature: a name, the box it occupies in the part's frame, its kind, and any limits
    of its own (``min_wall_mm``, ``min_feature_mm``, ``max_overhang_deg``, ``max_bridge_mm``).
    ``why`` says why a limit differs from the process's; a limit loosened without one is reported."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("feature: a feature needs a name")
    if any(r["type"] == "feature" and r["name"] == name for r in _REGISTRY):
        raise ValueError(f"feature {name!r} is declared twice in this build")
    unknown = sorted(set(limits) - set(LIMIT_KEYS))
    if unknown:
        raise ValueError(f"feature {name!r}: unknown limit(s) {', '.join(unknown)} (known: {', '.join(LIMIT_KEYS)})")
    values = {}
    for key, value in limits.items():
        value = float(value)
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"feature {name!r}: {key} must be a positive number, not {value!r}")
        values[key] = value
    _REGISTRY.append(dict(_where(), type="feature", name=name.strip(), kind=str(kind or "feature"),
                          box=_box(box, f"feature {name!r}"), limits=values, why=str(why or "")))


def suppress(rule: str, *, why: str, box: Optional[Sequence[float]] = None) -> None:
    """Accept a rule's findings, inside ``box`` (the part's frame) or anywhere: they are removed from
    the findings and listed in the report with ``why``, which is required."""
    if rule not in RULES:
        raise ValueError(f"suppress: unknown rule {rule!r} (rules: {', '.join(RULES)})")
    if not isinstance(why, str) or not why.strip():
        raise ValueError(f"suppress {rule!r}: a suppression needs its reason (why=...)")
    _REGISTRY.append(dict(_where(), type="suppress", rule=rule, why=why.strip(),
                          box=_box(box, f"suppress {rule!r}") if box is not None else None))


def print_pose(up: Sequence[float] = (0.0, 0.0, 1.0), spin_deg: float = 0.0, *,
               matrix: Optional[Sequence[Sequence[float]]] = None) -> None:
    """State how the part prints: the direction of the part that points up on the bed, then a turn
    about the bed's z; or the whole rotation as a 3x3 ``matrix`` (rows; the part frame to the bed's).
    It takes the place of the project's ``[qc] pose``."""
    if any(r["type"] == "pose" for r in _REGISTRY):
        raise ValueError("print_pose: the print pose is stated twice in this build")
    if matrix is not None:
        rows = [[float(v) for v in row] for row in matrix]
        if len(rows) != 3 or any(len(r) != 3 for r in rows):
            raise ValueError("print_pose: matrix must be 3x3")
        for i in range(3):
            for j in range(3):
                dot = sum(rows[i][k] * rows[j][k] for k in range(3))
                if abs(dot - (1.0 if i == j else 0.0)) > 1e-6:
                    raise ValueError("print_pose: matrix is not a rotation (its rows are not orthonormal)")
        det = (rows[0][0] * (rows[1][1] * rows[2][2] - rows[1][2] * rows[2][1])
               - rows[0][1] * (rows[1][0] * rows[2][2] - rows[1][2] * rows[2][0])
               + rows[0][2] * (rows[1][0] * rows[2][1] - rows[1][1] * rows[2][0]))
        if det < 0:
            raise ValueError("print_pose: matrix is a reflection, not a rotation (determinant -1)")
        pose: Dict[str, Any] = {"matrix": rows}
    else:
        vec = [float(v) for v in up]
        if len(vec) != 3 or not any(vec):
            raise ValueError("print_pose: up must be a non-zero vector (x, y, z)")
        pose = {"up": vec, "spin_deg": float(spin_deg)}
    _REGISTRY.append(dict(_where(), type="pose", pose=pose))


def reset() -> None:
    """Forget every annotation: called before each build."""
    _REGISTRY.clear()


def records() -> List[Dict[str, Any]]:
    """The annotations made since the last reset, as plain records (copies)."""
    return [dict(r) for r in _REGISTRY]
