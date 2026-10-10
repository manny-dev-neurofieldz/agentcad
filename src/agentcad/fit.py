"""Fit: pose two parts and measure whether they mate.

A mate stated in one program is a hypothesis; only a check with both bodies
tests it. ``fit`` loads two exact shapes (STEP or build123d sources, each
with its own defines), poses the second by an optional transform, and
reports:

* ``interference_mm3``: the volume of their intersection (zero is the only
  passing value for parts that must not touch);
* ``clearance_mm``: the minimum distance between the bodies (line-to-line
  mates read 0.000 here while every single-part instrument passes);
* per named window, the minimum distance between the two surfaces inside
  an axis-aligned box, so a key tip and a flange are read separately;
* an insertion sweep along an axis: the interference at each step of the
  second body sliding in, so a part that binds on the way in is seen.

Declared mates come from a ``[mates]`` table in the project's
``agentcad.toml`` (name -> window box and optional nominal clearance);
``--map`` gives the pose when no declaration exists. Renders through the
build123d engine's camera presets show the pair assembled and exploded.
"""

import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


def _b3d():
    from agentcad.engines.build123d_worker import _bootstrap
    return _bootstrap()


def pose(shape, offset: Sequence[float] = (0, 0, 0), spin_deg: float = 0.0, axis: str = "z"):
    """The shape moved by ``offset`` after a rotation of ``spin_deg`` about ``axis``."""
    b3d = _b3d()
    rot = {"x": (spin_deg, 0, 0), "y": (0, spin_deg, 0), "z": (0, 0, spin_deg)}[axis.lower()]
    return b3d.Pos(*offset) * (b3d.Rot(*rot) * shape)


def pose_matrix(shape, matrix: Sequence[Sequence[float]]):
    """The shape moved by a row-major 4x4 rigid transform (``agentcad.mates.pose_from_datums``)."""
    b3d = _b3d()
    from OCP.gp import gp_Trsf
    trsf = gp_Trsf()
    trsf.SetValues(*[float(matrix[i][j]) for i in range(3) for j in range(4)])
    return b3d.Location(trsf) * shape


def interference(a, b) -> float:
    try:
        common = a & b
        return float(common.volume) if common is not None else 0.0
    except Exception as e:  # a failed boolean is reported, never read as zero
        print(f"agentcad fit: intersection failed ({e}); interference unknown", file=sys.stderr)
        return float("nan")


def clearance(a, b) -> float:
    try:
        return float(a.distance_to(b))
    except Exception as e:
        print(f"agentcad fit: distance failed ({e})", file=sys.stderr)
        return float("nan")


def _lattice(shape, tol: float, step: Optional[float] = None):
    """Points ON the surface, not just its tessellation vertices, with the triangle each lies on.

    A planar face tessellates to a few large triangles whose vertices sit at its corners, so a
    window in the middle of a flat lip would see no points at all and a nearest-vertex distance
    overstates the true gap. Every triangle is covered by a barycentric lattice whose spacing is
    ``step`` (default: the tessellation tolerance times 20), so flat faces are sampled as densely
    as curved ones.

    Returns (points, triangle index per point, vertices, triangles, spacing), where ``spacing``
    bounds the distance from any point of a triangle to the nearest lattice point on it.
    """
    import numpy as np
    verts, tris = shape.tessellate(tolerance=tol, angular_tolerance=0.1)
    V = np.array([[v.X, v.Y, v.Z] for v in verts], dtype=float).reshape(-1, 3)
    T = np.array(tris, dtype=int).reshape(-1, 3)
    if len(T) == 0:
        return V, np.zeros(len(V), dtype=int), V, T, 0.0
    step = step or tol * 20.0
    A, B, C = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    longest = np.maximum.reduce([np.linalg.norm(B - A, axis=1), np.linalg.norm(C - B, axis=1), np.linalg.norm(A - C, axis=1)])
    n_per = np.clip(np.ceil(longest / step).astype(int), 1, 64)
    points, owners = [], []
    for n in np.unique(n_per):
        sel = np.nonzero(n_per == n)[0]
        i, j = np.meshgrid(np.arange(n + 1), np.arange(n + 1), indexing="ij")
        keep = (i + j) <= n
        u, v = i[keep] / n, j[keep] / n           # barycentric lattice on each selected triangle
        w = 1.0 - u - v
        pts = (w[None, :, None] * A[sel][:, None, :] + u[None, :, None] * B[sel][:, None, :] + v[None, :, None] * C[sel][:, None, :])
        points.append(pts.reshape(-1, 3))
        owners.append(np.repeat(sel, len(u)))
    return np.concatenate(points), np.concatenate(owners), V, T, float((longest / n_per).max())


