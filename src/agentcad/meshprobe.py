"""Probes of a triangle mesh: lines through it.

A mesh file (STL) is a soup of triangles with no connectivity and no exact
surface, so what these probes report is the tessellation's, to the
tessellation's tolerance, and the outputs say so. ``crossings`` finds where a
line meets the surface and in which direction, and ``LineScan`` turns those
into inside and outside.

It is written so that a line through a vertex or along an edge of the mesh
(which is where symmetric parts put them) does not break the count. A line is
tested against each triangle projected along the line, and a point on the
shared edge of two projected triangles is given to exactly one of them by a
fixed rule (the edge function is exactly antisymmetric, and a zero is broken
by the edge's direction), which is the same as nudging the line by an
infinitesimal amount. A line that lies in the surface has no side of its own,
so it is nudged four ways and counts as inside if any nudge puts it inside,
the same answer the exact kernel gives (the boundary is material).
"""

from pathlib import Path
from typing import List, Sequence, Tuple

import numpy as np

_CHUNK = 262144   # triangles per pass: bounds the temporaries on a large mesh


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
