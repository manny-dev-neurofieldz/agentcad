"""QC: design rules judged before a print, as findings.

A rule's limit comes from layers: the printer's process defaults (``agentcad.printers``), then
the project's ``[qc]`` table, then a feature's own annotation (``agentcad.annotate``). Every finding
names the layer that set its limit. A rule with a limit but no measurement yet is listed as not
measured, never as a finding: QC never fails a part on a number it did not take.

The ``[qc]`` table::

    [qc]
    gate = true                                # finalize holds the manifest back on an error
    printer = "mk4"                            # default: the [print] printer_profile, else mk4
    limits = { min_wall_mm = 1.6 }             # over the printer's process defaults
    severity = { build_volume = "warning" }    # error | warning | off, per rule
    pose = { up = [1, 0, 0], spin_deg = 0 }    # the print pose: the part's direction that points
                                               # up on the bed, then a turn about z

Measured, on the part's mesh in its print pose:

* ``build_volume``: the extent against the printer's build volume. The footprint may turn about z
  on the bed; a part that fits only turned is a warning that names the turn, one that fits at no
  turn (or is too tall) is an error.
* ``min_feature`` and ``min_wall``: the in-layer width of the material, the width the printer
  lays down in each layer. The part is cut at layer pitch; from points along every section edge a
  ray runs inward to the opposite boundary of the section, so the width is exact on the mesh, with
  no raster in between. Narrower than ``min_feature_mm`` is an error, narrower than
  ``min_wall_mm`` a warning. A corner is never read from inside itself: a hit closer than the
  limit along the boundary (two edges meeting, a tessellation step) is not the far side of a wall.
  A thin region is then checked through the part, along the inward normal of the faces it lies
  on: thin there too, it is a wall; thick behind, it is a layer cutting a sloped edge (a sliver),
  counted in the report but not judged. A wall no feature annotation claims is unattributed and
  never more than a warning.
* floors: material along z on a grid of vertical lines; a run thinner than the wall limit, inside a
  thin area (its rim left out), is judged as a wall is.
* ``max_overhang``: faces turned down further than ``max_overhang_deg`` from vertical, the face
  on the bed (within one layer of the lowest point) and bridge ceilings excepted, grouped into
  regions that share a vertex.
* ``max_bridge``: a ceiling held at both ends along a principal axis is a bridge; its span, against
  ``max_bridge_mm`` unless the print intent plans supports.

A program's annotations (features with boxes and limits, suppressions with reasons, a print pose)
attribute findings: a claimed finding names the feature and its declaring line and may be an
error; suppressions and loosened limits are listed with their reasons.
"""

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from agentcad import printers
from agentcad.findings import Finding

#: Rules QC measures, with their default severity.
RULES = {"build_volume": "error", "min_feature": "error", "min_wall": "warning", "max_overhang": "warning",
         "max_bridge": "warning"}
#: The limit each measured rule reads.
LIMIT_OF = {"min_feature": "min_feature_mm", "min_wall": "min_wall_mm", "max_overhang": "max_overhang_deg",
            "max_bridge": "max_bridge_mm"}
#: The rules that read a width off the mesh: of a wall, of a floor, of a feature.
WALL_RULES = ("min_feature", "min_wall")
#: At most this many sections per part: a taller part is cut at a coarser pitch, and the report says so.
MAX_SECTIONS = 400
SEVERITIES = ("error", "warning", "off")


@dataclass
class QCSettings:
    gate: bool = False
    printer: Optional[str] = None
    limits: Dict[str, float] = field(default_factory=dict)
    severity: Dict[str, str] = field(default_factory=dict)
    pose: Optional[Dict[str, Any]] = None

    @classmethod
    def from_table(cls, table: Dict[str, Any]) -> "QCSettings":
        severity = {str(k): str(v).lower() for k, v in (table.get("severity") or {}).items()}
        bad = {k: v for k, v in severity.items() if v not in SEVERITIES}
        if bad:
            raise ValueError(f"[qc] severity: each rule is one of {', '.join(SEVERITIES)}, not {bad}")
        return cls(gate=bool(table.get("gate", False)), printer=table.get("printer"),
                   limits={str(k): float(v) for k, v in (table.get("limits") or {}).items()},
                   severity=severity, pose=dict(table["pose"]) if table.get("pose") else None)


def settings(cfg) -> Optional[QCSettings]:
    """The project's QC settings, or None when it declares no ``[qc]`` table."""
    table = getattr(cfg, "qc", None)
    return QCSettings.from_table(table) if table is not None else None


def printer_for(cfg, qs: QCSettings, override: Optional[str] = None) -> printers.Printer:
    """The printer QC judges against: ``override``, else ``[qc] printer``, else the printer whose
    label is the project's ``[print] printer_profile``, else the MK4."""
    name = override or qs.printer
    if name:
        return printers.get(name, cfg)
    profile = getattr(getattr(cfg, "print", None), "printer_profile", "")
    return printers.by_label(profile, cfg) or printers.get("mk4", cfg)


def limits(printer: printers.Printer, qs: QCSettings) -> Dict[str, Tuple[float, str]]:
    """Each rule's limit and the layer that set it."""
    out = {k: (float(v), printer.defaults_layer()) for k, v in printer.defaults().items()}
    for k, v in qs.limits.items():
        out[k] = (float(v), "project [qc]")
    return out


def pose_rotation(pose: Optional[Dict[str, Any]]):
    """The rotation taking the part to its print pose: ``up`` (default +z) onto +z, then
    ``spin_deg`` about z; or the rotation itself, as ``matrix`` (3x3, rows)."""
    import numpy as np
    pose = pose or {}
    if pose.get("matrix") is not None:
        M = np.array(pose["matrix"], dtype=float)
        if M.shape != (3, 3) or not np.allclose(M @ M.T, np.eye(3), atol=1e-6) or np.linalg.det(M) < 0:
            raise ValueError(f"a pose matrix must be a 3x3 rotation, not {pose['matrix']!r}")
        return M
    up = np.array(pose.get("up", (0.0, 0.0, 1.0)), dtype=float)
    if up.shape != (3,) or not np.linalg.norm(up):
        raise ValueError(f"[qc] pose up must be a non-zero vector [x, y, z], not {pose.get('up')!r}")
    up /= np.linalg.norm(up)
    z = np.array([0.0, 0.0, 1.0])
    axis, c = np.cross(up, z), float(np.dot(up, z))
    if np.linalg.norm(axis) < 1e-12:
        R = np.eye(3) if c > 0 else np.diag([1.0, -1.0, -1.0])        # already up, or upside down
    else:
        k = axis / np.linalg.norm(axis)
        K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
        s = math.sqrt(max(0.0, 1.0 - c * c))
        R = np.eye(3) + s * K + (1 - c) * (K @ K)                     # Rodrigues: up onto z
    a = math.radians(float(pose.get("spin_deg", 0.0)))
    spin = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
    return spin @ R


def _footprint(P, deg: float):
    import numpy as np
    a = math.radians(deg)
    xy = P[:, :2] @ np.array([[math.cos(a), math.sin(a)], [-math.sin(a), math.cos(a)]])
    return xy.max(axis=0) - xy.min(axis=0)


