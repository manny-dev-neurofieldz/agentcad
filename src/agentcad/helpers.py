"""Program-side helpers a build123d source can import: ``from agentcad.helpers import soften``.

These are build123d helpers and say so: they take and return build123d shapes and are
not routed through the engine contract. They exist because the same forty lines were
written into a commission's source by hand (edge classification, a fillet on the
concave joints, a chamfer on the convex edges, counts of what refused) and the next
part would have written them again.

Rules the helpers keep:

* never a bare ``except``: a refused edge is listed with its kind, length, midpoint
  and the error's name, so a fillet that fails is a finding and not a silent no-op;
* a helper never mutates its input; it returns a new shape and a ``Report`` whose
  ``lines`` print through :func:`agentcad.report.render_lines`;
* boxes use the same order as fit windows, ``[x0, y0, z0, x1, y1, z1]``.
"""

import math
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from agentcad.report import Report

Box6 = Sequence[float]
Excluder = Union[Callable[[Any, Any], bool], Iterable[Box6], None]


@dataclass
class EdgeSide:
    """One edge of a solid with its convexity, read at its midpoint."""
    edge: Any
    convex: bool
    midpoint: Any
    length: float


def _in_box(p, box: Box6) -> bool:
    x0, y0, z0, x1, y1, z1 = box
    return x0 <= p.X <= x1 and y0 <= p.Y <= y1 and z0 <= p.Z <= z1


def _excluder(exclude: Excluder) -> Callable[[Any, Any], bool]:
    if exclude is None:
        return lambda e, p: False
    if callable(exclude):
        return exclude
    boxes = [tuple(float(v) for v in b) for b in exclude]
    return lambda e, p: any(_in_box(p, b) for b in boxes)


def edge_sides(part, ring_mm: float = 0.3) -> List[EdgeSide]:
    """Every two-face edge of ``part`` classified convex or concave.

    Convexity is the material fraction on an 8-point ring of radius ``ring_mm`` around the
    edge's midpoint, in the plane normal to its tangent: about a quarter of the ring is
    inside at a convex edge and about three quarters at an inside corner. Edges whose two
    faces are tangent-continuous (a fillet's seam) are left out; softening one again is
    never wanted.
    """
    faces_of: Dict[Tuple[float, float, float, float], List[Any]] = {}
    edges_of: Dict[Tuple[float, float, float, float], Any] = {}
    for f in part.faces():
        for e in f.edges():
            m = e.position_at(0.5)
            key = (round(m.X, 3), round(m.Y, 3), round(m.Z, 3), round(e.length, 3))
            edges_of.setdefault(key, e)
            faces_of.setdefault(key, []).append(f)
    out: List[EdgeSide] = []
    for key, fs in faces_of.items():
        if len(fs) != 2:
            continue
        e = edges_of[key]
        p = e.position_at(0.5)
        try:
            n1, n2 = fs[0].normal_at(p), fs[1].normal_at(p)
            t = e.tangent_at(0.5)
        except Exception:  # a degenerate face has no normal here; it cannot be softened either
            continue
        if (n1 + n2).length < 1e-6 or (n1 - n2).length < 1e-6:
            continue
        u = n1.normalized()
        w = t.cross(u).normalized()
        inside = 0
        for k in range(8):
            a = math.pi / 8 + k * math.pi / 4
            q = p + (u * math.cos(a) + w * math.sin(a)) * ring_mm
            inside += 1 if part.is_inside(q) else 0
        out.append(EdgeSide(e, inside <= 4, p, float(e.length)))
    return out


def _reselect(shape, edges, tol: float = 1e-3) -> List[Any]:
    """The edges of ``shape`` that are ``edges`` after the topology changed under them.

    A neighbour's chamfer or fillet trims an edge at one end, so its midpoint moves and its
    length shrinks, but the trimmed edge still passes through the old midpoint. An edge is
    matched when its midpoint coincides with the old one, or else when the old midpoint lies
    on it (within ``tol``), the tangents are parallel and it is no longer than before. Exact
    midpoint matching lost 6 of 16 edges on the FS-4DA bar; a distance tolerance of half the
    feature size matched a fillet seam instead of a 1.5 mm tab-root edge."""
    out: List[Any] = []
    taken: List[Any] = []
    new_edges = list(shape.edges())
    for old in edges:
        m, t, L = old.position_at(0.5), old.tangent_at(0.5), old.length
        best, best_d = None, None
        for e in new_edges:
            if any(e is x for x in taken) or e.length > L + 1e-6:
                continue
            d_mid = (e.position_at(0.5) - m).length
            if d_mid < 1e-3:
                best, best_d = e, 0.0
                break
            try:
                on_curve = e.distance_to(m) < tol and abs(e.tangent_at(0.5).dot(t)) > 0.999
            except Exception:
                on_curve = False
            if on_curve and (best is None or d_mid < best_d):
                best, best_d = e, d_mid
        if best is not None:
            out.append(best)
            taken.append(best)
    return out