def _points(shape, tol: float, step: Optional[float] = None):
    """The surface lattice of :func:`_lattice`, points only."""
    return _lattice(shape, tol, step)[0]


def _closest_on_triangles(P, A, B, C):
    """The closest point of triangle (A[k], B[k], C[k]) to P[k], row by row (Voronoi regions of
    the triangle, as in Ericson's Real-Time Collision Detection, 5.1.5)."""
    import numpy as np
    ab, ac = B - A, C - A
    ap, bp, cp = P - A, P - B, P - C
    d1, d2 = (ab * ap).sum(1), (ac * ap).sum(1)
    d3, d4 = (ab * bp).sum(1), (ac * bp).sum(1)
    d5, d6 = (ab * cp).sum(1), (ac * cp).sum(1)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
    with np.errstate(divide="ignore", invalid="ignore"):
        denom = va + vb + vc
        Q = A + ab * (vb / denom)[:, None] + ac * (vc / denom)[:, None]              # inside the face
        regions = (  # later entries take precedence, so the order is Ericson's tests in reverse
            ((va <= 0) & (d4 - d3 >= 0) & (d5 - d6 >= 0), B + (C - B) * ((d4 - d3) / ((d4 - d3) + (d5 - d6)))[:, None]),
            ((vb <= 0) & (d2 >= 0) & (d6 <= 0), A + ac * (d2 / (d2 - d6))[:, None]),
            ((d6 >= 0) & (d5 <= d6), C),
            ((vc <= 0) & (d1 >= 0) & (d3 <= 0), A + ab * (d1 / (d1 - d3))[:, None]),
            ((d3 >= 0) & (d4 <= d3), B),
            ((d1 <= 0) & (d2 <= 0), A),
        )
        for mask, point in regions:
            Q[mask] = point[mask]
    bad = ~np.isfinite(Q).all(axis=1)          # a degenerate triangle: its nearest corner
    if bad.any():
        corners = np.stack([A[bad], B[bad], C[bad]], axis=1)
        nearest = np.linalg.norm(corners - P[bad][:, None, :], axis=2).argmin(axis=1)
        Q[bad] = corners[np.arange(len(corners)), nearest]
    return Q


def _surface_distances(P, lattice, tree=None):
    """Distance from each point to the tessellated surface of ``lattice`` (exact to the tessellation,
    not to the lattice's sample points). The nearest lattice point bounds each distance from above;
    every triangle with a lattice point within that bound plus the lattice spacing is tested, which
    includes the triangle holding the closest point."""
    import numpy as np
    from scipy.spatial import cKDTree
    pts, owners, V, T, spacing = lattice
    if len(P) == 0 or len(T) == 0:
        return np.full(len(P), np.inf)
    tree = tree if tree is not None else cKDTree(pts)
    upper = tree.query(P)[0]
    near = tree.query_ball_point(P, upper + spacing + 1e-9)
    counts = np.fromiter((len(n) for n in near), dtype=np.int64, count=len(near))
    pair_point = np.repeat(np.arange(len(P), dtype=np.int64), counts)
    pair_tri = owners[np.concatenate([np.asarray(n, dtype=np.int64) for n in near])]
    key = np.unique(pair_point * len(T) + pair_tri)
    pair_point, pair_tri = key // len(T), key % len(T)
    tri = T[pair_tri]
    Q = _closest_on_triangles(P[pair_point], V[tri[:, 0]], V[tri[:, 1]], V[tri[:, 2]])
    out = upper.copy()
    np.minimum.at(out, pair_point, np.linalg.norm(Q - P[pair_point], axis=1))
    return out


