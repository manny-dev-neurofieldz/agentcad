"""Probes of a triangle mesh: lines through it and planes across it.

A mesh file (STL) is a soup of triangles with no connectivity and no exact
surface, so what these probes report is the tessellation's, to the
tessellation's tolerance, and the outputs say so. Two operations carry the
rest:

``crossings``     where a line meets the surface, and in which direction;
``plane_loops``   the closed loops where a plane cuts the mesh.

Both are written so that a line or a plane through a vertex or along an edge
of the mesh (which is where symmetric parts put them) does not break the
count. A line is tested against each triangle projected along the line, and
a point on the shared edge of two projected triangles is given to exactly one
of them by a fixed rule (the edge function is exactly antisymmetric, and a
zero is broken by the edge's direction), which is the same as nudging the line
by an infinitesimal amount. A line that lies in the surface has no side of its
own, so it is nudged four ways and counts as inside if any nudge puts it
inside, the same answer the exact kernel gives (the boundary is material).
A plane through vertices reads as moved a hair toward lower coordinates (see ``plane_loops``).
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

_CHUNK = 262144          # triangles per pass: bounds the temporaries on a large mesh
_CELLS = (1 << 21) - 2    # welding grid per axis: three axes pack into one 63-bit key


class Mesh:
    """The triangles of a mesh file, their bounding box and which way they wind.

    ``tri`` is (N, 3, 3) float64. ``orient`` is +1 when the normals point out of the
    enclosed volume (a positive signed volume) and -1 when they point in; a mesh
    that is not closed has no meaningful sign and reads as +1.
    """

    def __init__(self, path: Path, tri: "np.ndarray"):
        self.path = Path(path)
        self.tri = tri
        pts = tri.reshape(-1, 3)
        self.lo, self.hi = pts.min(axis=0), pts.max(axis=0)
        self.diag = float(np.linalg.norm(self.hi - self.lo))
        centre = (self.lo + self.hi) / 2.0
        a, b, c = tri[:, 0] - centre, tri[:, 1] - centre, tri[:, 2] - centre
        volume = float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)
        self.orient = -1 if volume < 0 else 1
        self._welded: Optional[Tuple["np.ndarray", "np.ndarray"]] = None

    def welded(self) -> Tuple["np.ndarray", "np.ndarray"]:
        """(points, triangle rows of point indices): vertices that coincide are one point. Cached."""
        if self._welded is None:
            points, inverse = _weld(self.tri.reshape(-1, 3), self.lo, self.diag)
            self._welded = (points, inverse.reshape(-1, 3))
        return self._welded

    @property
    def n_triangles(self) -> int:
        return int(len(self.tri))

    @property
    def tolerance(self) -> float:
        """Distances below this are one place: float32 vertices carry about 1e-7 of their magnitude."""
        return 1e-6 * max(1.0, self.diag)


def load_mesh(path: Path) -> Mesh:
    """An STL file (binary or ASCII) as a ``Mesh``; an empty file is an error."""
    from agentcad.meshmeasure import read_stl

    V, F = read_stl(Path(path))
    if len(F) == 0:
        raise ValueError(f"{path}: the mesh has no triangles")
    return Mesh(path, np.ascontiguousarray(V[F], dtype=np.float64))


# --- lines ---------------------------------------------------------------------------

def basis(direction: Sequence[float]) -> Tuple["np.ndarray", "np.ndarray", "np.ndarray"]:
    """A right-handed orthonormal (u, v, d) with ``d`` the unit direction: u x v = d."""
    d = np.asarray(direction, dtype=float)
    norm = float(np.linalg.norm(d))
    if norm == 0.0:
        raise ValueError("a line needs a direction other than 0,0,0")
    d = d / norm
    helper = np.zeros(3)
    helper[int(np.argmin(np.abs(d)))] = 1.0
    u = np.cross(d, helper)
    u = u / np.linalg.norm(u)
    return u, np.cross(d, u), d


_NUDGES = 4   # tie rules: the line moved a hair toward +v, -v, +u, -u (see _edge_sign)


def _edge_sign(e, ax, ay, bx, by, rule: int = 0):
    """Side of an edge the line is on: the sign of ``e``, and for an exact zero a sign fixed by the
    edge's direction and the nudge ``rule``, so the two triangles that share the edge (which see it
    in opposite directions) always disagree. Rule 0 moves the line a hair toward +v (and, to break
    a tie in that, toward +u), rule 1 toward -v, rule 2 toward +u, rule 3 toward -u."""
    s = np.sign(e)
    tie = e == 0
    if tie.any():
        dx, dy = np.sign(bx - ax), np.sign(by - ay)
        if rule == 0:
            nudge = np.where(dx != 0, dx, -dy)
        elif rule == 1:
            nudge = np.where(dx != 0, -dx, -dy)
        elif rule == 2:
            nudge = np.where(dy != 0, -dy, dx)
        else:
            nudge = np.where(dy != 0, dy, dx)
        s = np.where(tie, nudge, s)
    return s


def crossings(mesh: Mesh, origin: Sequence[float], direction: Sequence[float],
              rule: int = 0) -> Tuple["np.ndarray", "np.ndarray", bool]:
    """Parameters ``t`` along the whole line ``origin + t * direction`` where it meets a triangle,
    sorted; the sign of each (+1 where the line leaves along the triangle's normal, -1 where it
    arrives against it); and whether the line met a vertex or an edge exactly, which is when the
    nudge ``rule`` (0 to 3) matters. A line through a vertex or along an edge meets each crossing once."""
    o = np.asarray(origin, dtype=float)
    u, v, d = basis(direction)
    ts: List["np.ndarray"] = []
    ss: List["np.ndarray"] = []
    tied = False
    for k in range(0, len(mesh.tri), _CHUNK):
        rel = mesh.tri[k:k + _CHUNK] - o
        a = rel[..., 0] * u[0] + rel[..., 1] * u[1] + rel[..., 2] * u[2]
        b = rel[..., 0] * v[0] + rel[..., 1] * v[1] + rel[..., 2] * v[2]
        near = (a.min(axis=1) <= 0) & (a.max(axis=1) >= 0) & (b.min(axis=1) <= 0) & (b.max(axis=1) >= 0)
        if not near.any():
            continue
        rel, a, b = rel[near], a[near], b[near]
        z = rel[..., 0] * d[0] + rel[..., 1] * d[1] + rel[..., 2] * d[2]
        a0, a1, a2, b0, b1, b2 = a[:, 0], a[:, 1], a[:, 2], b[:, 0], b[:, 1], b[:, 2]
        e0 = a1 * b2 - b1 * a2           # edge 1->2, the weight of vertex 0
        e1 = a2 * b0 - b2 * a0
        e2 = a0 * b1 - b0 * a1
        tied = tied or bool(((e0 == 0) | (e1 == 0) | (e2 == 0)).any())
        s0 = _edge_sign(e0, a1, b1, a2, b2, rule)
        s1 = _edge_sign(e1, a2, b2, a0, b0, rule)
        s2 = _edge_sign(e2, a0, b0, a1, b1, rule)
        total = e0 + e1 + e2
        hit = (s0 == s1) & (s1 == s2) & (total * s0 > 0)
        if not hit.any():
            continue
        t = (e0[hit] * z[hit, 0] + e1[hit] * z[hit, 1] + e2[hit] * z[hit, 2]) / total[hit]
        ts.append(t)
        ss.append(s0[hit])
    if not ts:
        return np.empty(0), np.empty(0), tied
    t, s = np.concatenate(ts), np.concatenate(ss)
    order = np.argsort(t, kind="stable")
    return t[order], s[order], tied


class LineScan:
    """What a line does to a mesh: where it crosses the surface and whether a parameter is inside.

    The state after each place (crossings closer than the mesh tolerance are one place) is the
    winding number, which counts a part inside two overlapping shells as inside. A mesh that is not
    closed or not consistently wound along the line has no winding that makes sense; the scan then
    reads the parity of the crossings and says so in ``warnings``. A line that meets a vertex or an
    edge exactly is scanned under each of the four nudges and is inside where any nudge is, so a
    line lying in the surface is material, as it is for the exact kernel.
    """

    def __init__(self, mesh: Mesh, origin: Sequence[float], direction: Sequence[float]):
        self.warnings: List[str] = []
        self._variants: List[Tuple["np.ndarray", "np.ndarray"]] = []
        t, s, tied = crossings(mesh, origin, direction, 0)
        self.crossings = int(len(t))
        self._add(mesh, t, s)
        if tied:
            for rule in range(1, _NUDGES):
                self._add(mesh, *crossings(mesh, origin, direction, rule)[:2])
        places = np.concatenate([p for p, _ in self._variants]) if self._variants else np.empty(0)
        places = np.sort(places)
        keep = np.concatenate([[True], np.diff(places) > mesh.tolerance]) if len(places) else np.zeros(0, dtype=bool)
        self.cuts: List[float] = [float(x) for x in places[keep]]

    def _add(self, mesh: Mesh, t: "np.ndarray", s: "np.ndarray") -> None:
        if len(t) == 0:
            self._variants.append((np.empty(0), np.zeros(1, dtype=bool)))
            return
        breaks = np.flatnonzero(np.diff(t) > mesh.tolerance) + 1
        groups = np.split(np.arange(len(t)), breaks)
        places = np.array([float(t[g].mean()) for g in groups])
        arrive = np.array([float(-s[g].sum()) * mesh.orient for g in groups])   # +1 arriving, -1 leaving
        winding = np.cumsum(arrive)
        if (winding < -0.5).any() or abs(winding[-1]) > 0.5:
            parity = np.cumsum([len(g) % 2 for g in groups]) % 2
            state = np.concatenate([[False], parity == 1])
            note = ("the mesh is not closed or not consistently wound along this line "
                    f"({len(t)} crossings); inside and outside are read from the crossing parity")
            if note not in self.warnings:
                self.warnings.append(note)
        else:
            state = np.concatenate([[False], winding > 0.5])
        self._variants.append((places, state))

    def inside(self, t: float) -> bool:
        """Is the point at parameter ``t`` inside the mesh (under any nudge)."""
        return any(bool(state[int(np.searchsorted(places, t))]) for places, state in self._variants)


# --- planes ----------------------------------------------------------------------------------

def _weld(points: "np.ndarray", lo: "np.ndarray", diag: float) -> Tuple["np.ndarray", "np.ndarray"]:
    """(unique points, index of each input point among them): vertices that coincide are one."""
    cell = max(diag, 1e-12) / _CELLS
    q = np.floor((points - lo) / cell).astype(np.int64)
    key = (q[:, 0] << 42) | (q[:, 1] << 21) | q[:, 2]
    _, first, inverse = np.unique(key, return_index=True, return_inverse=True)
    return points[first], inverse.reshape(-1)


def _plane_segments(mesh: Mesh, axis: int, coord: float, on_plane_above: bool) -> Tuple["np.ndarray", "np.ndarray"]:
    """Crossing points (one per mesh edge that the plane cuts) and the segments between them
    (one per triangle that it cuts). A vertex on the plane counts as above it, or below it."""
    pts, tri = mesh.welded()
    dist = pts[:, axis] - coord
    above = dist >= 0 if on_plane_above else dist > 0
    sides = above[tri]
    cut = sides.any(axis=1) & ~sides.all(axis=1)
    if not cut.any():
        return np.empty((0, 3)), np.empty((0, 2), dtype=np.int64)
    tri = tri[cut]
    n = np.int64(len(pts))
    keys, crosses = [], []
    for i, j in ((0, 1), (1, 2), (2, 0)):
        a, b = tri[:, i], tri[:, j]
        lo_v, hi_v = np.minimum(a, b), np.maximum(a, b)
        keys.append(lo_v * n + hi_v)
        crosses.append(above[a] != above[b])
    keys, crosses = np.stack(keys, axis=1), np.stack(crosses, axis=1)
    pair = keys[crosses].reshape(-1, 2)                      # exactly two cut edges per cut triangle
    unique, inverse = np.unique(pair.ravel(), return_inverse=True)
    segments = inverse.reshape(-1, 2)
    a_id, b_id = unique // n, unique % n
    da, db = dist[a_id], dist[b_id]
    t = da / (da - db)
    points = pts[a_id] + t[:, None] * (pts[b_id] - pts[a_id])
    return points, segments


def _chains(n_points: int, segments: "np.ndarray") -> List[Tuple[List[int], bool]]:
    """Segments joined end to end: (point indices, closed). Open chains are walked from their
    ends first, so a mesh with a hole in it gives whole chains, not halves."""
    adjacent: List[List[Tuple[int, int]]] = [[] for _ in range(n_points)]
    for si, (a, b) in enumerate(segments.tolist()):
        adjacent[a].append((b, si))
        adjacent[b].append((a, si))
    used = [False] * len(segments)

    def walk(start: int) -> Tuple[List[int], bool]:
        path, node = [start], start
        while True:
            step = next(((m, si) for m, si in adjacent[node] if not used[si]), None)
            if step is None:
                return path, False
            used[step[1]] = True
            node = step[0]
            path.append(node)
            if node == start:
                return path[:-1], True

    chains = []
    for start in [i for i in range(n_points) if len(adjacent[i]) == 1] + list(range(n_points)):
        while any(not used[si] for _, si in adjacent[start]):
            chains.append(walk(start))
    return chains


def _line_distances(P: "np.ndarray", i: int, j: int) -> Tuple["np.ndarray", "np.ndarray", float]:
    """For the points strictly between index i and j: distance to the line through P[i], P[j] and
    the position along it, with the line's length."""
    a, b = P[i], P[j]
    ab = b - a
    length = float(np.linalg.norm(ab))
    mid = P[i + 1:j] - a
    if length == 0.0:
        return np.linalg.norm(mid, axis=1), np.zeros(len(mid)), 0.0
    along = mid @ ab / length
    off = np.linalg.norm(mid - np.outer(along, ab / length), axis=1)
    return off, along, length


