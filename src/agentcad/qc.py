"""QC: design rules judged before a print, as findings.

A rule's limit comes from layers: the printer's process defaults (``agentcad.printers``), then
the project's ``[qc]`` table; a feature's own annotation will be the third. Every finding names
the layer that set its limit. A rule with a limit but no measurement yet is listed as not
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
  counted in the report but not judged. Until a feature annotation names it, a wall finding is
  unattributed and never more than a warning.
* ``max_overhang``: faces turned down further than ``max_overhang_deg`` from vertical, the face
  on the bed (within one layer of the lowest point) excepted, grouped into regions that share a
  vertex.
"""

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from agentcad import printers
from agentcad.findings import Finding

#: Rules QC measures, with their default severity.
RULES = {"build_volume": "error", "min_feature": "error", "min_wall": "warning", "max_overhang": "warning"}
#: The limit each measured rule reads.
LIMIT_OF = {"min_feature": "min_feature_mm", "min_wall": "min_wall_mm", "max_overhang": "max_overhang_deg"}
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
    ``spin_deg`` about z."""
    import numpy as np
    pose = pose or {}
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


def in_layer_widths(polys, spacing: float, corner: float = 0.0):
    """Points along every edge of a section (at most ``spacing`` apart) and, for each, the distance
    along the inward normal to the boundary across the material: the material's width there.

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
        return np.zeros((0, 2)), np.zeros(0)
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
    return P, np.where(hit, dist, np.inf).min(axis=1)


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
        P, W = in_layer_widths(polys, spacing, corner=limit)
        keep = W < limit
        thin.extend((p[0], p[1], float(z), float(w)) for p, w in zip(P[keep], W[keep]))
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

def measure_overhang(mesh, limit_deg: float, first_layer: float = 0.2) -> List[Dict[str, Any]]:
    """Regions of faces turned down further than ``limit_deg`` from vertical (the face on the bed
    excepted), joined where they share a vertex: area, worst angle and where."""
    import numpy as np
    tri = mesh.tri
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]) * mesh.orient
    area2 = np.linalg.norm(n, axis=1)
    ok = area2 > 1e-12
    down = np.zeros(len(tri))
    down[ok] = -n[ok, 2] / area2[ok]                       # 1 for a face looking straight down
    angle = np.degrees(np.arcsin(np.clip(down, -1.0, 1.0)))   # from vertical: 0 a wall, 90 a ceiling
    centroid_z = tri[:, :, 2].mean(axis=1)
    flagged = np.nonzero(ok & (angle > limit_deg + 1e-6) & (centroid_z > float(mesh.lo[2]) + first_layer))[0]
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


# --- judging --------------------------------------------------------------------------------------

def _to_part_frame(point, pose):
    import numpy as np
    return [float(v) for v in pose_rotation(pose).T @ np.asarray(point, dtype=float)]


def _fmt_point(p):
    return "(" + ", ".join(f"{v:.2f}" for v in p) + ")"


def check_walls(walls: Dict[str, Any], lim: Dict[str, Tuple[float, str]], qs: QCSettings) -> List[Finding]:
    """A finding per thin region: an error under the minimum feature, a warning under the minimum wall."""
    out = []
    feature = lim.get("min_feature_mm")
    for r in walls["regions"]:
        if r.get("kind") != "wall":
            continue                    # thin only where a layer cuts a sloped edge: counted, not judged
        w = r["width_mm"]
        is_feature = feature is not None and w < feature[0]
        rule = "min_feature" if is_feature else "min_wall"
        value, layer = feature if is_feature else lim["min_wall_mm"]
        severity = qs.severity.get(rule, RULES[rule])
        if severity == "off":
            continue
        if severity == "error":
            severity = "warning"        # unattributed: no feature annotation names it, so never an error
        where = _fmt_point(_to_part_frame(r["at"], qs.pose))
        z0, z1 = r["z_range"]
        what = "narrower than the smallest feature it can print" if is_feature else "thinner than a wall should be"
        out.append(Finding(
            "wall", severity, f"{w:.3f} mm", f"at least {value:g} mm", "material narrower than the limit prints "
            "weak, as a seam, or not at all", "[qc]", rule=rule, layer=layer,
            location=f"{where} in the part's frame", uncertainty=0.0,
            fix="thicken the wall there, or move the feature that thins it",
            message=(f"a wall {w:.3f} mm wide in its layer at {where} (part frame) is {what} ({value:g} mm); "
                     f"it runs over {r['layers']} layer(s), z {z0:.2f} to {z1:.2f} in the print pose, "
                     f"{r['depth_min_mm']:.3f} mm of material through the part at its thinnest "
                     f"(median {r['depth_mm']:.3f})")))
    return out


