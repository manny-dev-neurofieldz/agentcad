"""RAYS: where a line is in material and where it is in void.

A line is a start point and a direction; a fan is a set of lines that leave one
point on an axis, square to it, at equal angle steps. Along each line the
probe reports intervals of ``material`` and ``void`` with their entry, exit
and length, where the parameter ``t`` is the distance along the line from its
start point. That is a wall thickness, a bore depth, a gap, a rib: the numbers
a render cannot give.

Two kinds of source, and the record says which:

``brep``   a build123d program or a STEP file. Every crossing of the line with a
           face is found exactly, and the state of each stretch between two
           crossings is read by classifying its midpoint against the solid, so
           a line that only touches a surface (a tangent) does not open a gap.
           A line lying in a face counts as material.
``mesh``   an STL file. Crossings are found with a fixed tie rule so a line
           through a vertex or along an edge is counted once (``meshprobe``),
           and the states are the winding number along the line. The intervals
           are the tessellation's, to the tessellation's tolerance.

A range an instrument applies is recorded with its reason: by default the line
is followed from its start (not behind it) through the part's bounding box, and
an interval cut short by the end of the range, not by the part, is flagged
``clipped_start`` / ``clipped_end`` so it is never read as a full thickness.

``ray_intervals`` is the library entry point: give it a target from
``load_target`` and a line, get the record back. Checks such as a minimum wall
are built on it.
"""

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

SCHEMA = "agentcad.probe.rays/1"


# --- vectors (plain Python: a line is three numbers) ----------------------------------------

def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Sequence[float], b: Sequence[float]) -> List[float]:
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _unit(v: Sequence[float], why: str = "a direction needs a vector other than 0,0,0") -> List[float]:
    n = math.sqrt(_dot(v, v))
    if n == 0.0:
        raise ValueError(why)
    return [float(x) / n for x in v]


def _vec3(text: str, what: str, spec: str) -> List[float]:
    try:
        v = [float(p) for p in text.split(",")]
    except ValueError:
        v = []
    if len(v) != 3:
        raise ValueError(f"{what} spec {spec!r}: {text!r} is not three numbers separated by commas")
    return v


# --- lines and fans ---------------------------------------------------------------------------

def parse_line(spec: str, label: Optional[str] = None) -> Dict[str, Any]:
    """``x,y,z:dx,dy,dz[:length]`` as a line: origin, unit direction and an optional length (mm)."""
    parts = spec.split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"line spec {spec!r}: expected x,y,z:dx,dy,dz[:length]")
    origin = _vec3(parts[0], "line", spec)
    direction = _unit(_vec3(parts[1], "line", spec), f"line spec {spec!r}: the direction is 0,0,0")
    length = None
    if len(parts) == 3:
        try:
            length = float(parts[2])
        except ValueError:
            raise ValueError(f"line spec {spec!r}: the length {parts[2]!r} is not a number")
        if length <= 0:
            raise ValueError(f"line spec {spec!r}: the length must be positive")
    return {"label": label, "origin": origin, "direction": direction, "length": length, "fan": None}


def fan_basis(axis: Sequence[float]) -> Tuple[List[float], List[float]]:
    """(e1, e2): the direction of 0 degrees and of 90 degrees for a fan about ``axis``.

    e1 is the world axis most nearly square to the fan axis (X, then Y, then Z when equally square),
    made exactly square to it; e2 = axis x e1, so angles follow the right-hand rule about the axis."""
    a = _unit(axis)
    k = min(range(3), key=lambda i: (round(abs(a[i]), 12), i))
    ref = [0.0, 0.0, 0.0]
    ref[k] = 1.0
    along = _dot(ref, a)
    e1 = _unit([ref[i] - along * a[i] for i in range(3)])
    return e1, _cross(a, e1)