def _runs(P: "np.ndarray", tol: float) -> List[Tuple["np.ndarray", "np.ndarray"]]:
    """A polyline as the fewest straight runs that keep every vertex within ``tol`` of its run:
    the many collinear segments a flat face contributes become one edge, a polylined arc does not."""
    out, s, m = [], 0, len(P)
    while s < m - 1:
        end = s + 1
        while end + 1 < m:
            off, along, length = _line_distances(P, s, end + 1)
            if len(off) and (off.max() > tol or (np.diff(np.concatenate([[0.0], along, [length]])) < -tol).any()):
                break
            end += 1
        out.append((P[s], P[end]))
        s = end
    return out


def _start_at_a_corner(P: "np.ndarray", tol: float) -> "np.ndarray":
    """A closed loop's points rotated to begin at a corner, so a straight run is never split at the seam."""
    prev, nxt = np.roll(P, 1, axis=0), np.roll(P, -1, axis=0)
    chord = nxt - prev
    length = np.linalg.norm(chord, axis=1)
    safe = np.where(length > 0, length, 1.0)
    offset = np.linalg.norm(np.cross(P - prev, chord), axis=1) / safe
    corners = np.flatnonzero(offset > tol)
    return np.roll(P, -int(corners[0]), axis=0) if len(corners) else P