def window_clearances(a, b, windows: Dict[str, Sequence[float]], tol: Optional[float] = None,
                      step: Optional[float] = None) -> Dict[str, Any]:
    """Minimum surface-to-surface distance inside each window box (x0,y0,z0,x1,y1,z1), both ways.

    ``tol`` is the tessellation tolerance (default: A's diagonal / 2000) and ``step`` the lattice
    spacing (default: 20 times ``tol``)."""
    import numpy as np
    from scipy.spatial import cKDTree

    bb = a.bounding_box()
    diag = math.sqrt(bb.size.X ** 2 + bb.size.Y ** 2 + bb.size.Z ** 2)
    tol = tol or diag / 2000.0
    A, B = _points(a, tol, step), _points(b, tol, step)   # surface lattices, both bodies
    out: Dict[str, Any] = {}
    for name, box in windows.items():
        lo, hi = np.array(box[:3], dtype=float), np.array(box[3:], dtype=float)
        ia = A[np.all((A >= lo) & (A <= hi), axis=1)]
        ib = B[np.all((B >= lo) & (B <= hi), axis=1)]
        if len(ia) == 0 or len(ib) == 0:
            out[name] = {"note": "one side has no surface in this window", "n_a": int(len(ia)), "n_b": int(len(ib))}
            continue
        d_ab = cKDTree(ib).query(ia)[0]
        d_ba = cKDTree(ia).query(ib)[0]
        out[name] = {"min_mm": float(min(d_ab.min(), d_ba.min())), "p05_mm": float(np.percentile(np.concatenate([d_ab, d_ba]), 5)),
                     "n_a": int(len(ia)), "n_b": int(len(ib))}
    return out


def contacts(a, b, threshold: float = 0.05, tol: Optional[float] = None, step: Optional[float] = None,
             link_mm: Optional[float] = None) -> List[Dict[str, Any]]:
    """Where the two bodies come within ``threshold`` of each other.

    The points of A's surface lattice whose distance to B's surface (exact to B's tessellation) is
    at most ``threshold``, joined into regions: points closer than ``link_mm`` (default: twice A's
    lattice spacing) belong to one region. Each region gives its centroid, bounding box, smallest
    distance and point count, largest first. Overlapping volume is ``interference``'s question;
    this one answers where the surfaces meet."""
    import numpy as np
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree

    bb = a.bounding_box()
    diag = math.sqrt(bb.size.X ** 2 + bb.size.Y ** 2 + bb.size.Z ** 2)
    tol = tol or diag / 2000.0
    pts_a, _, _, _, spacing_a = _lattice(a, tol, step)
    lat_b = _lattice(b, tol, step)
    tree_b = cKDTree(lat_b[0])
    # the nearest lattice point of B is at most `spacing` farther than B's surface: prune with it
    candidates = pts_a[tree_b.query(pts_a)[0] <= threshold + lat_b[4]]
    dist = _surface_distances(candidates, lat_b, tree_b)
    close, dist = candidates[dist <= threshold], dist[dist <= threshold]
    if len(close) == 0:
        return []
    link = link_mm or 2.0 * max(spacing_a, 1e-6)
    pairs = cKDTree(close).query_pairs(link, output_type="ndarray")
    graph = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(len(close), len(close)))
    n_regions, label = connected_components(graph, directed=False)
    out = []
    for k in range(n_regions):
        pts, d = close[label == k], dist[label == k]
        out.append({"centroid": [float(v) for v in pts.mean(axis=0)], "min": [float(v) for v in pts.min(axis=0)],
                    "max": [float(v) for v in pts.max(axis=0)], "min_mm": float(d.min()), "points": int(len(pts))})
    return sorted(out, key=lambda r: -r["points"])


DEFAULT_TOL_MM = 0.05


def judge_windows(results: Dict[str, Any], nominals: Dict[str, Sequence[Optional[float]]]) -> Dict[str, Dict[str, Any]]:
    """A verdict per declared window: ``fail`` when the measured clearance is below the nominal by
    more than the tolerance, ``pass`` otherwise, ``unmeasured`` when the window could not be measured
    (never a silent pass). ``nominals`` maps a window to (nominal_mm, tol_mm or None)."""
    verdicts: Dict[str, Dict[str, Any]] = {}
    for name, (nominal, tol) in nominals.items():
        if nominal is None:
            continue
        tol = DEFAULT_TOL_MM if tol is None else float(tol)
        measured = (results.get(name) or {}).get("min_mm")
        if measured is None:
            verdicts[name] = {"verdict": "unmeasured", "nominal_mm": nominal, "tol_mm": tol}
            continue
        ok = measured >= float(nominal) - tol
        verdicts[name] = {"verdict": "pass" if ok else "fail", "nominal_mm": float(nominal), "tol_mm": tol,
                          "min_mm": measured}
    return verdicts