def parse_fan(spec: str, label: Optional[str] = None) -> List[Dict[str, Any]]:
    """``x,y,z:ax,ay,az:step[:from[:to]]`` as the lines of a fan.

    The lines start at the point on the axis, square to ``ax,ay,az``, at ``from`` (default 0), ``from +
    step``, and so on through ``to`` (default a full turn, whose last angle is dropped as the first
    again). Angles are in degrees; 0 is ``fan_basis``'s e1."""
    parts = spec.split(":")
    if not 3 <= len(parts) <= 5:
        raise ValueError(f"fan spec {spec!r}: expected x,y,z:ax,ay,az:step[:from[:to]]")
    centre = _vec3(parts[0], "fan", spec)
    axis = _unit(_vec3(parts[1], "fan", spec), f"fan spec {spec!r}: the axis direction is 0,0,0")
    try:
        step = float(parts[2])
        start = float(parts[3]) if len(parts) > 3 else 0.0
        stop = float(parts[4]) if len(parts) > 4 else start + 360.0
    except ValueError:
        raise ValueError(f"fan spec {spec!r}: step, from and to are angles in degrees")
    if not 0 < step <= 360:
        raise ValueError(f"fan spec {spec!r}: the step must be above 0 and at most 360 degrees")
    if stop < start:
        raise ValueError(f"fan spec {spec!r}: 'to' is below 'from'")
    angles = [start + k * step for k in range(int(math.floor((stop - start) / step + 1e-9)) + 1)]
    if stop - start >= 360.0 - 1e-9:
        angles = [a for a in angles if a < start + 360.0 - 1e-9]
    e1, e2 = fan_basis(axis)
    lines = []
    for a in angles:
        c, s = math.cos(math.radians(a)), math.sin(math.radians(a))
        lines.append({"label": f"{label}@{a:g}" if label else None, "origin": list(centre),
                      "direction": _unit([e1[i] * c + e2[i] * s for i in range(3)]), "length": None,
                      "fan": {"axis_point": list(centre), "axis_direction": list(axis), "angle_deg": a}})
    return lines


# --- targets ------------------------------------------------------------------------------------

class _BrepScan:
    def __init__(self, cuts: List[float], classifiers, origin, direction, tol: float):
        self.cuts, self.warnings = cuts, []
        self._classifiers, self._o, self._d, self._tol = classifiers, origin, direction, tol

    def inside(self, t: float) -> bool:
        from OCP.gp import gp_Pnt
        from OCP.TopAbs import TopAbs_IN, TopAbs_ON

        p = gp_Pnt(self._o[0] + t * self._d[0], self._o[1] + t * self._d[1], self._o[2] + t * self._d[2])
        for classifier in self._classifiers:
            classifier.Perform(p, self._tol)
            if classifier.State() in (TopAbs_IN, TopAbs_ON):
                return True
        return False


class BrepTarget:
    """A solid read exactly: faces intersected with the line, midpoints classified against the solids."""
    kind = "brep"
    method = "exact face crossings; each stretch between them classified at its midpoint"

    def __init__(self, shape):
        from OCP.BRepClass3d import BRepClass3d_SolidClassifier
        from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector

        solids = list(shape.solids())
        if not solids:
            raise ValueError("rays need a solid: the shape has none (a face or a wire has no inside)")
        bb = shape.bounding_box()
        self.lo = [bb.min.X, bb.min.Y, bb.min.Z]
        self.hi = [bb.max.X, bb.max.Y, bb.max.Z]
        self.diag = math.sqrt(sum((h - l) ** 2 for l, h in zip(self.lo, self.hi)))
        self.tolerance = 1e-6 * max(1.0, self.diag)
        self._intersector = IntCurvesFace_ShapeIntersector()
        self._intersector.Load(shape.wrapped, self.tolerance)
        self._classifiers = [BRepClass3d_SolidClassifier(s.wrapped) for s in solids]
        self.facts: Dict[str, Any] = {"solids": len(solids)}

    def scan(self, origin, direction, t0: float, t1: float) -> _BrepScan:
        from OCP.gp import gp_Dir, gp_Lin, gp_Pnt

        self._intersector.Perform(gp_Lin(gp_Pnt(*origin), gp_Dir(*direction)), t0, t1)
        cuts = sorted(float(self._intersector.WParameter(i)) for i in range(1, self._intersector.NbPnt() + 1))
        return _BrepScan(cuts, self._classifiers, origin, direction, self.tolerance)