def check_build_volume(vertices, printer: printers.Printer, pose: Optional[Dict[str, Any]] = None,
                       severity: str = "error") -> Finding:
    """The part's extent in the print pose against the printer's build volume."""
    import numpy as np
    P = np.asarray(vertices, dtype=float) @ pose_rotation(pose).T
    ext = P.max(axis=0) - P.min(axis=0)
    X, Y, Z = printer.build_volume
    eps = 1e-6 * max(1.0, float(ext.max()))
    found = f"{ext[0]:.1f} x {ext[1]:.1f} x {ext[2]:.1f} mm"
    intended = f"within {X:g} x {Y:g} x {Z:g} mm ({printer.label})"
    layer = f"printer {printer.name} ({printer.label}, {printer.source})"

    def finding(sev: str, message: str, fix: str = "") -> Finding:
        if sev == "error" and severity == "warning":
            sev = "warning"
        return Finding("extent", sev, found, intended, "a part that does not fit the build volume cannot print",
                       f"[qc] on {printer.name}", rule="build_volume", layer=layer, fix=fix, message=message)

    if ext[2] > Z + eps:
        return finding("error", f"{found} in the print pose: {ext[2]:.1f} mm tall against the {printer.label}'s "
                                f"{Z:g} mm; no turn about z helps",
                       "lay the part down (a [qc] pose up direction), split it, or choose a printer with more height")
    fits = lambda w: w[0] <= X + eps and w[1] <= Y + eps
    if fits(ext):
        return finding("ok", f"{found} in the print pose fits the {printer.label}'s {X:g} x {Y:g} x {Z:g} mm")
    for deg in [90] + [d for d in range(1, 180) if d != 90]:      # a quarter turn first, then the smallest that fits
        if fits(_footprint(P, deg)):
            return finding("warning", f"{found} in the print pose fits the {X:g} x {Y:g} mm bed only spun {deg} "
                                      f"degrees about z", f"set [qc] pose spin_deg = {deg}, and place it so on the bed")
    return finding("error", f"{found} in the print pose: the footprint fits the {X:g} x {Y:g} mm bed at no turn about z",
                   "re-pose the part, split it, or choose a printer with a larger bed")


def mesh_vertices(stl: Optional[Path]):
    """The vertices of an STL, or None when it is missing or unreadable (QC then measures nothing)."""
    mesh = load_mesh(stl)
    return mesh.tri.reshape(-1, 3) if mesh is not None else None


def load_mesh(stl: Optional[Path]):
    """The mesh of an STL (``agentcad.meshprobe.Mesh``), or None when it is missing or unreadable."""
    if stl is None or not Path(stl).is_file():
        return None
    try:
        from agentcad import meshprobe
        return meshprobe.load_mesh(Path(stl))
    except Exception:
        return None


def posed(mesh, pose: Optional[Dict[str, Any]]):
    """The mesh turned into its print pose."""
    from agentcad import meshprobe
    return meshprobe.Mesh(mesh.path, mesh.tri @ pose_rotation(pose).T)


# --- walls: in-layer width, exact on the section polygons ----------------------------------------

def section_polygons(mesh, z: float):
    """The closed loops where the plane at height ``z`` cuts the mesh, as (n, 2) arrays of x, y."""
    import numpy as np
    from agentcad import meshprobe
    return [np.array([e["start"][:2] for e in L["edges"]], dtype=float)
            for L in meshprobe.plane_loops(mesh, 2, z) if L["closed"] and len(L["edges"]) >= 3]


def in_layer_widths(polys, spacing: float, corner: float = 0.0, with_normals: bool = False):
    """Points along every edge of a section (at most ``spacing`` apart) and, for each, the distance
    along the inward normal to the boundary across the material: the material's width there. With
    ``with_normals``, the inward normals too, as a third array.

    A hit on the same loop within ``corner`` of the point, measured along the boundary, is a corner
    read from inside itself (two edges meeting, a tessellation step), not the far side of a wall,
    and is skipped; the far side of a real wall lies further round the boundary than that."""
    import numpy as np
    A = np.concatenate(polys)
    B = np.concatenate([np.roll(p, -1, axis=0) for p in polys])
    E = B - A
    lengths = np.hypot(E[:, 0], E[:, 1])
    loop = np.concatenate([np.full(len(p), k) for k, p in enumerate(polys)])
    starts = np.concatenate([np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(np.vstack([p, p[:1]]), axis=0).T))[:-1]])
                             for p in polys])
    perimeter = np.array([float(np.hypot(*np.diff(np.vstack([p, p[:1]]), axis=0).T).sum()) for p in polys])
    pts, nrm, at_loop, at_arc = [], [], [], []
    for a, d, length, k, s0 in zip(A, E, lengths, loop, starts):
        if length < 1e-9:
            continue
        n = int(max(1, math.ceil(length / spacing)))
        t = (np.arange(n) + 0.5) / n
        pts.append(a + np.outer(t, d))
        nrm.append(np.tile([-d[1] / length, d[0] / length], (n, 1)))
        at_loop.append(np.full(n, k))
        at_arc.append(s0 + t * length)
    if not pts:
        return (np.zeros((0, 2)), np.zeros(0)) + ((np.zeros((0, 2)),) if with_normals else ())
    P, N = np.concatenate(pts), np.concatenate(nrm)
    P_loop, P_arc = np.concatenate(at_loop), np.concatenate(at_arc)

    def inside(Q):          # even-odd against every edge of the section
        y, x = Q[:, 1:2], Q[:, 0:1]
        ay, by, ax, bx = A[None, :, 1], B[None, :, 1], A[None, :, 0], B[None, :, 0]
        crosses = (ay > y) != (by > y)
        with np.errstate(divide="ignore", invalid="ignore"):
            xi = ax + (y - ay) * (bx - ax) / (by - ay)
        return ((crosses & (x < xi)).sum(axis=1) % 2) == 1

    N[~inside(P + 1e-4 * N)] *= -1          # each normal points into the material
    den = N[:, None, 0] * E[None, :, 1] - N[:, None, 1] * E[None, :, 0]
    w = A[None, :, :] - P[:, None, :]
    with np.errstate(divide="ignore", invalid="ignore"):
        dist = (w[..., 0] * E[None, :, 1] - w[..., 1] * E[None, :, 0]) / den
        u = (w[..., 0] * N[:, None, 1] - w[..., 1] * N[:, None, 0]) / den
    hit = (np.abs(den) > 1e-12) & (dist > 1e-6) & (u >= -1e-9) & (u <= 1 + 1e-9)
    if corner > 0:
        same = P_loop[:, None] == loop[None, :]
        along = np.abs(P_arc[:, None] - (starts[None, :] + np.clip(u, 0, 1) * lengths[None, :]))
        along = np.minimum(along, perimeter[P_loop][:, None] - along)
        hit &= ~(same & (along < corner))
    widths = np.where(hit, dist, np.inf).min(axis=1)
    return (P, widths, N) if with_normals else (P, widths)


def _clusters(points, link: float):
    """Labels joining points closer than ``link`` (transitively)."""
    import numpy as np
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree
    if len(points) == 0:
        return np.zeros(0, dtype=int)
    pairs = cKDTree(points).query_pairs(link, output_type="ndarray")
    graph = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(len(points), len(points)))
    return connected_components(graph, directed=False)[1]


