"""RECOVER and COMPARE: section loops, arc fits, an inventory, and a comparison.

Two exchange formats carry everything between these tools, so any probe can
feed any comparison:

``loops.json``   {"source": str, "planes": [{"plane": "y=3.2", "loops": [{"edges": [
                 {"type": "line"|"circle"|"bspline"|..., "start": [x,y,z], "end": [x,y,z],
                  "length": L, "center": [x,y,z]|null, "radius": r|null, "sweep_deg": a|null,
                  "midpoint": [x,y,z]}],
                 "closed": bool, "n_edges": n, "length": L, "fit": {...}|null}]}]}
``points.json``  {"source": str, "sampler": {"kind": "tessellation", "tolerance": t}, "points": [[x,y,z], ...]}

A cap an instrument applies is printed with its value; none is silent
(a forty-loop cap once hid nineteen rack teeth). Cylindrical faces report
their axis, never their centroid (a centroid read as an axis rotated a part
by ninety degrees). B-rep sources (build123d programs, STEP) are probed
exactly; mesh sources (STL, or the other engines' exports) only in the
sampled compartment, and the output says which. The two exceptions read a
mesh's own triangles and say so: section loops of an STL (``mesh_section_plane``,
the tessellation's section) and ``agentcad.rays`` (lines through a mesh).
"""

import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# --- shapes -------------------------------------------------------------------

def _b3d():
    from agentcad.engines.build123d_worker import _bootstrap
    return _bootstrap()


def load_shape(source: Path, defines: Optional[Dict[str, str]] = None):
    """A build123d shape from a STEP file or a build123d program (in-process).

    Programs follow the engine contract (build(**params) or a named product);
    they run in this process because a probe is a diagnostic the caller
    watches, not a session step.
    """
    from agentcad.engines.build123d_worker import _execute, _harvest

    b3d = _b3d()
    source = Path(source)
    if source.suffix.lower() in (".step", ".stp"):
        return b3d.import_step(str(source))
    if source.suffix.lower() == ".py":
        warnings: List[str] = []
        shape = _harvest(b3d, _execute(str(source)), dict(defines or {}), warnings)
        for w in warnings:
            print(f"agentcad probe: {w}", file=sys.stderr)
        return shape
    raise ValueError(f"{source}: probes read STEP or build123d programs exactly (probe section and probe rays also read "
                     f"an STL); other meshes only through compare")


# --- planes -----------------------------------------------------------------

def plane_spec(spec: str, centre: Optional[Sequence[float]] = None) -> Tuple[str, float]:
    """'y=3.2' | 'z=mid' | 'x=-4' -> ('y', 3.2): the axis and the coordinate.

    'mid' is the centre of the part's bounding box on that axis, given as ``centre`` (x, y, z).
    """
    axis, _, value = spec.partition("=")
    axis = axis.strip().lower()
    if axis not in ("x", "y", "z") or not value:
        raise ValueError(f"plane spec {spec!r}: expected x=|y=|z= followed by a number or 'mid'")
    if value.strip() == "mid":
        if centre is None:
            raise ValueError("'mid' needs a shape")
        return axis, float(centre["xyz".index(axis)])
    return axis, float(value)


def parse_plane(spec: str, shape=None):
    """'y=3.2' | 'z=mid' | 'x=-4' -> a build123d Plane through that coordinate.

    'mid' is the centre of the shape's bounding box on that axis.
    """
    b3d = _b3d()
    centre = None
    if shape is not None:
        c = shape.bounding_box().center()
        centre = (c.X, c.Y, c.Z)
    axis, coord = plane_spec(spec, centre)
    if axis == "x":
        return b3d.Plane(origin=(coord, 0, 0), x_dir=(0, 1, 0), z_dir=(1, 0, 0)), coord
    if axis == "y":
        return b3d.Plane(origin=(0, coord, 0), x_dir=(1, 0, 0), z_dir=(0, 1, 0)), coord
    return b3d.Plane(origin=(0, 0, coord), x_dir=(1, 0, 0), z_dir=(0, 0, 1)), coord


# --- section loops -----------------------------------------------------------

def _edge_record(b3d, e) -> Dict[str, Any]:
    kind = str(e.geom_type).split(".")[-1].lower()
    s, t, m = e.position_at(0), e.position_at(1), e.position_at(0.5)
    rec: Dict[str, Any] = {"type": kind, "start": [s.X, s.Y, s.Z], "end": [t.X, t.Y, t.Z],
                           "length": float(e.length), "center": None, "radius": None, "sweep_deg": None,
                           "midpoint": [m.X, m.Y, m.Z]}
    if kind == "circle":
        try:
            c = e.arc_center
            rec["center"] = [c.X, c.Y, c.Z]
            rec["radius"] = float(e.radius)
            rec["sweep_deg"] = math.degrees(float(e.length) / float(e.radius)) if float(e.radius) else None
        except Exception:  # an arc that refuses its centre stays a plain edge
            pass
    return rec