def _loops(mesh: Mesh, axis: int, coord: float, on_plane_above: bool, tol: float) -> List[Dict[str, Any]]:
    points, segments = _plane_segments(mesh, axis, coord, on_plane_above)
    loops: List[Dict[str, Any]] = []
    for path, closed in _chains(len(points), segments):
        P = points[path]
        if closed and len(P) >= 3:
            P = _start_at_a_corner(P, tol)
            P = np.vstack([P, P[:1]])
        edges = []
        for start, end in _runs(P, tol):
            length = float(np.linalg.norm(end - start))
            edges.append({"type": "line", "start": [float(x) for x in start], "end": [float(x) for x in end],
                          "length": length, "center": None, "radius": None, "sweep_deg": None,
                          "midpoint": [float(x) for x in (start + end) / 2.0]})
        length = float(sum(e["length"] for e in edges))
        if length > tol:                                   # a point where the plane only touches is not a loop
            loops.append({"edges": edges, "closed": bool(closed), "n_edges": len(edges), "length": length, "fit": None})
    return loops


def plane_loops(mesh: Mesh, axis: int, coord: float) -> List[Dict[str, Any]]:
    """Loops where the plane ``axis = coord`` (axis 0, 1 or 2) cuts the mesh, as the loop records of
    ``probe.section_loops``: straight ``line`` edges (collinear segments merged), ``closed``,
    ``n_edges``, ``length`` and a ``fit`` of None, longest loop first. A mesh with a hole in it
    gives chains with ``closed`` False.

    A plane that passes exactly through vertices reads as the plane moved a hair toward lower
    coordinates, so a face lying in it belongs to the part above it. The one exception is the mesh's
    lowest coordinate, where nothing is below: there the plane reads as moved a hair up, so a part
    standing on z=0 and cut at z=0 gives the outline of its bottom face.
    """
    tol = 1e-6 * max(1.0, mesh.diag)
    loops = _loops(mesh, axis, coord, coord > float(mesh.lo[axis]) + tol, tol)
    loops.sort(key=lambda L: -L["length"])
    return loops