def measure_walls(mesh, limit: float, layer: float = 0.2) -> Dict[str, Any]:
    """Every place the in-layer width is under ``limit``, grouped into regions: each with its
    narrowest width and where it is (print-pose coordinates), its height range and layer count."""
    import numpy as np
    lo, hi = float(mesh.lo[2]), float(mesh.hi[2])
    pitch = max(layer, (hi - lo) / MAX_SECTIONS)
    spacing = max(limit / 4.0, 1e-3)
    thin, n_sections = [], 0
    for z in np.arange(lo + pitch / 2.0, hi, pitch):
        polys = section_polygons(mesh, float(z))
        if not polys:
            continue
        n_sections += 1
        P, W, N = in_layer_widths(polys, spacing, corner=limit, with_normals=True)
        keep = W < limit
        thin.extend((p[0], p[1], float(z), float(w), n[0], n[1]) for p, w, n in zip(P[keep], W[keep], N[keep]))
    regions = []
    if thin:
        T = np.array(thin)
        # the two faces of one thin wall are less than the limit apart: join across it
        labels = _clusters(T[:, :3], max(2.0 * spacing, 1.5 * pitch, limit))
        for k in np.unique(labels):
            R = T[labels == k]
            at = R[np.argmin(R[:, 3])]
            depth, thinnest = _material_depth(mesh, R, limit)
            regions.append({"width_mm": float(at[3]), "at": [float(v) for v in at[:3]],
                            "normal": [float(at[4]), float(at[5]), 0.0],      # into the material, across the wall
                            "z_range": [float(R[:, 2].min()), float(R[:, 2].max())],
                            "layers": int(len(np.unique(R[:, 2]))), "samples": int(len(R)),
                            "depth_mm": depth, "depth_min_mm": thinnest,
                            "kind": "wall" if depth < limit else "layer_sliver"})
        regions.sort(key=lambda r: r["width_mm"])
    return {"pitch_mm": float(pitch), "spacing_mm": float(spacing), "sections": n_sections, "regions": regions}


def _material_depth(mesh, samples, limit: float, n: int = 9) -> Tuple[float, float]:
    """The material behind a thin region, through the part: the median, over up to ``n`` of its
    samples (the thinnest first, then spread), of the depth along the inward normal of the face each
    lies on, and the least of them. A wall thin in its layer and through the part is a thin wall;
    one thin only in its layer is a layer cutting a sloped edge (a sliver), with full material
    behind it."""
    import numpy as np
    from agentcad.fit import _closest_on_triangles
    from agentcad.rays import MeshTarget, ray_intervals

    order = np.argsort(samples[:, 3])
    pick = list(order[:3]) + list(order[np.linspace(0, len(order) - 1, max(0, n - 3)).astype(int)])
    pick = list(dict.fromkeys(int(i) for i in pick))[:n]
    tri = mesh.tri
    normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]) * mesh.orient
    lengths = np.linalg.norm(normals, axis=1)
    lo, hi = tri.min(axis=1), tri.max(axis=1)
    target = MeshTarget(mesh)
    depths = []
    for i in pick:
        p = samples[i, :3]
        # the face a sample lies on: among the triangles whose box holds it (a long side triangle's
        # centre can be far from a point near its end), the nearest exactly
        near = np.nonzero(np.all((lo <= p + 10 * mesh.tolerance) & (hi >= p - 10 * mesh.tolerance), axis=1))[0]
        if not len(near):
            continue
        q = _closest_on_triangles(np.tile(p, (len(near), 1)), tri[near, 0], tri[near, 1], tri[near, 2])
        j = near[int(np.argmin(np.linalg.norm(q - p, axis=1)))]
        if lengths[j] < 1e-12:
            continue
        outward = normals[j] / lengths[j]
        rec = ray_intervals(target, p + 1e-3 * outward, -outward, length=3.0 * limit)
        material = [iv for iv in rec["intervals"] if iv["kind"] == "material"]
        if material:
            first = material[0]
            depths.append(float("inf") if first.get("clipped_end") else float(first["length"]))
    return (float(np.median(depths)), float(min(depths))) if depths else (float("inf"), float("inf"))


# --- overhangs: faces turned down past the limit --------------------------------------------------

def _face_angles(mesh):
    """Per triangle: twice its area, its angle from vertical (0 a wall, 90 a face looking straight
    down, negative facing up) and its centroid height."""
    import numpy as np
    tri = mesh.tri
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]) * mesh.orient
    area2 = np.linalg.norm(n, axis=1)
    ok = area2 > 1e-12
    down = np.zeros(len(tri))
    down[ok] = -n[ok, 2] / area2[ok]                       # 1 for a face looking straight down
    angle = np.degrees(np.arcsin(np.clip(down, -1.0, 1.0)))
    angle[~ok] = -90.0
    return area2, angle, tri[:, :, 2].mean(axis=1)


def measure_overhang(mesh, limit_deg: float, first_layer: float = 0.2, exclude=None) -> List[Dict[str, Any]]:
    """Regions of faces turned down further than ``limit_deg`` from vertical (the face on the bed,
    and any face ``exclude`` marks, excepted), joined where they share a vertex: area, worst angle
    and where."""
    import numpy as np
    tri = mesh.tri
    area2, angle, centroid_z = _face_angles(mesh)
    keep = (angle > limit_deg + 1e-6) & (centroid_z > float(mesh.lo[2]) + first_layer)
    if exclude is not None:
        keep &= ~exclude
    flagged = np.nonzero(keep)[0]
    if not len(flagged):
        return []
    points, rows = mesh.welded()
    labels = _clusters_by_vertex(rows[flagged], len(points))
    regions = []
    for k in np.unique(labels):
        idx = flagged[labels == k]
        c = tri[idx].reshape(-1, 3)
        regions.append({"area_mm2": float(area2[idx].sum() / 2.0), "worst_deg": float(angle[idx].max()),
                        "at": [float(v) for v in c.mean(axis=0)], "min": [float(v) for v in c.min(axis=0)],
                        "max": [float(v) for v in c.max(axis=0)], "faces": int(len(idx))})
    return sorted(regions, key=lambda r: -r["area_mm2"])


def _clusters_by_vertex(rows, n_points: int):
    """Labels joining triangles (rows of welded point indices) that share a vertex."""
    import numpy as np
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    m = len(rows)
    tri_ids = np.repeat(np.arange(m), 3)
    graph = coo_matrix((np.ones(3 * m), (tri_ids, rows.reshape(-1) + m)), shape=(m + n_points, m + n_points))
    return connected_components(graph, directed=False)[1][:m]


# --- bridges: ceilings held at both ends ------------------------------------------------------------

#: A face within this many degrees of looking straight down is a ceiling a bridge can span.
CEILING_DEG = 5.0


def _inside(target, mesh, x: float, y: float, z: float) -> bool:
    """Whether (x, y, z) is in the part's material, read off a vertical line through it."""
    from agentcad.rays import ray_intervals
    lo, hi = float(mesh.lo[2]), float(mesh.hi[2])
    rec = ray_intervals(target, (x, y, lo - 1.0), (0.0, 0.0, 1.0), length=hi - lo + 2.0)
    return any(iv["kind"] == "material" and iv["entry_point"][2] - 1e-9 <= z <= iv["exit_point"][2] + 1e-9
               for iv in rec["intervals"])