def section_loops(shape, plane, max_loops: Optional[int] = None) -> List[Dict[str, Any]]:
    """Closed loops of exact edges where ``plane`` cuts ``shape``.

    ``max_loops`` caps the loops kept; when it applies, the cap is printed
    and recorded so it is never mistaken for the geometry's own count.
    """
    b3d = _b3d()
    cut = b3d.section(shape, section_by=plane) if hasattr(b3d, "section") else None
    faces = list(cut.faces()) if cut is not None else []
    if not faces:
        # a plane that grazes nothing, or a shape without solids: try the edges
        try:
            faces = list((shape & b3d.Plane(plane).to_face() if False else []) or [])
        except Exception:
            faces = []
    wires = []
    for f in faces:
        wires.append(f.outer_wire())
        wires.extend(f.inner_wires())
    loops = []
    for w in wires:
        edges = [_edge_record(b3d, e) for e in w.edges()]
        loops.append({"edges": edges, "closed": bool(w.is_closed), "n_edges": len(edges),
                      "length": float(w.length), "fit": None})
    return _cap_loops(loops, max_loops)


def _cap_loops(loops: List[Dict[str, Any]], max_loops: Optional[int]) -> List[Dict[str, Any]]:
    """Longest loop first, each carrying the plane's total; a cap is printed and recorded, never silent."""
    loops.sort(key=lambda L: -L["length"])
    total = len(loops)
    if max_loops is not None and total > max_loops:
        print(f"agentcad probe: cap max_loops={max_loops} applied: {total} loops on this plane, {max_loops} kept "
              f"(the cap is the instrument's, not the part's)", file=sys.stderr)
        loops = loops[:max_loops]
    for L in loops:
        L["total_on_plane"] = total
    return loops


# --- section loops of a mesh --------------------------------------------------------------------

def mesh_section_plane(mesh, spec: str, axis: Optional[str] = None, center: Optional[Sequence[float]] = None,
                       max_loops: Optional[int] = None) -> Dict[str, Any]:
    """Loops where a plane cuts a mesh (``meshprobe.Mesh``), as the plane record ``probe section`` writes.

    The loops are the exact loops' records (``edges`` of type ``line``, ``closed``, ``n_edges``,
    ``length``, ``fit``, ``total_on_plane``) and are polylines: the tessellation's section, not the
    part's. Each also carries ``extents``: its radial extent (nearest and farthest distance from the
    axis) and axial extent (lowest and highest position along it). The axis runs along ``axis``
    ('x', 'y' or 'z'; default the plane's own normal) through ``center`` (the two coordinates across
    the axis, ascending; default the middle of the mesh's bounding box). The plane's ``extents`` cover
    every loop on it, kept or capped.
    """
    from agentcad import meshprobe

    plane_axis, coord = plane_spec(spec, (mesh.lo + mesh.hi) / 2.0)
    loops = meshprobe.plane_loops(mesh, "xyz".index(plane_axis), coord)
    along = "xyz".index((axis or plane_axis).lower())
    across = [k for k in range(3) if k != along]
    centre = [float(c) for c in center] if center is not None else [float((mesh.lo[k] + mesh.hi[k]) / 2.0) for k in across]
    for L in loops:
        L["fit"] = fit_polyline_loop(L)
        L["extents"] = meshprobe.loop_extents(L, along, centre)
    extents = meshprobe.merge_extents([L["extents"] for L in loops])
    loops = _cap_loops(loops, max_loops)
    return {"plane": spec, "coordinate": coord, "n_loops": loops[0]["total_on_plane"] if loops else 0,
            "extents": extents, "loops": loops}


# --- arc fit ---------------------------------------------------------------------

def fit_circle(points: Sequence[Sequence[float]]) -> Optional[Dict[str, Any]]:
    """Least-squares circle through planar points (Kasa fit): centre, radius, rms residual."""
    import numpy as np

    P = np.asarray(points, dtype=float)
    if len(P) < 3:
        return None
    # project to the plane of best fit
    centroid = P.mean(axis=0)
    _, _, vt = np.linalg.svd(P - centroid)
    u, v = vt[0], vt[1]
    x = (P - centroid) @ u
    y = (P - centroid) @ v
    A = np.column_stack([x, y, np.ones_like(x)])
    b = x ** 2 + y ** 2
    try:
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    except np.linalg.LinAlgError:
        return None
    cx, cy = sol[0] / 2, sol[1] / 2
    r = math.sqrt(max(sol[2] + cx ** 2 + cy ** 2, 0.0))
    resid = np.sqrt((x - cx) ** 2 + (y - cy) ** 2) - r
    centre = centroid + cx * u + cy * v
    return {"center": [float(t) for t in centre], "radius": float(r), "rms": float(np.sqrt((resid ** 2).mean())),
            "max": float(np.abs(resid).max()), "n": int(len(P))}