def insertion_sweep(a, b, axis: str = "z", travel: float = 10.0, steps: int = 10) -> List[Dict[str, float]]:
    """Interference of ``b`` at each step as it slides ``travel`` along ``axis`` into place (from out to in)."""
    b3d = _b3d()
    unit = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}[axis.lower()]
    rows = []
    for i in range(steps, -1, -1):
        s = travel * i / steps
        moved = b3d.Pos(unit[0] * s, unit[1] * s, unit[2] * s) * b
        rows.append({"offset_mm": s, "interference_mm3": interference(a, moved)})
    return rows


def _assembly_frame(source: Path, defines):
    """A build123d program whose build() takes print_orient gets it False unless the caller set it:
    parts are compared in the assembly frame, not oriented for a print bed."""
    import inspect
    defines = dict(defines or {})
    if Path(source).suffix.lower() == ".py" and "print_orient" not in defines:
        try:
            from agentcad.engines.build123d_worker import _execute
            build = _execute(str(Path(source).resolve())).get("build")
            if callable(build) and "print_orient" in inspect.signature(build).parameters:
                defines["print_orient"] = "false"
        except Exception as e:  # a source that will not import fails later, with its own message
            print(f"agentcad fit: could not inspect {source} for print_orient ({e})", file=sys.stderr)
    return defines


def fit(a_source: Path, b_source: Path, *, a_defines=None, b_defines=None,
        offset=(0, 0, 0), spin_deg=0.0, spin_axis="z", transform: Optional[Sequence[Sequence[float]]] = None,
        windows: Optional[Dict[str, Sequence[float]]] = None,
        sweep_axis: Optional[str] = None, sweep_travel: float = 10.0, sweep_steps: int = 10,
        sample_step: Optional[float] = None, contact_mm: Optional[float] = 0.05,
        out_dir: Optional[Path] = None, frame: Optional[Sequence[Sequence[float]]] = None) -> Dict[str, Any]:
    from agentcad.probe import load_shape

    a_defines, b_defines = _assembly_frame(a_source, a_defines), _assembly_frame(b_source, b_defines)
    a = load_shape(Path(a_source), a_defines)
    b_shape = load_shape(Path(b_source), b_defines)
    b = pose_matrix(b_shape, transform) if transform is not None else pose(b_shape, offset, spin_deg, spin_axis)
    result: Dict[str, Any] = {
        "a": str(a_source), "b": str(b_source),
        "a_defines": dict(a_defines or {}), "b_defines": dict(b_defines or {}),
        "pose": ({"transform": [list(map(float, r)) for r in transform]} if transform is not None
                 else {"offset": list(offset), "spin_deg": spin_deg, "spin_axis": spin_axis}),
        "interference_mm3": interference(a, b),
        "clearance_mm": clearance(a, b),
    }
    if windows:
        try:
            result["windows"] = window_clearances(a, b, windows, step=sample_step)
        except ImportError as e:
            result["windows_error"] = f"scipy unavailable: {e}"
    if contact_mm is not None:
        try:
            result["contact_mm"] = float(contact_mm)
            result["contacts"] = contacts(a, b, threshold=contact_mm, step=sample_step)
        except ImportError as e:
            result["contacts_error"] = f"scipy unavailable: {e}"
    if sweep_axis:
        result["insertion"] = insertion_sweep(a, b, sweep_axis, sweep_travel, steps=sweep_steps)
    if out_dir is not None:
        result["renders"] = _render_pair(a, b, Path(out_dir))
        result["renders"].update(render_cut(a, b, Path(out_dir), frame))
    return result


PENETRATION_RGB = (224, 0, 0)       # the colour that marks overlapping material in every cut view
_A_RGB, _B_RGB = (190, 198, 210), (74, 123, 208)


