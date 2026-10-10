"""RECOVER, part two: the arcs and chains inside section loops.

A section loop of a mesh-converted body comes through as hundreds of short LINE
edges, and a loop of exact edges hides its construction (which arc is tangent to
which). This module reads a loop record (:func:`agentcad.probe.section_loops`) in the
section plane's own 2D frame and returns what the designer drew: lines and arcs, each
with its numbers, and a judged tangency at every joint.

The method is the one the curvature-run tool it grew from used (order the vertices,
read the signed turn at each, fit least-squares circles, test neighbouring arcs for
tangency), with a scale added so it can be trusted on other parts:

* the edges are chained head to tail and the loop is read counter-clockwise, so
  ``cw`` and ``ccw`` mean one thing whatever order the kernel listed the edges in;
* a vertex that turns more than ``corner_deg`` is a corner, never a sample of an arc;
* between corners a run of vertices grows while ONE line or ONE circle holds every
  vertex within ``fit_tol`` millimetres (a tolerance has a scale; a curvature
  threshold does not). A run grown that way swallows the first vertices of the next
  arc, because at a tangent joint position cannot yet tell the two apart, so every
  boundary is then moved to the position at which the two segments around it fit
  best, found by trying every position at which both still fit (and a short segment's
  two boundaries together);
* edges that are already exact lines or arcs pass through with their own numbers;
* edges that are neither are listed in ``unsupported`` and break the chain there,
  never guessed into lines.

A joint is judged from the fitted primitives alone: ``not tangent`` when the centre
distance is more than ``tangent_tol`` from the tangent one, ``kinked`` when it passes but
the curves cross at over a degree (the distance is second order in that angle), else
``tangent``; two lines meeting are a ``corner``.

Arcs report ``direction`` as seen in the 2D frame of :func:`agentcad.probe.plane_axes`
(the frame the overlays draw): ``ccw`` turns left. In a loop read counter-clockwise a
``ccw`` arc bulges outward (``convex``) and a ``cw`` arc bulges inward.

:func:`chain_literal` writes a recovered loop as a Python list a build123d program can paste:
``("line", p0, p1)`` and ``("arc", center, radius, p0, p1, direction)``, each segment ending at
exactly the numbers the next begins with.
"""

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from agentcad.probe import fit_circle, plane_axes

FIT_TOL = 0.005        # mm: how far a vertex may lie from the line or arc it is assigned to
TANGENT_TOL = 0.01     # mm: how far the centres may sit from the tangent distance
CORNER_DEG = 30.0      # a vertex turning more than this is a corner, not a sample of an arc
MIN_ARC_POINTS = 4     # fewer vertices than this always fit a circle, so they cannot show one
JOIN_TOL = 1e-3        # mm: end points this close are the same vertex when edges are chained
MIN_LEN = 0.02         # mm: segments shorter than this are slivers a chain merges into a neighbour
KINK_DEG = 1.0         # a joint whose gap passes but whose curves cross at more than this is called kinked
_AXES = "xyz"
_MAX_REFINE_ROUNDS = 12
_MAX_WINDOW = 60       # vertices each side of a boundary tried when it is refined
_SHORT = 8             # a segment of at most this many vertices has both its boundaries refined together
_SHORT_REACH = 3       # ... within this many vertices of where they are


def _pt(p: Sequence[float]) -> str:
    return f"({p[0]:.4f}, {p[1]:.4f})"


# --- chaining the edges of a loop ---------------------------------------------------------------

def _edge_items(loop: Dict[str, Any], axes: Tuple[int, int]) -> List[Dict[str, Any]]:
    """The loop's edges in the section plane's 2D frame. A circular edge keeps its centre, radius and
    the turn direction its quarter point fixes; a circle without them cannot be read and becomes ``other``."""
    i, j = axes

    def flat(p):
        return (float(p[i]), float(p[j]))

    items = []
    for k, e in enumerate(loop.get("edges", [])):
        it: Dict[str, Any] = {"edge": k, "type": e["type"], "kind": "other", "p0": flat(e["start"]),
                              "p1": flat(e["end"]), "length": float(e["length"]),
                              "why": f"{e['type']} edge is neither a line nor an arc"}
        if e["type"] == "line":
            it["kind"] = "line"
        elif e["type"] == "circle":
            if e.get("center") and e.get("radius") and e.get("via") and e.get("sweep_deg") is not None:
                c, v = flat(e["center"]), flat(e["via"])
                s = it["p0"]
                cross = (s[0] - c[0]) * (v[1] - c[1]) - (s[1] - c[1]) * (v[0] - c[0])
                it.update(kind="circle", center=c, radius=float(e["radius"]), sweep_deg=float(e["sweep_deg"]),
                          dir=1 if cross > 0 else -1)
            else:
                it["why"] = "circle edge without a center, radius or direction point"
        items.append(it)
    return items