def fit_polyline_loop(loop: Dict[str, Any], min_edges: int = 12) -> Optional[Dict[str, Any]]:
    """For a loop made of many short lines (a polylined arc from a mesh-converted
    body), a circle fit of its vertices; None for loops of exact curves."""
    edges = loop["edges"]
    if len(edges) < min_edges or any(e["type"] != "line" for e in edges):
        return None
    pts = [e["start"] for e in edges]
    fit = fit_circle(pts)
    if fit:
        fit["note"] = f"{len(edges)} line segments read as one circle; rms {fit['rms']:.4g}"
    return fit


# --- inventory -------------------------------------------------------------------

def inventory(shape, planes: Sequence[str] = (), max_loops: Optional[int] = None) -> Dict[str, Any]:
    """bbox, volume, face census, cylinder axes, and section loops on named planes."""
    from agentcad.engines.build123d_worker import _face_census, _measure

    b3d = _b3d()
    md = _measure(b3d, shape)
    out: Dict[str, Any] = {k: md.get(k) for k in ("bbox_min", "bbox_size", "volume", "area", "counts", "face_census", "is_valid")}
    cylinders = []
    for f in shape.faces():
        kind = str(f.geom_type).split(".")[-1].lower()
        if kind not in ("cylinder", "cone"):
            continue
        rec: Dict[str, Any] = {"type": kind, "area": float(f.area)}
        try:
            ax = f.axis_of_rotation
            rec["axis_origin"] = [ax.position.X, ax.position.Y, ax.position.Z]
            rec["axis_direction"] = [ax.direction.X, ax.direction.Y, ax.direction.Z]
        except Exception as e:  # a face without an axis is reported as such, never by its centroid
            rec["axis_error"] = str(e).splitlines()[-1] if str(e) else type(e).__name__
        try:
            rec["radius"] = float(f.radius) if hasattr(f, "radius") else None
        except Exception:
            rec["radius"] = None
        cylinders.append(rec)
    out["cylinders"] = cylinders
    out["census_notes"] = _census_notes(b3d, shape, out.get("face_census"))
    out["planes"] = []
    for spec in planes:
        plane, coord = parse_plane(spec, shape)
        loops = section_loops(shape, plane, max_loops=max_loops)
        for L in loops:
            L["fit"] = fit_polyline_loop(L)
        out["planes"].append({"plane": spec, "coordinate": coord, "n_loops": loops[0]["total_on_plane"] if loops else 0,
                              "loops": loops})
    return out


def _census_notes(b3d, shape, census) -> List[str]:
    """Sentences saying a zero in the census may be the representation's: the whole shape first,
    then each solid of a compound (a spline body beside an analytic one)."""
    from agentcad.engines.build123d_worker import _face_census
    from agentcad.report import census_hides_analytic

    whole = census_hides_analytic(census)
    if whole:
        return [whole]
    solids = list(shape.solids())
    if len(solids) < 2:
        return []
    notes = []
    for i, solid in enumerate(solids, 1):
        note = census_hides_analytic(_face_census(b3d, solid))
        if note:
            notes.append(f"solid {i} of {len(solids)}: {note}")
    return notes


# --- sampled points ---------------------------------------------------------------

def sample_points(source: Path, tolerance: Optional[float] = None, defines=None) -> Dict[str, Any]:
    """Surface points of a shape (tessellation vertices) or of a mesh file."""
    import numpy as np

    source = Path(source)
    if source.suffix.lower() == ".stl":
        from agentcad.meshmeasure import read_stl
        V, _ = read_stl(source)
        pts = np.unique(np.round(V, 6), axis=0)
        return {"source": str(source), "sampler": {"kind": "stl_vertices"}, "points": pts.tolist()}
    shape = load_shape(source, defines)
    b3d = _b3d()
    bb = shape.bounding_box()
    diag = math.sqrt(bb.size.X ** 2 + bb.size.Y ** 2 + bb.size.Z ** 2)
    tol = tolerance or diag / 1000.0
    verts, _ = shape.tessellate(tolerance=tol, angular_tolerance=0.1)
    pts = np.array([[v.X, v.Y, v.Z] for v in verts])
    return {"source": str(source), "sampler": {"kind": "tessellation", "tolerance": tol}, "points": pts.tolist()}


WORST_FRACTION = 0.05      # the share of sampled points whose location a comparison reports
_CLUSTER_CELLS = 20        # cluster cells per bounding-box diagonal
_CLUSTERS_SHOWN = 5