class MeshTarget:
    """A triangle mesh: crossings with a tie rule, states from the winding number along the line."""
    kind = "mesh"
    method = "triangle crossings with a fixed tie rule; states from the winding number (tessellation tolerance)"

    def __init__(self, mesh):
        self.mesh = mesh
        self.lo, self.hi = [float(x) for x in mesh.lo], [float(x) for x in mesh.hi]
        self.diag, self.tolerance = mesh.diag, mesh.tolerance
        self.facts = {"triangles": mesh.n_triangles, "winding": "outward" if mesh.orient > 0 else "inward"}

    def scan(self, origin, direction, t0: float, t1: float):
        from agentcad.meshprobe import LineScan

        return LineScan(self.mesh, origin, direction)


def load_target(source: Path, defines: Optional[Dict[str, str]] = None):
    """The target for a build123d program or STEP file (exact) or an STL file (mesh)."""
    source = Path(source)
    suffix = source.suffix.lower()
    if suffix == ".stl":
        from agentcad.meshprobe import load_mesh

        return MeshTarget(load_mesh(source))
    if suffix in (".py", ".step", ".stp"):
        from agentcad.probe import load_shape

        return BrepTarget(load_shape(source, defines))
    raise ValueError(f"{source}: probe rays reads a build123d program, a STEP file or an STL mesh")


# --- one line ----------------------------------------------------------------------------------

def _window(target, o: Sequence[float], d: Sequence[float], length: Optional[float]) -> Optional[Tuple[float, float, str]]:
    """The stretch of the line to follow, (t0, t1, why): ``length`` from the start when given, else
    from the start (or where the line meets the bounding box, if later) to where it leaves the box.
    None when the line misses the box."""
    if length is not None:
        return 0.0, float(length), "length"
    tol = target.tolerance
    near, far = 0.0, math.inf
    for k in range(3):
        if abs(d[k]) < 1e-12:
            if o[k] < target.lo[k] - tol or o[k] > target.hi[k] + tol:
                return None
            continue
        a, b = (target.lo[k] - o[k]) / d[k], (target.hi[k] - o[k]) / d[k]
        near, far = max(near, min(a, b)), min(far, max(a, b))
    if far < near:
        return None
    return near, far, "bounding box"


def ray_intervals(target, origin: Sequence[float], direction: Sequence[float], length: Optional[float] = None,
                  label: Optional[str] = None) -> Dict[str, Any]:
    """Material and void intervals along one line, as a record.

    ``length`` follows the line that far from its start; without it the line is followed through the
    bounding box. Each interval has ``kind``, ``entry`` and ``exit`` (distances along the line),
    ``length``, ``entry_point`` and ``exit_point``, and ``clipped_start`` / ``clipped_end`` when the
    range, not the part, ended it; a void also says whether it is ``enclosed`` by material."""
    o = [float(x) for x in origin]
    d = _unit(direction)
    tol = target.tolerance
    rec: Dict[str, Any] = {"label": label, "origin": o, "direction": d, "range": None, "range_from": None,
                           "intervals": [], "crossings": 0, "material": 0.0, "void": 0.0, "warnings": []}
    window = _window(target, o, d, length)
    if window is None:
        rec["note"] = "the line misses the part's bounding box"
        return rec
    t0, t1, rec["range_from"] = window
    rec["range"] = [t0, t1]
    if t1 - t0 <= tol:
        rec["note"] = "the range is shorter than the tolerance: nothing to report"
        return rec
    scan = target.scan(o, d, t0 - 10 * tol, t1 + 10 * tol)
    rec["warnings"] = list(scan.warnings)
    rec["crossings"] = sum(1 for c in scan.cuts if t0 - tol <= c <= t1 + tol)
    at_start = any(abs(c - t0) <= tol for c in scan.cuts)
    at_end = any(abs(c - t1) <= tol for c in scan.cuts)

    marks = [t0]
    for c in scan.cuts:
        if t0 + tol < c < t1 - tol and c - marks[-1] > tol:
            marks.append(c)
    marks.append(t1)
    runs: List[List[Any]] = []
    for a, b in zip(marks[:-1], marks[1:]):
        kind = "material" if scan.inside((a + b) / 2.0) else "void"
        if runs and runs[-1][0] == kind:
            runs[-1][2] = b
        else:
            runs.append([kind, a, b])
    for i, (kind, a, b) in enumerate(runs):
        point = lambda t: [o[k] + t * d[k] for k in range(3)]
        item: Dict[str, Any] = {"kind": kind, "entry": a, "exit": b, "length": b - a,
                                "entry_point": point(a), "exit_point": point(b),
                                "clipped_start": i == 0 and not at_start,
                                "clipped_end": i == len(runs) - 1 and not at_end}
        if kind == "void":
            item["enclosed"] = 0 < i < len(runs) - 1
        rec["intervals"].append(item)
        rec[kind] += b - a
    rec["enclosed_void"] = sum(i["length"] for i in rec["intervals"] if i["kind"] == "void" and i["enclosed"])
    return rec