def loop_extents(loop: Dict[str, Any], axis: int, center: Sequence[float]) -> Dict[str, Any]:
    """Radial and axial extent of a loop about the axis through ``center`` (the two coordinates
    across the axis, in ascending order) along coordinate ``axis``: the distance of the loop's
    nearest and farthest points from the axis, and its lowest and highest position along it."""
    across = [k for k in range(3) if k != axis]
    starts = np.array([e["start"] for e in loop["edges"]])
    ends = np.array([e["end"] for e in loop["edges"]])
    p = starts[:, across] - np.asarray(center, dtype=float)
    q = ends[:, across] - np.asarray(center, dtype=float)
    seg = q - p
    span = (seg ** 2).sum(axis=1)
    u = np.where(span > 0, np.clip(-(p * seg).sum(axis=1) / np.where(span > 0, span, 1.0), 0.0, 1.0), 0.0)
    nearest = np.linalg.norm(p + u[:, None] * seg, axis=1)
    farthest = np.maximum(np.linalg.norm(p, axis=1), np.linalg.norm(q, axis=1))
    along = np.concatenate([starts[:, axis], ends[:, axis]])
    return {"axis": "xyz"[axis], "center": [float(c) for c in center],
            "radial": [float(nearest.min()), float(farthest.max())],
            "axial": [float(along.min()), float(along.max())]}


def merge_extents(extents: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The extents of several loops taken together (None when there are none)."""
    if not extents:
        return None
    out = dict(extents[0])
    out["radial"] = [min(e["radial"][0] for e in extents), max(e["radial"][1] for e in extents)]
    out["axial"] = [min(e["axial"][0] for e in extents), max(e["axial"][1] for e in extents)]
    return out