def measure_bridges(mesh, first_layer: float = 0.2) -> Dict[str, Any]:
    """Ceilings (faces within ``CEILING_DEG`` of looking straight down, the bed excepted), joined
    where they share a vertex. Along each principal axis of a ceiling's footprint, material just
    beyond both ends means the ceiling is held there: a ceiling held along an axis is a bridge whose
    span is its extent along that axis (the shorter, when held along both, as a roof held all round).
    A ceiling held at one end or none is a cantilever or a floating roof and stays an overhang.
    Returns the bridges and the mask of the faces they cover."""
    import numpy as np
    from agentcad.rays import MeshTarget
    tri = mesh.tri
    area2, angle, centroid_z = _face_angles(mesh)
    flagged = np.nonzero((angle >= 90.0 - CEILING_DEG) & (centroid_z > float(mesh.lo[2]) + first_layer))[0]
    mask = np.zeros(len(tri), dtype=bool)
    bridges: List[Dict[str, Any]] = []
    if not len(flagged):
        return {"bridges": bridges, "mask": mask}
    points, rows = mesh.welded()
    labels = _clusters_by_vertex(rows[flagged], len(points))
    target = MeshTarget(mesh)
    step = max(4.0 * float(mesh.tolerance), 0.3)          # beyond the ceiling's edge, and below it
    for k in np.unique(labels):
        idx = flagged[labels == k]
        P = tri[idx].reshape(-1, 3)
        xy, z = P[:, :2], float(P[:, 2].mean())
        # principal axes from the footprint's exact second moments (a triangle's integral of x x^T is
        # A/12 (sum p p^T + (sum p)(sum p)^T)): vertex statistics would tilt with the triangulation
        T2 = tri[idx][:, :, :2]
        A = 0.5 * np.abs((T2[:, 1, 0] - T2[:, 0, 0]) * (T2[:, 2, 1] - T2[:, 0, 1])
                         - (T2[:, 2, 0] - T2[:, 0, 0]) * (T2[:, 1, 1] - T2[:, 0, 1]))
        if A.sum() <= 1e-12:
            continue
        s = T2.sum(axis=1)
        c = (A[:, None] * s / 3.0).sum(axis=0) / A.sum()
        M = (A[:, None, None] / 12.0 * (np.einsum("tki,tkj->tij", T2, T2) + np.einsum("ti,tj->tij", s, s))).sum(axis=0)
        X = xy - c
        _, V = np.linalg.eigh(M / A.sum() - np.outer(c, c))
        held = []
        for axis in (V[:, 0], V[:, 1]):
            s = X @ axis
            # material within reach beyond an end holds it there: a fillet between the ceiling and its
            # support leaves void just beyond the ceiling's edge, the support itself is a little further
            reach = max(2.0, 0.2 * float(s.max() - s.min()))
            offsets = np.arange(step, reach + 1e-9, step)

            def holds(edge, sign):
                return any(_inside(target, mesh, float(p[0]), float(p[1]), z - step)
                           for p in (c + (edge + sign * d) * axis for d in offsets))

            if holds(s.min(), -1.0) and holds(s.max(), 1.0):
                held.append((float(s.max() - s.min()), axis))
        if not held:
            continue
        span, axis = min(held, key=lambda h: h[0])
        across = X @ np.array([-axis[1], axis[0]])
        mask[idx] = True
        bridges.append({"span_mm": span, "width_mm": float(across.max() - across.min()),
                        "direction": [float(axis[0]), float(axis[1])], "at": [float(c[0]), float(c[1]), z],
                        "area_mm2": float(area2[idx].sum() / 2.0), "faces": int(len(idx)), "uncertainty_mm": step})
    bridges.sort(key=lambda b: -b["span_mm"])
    return {"bridges": bridges, "mask": mask}


# --- floors: thin across the layers ---------------------------------------------------------------

#: At most this many vertical lines per side of the floor grid; a larger part is sampled coarser.
FLOOR_GRID = 120