def _apply_by_bisection(shape, edges: List[Any], op: Callable[[List[Any], float], Any],
                        sizes: Sequence[float], kind: str, stats: Dict[str, Any], refused: List[Dict[str, Any]]):
    """Apply ``op(edges, size)`` at the first size in ``sizes`` that builds a valid shape; on refusal
    split the selection in half and retry each half on the shape as it now is, so one bad edge
    costs itself and not its neighbours. Single edges that take no size are listed, with the
    error's name, never swallowed."""
    if not edges:
        return shape
    last_err: Optional[BaseException] = None
    for size in sizes:
        try:
            s2 = op(edges, size)
            if s2.is_valid:
                stats["applied"] += len(edges)
                stats["by_size"][size] = stats["by_size"].get(size, 0) + len(edges)
                return s2
            last_err = ValueError("result not valid")
        except Exception as err:  # noqa: BLE001 - recorded below, never dropped
            last_err = err
    if len(edges) == 1:
        e = edges[0]
        p = e.position_at(0.5)
        stats["refused"] += 1
        refused.append({"kind": kind, "length_mm": float(e.length),
                        "midpoint": [round(p.X, 3), round(p.Y, 3), round(p.Z, 3)],
                        "sizes_tried": list(sizes),
                        "error": f"{type(last_err).__name__}: {last_err}" if last_err else "unknown"})
        return shape
    h = len(edges) // 2
    s2 = _apply_by_bisection(shape, edges[:h], op, sizes, kind, stats, refused)
    rest = _reselect(s2, edges[h:])
    if len(rest) < len(edges) - h:
        # an edge whose midpoint moved when its neighbour was softened cannot be found again;
        # it is reported as lost, never dropped from the count (the hand-written version lost 6 of 16)
        found = [e.position_at(0.5) for e in rest]
        for e in edges[h:]:
            p = e.position_at(0.5)
            if not any((p - f).length < 1e-3 for f in found):
                stats["lost"] += 1
                refused.append({"kind": kind, "length_mm": float(e.length),
                                "midpoint": [round(p.X, 3), round(p.Y, 3), round(p.Z, 3)],
                                "sizes_tried": [], "error": "edge not found again after a neighbouring edge changed"})
    return _apply_by_bisection(s2, rest, op, sizes, kind, stats, refused)


def soften(part, fillet_r: float = 1.0, chamfer_c: float = 0.4, exclude: Excluder = None,
           min_len: float = 1.0, chamfer_min_len: Optional[float] = None,
           fillet_within: Optional[Iterable[Box6]] = None) -> Tuple[Any, Report]:
    """Fillet the concave joints of ``part`` and chamfer its convex edges; return the new part and a report.

    ``fillet_r`` is tried first, then half of it, on every concave edge at least ``min_len``
    long (inside ``fillet_within`` boxes when given). ``chamfer_c`` is tried, then half, on
    every convex edge at least ``chamfer_min_len`` long (default three times ``min_len``).
    ``exclude`` keeps edges sharp: a callable ``(edge, midpoint) -> bool`` or boxes
    ``[x0, y0, z0, x1, y1, z1]`` around a coin path, a thread, a mating face. Zero or
    negative ``fillet_r`` / ``chamfer_c`` skips that pass.

    The report's ``deltas`` carry ``fillets`` and ``chamfers`` (applied, refused, lost, candidates,
    by_size; applied + refused + lost == candidates) and ``refused_edges`` (kind, length, midpoint, sizes tried, error); its ``lines``
    print through ``agentcad.report.render_lines`` and every refusal is also a warning.
    """
    from build123d import chamfer, fillet

    keep_sharp = _excluder(exclude)
    chamfer_min_len = 3.0 * min_len if chamfer_min_len is None else chamfer_min_len
    within = [tuple(float(v) for v in b) for b in fillet_within] if fillet_within else None
    refused: List[Dict[str, Any]] = []
    rep = Report()
    shape = part

    sides = edge_sides(shape)
    f_stats = {"applied": 0, "refused": 0, "lost": 0, "candidates": 0, "size": fillet_r, "by_size": {}}
    if fillet_r > 0:
        sel = [s.edge for s in sides if not s.convex and s.length >= min_len and not keep_sharp(s.edge, s.midpoint)
               and (within is None or any(_in_box(s.midpoint, b) for b in within))]
        f_stats["candidates"] = len(sel)
        shape = _apply_by_bisection(shape, sel, lambda es, r: fillet(es, r), (fillet_r, fillet_r / 2), "fillet", f_stats, refused)

    c_stats = {"applied": 0, "refused": 0, "lost": 0, "candidates": 0, "size": chamfer_c, "by_size": {}}
    if chamfer_c > 0:
        sides = edge_sides(shape)   # re-read: the fillets changed the topology
        sel = [s.edge for s in sides if s.convex and s.length >= chamfer_min_len and not keep_sharp(s.edge, s.midpoint)]
        c_stats["candidates"] = len(sel)
        shape = _apply_by_bisection(shape, sel, lambda es, c: chamfer(es, c), (chamfer_c, chamfer_c / 2), "chamfer", c_stats, refused)

    rep.deltas = {"fillets": f_stats, "chamfers": c_stats, "refused_edges": refused}
    rep.lines.append(f"soften: fillets {f_stats['applied']}/{f_stats['candidates']} at r={fillet_r} "
                     f"({', '.join(f'{n} at {r}' for r, n in f_stats['by_size'].items()) or 'none'}), refused {f_stats['refused']}, lost {f_stats['lost']}")
    rep.lines.append(f"soften: chamfers {c_stats['applied']}/{c_stats['candidates']} at c={chamfer_c} "
                     f"({', '.join(f'{n} at {c}' for c, n in c_stats['by_size'].items()) or 'none'}), refused {c_stats['refused']}, lost {c_stats['lost']}")
    for r in refused:
        rep.warnings.append(f"{r['kind']} refused on a {r['length_mm']:.2f} mm edge at {tuple(r['midpoint'])}: {r['error']}")
    rep.changed = bool(f_stats["applied"] or c_stats["applied"])
    return shape, rep