def deviation(a: Sequence[Sequence[float]], b: Sequence[Sequence[float]]) -> Dict[str, Any]:
    """Nearest-neighbour distances from a to b: p50, p95, max, rms, and where the worst 5% lie (needs scipy)."""
    import numpy as np
    from scipy.spatial import cKDTree

    A, B = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    d, _ = cKDTree(B).query(A)
    return {"p50": float(np.percentile(d, 50)), "p95": float(np.percentile(d, 95)), "max": float(d.max()), "n": int(len(A)),
            "rms": float(np.sqrt((d ** 2).mean())), "worst5": worst_region(A, d)}


def worst_region(points: Sequence[Sequence[float]], dist: Sequence[float], fraction: float = WORST_FRACTION,
                 shown: int = _CLUSTERS_SHOWN) -> Dict[str, Any]:
    """Where the worst ``fraction`` of the deviations lie: their bounding box, and clusters.

    The points with the largest distances (the top ``fraction`` of them and every point tied with
    the last of them, those above zero) are
    grouped by the cubic cells they fall in, cells of 1/20 of the bounding-box diagonal of all the
    points; cells that touch (by face, edge or corner) join into one cluster. A cluster reports the
    mean of its points as its centre, its size, its worst distance and its box, and the ``shown``
    clusters with the worst distances are kept (``n_clusters`` counts all). The rule is stated in
    ``method`` so the centres are never read as a fit.
    """
    import numpy as np

    P, d = np.asarray(points, dtype=float), np.asarray(dist, dtype=float)
    pick = np.argsort(-d, kind="stable")[:max(1, math.ceil(fraction * len(d)))]
    if len(pick):
        # every point tied with the last one picked joins: equal deviations are never split by sort order
        floor = float(d[pick].min())
        pick = np.nonzero(d >= floor - 1e-9 * max(1.0, abs(floor)))[0]
    pick = pick[d[pick] > 0]
    out: Dict[str, Any] = {"fraction": fraction, "n": int(len(pick)), "of": int(len(d))}
    if not len(pick):
        out["note"] = "no deviation above zero: nothing to locate"
        return out
    worst, worst_d = P[pick], d[pick]
    lo, hi = P.min(axis=0), P.max(axis=0)
    diag = float(np.linalg.norm(hi - lo))
    cell = diag / _CLUSTER_CELLS if diag > 0 else 1.0
    clusters = _grid_clusters(worst, worst_d, lo, cell)
    clusters.sort(key=lambda c: (-c["max"], -c["n"]))
    out.update(threshold=float(worst_d.min()), bbox_min=worst.min(axis=0).tolist(), bbox_max=worst.max(axis=0).tolist(),
               cell=cell, n_clusters=len(clusters), clusters=clusters[:shown],
               method=f"the worst {fraction:.0%} of the points by distance, and every point tied with the last "
                      f"of them; occupied cells of {cell:.4g} "
                      f"(1/{_CLUSTER_CELLS} of the bounding-box diagonal) that touch form one cluster, "
                      f"centre = mean of its points")
    return out