def check_overhang(regions: List[Dict[str, Any]], lim: Dict[str, Tuple[float, str]], qs: QCSettings) -> List[Finding]:
    value, layer = lim["max_overhang_deg"]
    severity = qs.severity.get("max_overhang", RULES["max_overhang"])
    if severity == "off":
        return []
    out = []
    for r in regions:
        where = _fmt_point(_to_part_frame(r["at"], qs.pose))
        out.append(Finding(
            "overhang", severity, f"{r['area_mm2']:.0f} mm2 at up to {r['worst_deg']:.0f} deg from vertical",
            f"faces at most {value:g} deg from vertical", "a face turned further down prints in air unless it is "
            "supported", "[qc]", rule="max_overhang", layer=layer, location=f"{where} in the part's frame",
            uncertainty=0.0, fix="re-pose the part, add a chamfer under the ledge, or plan supports there",
            message=(f"{r['area_mm2']:.0f} mm2 of faces turned down up to {r['worst_deg']:.0f} deg from vertical "
                     f"around {where} (part frame), past the {value:g} deg limit")))
    return out


def run(cfg, stl: Optional[Path], qs: QCSettings, printer_override: Optional[str] = None) -> Dict[str, Any]:
    """Judge one part's mesh (an STL): the printer, every limit with its layer, the findings, what
    each measurement sampled, and the rules not measured (with why)."""
    printer = printer_for(cfg, qs, printer_override)
    lim = limits(printer, qs)
    layer = float(getattr(getattr(cfg, "print", None), "layer_height", 0.2) or 0.2)
    mesh = load_mesh(stl)
    found: List[Finding] = []
    not_measured: Dict[str, str] = {}
    sampled: Dict[str, Any] = {}
    if mesh is None:
        for rule in RULES:
            not_measured[rule] = "no mesh of the part to measure"
    else:
        part = posed(mesh, qs.pose)
        if qs.severity.get("build_volume", RULES["build_volume"]) == "off":
            not_measured["build_volume"] = "turned off in [qc] severity"
        else:
            found.append(check_build_volume(mesh.tri.reshape(-1, 3), printer, qs.pose,
                                            qs.severity.get("build_volume", RULES["build_volume"])))
        wall_limits = [lim[k][0] for k in ("min_feature_mm", "min_wall_mm") if k in lim]
        if wall_limits:
            walls = measure_walls(part, max(wall_limits), layer)
            sampled["walls"] = {k: walls[k] for k in ("pitch_mm", "spacing_mm", "sections")}
            sampled["walls"]["layer_slivers"] = sum(r["kind"] == "layer_sliver" for r in walls["regions"])
            found += check_walls(walls, lim, qs)
        else:
            not_measured["min_wall"] = "no wall limit for this process"
        if "max_overhang_deg" in lim:
            found += check_overhang(measure_overhang(part, lim["max_overhang_deg"][0], layer), lim, qs)
        else:
            not_measured["max_overhang"] = "no overhang limit for this process (resin prints on supports)"
    measured_limits = set(LIMIT_OF.values()) if mesh is not None else set()
    for key in lim:
        if key not in measured_limits:
            not_measured.setdefault(key, "no measurement for this rule yet")
    return {"printer": printer.to_dict(), "pose": qs.pose or {"up": [0, 0, 1], "spin_deg": 0}, "gate": qs.gate,
            "limits": {k: {"value": v, "layer": layer_name} for k, (v, layer_name) in lim.items()},
            "sampled": sampled, "findings": [f.to_dict() for f in found], "not_measured": not_measured}


def errors(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [f for f in report.get("findings", []) if f.get("severity") == "error"]