def cut_frame(b, frame: Optional[Sequence[Sequence[float]]] = None):
    """(origin, x, axis) unit vectors for the cut views: the mate's own frame when one is known
    (A's axis point and direction, and its key line), else B's bounding-box centre with z as the
    axis and x across it."""
    import numpy as np
    if frame is not None:
        o, x, z = (np.array(v, dtype=float) for v in frame)
    else:
        c = b.bounding_box().center()
        o, x, z = np.array([c.X, c.Y, c.Z]), np.array([1.0, 0, 0]), np.array([0, 0, 1.0])
    z = z / np.linalg.norm(z)
    x = x - np.dot(x, z) * z
    if np.linalg.norm(x) < 1e-9:
        x = np.cross([0.0, 1.0, 0.0] if abs(z[0]) > 0.9 else [1.0, 0.0, 0.0], z)
    x = x / np.linalg.norm(x)
    return o, x, z


def _section_triangles(shape, b3d, origin, normal, x_dir, tol):
    """Triangles of the faces where a plane cuts ``shape`` (empty when it misses)."""
    import numpy as np
    plane = b3d.Plane(origin=tuple(origin), x_dir=tuple(x_dir), z_dir=tuple(normal))
    try:
        cut = b3d.section(shape, section_by=plane)
        faces = list(cut.faces()) if cut is not None else []
    except Exception:
        faces = []
    tris = []
    for f in faces:
        verts, idx = f.tessellate(tolerance=tol, angular_tolerance=0.2)
        V = np.array([[v.X, v.Y, v.Z] for v in verts], dtype=float)
        tris.extend(V[list(t)] for t in idx)
    return tris


def render_cut(a, b, out_dir: Path, frame: Optional[Sequence[Sequence[float]]] = None) -> Dict[str, str]:
    """A cutaway of the pair through the mate's axis and two section overlays in the planes that
    contain the axis; overlapping material is filled in PENETRATION_RGB in all three."""
    try:
        import numpy as np
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.collections import PolyCollection
    except ImportError as e:
        print(f"agentcad fit: cut views skipped ({e})", file=sys.stderr)
        return {}
    b3d = _b3d()
    out_dir.mkdir(parents=True, exist_ok=True)
    o, x, z = cut_frame(b, frame)
    y = np.cross(z, x)
    bb = (a + b).bounding_box()
    diag = math.sqrt(bb.size.X ** 2 + bb.size.Y ** 2 + bb.size.Z ** 2)
    tol = max(diag / 1500.0, 1e-4)
    try:
        common = a & b
        overlap = common if common is not None and float(common.volume) > 1e-9 else None
    except Exception:
        overlap = None
    renders: Dict[str, str] = {}
    hex_of = lambda rgb: "#%02x%02x%02x" % rgb
    for name, normal, across in (("section_1", y, x), ("section_2", x, y)):
        fig, ax = plt.subplots(figsize=(6, 6))
        for shape, rgb, alpha in ((a, _A_RGB, 1.0), (b, _B_RGB, 0.75), (overlap, PENETRATION_RGB, 1.0)):
            if shape is None:
                continue
            tris = _section_triangles(shape, b3d, o, normal, across, tol)
            uv = [np.stack([(t - o) @ across, (t - o) @ z], axis=1) for t in tris]
            if uv:   # edges in the face colour close the hairline seams between triangles
                ax.add_collection(PolyCollection(uv, facecolors=hex_of(rgb), edgecolors=hex_of(rgb),
                                                 linewidths=0.4, alpha=alpha))
        ax.autoscale(); ax.set_aspect("equal")
        ax.set_xlabel("across the axis (mm)"); ax.set_ylabel("along the axis (mm)")
        ax.set_title(f"{name}: part A grey, part B blue, overlap red")
        path = out_dir / f"fit_{name}.png"
        fig.savefig(path, dpi=110); plt.close(fig)
        renders[name] = str(path)
    try:
        import pyvista as pv
    except ImportError as e:
        print(f"agentcad fit: cutaway skipped (pyvista unavailable: {e})", file=sys.stderr)
        return renders
    pv.OFF_SCREEN = True
    size = 4.0 * diag
    keep = b3d.Location(b3d.Plane(origin=tuple(o), x_dir=tuple(x), z_dir=tuple(y))) * b3d.Pos(0, 0, -size / 2) \
        * b3d.Box(size, size, size)      # the half-space behind the cut plane: what stays

    def mesh_of(shape):
        verts, idx = shape.tessellate(tolerance=tol, angular_tolerance=0.1)
        V = np.array([[v.X, v.Y, v.Z] for v in verts]); F = np.array(idx)
        return pv.PolyData(V, np.hstack([np.full((len(F), 1), 3), F]).ravel()) if len(F) else None

    plotter = pv.Plotter(off_screen=True, window_size=[900, 900])
    plotter.set_background("white")
    for shape, rgb, opacity in ((a, _A_RGB, 1.0), (b, _B_RGB, 0.9), (overlap, PENETRATION_RGB, 1.0)):
        if shape is None:
            continue
        try:
            half = shape & keep
            mesh = mesh_of(half) if half is not None else None
        except Exception:
            mesh = None
        if mesh is not None:
            if rgb == PENETRATION_RGB:
                # its cut face is coplanar with both parts' cut faces: nudge it toward the camera so
                # the depth test shows it instead of hiding it behind them
                mesh = mesh.translate(tuple(y * diag * 0.003), inplace=False)
            plotter.add_mesh(mesh, color=hex_of(rgb), opacity=opacity, smooth_shading=False,
                             lighting=rgb != PENETRATION_RGB)      # the mark is flat colour, never shaded
    eye = o + y * diag * 1.6 + z * diag * 0.35 + x * diag * 0.35
    plotter.camera_position = [tuple(eye), tuple(o), tuple(z)]
    path = out_dir / "fit_cutaway.png"
    plotter.screenshot(str(path)); plotter.close()
    renders["cutaway"] = str(path)
    return renders