def _grid_clusters(points, dist, origin, cell: float) -> List[Dict[str, Any]]:
    """Points grouped by the cubic cells (side ``cell`` from ``origin``) they fall in, touching cells joined."""
    import numpy as np

    keys = np.floor((points - origin) / cell).astype(np.int64)
    cells, inverse = np.unique(keys, axis=0, return_inverse=True)
    inverse = inverse.reshape(-1)
    index = {tuple(c): i for i, c in enumerate(cells.tolist())}
    parent = list(range(len(cells)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for (cx, cy, cz), i in index.items():
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    j = index.get((cx + dx, cy + dy, cz + dz))
                    if j is not None:
                        parent[find(j)] = find(i)
    roots = np.array([find(i) for i in range(len(cells))])[inverse]
    clusters = []
    for root in np.unique(roots):
        m = roots == root
        pts = points[m]
        clusters.append({"center": pts.mean(axis=0).tolist(), "n": int(m.sum()), "max": float(dist[m].max()),
                         "bbox_min": pts.min(axis=0).tolist(), "bbox_max": pts.max(axis=0).tolist()})
    return clusters


# --- compare ---------------------------------------------------------------------

def compare(original: Path, candidate: Path, planes: Sequence[str] = (), windows: Optional[Dict[str, Sequence[float]]] = None,
            out_dir: Optional[Path] = None, defines: Optional[Dict[str, str]] = None,
            max_loops: Optional[int] = None) -> Dict[str, Any]:
    """Loop counts per plane (the gate), sampled deviation both ways, overlay PNGs.

    Exact sources (STEP, build123d) are sectioned; a mesh candidate or
    original is compared in the sampled compartment only, and ``result["planes"]``
    says so instead of pretending.
    """
    result: Dict[str, Any] = {"original": str(original), "candidate": str(candidate), "planes": [], "gate": None}
    exact = all(Path(p).suffix.lower() in (".step", ".stp", ".py") for p in (original, candidate))
    if exact and planes:
        so, sc = load_shape(original), load_shape(candidate, defines)
        gate_ok = True
        for spec in planes:
            po, _ = parse_plane(spec, so)
            pc, _ = parse_plane(spec, sc)
            lo = section_loops(so, po, max_loops=max_loops)
            lc = section_loops(sc, pc, max_loops=max_loops)
            no = lo[0]["total_on_plane"] if lo else 0
            nc = lc[0]["total_on_plane"] if lc else 0
            entry: Dict[str, Any] = {"plane": spec, "loops_original": no, "loops_candidate": nc, "equal": no == nc}
            if no != nc:
                gate_ok = False
            if windows:
                entry["windows"] = {}
                for name, (x0, y0, x1, y1) in windows.items():
                    w = _window_distance(lo, lc, spec, (x0, y0, x1, y1))
                    if out_dir is not None:
                        w["overlay"] = str(_overlay_png(lo, lc, spec, Path(out_dir), window=(x0, y0, x1, y1), name=name, stats=w))
                    entry["windows"][name] = w
            if out_dir is not None:
                entry["overlay"] = str(_overlay_png(lo, lc, spec, Path(out_dir)))
            result["planes"].append(entry)
        result["gate"] = gate_ok
    elif planes:
        result["planes_note"] = "a mesh source has no exact loops; only the sampled deviation is reported"
    try:
        po = sample_points(original)["points"]
        pc = sample_points(candidate, defines=defines)["points"]
        result["deviation"] = {"candidate_to_original": deviation(pc, po), "original_to_candidate": deviation(po, pc)}
    except ImportError as e:
        result["deviation_error"] = f"scipy unavailable: {e}"
    return result


def _arc_angles(e, keep, n: int) -> List[float]:
    """Angles (radians, about the edge's centre in the section plane's axes) sampling a circle edge.

    The direction comes from the edge's midpoint: the arc runs the way that passes it. A closed circle
    (start at end, or a sweep of a full turn) is sampled once round. A record without a midpoint (a
    loops.json written before it was recorded) is read as the arc that runs counter-clockwise."""
    s, t, c = e["start"], e["end"], e["center"]
    a0 = math.atan2(s[keep[1]] - c[keep[1]], s[keep[0]] - c[keep[0]])
    a1 = math.atan2(t[keep[1]] - c[keep[1]], t[keep[0]] - c[keep[0]])
    turn = 2 * math.pi
    ccw = (a1 - a0) % turn
    full = (e.get("sweep_deg") or 0.0) >= 359.0 or min(ccw, turn - ccw) < 1e-9
    m = e.get("midpoint")
    if full:
        sweep = turn
    elif m is None or (math.atan2(m[keep[1]] - c[keep[1]], m[keep[0]] - c[keep[0]]) - a0) % turn < ccw:
        sweep = ccw
    else:
        sweep = ccw - turn
    return [a0 + sweep * i / n for i in range(n + 1)]


def _loop_points_2d(loops, spec: str, n_per_edge: int = 24):
    """Points of every loop projected to the section plane's 2D axes."""
    axis = spec.partition("=")[0].strip().lower()
    keep = {"x": (1, 2), "y": (0, 2), "z": (0, 1)}[axis]
    pts = []
    for L in loops:
        for e in L["edges"]:
            if e["type"] == "circle" and e["center"] and e["radius"]:
                c = e["center"]
                for a in _arc_angles(e, keep, n_per_edge):
                    pts.append((c[keep[0]] + e["radius"] * math.cos(a), c[keep[1]] + e["radius"] * math.sin(a)))
            else:
                pts.append((e["start"][keep[0]], e["start"][keep[1]]))
                pts.append((e["end"][keep[0]], e["end"][keep[1]]))
    return pts


def _window_distance(lo, lc, spec, window) -> Dict[str, Any]:
    import numpy as np
    from scipy.spatial import cKDTree

    x0, y0, x1, y1 = window
    def inside(pts):
        return np.array([p for p in pts if x0 <= p[0] <= x1 and y0 <= p[1] <= y1])
    a, b = inside(_loop_points_2d(lo, spec)), inside(_loop_points_2d(lc, spec))
    if len(a) == 0 or len(b) == 0:
        return {"note": "no geometry of one side inside the window", "n_original": int(len(a)), "n_candidate": int(len(b))}
    d = cKDTree(b).query(a)[0]
    return {"p95": float(np.percentile(d, 95)), "max": float(d.max()), "n_original": int(len(a)), "n_candidate": int(len(b))}


def _overlay_png(lo, lc, spec: str, out_dir: Path, window=None, name: Optional[str] = None,
                 stats: Optional[Dict[str, Any]] = None) -> Path:
    """The two sections over each other: the whole section, or with ``window`` (x0, y0, x1, y1 in the
    section plane's axes) zoomed to it, the curves sampled finely enough to stay smooth there."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7, 7))
    for loops, color, label in ((lo, "black", "original"), (lc, "#e94560", "candidate")):
        first = True
        for L in loops:
            pts = _loop_points_2d([L], spec, 24 if window is None else 400)
            if pts:
                xs, ys = zip(*pts)
                ax.plot(list(xs) + [xs[0]], list(ys) + [ys[0]], color=color, lw=0.8, label=label if first else None)
                first = False
    ax.set_aspect("equal"); ax.legend()
    stem = f"overlay_{spec.replace('=', '_').replace('.', 'p')}"
    if window is None:
        ax.set_title(f"section {spec}: {len(lo)} vs {len(lc)} loops")
    else:
        x0, y0, x1, y1 = window
        ax.set_xlim(x0, x1); ax.set_ylim(y0, y1)
        across = {"x": ("y", "z"), "y": ("x", "z"), "z": ("x", "y")}[spec.partition("=")[0].strip().lower()]
        ax.set_xlabel(across[0]); ax.set_ylabel(across[1])
        title = f"section {spec}, window {name}"
        if stats and "p95" in stats:
            title += f": p95 {stats['p95']:.3g}, max {stats['max']:.3g}"
        ax.set_title(title)
        stem += "_" + re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name))
    path = out_dir / f"{stem}.png"
    fig.savefig(path, dpi=120); plt.close(fig)
    return path


def write_json(data: Dict[str, Any], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, default=float))
    return path


# --- a fillet on the live part ------------------------------------------------

class _Captured(BaseException):
    """Raised inside the source at the call under study; a BaseException so a source's own
    ``except Exception`` around a fillet cannot swallow it."""

    def __init__(self, op: str, objects, size, kwargs):
        super().__init__(op)
        self.op, self.objects, self.size, self.kwargs = op, list(objects), size, dict(kwargs)


def capture_call(source: Path, at: str = "fillet", index: int = 0, defines: Optional[Dict[str, str]] = None) -> _Captured:
    """Run ``source`` until its ``index``-th call of ``at`` (``fillet`` or ``chamfer``) and return that
    call's edge selection and size, with the live part still attached to the edges.

    The source is never modified: build123d's ``fillet``/``chamfer`` are replaced for the run so
    the program's own ``from build123d import fillet`` binds the wrapper, and restored after.
    Later cuts remove the edges a fillet selects, which is why the probe stops here instead of
    inspecting the finished part.
    """
    import build123d as b3d_mod
    from agentcad.engines.build123d_worker import _execute, _harvest

    op = at.strip().rstrip("(")
    if op not in ("fillet", "chamfer"):
        raise ValueError(f"--at must be fillet or chamfer, not {at!r}")
    originals = {name: getattr(b3d_mod, name) for name in ("fillet", "chamfer")}
    seen = {"n": 0}

    def wrap(name):
        real = originals[name]

        def wrapper(objects, *args, **kwargs):
            if name == op:
                k = seen["n"]
                seen["n"] += 1
                if k == index:
                    size = args[0] if args else kwargs.get("radius", kwargs.get("length"))
                    objs = list(objects) if not hasattr(objects, "geom_type") else [objects]
                    raise _Captured(name, objs, size, kwargs)
            return real(objects, *args, **kwargs)
        return wrapper

    for name in originals:
        setattr(b3d_mod, name, wrap(name))
    try:
        namespace = _execute(str(Path(source).resolve()))
        _harvest(_b3d(), namespace, dict(defines or {}), [])
    except _Captured as cap:
        return cap
    finally:
        for name, real in originals.items():
            setattr(b3d_mod, name, real)
    raise LookupError(f"{source}: no {op} call number {index} (saw {seen['n']})")


def _live_part(edges):
    """The solid the selected edges belong to (an edge from shape.edges() knows its parent; one
    from a face's edges() knows the face, whose parent is the shape)."""
    for e in edges:
        p = getattr(e, "topo_parent", None)
        for _ in range(3):
            if p is None:
                break
            if p.solids():
                return p
            p = getattr(p, "topo_parent", None)
    return None


def fillet_probe(source: Path, at: str = "fillet", index: int = 0, radii: Sequence[float] = (1.0, 0.6, 0.4, 0.25),
                 short_mm: float = 0.2, defines: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Why does this fillet fail: the selected chain on the live part, the sub-``short_mm`` edges
    and steps touching it, the sizes the whole selection and each edge alone will take, and
    whether the live part is watertight.
    """
    b3d = _b3d()
    cap = capture_call(source, at, index, defines)
    op = getattr(b3d, cap.op)
    live = _live_part(cap.objects)
    out: Dict[str, Any] = {"source": str(source), "op": cap.op, "index": index, "size_in_source": cap.size,
                           "n_selected": len(cap.objects), "live_part": None, "chain": [], "steps": [],
                           "whole": {}, "each": [], "watertight": None}
    if live is None:
        out["error"] = "the selected edges carry no parent shape; select from part.edges() or part.faces()[i].edges()"
        return out
    out["live_part"] = {"volume": float(live.volume), "solids": len(live.solids()), "faces": len(live.faces()),
                        "edges": len(live.edges()), "is_valid": bool(live.is_valid)}

    def vkey(v):
        return (round(v.X, 4), round(v.Y, 4), round(v.Z, 4))

    sel_keys = set()
    for i, e in enumerate(cap.objects):
        rec = _edge_record(b3d, e)
        m = e.position_at(0.5)
        rec.update({"i": i, "midpoint": [m.X, m.Y, m.Z], "short": float(e.length) < short_mm})
        out["chain"].append(rec)
        sel_keys.add((vkey(e.position_at(0.5)), round(float(e.length), 4)))
    sel_verts = {vkey(v) for e in cap.objects for v in (e.position_at(0), e.position_at(1))}
    for e in live.edges():
        key = (vkey(e.position_at(0.5)), round(float(e.length), 4))
        if key in sel_keys or float(e.length) >= short_mm:
            continue
        ends = {vkey(e.position_at(0)), vkey(e.position_at(1))}
        if ends & sel_verts:
            m = e.position_at(0.5)
            out["steps"].append({"type": _edge_record(b3d, e)["type"], "length": float(e.length), "midpoint": [m.X, m.Y, m.Z],
                                 "touches": sorted(i for i, s in enumerate(cap.objects)
                                                   if ends & {vkey(s.position_at(0)), vkey(s.position_at(1))})})

    def attempt(edges, size):
        try:
            r = op(edges, size)
            return "ok" if r.is_valid else "built but not valid"
        except Exception as e:  # noqa: BLE001 - the error's name is the finding
            return f"{type(e).__name__}: {str(e).splitlines()[0][:120]}"

    for r in radii:
        out["whole"][str(r)] = attempt(cap.objects, r)
    for i, e in enumerate(cap.objects):
        row = {"i": i, "takes": None, "results": {}}
        for r in sorted(radii, reverse=True):
            res = attempt([e], r)
            row["results"][str(r)] = res
            if res == "ok" and row["takes"] is None:
                row["takes"] = r
        out["each"].append(row)

    try:
        import numpy as np
        import pyvista as pv
        verts, tris = live.tessellate(tolerance=0.05, angular_tolerance=0.2)
        V = np.array([[v.X, v.Y, v.Z] for v in verts]); F = np.array(tris)
        mesh = pv.PolyData(V, np.hstack([np.full((len(F), 1), 3), F]).ravel()).clean(tolerance=1e-6)   # faces tessellate apart; merge their shared vertices
        boundary = mesh.extract_feature_edges(boundary_edges=True, feature_edges=False, manifold_edges=False, non_manifold_edges=False)
        out["watertight"] = {"boundary_edges": int(boundary.n_cells), "ok": int(boundary.n_cells) == 0}
    except ImportError as e:
        out["watertight"] = {"error": f"pyvista unavailable: {e}"}
    return out


def render_fillet_probe(res: Dict[str, Any]) -> List[str]:
    lines = [f"{res['op']} call {res['index']} in {res['source']}: {res['n_selected']} edge(s) selected, size {res['size_in_source']}"]
    if res.get("error"):
        return lines + [f"  {res['error']}"]
    lp = res["live_part"]
    lines.append(f"  live part: volume {lp['volume']:.4g}, {lp['solids']} solid(s), {lp['faces']} faces, {lp['edges']} edges, valid {lp['is_valid']}")
    for e in res["chain"]:
        m = e["midpoint"]
        flag = "  SHORT" if e["short"] else ""
        lines.append(f"  edge {e['i']}: {e['type']} {e['length']:.3f} mm at ({m[0]:.3f}, {m[1]:.3f}, {m[2]:.3f}){flag}")
    for s in res["steps"]:
        m = s["midpoint"]
        lines.append(f"  STEP {s['length']:.3f} mm ({s['type']}) at ({m[0]:.3f}, {m[1]:.3f}, {m[2]:.3f}) touching edge(s) {s['touches']}")
    for r, v in res["whole"].items():
        lines.append(f"  whole selection at {r}: {v}")
    for row in res["each"]:
        takes = f"takes {row['takes']}" if row["takes"] is not None else "takes none of " + ", ".join(row["results"])
        lines.append(f"  edge {row['i']} alone: {takes}")
    w = res.get("watertight")
    if w:
        lines.append(f"  watertight: {'yes' if w.get('ok') else 'NO'}" + (f" ({w['boundary_edges']} boundary edges)" if "boundary_edges" in w else f" ({w.get('error')})"))
    return lines


# --- draft: will the part leave its mold --------------------------------------------------------

def draft_analysis(shape, pull: Sequence[float] = (0.0, 0.0, 1.0), samples: int = 7,
                   perpendicular_deg: float = 1.0) -> Dict[str, Any]:
    """Face-by-face draft against a pull direction.

    The draft at a point is asin(n . d), with n the face's outward normal and d the unit pull, in
    degrees: positive means the face leans so it releases (the rule is the same for a pocket and a
    boss), zero is a vertical wall that drags, negative is an undercut that locks. Each face is sampled
    on a samples x samples grid of (u, v) inside it, so a curved face reports its range. A face whose
    normal is within ``perpendicular_deg`` of the pull everywhere (a floor, a top, a parting face) is
    reported as perpendicular and NOT given a draft: the analysis says what it cannot judge instead of
    folding it into a number.
    """
    b3d = _b3d()
    d = b3d.Vector(*pull).normalized()
    limit = math.cos(math.radians(perpendicular_deg))
    faces: List[Dict[str, Any]] = []
    for i, f in enumerate(shape.faces()):
        dots = []
        for a in range(samples):
            for b in range(samples):
                try:
                    dots.append(f.normal_at((a + 0.5) / samples, (b + 0.5) / samples).dot(d))
                except Exception as e:  # a degenerate patch has no normal; say so on the row
                    dots.append(float("nan"))
        c = f.center()
        row: Dict[str, Any] = {"index": i, "type": str(f.geom_type).split(".")[-1].lower(),
                               "center": [c.X, c.Y, c.Z], "area": float(f.area)}
        finite = [x for x in dots if x == x]
        if not finite:
            row.update({"class": "unmeasured"})
        elif all(abs(x) > limit for x in finite):
            row.update({"class": "perpendicular"})
        else:
            degs = [math.degrees(math.asin(max(-1.0, min(1.0, x)))) for x in finite]
            row.update({"class": "side", "min_deg": min(degs), "max_deg": max(degs)})
        faces.append(row)
    sides = [r for r in faces if r["class"] == "side"]
    return {"pull": [d.X, d.Y, d.Z], "samples": samples, "perpendicular_deg": perpendicular_deg,
            "faces": faces,
            "summary": {"side_faces": len(sides),
                        "perpendicular_faces": sum(1 for r in faces if r["class"] == "perpendicular"),
                        "unmeasured_faces": sum(1 for r in faces if r["class"] == "unmeasured"),
                        "min_deg": min((r["min_deg"] for r in sides), default=None),
                        "max_deg": max((r["max_deg"] for r in sides), default=None)}}


def draft_failures(res: Dict[str, Any], min_draft_deg: float) -> List[Dict[str, Any]]:
    """Side faces whose smallest draft is below ``min_draft_deg`` (undercuts are the negative ones)."""
    return [r for r in res["faces"] if r["class"] == "side" and r["min_deg"] < min_draft_deg - 1e-9]


def render_draft(res: Dict[str, Any], min_draft_deg: Optional[float] = None, show: int = 12) -> List[str]:
    s = res["summary"]
    rng = "n/a" if s["min_deg"] is None else f"{s['min_deg']:+.3f} .. {s['max_deg']:+.3f} deg"
    lines = [f"pull {tuple(round(v, 4) for v in res['pull'])}: {s['side_faces']} side face(s), draft {rng}; "
             f"{s['perpendicular_faces']} perpendicular to the pull (not judged)"
             + (f"; {s['unmeasured_faces']} unmeasured" if s["unmeasured_faces"] else "")]
    if min_draft_deg is not None:
        bad = draft_failures(res, min_draft_deg)
        lines.append(f"minimum draft {min_draft_deg:g} deg: " + ("PASS" if not bad else f"{len(bad)} face(s) below it"))
        for r in sorted(bad, key=lambda r: r["min_deg"])[:show]:
            c = r["center"]
            kind = "UNDERCUT" if r["min_deg"] < -1e-9 else ("no draft" if abs(r["max_deg"]) < 1e-6 else "too little")
            lines.append(f"  face {r['index']} {r['type']} at ({c[0]:.3g}, {c[1]:.3g}, {c[2]:.3g}): "
                         f"{r['min_deg']:+.3f} .. {r['max_deg']:+.3f} deg  {kind}")
    return lines