def _flipped(it: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(it)
    out["p0"], out["p1"] = it["p1"], it["p0"]
    if "dir" in it:
        out["dir"] = -it["dir"]
    return out


def _chain_items(items: List[Dict[str, Any]], tol: float):
    """Items in head-to-tail order, each flipped as needed: (chain, closed, leftover item numbers).
    The next item is the unused one with an end point nearest the tail, so an order the kernel
    left alone is kept and one it scrambled is repaired."""
    if not items:
        return [], False, []
    cell = max(tol, 1e-12)
    grid: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
    for k, it in enumerate(items):
        for end, p in ((0, it["p0"]), (1, it["p1"])):
            grid.setdefault((math.floor(p[0] / cell), math.floor(p[1] / cell)), []).append((k, end))

    def near(p):
        cx, cy = math.floor(p[0] / cell), math.floor(p[1] / cell)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for k, end in grid.get((cx + dx, cy + dy), ()):
                    q = items[k]["p1" if end else "p0"]
                    d = math.dist(p, q)
                    if d <= tol:
                        yield d, k, end

    used = [False] * len(items)
    used[0] = True
    chain = [items[0]]
    head, tail = items[0]["p0"], items[0]["p1"]
    while True:
        cands = [c for c in near(tail) if not used[c[1]]]
        if not cands:
            break
        _, k, end = min(cands)
        used[k] = True
        it = _flipped(items[k]) if end == 1 else items[k]
        chain.append(it)
        tail = it["p1"]
    closed = math.dist(tail, head) <= tol
    return chain, closed, [k for k, u in enumerate(used) if not u]


def _signed_area(chain: List[Dict[str, Any]]) -> float:
    """Shoelace area of the chain with each arc sampled, counter-clockwise positive."""
    pts: List[Tuple[float, float]] = []
    for it in chain:
        pts.append(it["p0"])
        if it["kind"] == "circle":
            c, r = it["center"], it["radius"]
            a0 = math.atan2(it["p0"][1] - c[1], it["p0"][0] - c[0])
            sweep = it["dir"] * math.radians(it["sweep_deg"])
            pts += [(c[0] + r * math.cos(a0 + sweep * t / 16), c[1] + r * math.sin(a0 + sweep * t / 16))
                    for t in range(1, 16)]
    n = len(pts)
    return 0.5 * sum(pts[k][0] * pts[(k + 1) % n][1] - pts[(k + 1) % n][0] * pts[k][1] for k in range(n))


# --- polylines ------------------------------------------------------------------------------------

def _dedupe(P: np.ndarray, cyclic: bool) -> np.ndarray:
    """Drop vertices that repeat the one before (a zero-length edge has no direction)."""
    if len(P) < 2:
        return P
    keep = np.r_[True, np.hypot(*np.diff(P, axis=0).T) > 1e-9]
    P = P[keep]
    if cyclic and len(P) > 1 and math.dist(P[0], P[-1]) <= 1e-9:
        P = P[:-1]
    return P


def signed_curvature(P: np.ndarray, cyclic: bool = False) -> np.ndarray:
    """Discrete curvature at each vertex: 1/R of the circle through it and its two neighbours, positive
    where the chain turns left. Exact on vertices that lie on a circle; the one vertex where two arcs
    join reads between the two."""
    P = np.asarray(P, dtype=float)
    n = len(P)
    if n < 3:
        return np.zeros(n)
    a, b, c = np.roll(P, 1, axis=0), P, np.roll(P, -1, axis=0)
    ab, bc, ca = b - a, c - b, a - c
    cross = ab[:, 0] * bc[:, 1] - ab[:, 1] * bc[:, 0]
    den = np.hypot(*ab.T) * np.hypot(*bc.T) * np.hypot(*ca.T)
    with np.errstate(divide="ignore", invalid="ignore"):
        k = np.where(den > 0, 2.0 * cross / den, 0.0)
    if not cyclic:
        k[0], k[-1] = k[1], k[-2]
    return k


def _turns(P: np.ndarray, cyclic: bool, d_min: float) -> np.ndarray:
    """Signed turn in radians at every vertex, between the direction arriving from the nearest vertex at
    least ``d_min`` back along the chain and the one leaving toward the nearest vertex ``d_min`` ahead.
    The baseline keeps a micro-edge, whose direction is only rounding, from reading as a corner."""
    n = len(P)
    if n < 3:
        return np.zeros(n)
    Q = np.vstack([P, P, P]) if cyclic else P
    s = np.r_[0.0, np.cumsum(np.hypot(*np.diff(Q, axis=0).T))]
    last = len(Q) - 1
    back = np.clip(np.searchsorted(s, s - d_min, side="right") - 1, 0, last)
    fwd = np.clip(np.searchsorted(s, s + d_min, side="left"), 0, last)
    vin, vout = Q - Q[back], Q[fwd] - Q
    turn = np.arctan2(vin[:, 0] * vout[:, 1] - vin[:, 1] * vout[:, 0], vin[:, 0] * vout[:, 0] + vin[:, 1] * vout[:, 1])
    return turn[n:2 * n] if cyclic else turn


def _line_fit(Q: np.ndarray) -> Dict[str, Any]:
    c = Q.mean(axis=0)
    _, _, vt = np.linalg.svd(Q - c, full_matrices=False)
    res = (Q - c) @ vt[1]
    return {"point": c, "dir": vt[0], "normal": vt[1], "max": float(np.abs(res).max()),
            "rms": float(np.sqrt((res ** 2).mean())), "n": int(len(Q))}


def _classify(Q: np.ndarray, fit_tol: float, min_pts: int):
    """('line', fit) when one straight line holds every vertex within ``fit_tol``, else ('arc', fit) when
    one circle does and there are enough vertices to show one, else (None, None). A line is tried first:
    a nearly straight run is a line, not a circle of enormous radius."""
    line = _line_fit(Q)
    if line["max"] <= fit_tol:
        return "line", line
    if len(Q) >= min_pts:
        arc = fit_circle(Q)
        if arc and arc["max"] <= fit_tol:
            arc["center"] = np.asarray(arc["center"], dtype=float)
            return "arc", arc
    return None, None


def _grow(first: int, last: int, ok) -> int:
    """The last vertex of the longest run starting at ``first`` for which ``ok(first, end)`` holds:
    doubling steps, then bisection, because a long arc is hundreds of vertices and a fit per vertex
    would be quadratic."""
    end, step = first + 1, 4
    fail = None
    while end < last:
        nxt = min(end + step, last)
        if ok(first, nxt):
            end, step = nxt, step * 2
        else:
            fail = nxt
            break
    if fail is None:
        return end
    while fail - end > 1:
        mid = (end + fail) // 2
        if ok(first, mid):
            end = mid
        else:
            fail = mid
    return end


def _sse(model) -> float:
    return model[1]["n"] * model[1]["rms"] ** 2


def _refine(Q, segs, models, classify, floor):
    """Move each boundary to where the two segments around it fit best. A run grown greedily swallows the
    first vertices of the next arc, because at a tangent joint the position of a vertex cannot yet tell
    the two apart (within the tolerance); and a long straight edge plus a few of those vertices can pass
    for one shallow circle. One vertex at a time that state is a trap (the line fits worse than the
    circle), so every position the boundary could take is tried at once: the positions at which both
    segments still fit form one stretch around it (a neighbour's vertex soon lies past the tolerance),
    found by walking out from the boundary until a position fails, each fitted line-first. The position
    with the least total squared residual wins if it beats the current one by more than ``floor``. Each
    accepted move lowers a number that cannot go below zero, so the loop ends."""
    for _ in range(_MAX_REFINE_ROUNDS):
        moved = False
        for j in range(1, len(segs)):
            (a0, b), (_, b1) = segs[j - 1], segs[j]
            here = _sse(models[j - 1]) + _sse(models[j])
            reach = min(_MAX_WINDOW, max(3, (b1 - a0) // 3))
            trial: Dict[int, Any] = {b: (here, models[j - 1], models[j])}

            def cost(pos):
                if pos not in trial:
                    ml, mr = classify(a0, pos), classify(pos, b1)
                    trial[pos] = None if ml[0] is None or mr[0] is None else (_sse(ml) + _sse(mr), ml, mr)
                return trial[pos]

            for direction in (-1, 1):
                pos = b + direction
                while a0 < pos < b1 and abs(pos - b) <= reach and cost(pos) is not None:
                    pos += direction
            best_cost, best = min((c[0], pos) for pos, c in trial.items() if c is not None)
            if best != b and here - best_cost > floor:
                _, ml, mr = trial[best]
                segs[j - 1], segs[j] = (a0, best), (best, b1)
                models[j - 1], models[j] = ml, mr
                moved = True
        if _refine_short(segs, models, classify, floor):
            moved = True
        if not moved:
            break


def _refine_short(segs, models, classify, floor) -> bool:
    """A short segment between two neighbours can be wrong in a way neither of its boundaries can undo
    alone: at coarse sampling a short straight side and one vertex from each neighbour fit a shallow arc
    of four vertices, and giving back either vertex on its own leaves a piece of three that fits nothing.
    So the two boundaries are moved together, over a few positions each, and the best triple wins."""
    moved = False
    for j in range(1, len(segs) - 1):
        (a0, p0), (_, p1), (_, b1) = segs[j - 1], segs[j], segs[j + 1]
        if not 3 <= p1 - p0 + 1 <= _SHORT:
            continue
        here = sum(_sse(models[k]) for k in (j - 1, j, j + 1))
        left, right = {}, {}
        best = (here, None)
        for q0 in range(max(a0 + 1, p0 - _SHORT_REACH), min(b1 - 2, p0 + _SHORT_REACH) + 1):
            if q0 not in left:
                left[q0] = classify(a0, q0)
            if left[q0][0] is None:
                continue
            for q1 in range(max(q0 + 1, p1 - _SHORT_REACH), min(b1 - 1, p1 + _SHORT_REACH) + 1):
                if q1 not in right:
                    right[q1] = classify(q1, b1)
                if right[q1][0] is None:
                    continue
                mid = classify(q0, q1)
                if mid[0] is None:
                    continue
                cost = _sse(left[q0]) + _sse(mid) + _sse(right[q1])
                if cost < best[0] - floor:
                    best = (cost, (q0, q1, left[q0], mid, right[q1]))
        if best[1] is not None:
            q0, q1, ml, mm, mr = best[1]
            segs[j - 1], segs[j], segs[j + 1] = (a0, q0), (q0, q1), (q1, b1)
            models[j - 1], models[j], models[j + 1] = ml, mm, mr
            moved = True
    return moved


def _fit_chain(Q: np.ndarray, fit_tol: float, min_pts: int):
    """Segment an open chain with no corners in it: [(first, last, kind, fit)] with the vertex ``last`` of
    each segment shared as the ``first`` of the next."""
    m = len(Q)
    if m < 2:
        return []
    if m == 2:
        return [(0, 1, "line", _line_fit(Q))]

    def classify(a, b):
        return _classify(Q[a:b + 1], fit_tol, min_pts)

    def ok(a, b):
        # a run too short to be an arc may still become one, so it is allowed to grow
        return b - a + 1 < min_pts or classify(a, b)[0] is not None

    bounds, first = [0], 0
    while first < m - 1:
        last = _grow(first, m - 1, ok)
        while last > first + 1 and classify(first, last)[0] is None:
            last -= 1
        bounds.append(last)
        first = last
    segs = [(bounds[k], bounds[k + 1]) for k in range(len(bounds) - 1)]
    models = [classify(a, b) for a, b in segs]
    _refine(Q, segs, models, classify, (fit_tol / 500.0) ** 2)
    return [(a, b, kind, fit) for (a, b), (kind, fit) in zip(segs, models)]


def _fit_segment(Q: np.ndarray, a: int, b: int, kind: str, fit: Dict[str, Any]) -> Dict[str, Any]:
    run = Q[a:b + 1]
    p0, p1 = [float(v) for v in run[0]], [float(v) for v in run[-1]]
    if kind == "line":
        return {"kind": "line", "source": "edge" if b - a == 1 else "fit", "p0": p0, "p1": p1,
                "length": math.dist(p0, p1), "rms": fit["rms"], "max": fit["max"], "n": int(len(run)),
                "n_edges": b - a}
    c = fit["center"]
    ang = np.arctan2(run[:, 1] - c[1], run[:, 0] - c[0])
    step = (np.diff(ang) + math.pi) % (2 * math.pi) - math.pi
    sweep = float(step.sum())
    return {"kind": "arc", "source": "fit", "center": [float(c[0]), float(c[1])], "radius": float(fit["radius"]),
            "sweep_deg": abs(math.degrees(sweep)), "direction": "ccw" if sweep > 0 else "cw",
            "p0": p0, "p1": p1, "length": float(fit["radius"]) * abs(sweep), "rms": fit["rms"], "max": fit["max"],
            "n": int(len(run)), "n_edges": b - a}


def _segment_open(Q: np.ndarray, p: Dict[str, float]) -> List[Dict[str, Any]]:
    """Segments of an open chain: cut at every corner, fit what lies between."""
    turns = _turns(Q, False, p["d_min"])
    cuts = [0] + [i for i in range(1, len(Q) - 1) if abs(turns[i]) > p["corner_rad"]] + [len(Q) - 1]
    out: List[Dict[str, Any]] = []
    for lo, hi in zip(cuts, cuts[1:]):
        sub = Q[lo:hi + 1]
        out += [_fit_segment(sub, a, b, kind, fit) for a, b, kind, fit in _fit_chain(sub, p["fit_tol"], p["min_pts"])]
    return out


def _segment_ring(P: np.ndarray, p: Dict[str, float]) -> List[Dict[str, Any]]:
    """Segments of a closed polyline. With a corner the ring is opened there; with none it is opened at
    the largest jump in signed curvature (where one arc most likely gives way to another) and, when it
    breaks into several segments, once more at the first boundary found, so no arc is split by the cut."""
    if len(P) < 2:
        return []
    turns = _turns(P, True, p["d_min"])
    corners = np.flatnonzero(np.abs(turns) > p["corner_rad"])
    if len(corners):
        start = int(corners[0])
        return _segment_open(np.vstack([np.roll(P, -start, axis=0), P[start]]), p)

    def opened(at):
        Q = np.vstack([np.roll(P, -at, axis=0), P[at]])
        return Q, _fit_chain(Q, p["fit_tol"], p["min_pts"])

    kap = signed_curvature(P, True)
    at = int(np.argmax(np.abs(kap - np.roll(kap, 1))))            # the largest jump: where one curvature gives way to another
    Q, segs = opened(at)
    if len(segs) > 1:
        at = (at + segs[0][1]) % len(P)
        Q, segs = opened(at)
    return [_fit_segment(Q, a, b, kind, fit) for a, b, kind, fit in segs]


# --- joints ---------------------------------------------------------------------------------------

def _joint(a: Dict[str, Any], b: Dict[str, Any], k: int, to: int, tol: float) -> Dict[str, Any]:
    """The judged tangency of two neighbouring segments, from the fitted primitives alone: where a fit
    happened to end must not decide it (one vertex of a 1 degree step on a 4 mm arc is 0.07 mm).

    Arcs: the centres sit |r1-r2| apart when they turn the same way, r1+r2 when they turn opposite ways;
    ``gap`` is how far they are from that. An arc and a line: the line sits r from the centre. The
    ``kink`` is the angle at which the two curves cross (the law of cosines on r1, r2 and the centre
    distance; for a line, acos(distance/r)); it is None when they do not cross at all. The gap is second
    order in the kink, so two circles crossing at 1.6 degrees have centres only 0.001 mm off the tangent
    distance. So the verdict has three levels: ``not tangent`` when the gap is beyond ``tol`` (the
    stated test, and noise-proof: it does not fire on data with 3e-4 mm of scatter), ``kinked`` when the
    gap passes but the curves cross at more than KINK_DEG (real, but a few percent of tangent joints
    show it at 1e-4 mm of scatter, so it is a different word), and ``tangent``."""
    joint: Dict[str, Any] = {"index": k, "to": to, "kind": "skipped", "verdict": "skipped", "gap": None,
                             "expected": None, "distance": None, "expected_distance": None, "kink_deg": None,
                             "tol": tol}
    if a["kind"] == "other" or b["kind"] == "other":
        return joint
    joint["kind"] = f"{a['kind']}-{b['kind']}"
    if a["kind"] == "line" and b["kind"] == "line":
        ta = (a["p1"][0] - a["p0"][0], a["p1"][1] - a["p0"][1])
        tb = (b["p1"][0] - b["p0"][0], b["p1"][1] - b["p0"][1])
        joint["kink_deg"] = math.degrees(math.atan2(abs(ta[0] * tb[1] - ta[1] * tb[0]), ta[0] * tb[0] + ta[1] * tb[1]))
        joint["verdict"] = "corner"
        return joint
    if a["kind"] == "arc" and b["kind"] == "arc":
        r1, r2 = a["radius"], b["radius"]
        d = math.dist(a["center"], b["center"])
        same = a["direction"] == b["direction"]
        joint["expected"] = "internal" if same else "external"
        expected = abs(r1 - r2) if same else r1 + r2
        cos = (r1 * r1 + r2 * r2 - d * d) / (2.0 * r1 * r2)        # angle between the two radii where they meet
        if abs(cos) <= 1.0 + 1e-12:
            psi = math.degrees(math.acos(max(-1.0, min(1.0, cos))))
            joint["kink_deg"] = psi if same else 180.0 - psi
    else:
        arc, line = (a, b) if a["kind"] == "arc" else (b, a)
        t = (line["p1"][0] - line["p0"][0], line["p1"][1] - line["p0"][1])
        n = math.hypot(*t) or 1.0
        off = (arc["center"][0] - line["p0"][0], arc["center"][1] - line["p0"][1])
        d = abs(t[0] * off[1] - t[1] * off[0]) / n
        r1, expected = arc["radius"], arc["radius"]
        joint["expected"] = "line"
        if d <= r1 * (1.0 + 1e-12):
            joint["kink_deg"] = math.degrees(math.acos(min(1.0, d / r1)))
    joint["distance"], joint["expected_distance"] = d, expected
    joint["gap"] = d - expected
    if abs(joint["gap"]) > tol:
        joint["verdict"] = "not tangent"
    else:
        joint["verdict"] = "kinked" if (joint["kink_deg"] or 0.0) > KINK_DEG else "tangent"
    return joint


def joint_counts(rec: Dict[str, Any]) -> Dict[str, int]:
    counts = {"tangent": 0, "kinked": 0, "not tangent": 0, "corner": 0, "skipped": 0}
    for j in rec["joints"]:
        counts[j["verdict"]] += 1
    return counts


# --- one loop ---------------------------------------------------------------------------------

def recover_loop(loop: Dict[str, Any], spec: str, fit_tol: float = FIT_TOL, tangent_tol: float = TANGENT_TOL,
                 corner_deg: float = CORNER_DEG, min_arc_points: int = MIN_ARC_POINTS,
                 join_tol: float = JOIN_TOL) -> Dict[str, Any]:
    """The lines and arcs of one section loop, with a verdict at each joint.

    ``loop`` is a record from :func:`agentcad.probe.section_loops` and ``spec`` the plane it was cut
    on (``z=3``), which fixes the 2D frame. Returns a JSON-ready record:

    ``segments``    in loop order starting at the lowest-left joint; each ``{"kind": "arc"|"line"|"other", ...}``
                    with ``p0``/``p1`` and, for an arc, ``center``, ``radius``, ``sweep_deg``, ``direction``,
                    ``convex``; ``rms``/``max`` are the vertex distances to the fitted primitive (0 for an
                    exact edge) and ``source`` says whether it was fitted or passed through;
    ``joints``      one per neighbouring pair: ``verdict`` tangent | kinked | not tangent | corner | skipped,
                    the ``gap`` between the centre distance and the tangent one (|r1-r2| for arcs turning
                    the same way, r1+r2 for opposite ways, r for an arc and a line) and ``kink_deg``, the
                    angle at which the two curves cross (None if they do not), both read off the fitted
                    primitives and never off the vertex a fit ended at; ``not tangent`` is ``gap`` beyond
                    ``tangent_tol``, ``kinked`` is a passing gap with a crossing over KINK_DEG;
    ``unsupported`` edges that are neither a line nor an arc, each with its type, ends and length;
    ``closed`` / ``orientation`` / ``notes`` / ``params`` / ``axes``.
    """
    axes = plane_axes(spec)
    p = {"fit_tol": float(fit_tol), "tangent_tol": float(tangent_tol), "kink_deg": KINK_DEG,
         "corner_deg": float(corner_deg), "min_arc_points": int(min_arc_points), "join_tol": float(join_tol)}
    rec: Dict[str, Any] = {"axes": [_AXES[axes[0]], _AXES[axes[1]]], "closed": False, "orientation": None,
                           "params": p, "segments": [], "joints": [], "unsupported": [], "notes": [],
                           "n_edges": len(loop.get("edges", []))}
    items = _edge_items(loop, axes)
    chain, closed, leftover = _chain_items(items, join_tol)
    if not chain:
        rec["notes"].append("the loop has no edges")
        return rec
    rec["closed"] = closed
    if leftover:
        rec["notes"].append(f"{len(leftover)} of {len(items)} edge(s) did not join this chain "
                            f"(edges {', '.join(str(items[k]['edge']) for k in leftover[:8])}"
                            f"{', ...' if len(leftover) > 8 else ''}) and are left out")
    if not closed:
        rec["notes"].append(f"the chain is open: its ends are {math.dist(chain[-1]['p1'], chain[0]['p0']):.4g} mm apart")
    else:
        area = _signed_area(chain)
        if area != 0.0:                                     # a lone ellipse has no area to read a sense from
            rec["orientation"] = "ccw"
            if area < 0:
                chain = [_flipped(it) for it in reversed(chain)]

    sp = {"fit_tol": float(fit_tol), "corner_rad": math.radians(corner_deg), "min_pts": int(min_arc_points),
          "d_min": max(4.0 * float(fit_tol), 1e-6)}
    is_line = [it["kind"] == "line" for it in chain]
    ring = closed and all(is_line)
    if closed and not ring and is_line[0]:
        r = is_line.index(False)
        chain = chain[r:] + chain[:r]

    segments: List[Dict[str, Any]] = []
    run: List[Dict[str, Any]] = []

    def flush():
        if not run:
            return
        if ring:
            segments.extend(_segment_ring(_dedupe(np.array([it["p0"] for it in run], dtype=float), True), sp))
        else:
            pts = np.array([run[0]["p0"]] + [it["p1"] for it in run], dtype=float)
            segments.extend(_segment_open(_dedupe(pts, False), sp))
        run.clear()

    for it in chain:
        if it["kind"] == "line":
            run.append(it)
            continue
        flush()
        if it["kind"] == "circle":
            full = it["sweep_deg"] >= 359.999 and math.dist(it["p0"], it["p1"]) <= join_tol
            segments.append({"kind": "arc", "source": "edge", "center": list(it["center"]), "radius": it["radius"],
                             "sweep_deg": it["sweep_deg"], "direction": "ccw" if it["dir"] > 0 else "cw",
                             "p0": list(it["p0"]), "p1": list(it["p0"] if full else it["p1"]), "length": it["length"],
                             "rms": 0.0, "max": 0.0, "n": None, "n_edges": 1})
        else:
            segments.append({"kind": "other", "source": "edge", "type": it["type"], "p0": list(it["p0"]),
                             "p1": list(it["p1"]), "length": it["length"], "n_edges": 1})
            rec["unsupported"].append({"edge": it["edge"], "type": it["type"], "start": list(it["p0"]),
                                       "end": list(it["p1"]), "length": it["length"],
                                       "why": it["why"]})
    flush()
    if not segments:
        rec["notes"].append("nothing could be read: the edges have no length")
        return rec

    n = len(segments)
    if closed and n > 1:
        for k in range(n):                                   # neighbours share one end point exactly
            prev = segments[k - 1]
            if math.dist(segments[k]["p0"], prev["p1"]) <= join_tol:
                segments[k]["p0"] = list(prev["p1"])
        low = min(range(n), key=lambda k: (round(segments[k]["p0"][0], 6), round(segments[k]["p0"][1], 6)))
        segments = segments[low:] + segments[:low]
    for k, s in enumerate(segments):
        s["index"] = k
        if s["kind"] == "arc":
            s["convex"] = (s["direction"] == "ccw") if rec["orientation"] == "ccw" else None
    rec["segments"] = segments
    pairs = range(n) if closed else range(n - 1)
    rec["joints"] = [_joint(segments[k], segments[(k + 1) % n], k, (k + 1) % n, tangent_tol) for k in pairs]
    return rec


# --- reading the result --------------------------------------------------------------------------

def _segment_line(s: Dict[str, Any]) -> str:
    n = s["index"] + 1
    if s["kind"] == "other":
        return f"  {n:>3} {s['type']}  {_pt(s['p0'])} -> {_pt(s['p1'])}  length {s['length']:.4f}  (REPORTED, not recovered)"
    origin = "exact edge" if s["source"] == "edge" else f"fitted to {s['n']} vertices"
    if s["kind"] == "line":
        return (f"  {n:>3} line {_pt(s['p0'])} -> {_pt(s['p1'])}  length {s['length']:.4f}  "
                f"rms {s['rms']:.2g} max {s['max']:.2g}  ({origin})")
    convex = {True: "convex", False: "concave", None: ""}[s.get("convex")]
    return (f"  {n:>3} arc  {s['direction']:<3} {convex:<7} r {s['radius']:.4f}  center {_pt(s['center'])}  "
            f"sweep {s['sweep_deg']:.2f} deg  rms {s['rms']:.2g} max {s['max']:.2g}  ({origin})")


def _joint_line(j: Dict[str, Any]) -> str:
    a, b = j["index"] + 1, j["to"] + 1
    if j["verdict"] == "skipped":
        return f"  {a}->{b} skipped: a neighbour is not a line or an arc"
    if j["verdict"] == "corner":
        return f"  {a}->{b} corner: two lines meet turning {j['kink_deg']:.2f} deg"
    if j["kind"] == "arc-arc":
        rule = "r1+r2" if j["expected"] == "external" else "|r1-r2|"
        what = f"centers {j['distance']:.4f} apart vs {rule} {j['expected_distance']:.4f}"
    else:
        what = f"center to line {j['distance']:.4f} vs r {j['expected_distance']:.4f}"
    tag = {"tangent": "tangent", "kinked": "KINKED", "not tangent": "NOT TANGENT"}[j["verdict"]]
    kink = "the curves do not cross" if j["kink_deg"] is None else f"they cross at {j['kink_deg']:.2f} deg"
    note = f" (over {KINK_DEG:g} deg: the centres are within tol but the directions differ)" if j["verdict"] == "kinked" else ""
    return f"  {a}->{b} {tag} ({j['kind']}): {what}, gap {j['gap']:+.4f} (tol {j['tol']:g} mm); {kink}{note}"


def render_arcs(rec: Dict[str, Any], show: int = 12) -> List[str]:
    """Lines for the terminal: the segments, then the joints with every one that is not tangent first.
    A cap is printed with its value; the JSON record has everything."""
    p, segs = rec["params"], rec["segments"]
    n_arc = sum(s["kind"] == "arc" for s in segs)
    n_line = sum(s["kind"] == "line" for s in segs)
    sense = {"ccw": "read counter-clockwise", None: "open chain, read as listed"}[rec["orientation"]]
    lines = [f"recovered: {n_arc} arc(s), {n_line} line(s), {sense}; axes ({rec['axes'][0]}, {rec['axes'][1]}); "
             f"fit-tol {p['fit_tol']:g} mm, tangent-tol {p['tangent_tol']:g} mm"]
    lines += [_segment_line(s) for s in segs[:show]]
    if len(segs) > show:
        lines.append(f"  ... {len(segs) - show} more segments not listed (--show {show}; -o writes all)")
    for u in rec["unsupported"]:
        lines.append(f"  REPORTED: edge {u['edge']} is a {u['type']} ({_pt(u['start'])} -> {_pt(u['end'])}, length "
                     f"{u['length']:.4f}): {u['why']}; it is not turned into a line")
    for note in rec["notes"]:
        lines.append(f"  note: {note}")
    if rec["joints"]:
        c = joint_counts(rec)
        lines.append(f"joints: {c['tangent']} tangent, {c['kinked']} kinked, {c['not tangent']} not tangent, "
                     f"{c['corner']} corner, {c['skipped']} skipped")
        rank = {"not tangent": 0, "kinked": 1, "tangent": 2, "corner": 3, "skipped": 4}
        order = sorted(rec["joints"], key=lambda j: (rank[j["verdict"]], j["index"]))
        lines += [_joint_line(j) for j in order[:show]]
        if len(order) > show:
            lines.append(f"  ... {len(order) - show} more joints not listed (--show {show}; -o writes all)")
    return lines


# --- a loop as a pasteable chain -------------------------------------------------------------------

def _arc_sweep(seg: Dict[str, Any]) -> float:
    """Degrees an arc turns from ``p0`` to ``p1`` about its center in its own direction (360 if closed)."""
    c, a, b = seg["center"], seg["p0"], seg["p1"]
    if a == b:
        return 360.0
    a0, a1 = math.atan2(a[1] - c[1], a[0] - c[0]), math.atan2(b[1] - c[1], b[0] - c[0])
    return math.degrees((a1 - a0 if seg["direction"] == "ccw" else a0 - a1) % (2 * math.pi))


def _remeasured(seg: Dict[str, Any]) -> None:
    if seg["kind"] == "line":
        seg["length"] = math.dist(seg["p0"], seg["p1"])
    elif seg["kind"] == "arc":
        seg["sweep_deg"] = _arc_sweep(seg)
        seg["length"] = seg["radius"] * math.radians(seg["sweep_deg"])


def _support(seg: Dict[str, Any], pt: Sequence[float]) -> Tuple[float, Tuple[float, float]]:
    """Signed distance from ``pt`` to the infinite line or circle a segment lies on, and its gradient."""
    if seg["kind"] == "line":
        dx, dy = seg["p1"][0] - seg["p0"][0], seg["p1"][1] - seg["p0"][1]
        n = math.hypot(dx, dy) or 1.0
        gx, gy = -dy / n, dx / n
        return (pt[0] - seg["p0"][0]) * gx + (pt[1] - seg["p0"][1]) * gy, (gx, gy)
    vx, vy = pt[0] - seg["center"][0], pt[1] - seg["center"][1]
    r = math.hypot(vx, vy) or 1e-12
    return r - seg["radius"], (vx / r, vy / r)


def _corner(a: Dict[str, Any], b: Dict[str, Any], start: Sequence[float], reach: float) -> List[float]:
    """The point where the lines or circles two neighbours lie on meet (the corner a sliver was a chamfer
    of), found from ``start`` by Newton steps on the two distances. If they do not meet near the sliver
    (parallel, or tangent, so the corner is ill-conditioned) the sliver's own midpoint is kept."""
    pt = np.array(start, dtype=float)
    for _ in range(12):
        da, ga = _support(a, pt)
        db, gb = _support(b, pt)
        step, *_ = np.linalg.lstsq(np.array([ga, gb]), -np.array([da, db]), rcond=None)
        pt = pt + step
        if math.hypot(*step) < 1e-12:
            break
    if math.dist(pt, start) > reach or abs(_support(a, pt)[0]) > 1e-6 or abs(_support(b, pt)[0]) > 1e-6:
        return [float(start[0]), float(start[1])]
    return [float(pt[0]), float(pt[1])]


def _merge_slivers(segs: List[Dict[str, Any]], closed: bool, min_len: float):
    """Remove every line or arc shorter than ``min_len``. Between two neighbours that are lines or arcs
    the joint moves to where they meet, so neither is tilted; next to an unsupported edge the other
    neighbour runs on to cover the sliver. The shortest goes first. A sliver whose neighbours are both
    unsupported edges stays: covering it would hide the gap."""
    segs = [dict(s, uid=k) for k, s in enumerate(segs)]
    merged: List[Dict[str, Any]] = []
    stuck = set()
    while len(segs) > (2 if closed else 1):
        small = [k for k, s in enumerate(segs) if s["kind"] != "other" and s["length"] < min_len and s["uid"] not in stuck]
        if not small:
            break
        k = min(small, key=lambda i: segs[i]["length"])
        n = len(segs)
        sliver = segs[k]
        prev = (k - 1) % n if (k > 0 or closed) else None
        nxt = (k + 1) % n if (k < n - 1 or closed) else None
        usable = lambda i: i is not None and segs[i]["kind"] != "other"
        if usable(prev) and usable(nxt):
            mid = [(sliver["p0"][0] + sliver["p1"][0]) / 2, (sliver["p0"][1] + sliver["p1"][1]) / 2]
            joint = _corner(segs[prev], segs[nxt], mid, 3.0 * min_len)
            segs[prev]["p1"], segs[nxt]["p0"] = list(joint), list(joint)
            _remeasured(segs[prev])
            _remeasured(segs[nxt])
        elif usable(prev):
            segs[prev]["p1"] = list(sliver["p1"])
            _remeasured(segs[prev])
        elif usable(nxt):
            segs[nxt]["p0"] = list(sliver["p0"])
            _remeasured(segs[nxt])
        else:
            stuck.add(sliver["uid"])
            continue
        merged.append({"kind": sliver["kind"], "length": sliver["length"], "at": list(sliver["p0"])})
        del segs[k]
    return segs, merged


def chain_literal(rec: Dict[str, Any], name: str = "LOOP", min_len: float = MIN_LEN, digits: int = 4,
                  header: Optional[str] = None) -> Dict[str, Any]:
    """A recovered loop as a Python literal to paste into a build123d program::

        LOOP = [
            ("arc", (5.0, 0.0), 3.0, (5.0, -3.0), (5.0, 3.0), "ccw"),     # center, radius, p0, p1, direction
            ("line", (5.0, 3.0), (-5.0, 3.0)),
            ...
        ]

    in the section plane's 2D frame, counter-clockwise, ``p0 == p1`` meaning the full circle. Every
    segment ends at the same numbers the next one begins with (each joint is rounded once and used for
    both), and segments shorter than ``min_len`` are removed, the joint moving to where their neighbours
    meet, and listed. An edge that
    is neither a line nor an arc is left out of the list as a visible gap with a comment saying what it
    was, never straightened into a line; the result then says ``complete: False``.

    Returns ``{"text", "segments", "slivers", "unsupported", "complete", "closed", ...}``.
    """
    closed = rec["closed"]
    segs, slivers = _merge_slivers(rec["segments"], closed, float(min_len))
    n = len(segs)

    def rounded(pt):
        return (round(pt[0], digits) + 0.0, round(pt[1], digits) + 0.0)     # + 0.0 turns -0.0 into 0.0

    joints = [rounded(sg["p0"]) for sg in segs]
    out_segs: List[Dict[str, Any]] = []
    for k, sg in enumerate(segs):
        nxt = k + 1 if k + 1 < n else (0 if closed else None)
        end = joints[nxt] if nxt is not None else rounded(sg["p1"])
        o = dict(sg, p0=joints[k], p1=end)
        if sg["kind"] == "arc":
            o["center"], o["radius"] = rounded(sg["center"]), round(sg["radius"], digits)
        out_segs.append(o)

    def num(v):
        return f"{v:.{digits}f}"

    def pt(v):
        return f"({num(v[0])}, {num(v[1])})"

    body = []
    for o in out_segs:
        if o["kind"] == "line":
            body.append(f'    ("line", {pt(o["p0"])}, {pt(o["p1"])}),')
        elif o["kind"] == "arc":
            body.append(f'    ("arc", {pt(o["center"])}, {num(o["radius"])}, {pt(o["p0"])}, {pt(o["p1"])}, "{o["direction"]}"),')
        else:
            body.append(f'    # REPORTED: a {o["type"]} edge from {pt(o["p0"])} to {pt(o["p1"])}, length {num(o["length"])}: '
                        f"not a line or an arc, so it is not in this list")
    n_line = sum(o["kind"] == "line" for o in out_segs)
    n_arc = sum(o["kind"] == "arc" for o in out_segs)
    u, v = rec["axes"]
    plane = (u + v).upper()
    lines = [f"# {header or 'loop'}: {n_line + n_arc} segment(s) ({n_line} line, {n_arc} arc), "
             f"{'counter-clockwise' if rec['orientation'] == 'ccw' else 'in the order listed'}; "
             f"coordinates are ({u}, {v}) in mm: build on Plane.{plane}",
             '# ("arc", center, radius, p0, p1, direction): p0 == p1 is the full circle; each segment ends where the next begins',
             f"# recovered with fit-tol {rec['params']['fit_tol']:g} mm; {len(slivers)} sliver(s) shorter than {min_len:g} mm merged"]
    complete = not rec["unsupported"] and bool(out_segs)
    if rec["unsupported"]:
        lines.append(f"# INCOMPLETE: {len(rec['unsupported'])} edge(s) are neither a line nor an arc (REPORTED below); "
                     "the list has a gap at each")
    if not closed:
        lines.append("# OPEN chain: the edges do not close, so the last segment does not end where the first begins")
    lines.append(f"{name} = [")
    lines += body
    lines.append("]")
    return {"text": "\n".join(lines) + "\n", "name": name, "segments": out_segs, "slivers": slivers,
            "unsupported": rec["unsupported"], "complete": complete, "closed": closed, "digits": digits,
            "min_len": float(min_len), "notes": list(rec["notes"])}


def chain_notes(result: Dict[str, Any]) -> List[str]:
    """What a chain left out or changed, as lines for the terminal (the literal carries them as comments too)."""
    lines = []
    for sl in result["slivers"]:
        lines.append(f"chain: merged a {sl['kind']} of {sl['length']:.4f} mm at {_pt(sl['at'])} (shorter than "
                     f"{result['min_len']:g} mm) into its neighbour")
    for un in result["unsupported"]:
        lines.append(f"REPORTED: edge {un['edge']} is a {un['type']} ({_pt(un['start'])} -> {_pt(un['end'])}, length "
                     f"{un['length']:.4f}): {un['why']}; it is not turned into a line, so the chain has a gap there")
    lines += [f"chain: {n}" for n in result["notes"]]
    if not result["closed"]:
        lines.append("chain: the edges do not close; the list is an open chain")
    return lines