def _render_pair(a, b, out_dir: Path) -> Dict[str, str]:
    """Assembled and exploded views of the pair through PyVista (best effort)."""
    try:
        import numpy as np
        import pyvista as pv
    except ImportError as e:
        print(f"agentcad fit: renders skipped (pyvista unavailable: {e})", file=sys.stderr)
        return {}
    b3d = _b3d()
    out_dir.mkdir(parents=True, exist_ok=True)
    pv.OFF_SCREEN = True

    def mesh_of(shape):
        bb = shape.bounding_box()
        tol = max(math.sqrt(bb.size.X ** 2 + bb.size.Y ** 2 + bb.size.Z ** 2) / 1000.0, 1e-4)
        verts, tris = shape.tessellate(tolerance=tol, angular_tolerance=0.1)
        V = np.array([[v.X, v.Y, v.Z] for v in verts]); F = np.array(tris)
        return pv.PolyData(V, np.hstack([np.full((len(F), 1), 3), F]).ravel())

    renders = {}
    bb = (a + b).bounding_box() if True else a.bounding_box()
    explode = max(bb.size.X, bb.size.Y, bb.size.Z) * 0.6
    for name, shift in (("assembled", 0.0), ("exploded", explode)):
        plotter = pv.Plotter(off_screen=True, window_size=[900, 900])
        plotter.set_background("white")
        plotter.add_mesh(mesh_of(a), color="#cfd8e3", smooth_shading=True, specular=0.15)
        plotter.add_mesh(mesh_of(b3d.Pos(0, 0, shift) * b), color="#e94560", smooth_shading=True, specular=0.15, opacity=0.85)
        plotter.camera_position = "iso"
        plotter.reset_camera()
        path = out_dir / f"fit_{name}.png"
        plotter.screenshot(str(path)); plotter.close()
        renders[name] = str(path)
    return renders