def measure_floors(mesh, limit: float) -> Dict[str, Any]:
    """Material along z on a grid of vertical lines over the part: a run shorter than ``limit`` is a
    thin floor or roof at that place, which the in-layer width cannot see (each layer of a thin plate
    is wide). A run at the edge of a thin area (a grid neighbour with no thin run at that height) is
    left out, so a chamfer or fillet at a floor's rim is not read as the floor. Each thin area gives
    the median and the least thickness of its interior, where it is and how much it covers."""
    import numpy as np
    from agentcad.rays import MeshTarget, ray_intervals
    lo, hi = np.asarray(mesh.lo, dtype=float), np.asarray(mesh.hi, dtype=float)
    spacing = max(float(limit), float(max(hi[0] - lo[0], hi[1] - lo[1])) / FLOOR_GRID, 1e-3)
    xs = np.arange(lo[0] + spacing / 2.0, hi[0], spacing)
    ys = np.arange(lo[1] + spacing / 2.0, hi[1], spacing)
    target = MeshTarget(mesh)
    runs: Dict[Tuple[int, int], List[Tuple[float, float]]] = {}
    for i, x in enumerate(xs):
        for j, y in enumerate(ys):
            rec = ray_intervals(target, (float(x), float(y), float(lo[2]) - 1.0), (0.0, 0.0, 1.0),
                                length=float(hi[2] - lo[2]) + 2.0)
            thin = [((iv["entry_point"][2] + iv["exit_point"][2]) / 2.0, float(iv["length"]))
                    for iv in rec["intervals"] if iv["kind"] == "material" and iv["length"] < limit]
            if thin:
                runs[(i, j)] = thin
    interior = []
    for (i, j), found in runs.items():
        for zm, thickness in found:
            if all(any(abs(z2 - zm) < limit for z2, _ in runs.get(nb, []))
                   for nb in ((i - 1, j), (i + 1, j), (i, j - 1), (i, j + 1))):
                interior.append((float(xs[i]), float(ys[j]), zm, thickness))
    regions = []
    if interior:
        T = np.array(interior)
        labels = _clusters(T[:, :3], 1.5 * spacing)
        for k in np.unique(labels):
            R = T[labels == k]
            at = R[np.argsort(R[:, 3])[len(R) // 2]]
            regions.append({"thickness_mm": float(np.median(R[:, 3])), "thinnest_mm": float(R[:, 3].min()),
                            "at": [float(v) for v in at[:3]], "z_range": [float(R[:, 2].min()), float(R[:, 2].max())],
                            "area_mm2": float(len(R) * spacing * spacing), "samples": int(len(R))})
        regions.sort(key=lambda r: r["thickness_mm"])
    return {"spacing_mm": float(spacing), "lines": int(len(xs) * len(ys)), "regions": regions}


# --- judging --------------------------------------------------------------------------------------

def _to_part_frame(point, pose):
    import numpy as np
    return [float(v) for v in pose_rotation(pose).T @ np.asarray(point, dtype=float)]


def _fmt_point(p):
    return "(" + ", ".join(f"{v:.2f}" for v in p) + ")"


@dataclass
class Annotated:
    """What a program declared with ``agentcad.annotate``, ready to judge with: its features, its
    suppressions and its print pose, each with the ``file:line`` that declared it."""
    features: List[Dict[str, Any]] = field(default_factory=list)
    suppressions: List[Dict[str, Any]] = field(default_factory=list)
    pose: Optional[Dict[str, Any]] = None
    pose_source: str = ""

    @classmethod
    def from_records(cls, records: Optional[Sequence[Dict[str, Any]]], origin_of: Optional[Dict[str, str]] = None
                     ) -> "Annotated":
        """``origin_of`` maps the copy of a source the engine built from to the user's file, so a
        line is named in the file the user edits. A record whose line is None (an OpenSCAD echo
        carries none) names the file alone."""
        import os
        origins = {os.path.realpath(k): v for k, v in (origin_of or {}).items() if k and v}
        out = cls()
        for r in records or []:
            path = str(r.get("file") or "")
            where = origins.get(os.path.realpath(path), path) if path else "?"
            line = r.get("line", "?")
            source = where if line is None else f"{where}:{line}"
            if r.get("type") == "feature":
                out.features.append(dict(r, source=source))
            elif r.get("type") == "suppress":
                out.suppressions.append(dict(r, source=source))
            elif r.get("type") == "pose" and out.pose is None:
                out.pose, out.pose_source = dict(r["pose"]), source
        return out

    def claim(self, point: Optional[Sequence[float]], tol: float) -> Optional[Dict[str, Any]]:
        """The feature whose box holds ``point`` (part frame); the smallest box when several do."""
        if point is None:
            return None
        hits = [f for f in self.features
                if all(f["box"][i] - tol <= point[i] <= f["box"][i + 3] + tol for i in range(3))]
        return min(hits, key=lambda f: math.prod(max(f["box"][i + 3] - f["box"][i], 1e-9) for i in range(3))) \
            if hits else None

    @staticmethod
    def limit(feat: Optional[Dict[str, Any]], key: str, lim: Dict[str, Tuple[float, str]]) -> Optional[Tuple[float, str]]:
        """A rule's limit for a place: the claiming feature's own, else the limit below it."""
        if feat is not None and key in feat.get("limits", {}):
            return float(feat["limits"][key]), f"feature {feat['name']!r} ({feat['source']})"
        return lim.get(key)


def _claimed(kind: str, feat: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {"feature": feat["name"], "source": feat["source"]} if feat else {"feature": "", "source": "[qc]"}


# --- mesh resolution: a width is read only where the mesh can show it ------------------------------

def mm_text(value: float) -> str:
    return f"{value:.2f} mm" if value >= 0.1 else f"{value:.3g} mm"


def mesh_facts(metadata: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """What an iteration's metadata says about how a grid engine made its mesh: ``voxel_mm`` (the cell
    edge) and ``stride`` (of the marching cubes), for the report's words, and ``offset`` (the engine's
    ``mesh_offset``: where the mesh's origin lies in the program's frame). None when it says none of them."""
    md = metadata or {}
    out: Dict[str, Any] = {}
    try:
        sizes = [float(v) for v in md.get("voxel_size") or ()]
    except (TypeError, ValueError):
        sizes = []
    if sizes:
        out["voxel_mm"] = max(sizes)
    surface = md.get("surface")
    stride = surface.get("mc_stride") if isinstance(surface, dict) else None
    if isinstance(stride, int) and not isinstance(stride, bool):
        out["stride"] = max(1, stride)
    try:
        offset = [float(v) for v in md.get("mesh_offset") or ()]
    except (TypeError, ValueError):
        offset = []
    if len(offset) == 3 and all(math.isfinite(v) for v in offset):
        out["offset"] = offset
    return out or None


def limits_in_force(lim: Dict[str, Tuple[float, str]], ann: "Annotated") -> Dict[str, List[float]]:
    """For each wall rule, every limit in force on the part: the layered one, then each feature's own."""
    out: Dict[str, List[float]] = {}
    for rule in WALL_RULES:
        key = LIMIT_OF[rule]
        out[rule] = ([lim[key][0]] if key in lim else []) + \
            [f["limits"][key] for f in ann.features if key in f.get("limits", {})]
    return out


def readable_rules(resolution_mm: float, in_force: Dict[str, List[float]],
                   source: Optional[Mapping[str, Any]] = None) -> Tuple[Tuple[str, ...], Dict[str, str]]:
    """The wall rules a mesh that resolves ``resolution_mm`` can be read for, and why not for the rest.
    A width is read only where the mesh resolves at most half the smallest limit in force for the rule
    (the layered limit and any feature's own): a sheet or gap narrower than about the resolution does not
    survive the contouring, and a width near the limit would be read off noise. A rule with no limit
    stays in. ``source`` is the voxel edge and stride, for the words."""
    keep: List[str] = []
    why: Dict[str, str] = {}
    for rule in WALL_RULES:
        smallest = min(in_force[rule]) if in_force[rule] else None
        if smallest is None or resolution_mm <= smallest / 2.0 * (1.0 + 1e-6):         # inclusive: half is enough
            keep.append(rule)
            continue
        made = []
        if source and source.get("voxel_mm") is not None:
            made.append(f"voxel {float(source['voxel_mm']):g} mm")
        if source and source.get("stride") is not None:
            made.append(f"stride {source['stride']}")
        by = f" ({' x '.join(made)})" if made else ""
        why[rule] = (f"the mesh resolves {mm_text(resolution_mm)}{by}; "
                     f"a {smallest:g} mm limit needs {smallest / 2.0:g} mm or finer")
    return tuple(keep), why


def _thin(kind: str, measured: float, region: Dict[str, Any], lim, qs: QCSettings, pose, ann: Annotated,
          tol: float, detail: str, rules: Tuple[str, ...] = WALL_RULES, uncertainty: float = 0.0):
    """A thin wall or floor judged at its place: an error under the minimum feature (only when a
    feature claims it), a warning under the minimum wall. ``rules`` are the wall rules the mesh can be
    read for (all of them, unless it is too coarse for one) and ``uncertainty`` how far the width may
    be off. Returns (finding, part-frame point, part-frame normal) or None: the normal is the line the
    measure read across a wall at that point (a floor has none: its line is the vertical)."""
    point = _to_part_frame(region["at"], pose)
    normal = _to_part_frame(region["normal"], pose) if region.get("normal") is not None else None
    feat = ann.claim(point, tol)
    fmin = ann.limit(feat, "min_feature_mm", lim) if "min_feature" in rules else None
    fwall = ann.limit(feat, "min_wall_mm", lim) if "min_wall" in rules else None
    if "min_wall" in rules:
        if fwall is None or measured >= fwall[0]:
            return None
        is_feature = fmin is not None and measured < fmin[0]
    else:                                  # a mesh too coarse for the wall rule: only the feature rule reads
        if fmin is None or measured >= fmin[0]:
            return None
        is_feature = True
    rule = "min_feature" if is_feature else "min_wall"
    value, layer = fmin if is_feature else fwall
    severity = qs.severity.get(rule, RULES[rule])
    if severity == "off":
        return None
    if severity == "error" and feat is None:
        severity = "warning"            # no feature annotation claims it, so never an error
    where = _fmt_point(point)
    name = f" of {feat['name']!r} ({feat['source']})" if feat else ""
    what = "narrower than the smallest feature it can print" if is_feature else f"thinner than a {kind} should be"
    coarse = f"; the mesh resolves {mm_text(uncertainty)}, so the width is good to about that" if uncertainty else ""
    finding = Finding(
        kind, severity, f"{measured:.3f} mm", f"at least {value:g} mm", "material narrower than the limit prints "
        "weak, as a seam, or not at all", rule=rule, layer=layer, location=f"{where} in the part's frame",
        uncertainty=uncertainty, fix=f"thicken the {kind} there, or move the feature that thins it",
        message=f"a {kind}{name} {measured:.3f} mm thick at {where} (part frame) is {what} ({value:g} mm); "
                f"{detail}{coarse}",
        **_claimed(kind, feat))
    return finding, point, normal


def check_walls(walls: Dict[str, Any], lim, qs: QCSettings, ann: Optional[Annotated] = None, pose=None, tol: float = 0.05,
                rules: Tuple[str, ...] = WALL_RULES, uncertainty: float = 0.0):
    """A finding per thin wall region (layer slivers are counted, not judged)."""
    ann, out = ann or Annotated(), []
    for r in walls["regions"]:
        if r.get("kind") != "wall":
            continue
        z0, z1 = r["z_range"]
        hit = _thin("wall", r["width_mm"], r, lim, qs, pose if pose is not None else qs.pose, ann, tol,
                    f"it runs over {r['layers']} layer(s), z {z0:.2f} to {z1:.2f} in the print pose, "
                    f"{r['depth_min_mm']:.3f} mm of material through the part at its thinnest (median {r['depth_mm']:.3f})",
                    rules, uncertainty)
        if hit:
            out.append(hit)
    return out


def check_floors(floors: Dict[str, Any], lim, qs: QCSettings, ann: Annotated, pose, tol: float,
                 rules: Tuple[str, ...] = WALL_RULES, uncertainty: float = 0.0):
    """A finding per thin floor or roof (its median thickness judged, its thinnest reported)."""
    out = []
    for r in floors["regions"]:
        z0, z1 = r["z_range"]
        hit = _thin("floor", r["thickness_mm"], r, lim, qs, pose, ann, tol,
                    f"{r['area_mm2']:.0f} mm2 of it, thinnest {r['thinnest_mm']:.3f} mm, at z {z0:.2f} to {z1:.2f} "
                    f"in the print pose (vertical lines {floors['spacing_mm']:.2f} mm apart)", rules, uncertainty)
        if hit:
            out.append(hit)
    return out


def check_overhang(regions: List[Dict[str, Any]], lim, qs: QCSettings, ann: Optional[Annotated] = None,
                   pose=None, tol: float = 0.05):
    ann, pose = ann or Annotated(), pose if pose is not None else qs.pose
    severity = qs.severity.get("max_overhang", RULES["max_overhang"])
    if severity == "off":
        return []
    out = []
    for r in regions:
        point = _to_part_frame(r["at"], pose)
        feat = ann.claim(point, tol)
        value, layer = ann.limit(feat, "max_overhang_deg", lim)
        if r["worst_deg"] <= value + 1e-6:
            continue
        where = _fmt_point(point)
        name = f" of {feat['name']!r} ({feat['source']})" if feat else ""
        out.append((Finding(
            "overhang", severity, f"{r['area_mm2']:.0f} mm2 at up to {r['worst_deg']:.0f} deg from vertical",
            f"faces at most {value:g} deg from vertical", "a face turned further down prints in air unless it is "
            "supported", rule="max_overhang", layer=layer, location=f"{where} in the part's frame",
            uncertainty=0.0, fix="re-pose the part, add a chamfer under the ledge, or plan supports there",
            message=(f"{r['area_mm2']:.0f} mm2 of faces{name} turned down up to {r['worst_deg']:.0f} deg from vertical "
                     f"around {where} (part frame), past the {value:g} deg limit"), **_claimed("overhang", feat)), point, None))
    return out


def check_bridges(bridges: List[Dict[str, Any]], lim, qs: QCSettings, ann: Annotated, pose, tol: float,
                  supports_planned: bool) -> Tuple[List[Tuple[Finding, Any]], List[Dict[str, Any]]]:
    """A finding per bridge longer than the process (or its feature) allows, unless the print intent
    plans supports; every bridge is also returned as a record with how it was judged."""
    severity = qs.severity.get("max_bridge", RULES["max_bridge"])
    out, records = [], []
    for b in bridges:
        point = _to_part_frame(b["at"], pose)
        feat = ann.claim(point, tol)
        limit = ann.limit(feat, "max_bridge_mm", lim)
        verdict = "within the limit" if limit is None or b["span_mm"] <= limit[0] else \
            ("supports planned" if supports_planned else "too long")
        records.append(dict(b, verdict=verdict, limit_mm=limit[0] if limit else None, **_claimed("bridge", feat)))
        if verdict != "too long" or severity == "off":
            continue
        value, layer = limit
        where = _fmt_point(point)
        name = f" of {feat['name']!r} ({feat['source']})" if feat else ""
        out.append((Finding(
            "bridge", severity, f"{b['span_mm']:.1f} mm span", f"at most {value:g} mm",
            "a longer bridge sags between its ends", rule="max_bridge", layer=layer,
            location=f"{where} in the part's frame", uncertainty=b["uncertainty_mm"],
            fix="shorten the span, add a support pillar, or plan supports in the print intent",
            message=(f"a bridge{name} spans {b['span_mm']:.1f} mm (width across its ends) at {where} (part frame), "
                     f"longer than {value:g} mm; supports are not planned"), **_claimed("bridge", feat)), point, None))
    return out, records


def _loosened(ann: Annotated, lim) -> Tuple[List[Dict[str, Any]], List[Finding]]:
    """Each limit a feature sets looser than the layer below it, listed like a suppression; one
    loosened without a reason is also a warning."""
    listed, found = [], []
    for feat in ann.features:
        for key, value in feat.get("limits", {}).items():
            below = lim.get(key)
            if below is None:
                continue
            looser = value > below[0] if key.startswith("max_") else value < below[0]
            if not looser:
                continue
            listed.append({"feature": feat["name"], "limit": key, "value": value, "below": below[0],
                           "below_layer": below[1], "why": feat.get("why", ""), "source": feat["source"]})
            if not feat.get("why"):
                found.append(Finding(
                    "annotation", "warning", f"{key} {value:g}", f"{below[0]:g} ({below[1]})",
                    "a limit loosened without a reason cannot be reviewed", rule="annotation",
                    layer="feature annotation", feature=feat["name"], source=feat["source"],
                    fix="add why=... to the feature saying why it may be thinner or steeper",
                    message=f"feature {feat['name']!r} ({feat['source']}) loosens {key} to {value:g} from "
                            f"{below[0]:g} without a reason"))
    return listed, found


def _apply_suppressions(pairs, ann: Annotated, tol: float) -> Tuple[List[Tuple[Any, ...]], List[Dict[str, Any]]]:
    kept, suppressed = [], []
    for entry in pairs:                           # (finding, point, ...): the rest stays with its finding
        finding, point = entry[0], entry[1]
        hit = next((s for s in ann.suppressions if s["rule"] == finding.rule and (
            s.get("box") is None or (point is not None and all(
                s["box"][i] - tol <= point[i] <= s["box"][i + 3] + tol for i in range(3))))), None)
        if hit is None:
            kept.append(entry)
        else:
            suppressed.append({"rule": finding.rule, "why": hit["why"], "source": hit["source"],
                               "finding": finding.sentence()})
    return kept, suppressed


def run(cfg, stl: Optional[Path], qs: QCSettings, printer_override: Optional[str] = None,
        annotations: Optional[Sequence[Dict[str, Any]]] = None, origin_of: Optional[Dict[str, str]] = None,
        resolution_mm: Optional[float] = None, grid: Optional[Mapping[str, Any]] = None
        ) -> Dict[str, Any]:
    """Judge one part's mesh (an STL): the printer, every limit with its layer, the findings, what
    each measurement sampled, and the rules not measured (with why). ``annotations`` are the records
    the part's program made (``agentcad.annotate``, or an OpenSCAD program's echo lines); ``origin_of``
    maps a built copy to the user's file.

    ``resolution_mm`` is the finest feature the engine's mesh can show (the engine's metadata key of
    that name; None for an engine whose mesh is exact). A width is read off the mesh only where it
    resolves at most half the smallest limit in force for the rule; a rule the mesh is too coarse for
    is listed as not measured, with the resolution and the limit, and when neither wall rule can be
    read the walls and floors are not measured at all. A wall or floor read off such a mesh carries the
    resolution as its uncertainty. Overhangs, bridges and the build volume do not depend on it.
    ``grid`` (``mesh_facts(metadata)``) is how a grid engine made the mesh: the voxel edge and stride, for
    the words, and the ``offset`` that puts a mesh written from the grid's corner back in the program's
    frame, where its feature boxes are."""
    res = None
    if resolution_mm is not None:
        try:
            res = float(resolution_mm)
        except (TypeError, ValueError):
            res = float("nan")
        if not (math.isfinite(res) and res > 0):
            raise ValueError(f"resolution_mm must be a positive number, not {resolution_mm!r}")
    printer = printer_for(cfg, qs, printer_override)
    lim = limits(printer, qs)
    layer = float(getattr(getattr(cfg, "print", None), "layer_height", 0.2) or 0.2)
    ann = Annotated.from_records(annotations, origin_of)
    pose = ann.pose if ann.pose is not None else qs.pose
    pose_from = f"annotation at {ann.pose_source}" if ann.pose is not None else ("[qc] pose" if qs.pose else "as modelled")
    mesh = load_mesh(stl)
    offset = (grid or {}).get("offset")
    if mesh is not None and offset and any(offset):
        # an engine that writes its mesh from the corner of its grid: put it where the program built the part,
        # for that is the frame the program's boxes, and the report's coordinates, are in
        import numpy as np
        from agentcad import meshprobe
        mesh = meshprobe.Mesh(mesh.path, mesh.tri + np.asarray(offset, dtype=float))
    pairs: List[Tuple[Finding, Any, Any]] = []     # (finding, part-frame point, the line across it or None)
    not_measured: Dict[str, str] = {}
    sampled: Dict[str, Any] = {}
    loosened, loose_findings = _loosened(ann, lim)
    if mesh is None:
        for rule in RULES:
            not_measured[rule] = "no mesh of the part to measure"
    else:
        part = posed(mesh, pose)
        tol = max(0.05, 1e-4 * float(part.diag), res or 0.0)       # a place on a coarse mesh is good to its resolution
        if qs.severity.get("build_volume", RULES["build_volume"]) == "off":
            not_measured["build_volume"] = "turned off in [qc] severity"
        else:
            pairs.append((check_build_volume(mesh.tri.reshape(-1, 3), printer, pose,
                                             qs.severity.get("build_volume", RULES["build_volume"])), None, None))
        in_force = limits_in_force(lim, ann)
        rules, noise, unreadable = WALL_RULES, 0.0, {}
        if res is not None:             # a coarse mesh is read for the rules it can show, with its resolution as the doubt
            rules, unreadable = readable_rules(res, in_force, grid)
            not_measured.update(unreadable)
            noise = res
        wall_limits = [v for rule in rules for v in in_force[rule]]
        if wall_limits:
            walls = measure_walls(part, max(wall_limits), layer)
            sampled["walls"] = {k: walls[k] for k in ("pitch_mm", "spacing_mm", "sections")}
            sampled["walls"]["layer_slivers"] = sum(r["kind"] == "layer_sliver" for r in walls["regions"])
            pairs += check_walls(walls, lim, qs, ann, pose, tol, rules, noise)
            floors = measure_floors(part, max(wall_limits))
            sampled["floors"] = {"spacing_mm": floors["spacing_mm"], "lines": floors["lines"],
                                 "thin_areas": len(floors["regions"])}
            pairs += check_floors(floors, lim, qs, ann, pose, tol, rules, noise)
        elif not unreadable:
            not_measured["min_wall"] = "no wall limit for this process"
        exclude = None
        if "max_bridge_mm" in lim or any("max_bridge_mm" in f.get("limits", {}) for f in ann.features):
            bridged = measure_bridges(part, layer)
            exclude = bridged["mask"]
            supports = bool((getattr(cfg, "print_intent", None) or {}).get("supports", False))
            found, sampled["bridges"] = check_bridges(bridged["bridges"], lim, qs, ann, pose, tol, supports)
            pairs += found
        if "max_overhang_deg" in lim:
            steepest = min([lim["max_overhang_deg"][0]] + [f["limits"]["max_overhang_deg"] for f in ann.features
                                                          if "max_overhang_deg" in f.get("limits", {})])
            pairs += check_overhang(measure_overhang(part, steepest, layer, exclude), lim, qs, ann, pose, tol)
        else:
            not_measured["max_overhang"] = "no overhang limit for this process (resin prints on supports)"
        kept, suppressed = _apply_suppressions(pairs, ann, tol)
    if mesh is None:
        kept, suppressed = [], []
    found = [f for f, *_ in kept]
    by_name = {f["name"]: f for f in ann.features}
    claimed = [{"finding": i, "feature": f.feature, "rule": f.rule, "kind": f.key, "at": point,
                "normal": normal,
                "threshold": Annotated.limit(by_name[f.feature], LIMIT_OF[f.rule], lim)[0],
                "knobs": list(by_name[f.feature].get("knobs", []))}
               for i, (f, point, normal) in enumerate(kept)
               if f.feature in by_name and f.rule in LIMIT_OF and point is not None
               and Annotated.limit(by_name[f.feature], LIMIT_OF[f.rule], lim) is not None]
    measured_limits = set(LIMIT_OF.values()) if mesh is not None else set()
    for key in lim:
        if key not in measured_limits:
            not_measured.setdefault(key, "no measurement for this rule yet")
    report = {"printer": printer.to_dict(), "pose": pose or {"up": [0, 0, 1], "spin_deg": 0}, "pose_from": pose_from,
              "gate": qs.gate, "limits": {k: {"value": v, "layer": layer_name} for k, (v, layer_name) in lim.items()},
              "sampled": sampled, "findings": [f.to_dict() for f in found + loose_findings],
              "annotations": {"features": [{"name": f["name"], "kind": f["kind"], "source": f["source"]} for f in ann.features],
                              "suppressions": len(ann.suppressions)},
              "suppressed": suppressed, "loosened": loosened, "claimed": claimed, "not_measured": not_measured}
    if res is not None:
        report["resolution"] = {"mm": res, **(dict(grid) if grid else {})}
    return report


# --- fixes by sensitivity: which knob moves a failing finding, and by how much ----------------------

#: At most this many rebuilds per ``sensitivity`` call (the base counts as one).
SENSITIVITY_RUNS = 16


def _build_mesh(source: Path, defines: Dict[str, str], out_dir: Path, n: int):
    """The program built with ``defines`` and tessellated for QC, or the error that stopped it."""
    from agentcad.fit import _b3d
    from agentcad.probe import load_shape
    try:
        shape = load_shape(source, defines)
        path = out_dir / f"run_{n}.stl"
        _b3d().export_stl(shape, str(path), tolerance=0.01, angular_tolerance=0.05)
        return load_mesh(path)
    except Exception as e:  # noqa: BLE001 - a knob value can break the program in any way; the error is the answer
        text = str(e).splitlines()[0][:160] if str(e) else ""
        return f"{type(e).__name__}: {text}" if text else type(e).__name__


def _quantity(claim: Dict[str, Any], mesh, pose, layer: float) -> Dict[str, Any]:
    """The claimed finding's measure on another build, at the same place: the width of a wall, the
    thickness of a floor, the worst angle of an overhang, the span of a bridge; ``clear`` when nothing
    near the place is within twice the limit (or, for an overhang, steeper than 20 degrees under it)."""
    import numpy as np
    if isinstance(mesh, str):
        return {"error": mesh}
    part = posed(mesh, pose)
    limit, kind = float(claim["threshold"]), claim["kind"]
    if kind == "wall":
        regions = [(r, r["width_mm"]) for r in measure_walls(part, 2.0 * limit, layer)["regions"] if r["kind"] == "wall"]
    elif kind == "floor":
        regions = [(r, r["thickness_mm"]) for r in measure_floors(part, 2.0 * limit)["regions"]]
    elif kind == "overhang":
        regions = [(r, r["worst_deg"]) for r in measure_overhang(part, max(0.0, limit - 20.0), layer)]
    elif kind == "bridge":
        regions = [(b, b["span_mm"]) for b in measure_bridges(part, layer)["bridges"]]
    else:
        return {"error": f"no measure for a {kind} finding"}
    reach = max(3.0 * limit, 2.0) if kind != "overhang" else max(5.0, float(part.diag) / 20.0)
    near = [(float(np.linalg.norm(np.subtract(_to_part_frame(r["at"], pose), claim["at"]))), q) for r, q in regions]
    near = [(d, q) for d, q in near if d <= reach]
    if not near:
        return _across(claim, part, pose, reach)
    nearest = float(min(near)[1])
    # Thin regions near the place can be the lips of an opening where the wall was (a bore grown through the
    # face): the line across the place itself tells a thinner wall from one that is gone. It is read as far as
    # the regions are found, so a wall a knob only moved sideways (further than the limit) is still on it.
    line = _line_across(claim, part, pose, reach)
    if line is not None and line[0] is None:
        return {"gone": True, "lips_mm": nearest}
    return {"value": nearest}


def _across(claim: Dict[str, Any], part, pose, reach: float) -> Dict[str, Any]:
    """A build with nothing thin near the claimed place: what the line the measure read across that place
    finds now (a wall's inward normal in the layer plane, the vertical through a floor). The material on it
    nearest the place, within ``reach``: ``clear`` with its length (``across_mm``) when there is some, ``gone``
    when there is none. An overhang or a bridge has no such line, and stays ``clear`` alone."""
    line = _line_across(claim, part, pose, reach)
    if line is None:
        return {"clear": True}
    return {"clear": True, "across_mm": line[1]} if line[0] is not None else {"gone": True}


def _line_across(claim: Dict[str, Any], part, pose, reach: float):
    """(gap, length) of the material on the line across the claimed place nearest to it, within ``reach``;
    (None, None) when there is none; None when the claim's kind has no such line (an overhang, a bridge, a
    wall without its normal)."""
    import numpy as np
    from agentcad.rays import MeshTarget, ray_intervals
    R = pose_rotation(pose)
    if claim["kind"] == "wall" and claim.get("normal"):
        d = R @ np.asarray(claim["normal"], dtype=float)
    elif claim["kind"] == "floor":
        d = np.array([0.0, 0.0, 1.0])
    else:
        return None
    d = d / np.linalg.norm(d)
    p = R @ np.asarray(claim["at"], dtype=float)
    span = float(part.diag) + 1.0                       # the whole part, so the material is never cut short
    rec = ray_intervals(MeshTarget(part), p - span * d, d, length=2.0 * span)
    best = None
    for iv in rec["intervals"]:
        if iv["kind"] == "material":
            gap = max(iv["entry"] - span, span - iv["exit"], 0.0)          # from the place to this material
            if gap <= reach and (best is None or gap < best[0]):
                best = (gap, float(iv["length"]))
    return best if best else (None, None)


def _effect(base: Dict[str, Any], side: Dict[str, Any]) -> Tuple[str, Optional[float]]:
    if "error" in side:
        return "refused", None
    state = lambda q: "gone" if "gone" in q else "clear" if "clear" in q else "value"      # noqa: E731
    if state(side) != "value" or state(base) != "value":
        return ("unchanged", None) if state(side) == state(base) else ("changed", None)
    change = side["value"] - base["value"]
    return ("changed" if abs(change) > 1e-3 else "unchanged"), change


def sensitivity(report: Dict[str, Any], source: Path, defines: Optional[Dict[str, str]] = None,
                max_runs: int = SENSITIVITY_RUNS, layer: float = 0.2) -> List[Dict[str, Any]]:
    """For each error a feature claims, the knobs the feature names, turned by +/- their delta: each
    rebuild is measured again for the finding's rule at the finding's place. Each knob is ``live``,
    ``saturated`` (only one direction moves it), ``dead`` or ``refused``; the finding's fix is
    rewritten to say what each knob does. Rebuilds stop at ``max_runs``, and the records say which
    knobs that left untried."""
    import tempfile
    from agentcad import knobs as knobmod
    from agentcad.engines.build123d_worker import _execute

    claims = [c for c in report.get("claimed", [])
              if c["knobs"] and report["findings"][c["finding"]]["severity"] == "error"]
    if not claims:
        return []
    source, defines = Path(source), dict(defines or {})
    build = _execute(str(source)).get("build")
    if not callable(build):
        raise ValueError(f"{source}: fixes need a parametric build(**params)")
    pose, out, cache = report["pose"], [], {}
    with tempfile.TemporaryDirectory() as tmp:
        def measured(overrides):
            key = tuple(sorted(overrides.items()))
            if key not in cache:
                cache[key] = _build_mesh(source, {**defines, **overrides}, Path(tmp), len(cache))
            return cache[key]

        measured({})
        for claim in claims:
            base = _quantity(claim, measured({}), pose, layer)
            rec = {"finding": claim["finding"], "feature": claim["feature"], "rule": claim["rule"], "kind": claim["kind"],
                   "threshold": claim["threshold"], "base": base, "knobs": []}
            for spec in claim["knobs"]:
                name, amount, relative = knobmod.parse_knob(spec)
                try:
                    value = knobmod._base_values(build, [name], defines)[name]
                except ValueError as e:
                    rec["knobs"].append({"name": name, "verdict": "refused", "error": str(e)})
                    continue
                delta = abs(value) * amount / 100.0 if relative else amount
                if isinstance(value, int):
                    delta = max(1, int(round(delta)))
                moves = {tag: value + sign * delta for tag, sign in (("plus", 1), ("minus", -1))}
                new = sum(1 for v in moves.values() if tuple(sorted({**{name: repr(v)}}.items())) not in cache)
                if len(cache) + new > max_runs:
                    rec["knobs"].append({"name": name, "verdict": "untried", "why": f"the {max_runs}-run budget is spent"})
                    continue
                sides = {tag: dict(_quantity(claim, measured({name: repr(v)}), pose, layer), knob=v)
                         for tag, v in moves.items()}
                effects = {tag: _effect(base, side) for tag, side in sides.items()}
                states = [s for s, _ in effects.values()]
                verdict = ("refused" if states.count("refused") == 2 else "partial" if "refused" in states
                           else "live" if states.count("changed") == 2 else "dead" if states.count("changed") == 0
                           else "saturated")
                rec["knobs"].append({"name": name, "base": value, "delta": delta, "verdict": verdict,
                                     "plus": dict(sides["plus"], change=effects["plus"][1]),
                                     "minus": dict(sides["minus"], change=effects["minus"][1])})
            out.append(rec)
            finding = report["findings"][claim["finding"]]
            finding["fix"] = _fix_sentence(rec, finding.get("fix", ""))
            finding["sentence"] = Finding.from_dict(finding).sentence()
    return out


def _fix_sentence(rec: Dict[str, Any], before: str) -> str:
    unit = "deg" if rec["rule"] == "max_overhang" else "mm"
    passes = (lambda v: v <= rec["threshold"]) if rec["rule"].startswith("max_") else (lambda v: v >= rec["threshold"])

    def side(tag, k):
        s = k[tag]
        head = f"{k['name']} {'+' if tag == 'plus' else '-'}{k['delta']:g}"
        if "error" in s:
            return f"{head} does not build"
        if "gone" in s:
            lips = f"; lips of {s['lips_mm']:.3f} mm remain near it" if "lips_mm" in s else ""
            return f"{head} leaves no material across the place: the material there is gone (a failure, not a fix){lips}"
        if "clear" in s:
            what = "no face steeper than 20 deg under the limit" if unit == "deg" else \
                f"no {rec.get('kind', 'feature')} under {2 * rec['threshold']:g} mm"
            if "across_mm" not in s:
                return f"{head} leaves {what} near it (cleared, or the material there is gone: look)"
            across = f"{s['across_mm']:.3f} mm across the place"
            return (f"{head} leaves {what} near it: cleared ({across})" if passes(s["across_mm"])
                    else f"{head} leaves {what} near it, and {across}, under the limit: look")
        verdict = " (passes)" if passes(s["value"]) else ""
        return f"{head} gives {s['value']:.3f} {unit}" + (f" ({s['change']:+.3f})" if s.get("change") is not None else "") + verdict

    parts = []
    for k in rec["knobs"]:
        if k["verdict"] in ("live", "saturated", "partial"):
            parts.append(", ".join(side(t, k) for t in ("plus", "minus")) +
                         (" (it moves only one way)" if k["verdict"] == "saturated" else ""))
        elif k["verdict"] == "dead":
            parts.append(f"{k['name']} moves nothing here")
        elif k["verdict"] == "untried":
            parts.append(f"{k['name']} not tried ({k['why']})")
        else:
            parts.append(f"{k['name']} could not be turned ({k.get('error', 'neither side builds')})")
    base = rec["base"]
    now = f"at {base['value']:.3f} {unit}" if "value" in base else "here"
    return f"{before}; measured {now}: " + "; ".join(parts) if parts else before


def errors(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [f for f in report.get("findings", []) if f.get("severity") == "error"]