# --- a source and its lines ---------------------------------------------------------------------

def probe_rays(source: Path, lines: Sequence[Dict[str, Any]], defines: Optional[Dict[str, str]] = None,
               length: Optional[float] = None) -> Dict[str, Any]:
    """The rays record (schema ``agentcad.probe.rays/1``) for ``lines`` through ``source``.

    ``length`` is the default for lines that give none. Line labels that are None become L1, L2, ..."""
    target = load_target(source, defines)
    res: Dict[str, Any] = {"schema": SCHEMA, "source": str(source), "kind": target.kind, "method": target.method,
                           "tolerance": target.tolerance, "bbox_min": list(target.lo), "bbox_max": list(target.hi),
                           "lines": []}
    res.update(target.facts)
    if defines and target.kind == "mesh":
        res["warnings"] = [f"-D {sorted(defines)} ignored: a mesh has no parameters"]
    for n, line in enumerate(lines, 1):
        rec = ray_intervals(target, line["origin"], line["direction"], line.get("length") or length,
                            label=line.get("label") or f"L{n}")
        if line.get("fan"):
            rec["fan"] = line["fan"]
        res["lines"].append(rec)
    return res


def _p(point: Sequence[float]) -> str:
    return "(" + ", ".join(f"{x:.3f}" for x in point) + ")"


def render_rays(res: Dict[str, Any], show: int = 12) -> List[str]:
    """The record as text: a header, then each line with its intervals (``show`` per line; the cap is
    printed when it applies)."""
    lo, hi = res["bbox_min"], res["bbox_max"]
    out = [f"{res['source']}: {res['kind']}, {res['method']}", f"  bbox {_p(lo)} .. {_p(hi)}"]
    out.extend(f"  warning: {w}" for w in res.get("warnings", []))
    for line in res["lines"]:
        out.append(f"{line['label']}: from {_p(line['origin'])} along {_p(line['direction'])}"
                   + (f", t {line['range'][0]:.4f} .. {line['range'][1]:.4f} ({line['range_from']})" if line["range"] else ""))
        if line.get("note"):
            out.append(f"  {line['note']}")
        for item in line["intervals"][:show]:
            flags = [f for f, on in (("clipped at the start", item["clipped_start"]), ("clipped at the end", item["clipped_end"]),
                                     ("enclosed", item.get("enclosed"))) if on]
            out.append(f"  {item['kind']:<8} t {item['entry']:9.4f} -> {item['exit']:9.4f}  length {item['length']:9.4f}"
                       f"  {_p(item['entry_point'])} -> {_p(item['exit_point'])}" + (f"  [{', '.join(flags)}]" if flags else ""))
        if len(line["intervals"]) > show:
            out.append(f"  ... {len(line['intervals']) - show} more interval(s) (cap --show {show}; the JSON has all)")
        runs = sum(1 for i in line["intervals"] if i["kind"] == "material")
        if line["intervals"]:
            out.append(f"  material {line['material']:.4f} in {runs} run(s), void {line['void']:.4f}"
                       f" (enclosed {line['enclosed_void']:.4f})")
        out.extend(f"  warning: {w}" for w in line["warnings"])
    return out