def parameter_snapshot(source: Path, defines=None) -> Dict[str, Any]:
    """What a fit was measured against: the source file's SHA-256 and, for a program with
    ``build()``, every parameter's value (its defaults with the defines applied). A later fit
    record, or a duty that asks whether a mate changed since its last fit, compares these."""
    import hashlib
    import inspect
    source = Path(source)
    snap: Dict[str, Any] = {"source": str(source)}
    try:
        snap["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    except OSError as e:
        snap["sha256_error"] = str(e)
    if source.suffix.lower() == ".py":
        try:
            from agentcad.engines.build123d_worker import _execute
            from agentcad.params import coerce_defines
            build = _execute(str(source.resolve())).get("build")
            if callable(build):
                params = {k: p.default for k, p in inspect.signature(build).parameters.items()
                          if p.default is not inspect.Parameter.empty}
                params.update(coerce_defines(defines, build))
                snap["params"] = {k: v for k, v in params.items() if isinstance(v, (bool, int, float, str)) or v is None}
        except Exception as e:  # a snapshot that cannot read the program says so; the fit still stands
            snap["params_error"] = f"{type(e).__name__}: {e}"
    return snap


def overall_verdict(res: Dict[str, Any], allow_mm3: float = 0.0) -> str:
    """One word for a fit: ``fail`` (overlap beyond ``allow_mm3`` or a window below nominal),
    ``unmeasured`` (a declared window read nothing), ``pass`` (every declared nominal met) or
    ``measured`` (numbers recorded, no nominal declared to judge them by)."""
    interference = res.get("interference_mm3")
    if interference is not None and interference == interference and interference > allow_mm3:
        return "fail"
    verdicts = [v["verdict"] for v in (res.get("verdicts") or {}).values()]
    if "fail" in verdicts:
        return "fail"
    if "unmeasured" in verdicts:
        return "unmeasured"
    return "pass" if verdicts else "measured"


def fit_record(res: Dict[str, Any], mate: Optional[str] = None, allow_mm3: float = 0.0) -> Dict[str, Any]:
    """The record a fit leaves in each part's manifest: when, what was measured (both sources'
    parameter snapshots), the pose, the numbers, and the verdict."""
    from datetime import datetime
    keep = ("a", "b", "a_defines", "b_defines", "pose", "interference_mm3", "clearance_mm",
            "windows", "verdicts", "contact_mm")
    record: Dict[str, Any] = {"recorded": datetime.now().astimezone().isoformat(timespec="seconds"),
                              "mate": mate or res.get("pose", {}).get("mate")}
    record.update({k: res[k] for k in keep if k in res})
    if "contacts" in res:
        record["contacts"] = res["contacts"][:20]
        record["contact_regions"] = len(res["contacts"])
    record["a_snapshot"] = parameter_snapshot(Path(res["a"]), res.get("a_defines"))
    record["b_snapshot"] = parameter_snapshot(Path(res["b"]), res.get("b_defines"))
    record["verdict"] = overall_verdict(res, allow_mm3)
    return record


def _record_key(f: Dict[str, Any]):
    return (f.get("mate"), f.get("a"), f.get("b"), json.dumps(f.get("a_defines") or {}, sort_keys=True),
            json.dumps(f.get("b_defines") or {}, sort_keys=True))


def record_fit(project_dir: Path, record: Dict[str, Any]) -> Optional[Path]:
    """Write ``record`` into a project's print manifest fit table, replacing an earlier record of
    the same mate, parts and defines. None when the project has no manifest yet (finalize it)."""
    from agentcad.manifest import PrintManifest
    project_dir = Path(project_dir)
    manifests = sorted(project_dir.glob("exports/*.print.json"))
    own = project_dir / "exports" / f"{project_dir.name}.print.json"
    path = own if own in manifests else (manifests[0] if manifests else None)
    if path is None:
        return None
    m = PrintManifest.load(path)
    m.fit = [f for f in m.fit if _record_key(f) != _record_key(record)] + [record]
    m.save(path)
    return path


def project_of(source: Path, max_up: int = 4) -> Optional[Path]:
    """The project folder a source belongs to: the nearest folder at or above it with an agentcad.toml."""
    folder = Path(source).resolve()
    folder = folder if folder.is_dir() else folder.parent
    for _ in range(max_up + 1):
        if (folder / "agentcad.toml").is_file():
            return folder
        if folder.parent == folder:
            break
        folder = folder.parent
    return None


def _build_takes(source: Path, param: str) -> bool:
    """Whether a build123d program's build() has a parameter named ``param``."""
    import inspect
    if Path(source).suffix.lower() != ".py":
        return False
    try:
        from agentcad.engines.build123d_worker import _execute
        build = _execute(str(Path(source).resolve())).get("build")
        return callable(build) and param in inspect.signature(build).parameters
    except Exception:
        return False


def declared_fits(project_dir: Path, own: str, sources: Dict[str, Any], assembly: bool = False,
                  contact_mm: Optional[float] = 0.05, out_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Fit every mate a project declares between two parts it can name, and record each fit in
    both parts' manifests and the project's (``session finalize`` runs this).

    ``sources`` maps a part name to (source, defines, project folder): the project itself under
    ``own`` and each part subproject under its folder name. A mate names its pair with
    ``parts = [a, b]``, or, in a project that is not an assembly, with ``counterpart`` (the
    project being the other part). A name that is not in ``sources`` is taken as a value of the
    project source's ``part`` parameter when its build() has one. The pose comes from both parts'
    own declarations of the mate when both declare datums; otherwise the parts are fitted as
    modelled (one assembly frame) and the pose notes say so."""
    from agentcad import mates as mates_mod
    results: List[Dict[str, Any]] = []
    own_src, own_defs, _ = sources[own]
    takes_part = _build_takes(own_src, "part")
    for name, m in mates_mod.load_all(project_dir).items():
        if m.parts and len(m.parts) == 2:
            pair = [str(x) for x in m.parts]
        elif m.counterpart and not assembly:
            pair = [own, str(m.counterpart)]
        else:
            results.append({"mate": name, "skipped": "an assembly's mate lists its parts = [a, b]" if m.counterpart
                            else "the mate names no parts"})
            continue
        sides, missing = [], None
        for part in pair:
            if part in sources and not (assembly and part == own):
                sides.append(sources[part])
            elif takes_part:
                sides.append((own_src, {**own_defs, "part": part}, project_dir))
            else:
                missing = part
                break
        if missing is not None:
            results.append({"mate": name, "skipped": f"part {missing} is neither a part subproject nor a value "
                                                     f"of the source's part parameter"})
            continue
        (a_src, a_defs, a_dir), (b_src, b_defs, b_dir) = sides
        transform, frame, pose_info = None, None, {"mate": name}
        try:
            posed = mates_mod.pose_for(name, Path(a_src), Path(b_src))
            transform = posed["matrix"]
            side = posed["a"]
            frame = (side.axis.point, side.key_line.direction if side.key_line else (1.0, 0.0, 0.0),
                     side.axis.direction)
            pose_info.update(a_declared_in=str(posed["a_path"]), b_declared_in=str(posed["b_path"]),
                             notes=posed["notes"])
        except mates_mod.MateError as e:
            pose_info["notes"] = [f"posed as modelled ({e})"]
        try:
            res = fit(Path(a_src), Path(b_src), a_defines=a_defs or None, b_defines=b_defs or None,
                      transform=transform, windows={name: m.window} if m.window else None, contact_mm=contact_mm,
                      out_dir=Path(out_dir) / name if out_dir is not None else None, frame=frame)
        except Exception as e:  # one mate that cannot be fitted never stops the others or the finalize
            results.append({"mate": name, "pair": pair, "skipped": f"fit failed: {type(e).__name__}: {e}"})
            continue
        res["pose"].update(pose_info)
        if m.window and m.nominal_mm is not None and res.get("windows"):
            res["verdicts"] = judge_windows(res["windows"], {name: (m.nominal_mm, m.tol_mm)})
        record = fit_record(res, mate=name)
        folders = dict.fromkeys(Path(d).resolve() for d in (a_dir, b_dir, project_dir))
        written = [str(w) for w in (record_fit(d, record) for d in folders) if w]
        results.append({"mate": name, "pair": pair, "record": record, "written": written})
    return results


def load_mates(project_dir: Path) -> Dict[str, Any]:
    """The raw [mates] table of a project's agentcad.toml, job.toml or part.toml (or a file path):
    name -> {window: [x0,y0,z0,x1,y1,z1], nominal_mm, parts: [a, b] or counterpart, and any datums}.

    ``parts`` names both bodies of the mate (a job toml lists every pair of an assembly);
    ``counterpart`` alone is enough in a part.toml, where the owner is the part itself.
    ``agentcad.mates`` holds the one definition; this keeps the raw form for callers that need it."""
    from agentcad.mates import read_table
    return read_table(project_dir)


def write_json(data: Dict[str, Any], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, default=float))
    return path
