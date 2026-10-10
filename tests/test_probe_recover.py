"""RECOVER curves: arcs inside section loops, loops as pasteable chains, drawn intent.

Every fixture is synthetic and built here: polylines sampled exactly on known
circles, so the radius, centre and sweep a recovery must return are known to
rounding, and a deliberately broken tangent joint has a known size. Pure
geometry tests need no CAD backend; the ones that section a real shape skip
without build123d.
"""

import math
import random

import pytest

from agentcad import curves

# --- builders -----------------------------------------------------------------------------------

def rad(deg):
    return math.radians(deg)


def arc_vertices(c, r, a0, sweep, step_deg):
    """Vertices on the circle (centre c, radius r) from angle a0 through a signed sweep (degrees,
    negative is clockwise): the start included, the end left to the next arc."""
    n = max(2, int(math.ceil(abs(sweep) / step_deg)))
    return [(c[0] + r * math.cos(rad(a0 + sweep * k / n)), c[1] + r * math.sin(rad(a0 + sweep * k / n)))
            for k in range(n)]


def trefoil_arcs(r_t=4.0, r_v=6.0, big_r=10.0, valley_radius=None, broken=0):
    """Three convex lobes (radius r_t, counter-clockwise) and three concave valleys (radius r_v,
    clockwise) around a ring of radius big_r, every neighbouring pair externally tangent. With
    ``valley_radius`` the valley number ``broken`` keeps its end points but is drawn on a circle of that
    radius, so both of its joints stop being tangent. Returns [(kind, centre, radius, start angle, sweep)]
    in counter-clockwise loop order."""
    order = [("lobe", 90), ("valley", 150), ("lobe", 210), ("valley", 270), ("lobe", 330), ("valley", 30)]
    centres = [(big_r * math.cos(rad(a)), big_r * math.sin(rad(a))) for _, a in order]
    radii = [r_t if kind == "lobe" else r_v for kind, _ in order]
    n = len(order)
    tangent = []
    for k in range(n):
        here, there = centres[k], centres[(k + 1) % n]
        d = math.dist(here, there)
        assert abs(d - (radii[k] + radii[(k + 1) % n])) < 1e-9, "the fixture must be tangent before it is broken"
        tangent.append((here[0] + radii[k] * (there[0] - here[0]) / d, here[1] + radii[k] * (there[1] - here[1]) / d))
    arcs = []
    valley_seen = 0
    for k, (kind, _) in enumerate(order):
        c, r = centres[k], radii[k]
        p0, p1 = tangent[k - 1], tangent[k]
        if kind == "valley":
            if valley_radius is not None and valley_seen == broken:
                mid = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
                half = math.dist(p0, p1) / 2
                h = math.sqrt(valley_radius ** 2 - half ** 2)
                away = (c[0] - mid[0], c[1] - mid[1])
                norm = math.hypot(*away)
                c = (mid[0] + h * away[0] / norm, mid[1] + h * away[1] / norm)
                r = valley_radius
            valley_seen += 1
        a0 = math.degrees(math.atan2(p0[1] - c[1], p0[0] - c[0]))
        a1 = math.degrees(math.atan2(p1[1] - c[1], p1[0] - c[0]))
        sweep = (a1 - a0) % 360 if kind == "lobe" else -((a0 - a1) % 360)
        arcs.append((kind, c, r, a0, sweep))
    return arcs


def ring_vertices(arcs, step_deg=1.0):
    pts = []
    for _, c, r, a0, sweep in arcs:
        pts += arc_vertices(c, r, a0, sweep, step_deg)
    return pts


def lift(p, spec):
    """A 2D point as the 3D point a section on ``spec`` would carry."""
    axis, _, value = spec.partition("=")
    v = float(value)
    return {"x": [v, p[0], p[1]], "y": [p[0], v, p[1]], "z": [p[0], p[1], v]}[axis]


def line_edge(p, q, spec="z=0"):
    a, b = lift(p, spec), lift(q, spec)
    return {"type": "line", "start": a, "end": b, "length": math.dist(a, b),
            "center": None, "radius": None, "sweep_deg": None, "via": None}


def arc_edge(c, r, a0, sweep, spec="z=0"):
    """An exact circular edge as section_loops records it: start, end, centre, radius, the length-derived
    sweep and a point a quarter of the way along, which fixes the direction."""
    def at(a):
        return (c[0] + r * math.cos(rad(a)), c[1] + r * math.sin(rad(a)))
    return {"type": "circle", "start": lift(at(a0), spec), "end": lift(at(a0 + sweep), spec),
            "length": abs(rad(sweep)) * r, "center": lift(c, spec), "radius": r, "sweep_deg": abs(sweep),
            "via": lift(at(a0 + sweep / 4), spec)}


def loop_of(edges, closed=True):
    return {"edges": edges, "closed": closed, "n_edges": len(edges),
            "length": sum(e["length"] for e in edges), "fit": None}


def polyline_loop(points, spec="z=0", closed=True):
    n = len(points)
    last = n if closed else n - 1
    return loop_of([line_edge(points[k], points[(k + 1) % n], spec) for k in range(last)], closed)


def shoelace(points):
    return 0.5 * sum(points[k][0] * points[(k + 1) % len(points)][1] - points[(k + 1) % len(points)][0] * points[k][1]
                     for k in range(len(points)))


def slot_vertices(half=5.0, r=3.0, step_deg=2.0):
    """A stadium: a line along the bottom, a semicircle round each end, a line along the top; counter-clockwise."""
    return (arc_vertices((half, 0), r, -90, 180, step_deg) + [(half, r)]
            + arc_vertices((-half, 0), r, 90, 180, step_deg) + [(-half, -r)])


def match(arcs, kind, centre, radius):
    """The one recovered arc near a drawn one (by centre and rough radius); the caller then checks its numbers."""
    near = [s for s in arcs if s["kind"] == "arc" and math.dist(s["center"], centre) < 0.05 and abs(s["radius"] - radius) < 0.5]
    assert len(near) == 1, f"{kind} arc at {centre}: {len(near)} candidates in {arcs}"
    return near[0]


# --- the builders themselves ----------------------------------------------------------------------

def test_the_trefoil_fixture_is_closed_and_enclosed_counter_clockwise():
    arcs = trefoil_arcs()
    assert [round(a[4]) for a in arcs] == [240, -120, 240, -120, 240, -120]
    assert sum(a[4] for a in arcs) == pytest.approx(360.0)           # the tangent turns add to one revolution
    assert shoelace(ring_vertices(arcs)) > 0


# --- arcs -----------------------------------------------------------------------------------------

def test_a_polylined_trefoil_comes_back_as_six_arcs_of_the_radii_it_was_drawn_with():
    arcs = trefoil_arcs()
    rec = curves.recover_loop(polyline_loop(ring_vertices(arcs)), "z=0")
    got = rec["segments"]
    assert [s["kind"] for s in got] == ["arc"] * 6 and rec["closed"] and rec["orientation"] == "ccw"
    for kind, c, r, a0, sweep in arcs:
        s = match(got, kind, c, r)
        assert abs(s["radius"] - r) < 1e-3                             # the spec's gate
        assert abs(s["radius"] - r) < 1e-6                             # exact vertices give exact fits
        assert math.dist(s["center"], c) < 1e-6
        assert abs(s["sweep_deg"] - abs(sweep)) < 0.05
        assert s["direction"] == ("ccw" if kind == "lobe" else "cw")
        assert s["convex"] == (kind == "lobe")
        assert s["rms"] < 1e-6 and s["source"] == "fit"


def test_every_joint_of_a_correct_trefoil_is_judged_tangent_and_the_gap_is_stated():
    rec = curves.recover_loop(polyline_loop(ring_vertices(trefoil_arcs())), "z=0", tangent_tol=0.01)
    assert len(rec["joints"]) == 6
    for j in rec["joints"]:
        assert j["verdict"] == "tangent" and j["kind"] == "arc-arc"
        assert j["expected"] == "external"                              # a lobe turns the other way from a valley
        assert abs(j["gap"]) < 1e-6 and j["kink_deg"] < 0.01 and j["tol"] == 0.01
    assert rec["params"]["tangent_tol"] == 0.01
    assert curves.joint_counts(rec) == {"tangent": 6, "kinked": 0, "not tangent": 0, "corner": 0, "skipped": 0}


@pytest.mark.parametrize("valley_radius,verdict", [(7.0, "not tangent"), (6.1, "kinked")])
def test_a_deliberately_broken_joint_is_flagged_and_its_neighbours_are_not(valley_radius, verdict):
    arcs = trefoil_arcs(valley_radius=valley_radius, broken=0)
    rec = curves.recover_loop(polyline_loop(ring_vertices(arcs)), "z=0", tangent_tol=0.01)
    segs, joints = rec["segments"], rec["joints"]
    k = [i for i, s in enumerate(segs) if abs(s["radius"] - valley_radius) < 1e-3]
    assert len(k) == 1, "the re-drawn valley is recovered at the radius it was drawn with"
    k = k[0]
    flagged = {j["index"] for j in joints if j["verdict"] != "tangent"}
    assert flagged == {(k - 1) % 6, k}                                 # exactly the two joints on that valley
    for j in joints:
        if j["index"] in flagged:
            assert j["verdict"] == verdict
        else:
            assert j["verdict"] == "tangent" and abs(j["gap"]) < 1e-6 and j["kink_deg"] < 0.01
    if verdict == "kinked":
        # the gap is second order in the crossing angle: these circles cross at 1.6 degrees and their
        # centres are under a thousandth of a millimetre off the tangent distance, so by the gap alone
        # both joints would pass. They are not called "not tangent" (the stated test), but they are not
        # called tangent either.
        assert all(abs(j["gap"]) < 0.001 and 1.0 < j["kink_deg"] < 2.5 for j in joints if j["index"] in flagged)
    else:
        assert all(abs(j["gap"]) > 0.01 for j in joints if j["index"] in flagged)
    shown = curves.render_arcs(rec)
    word = "NOT TANGENT" if verdict == "not tangent" else "KINKED"
    assert sum(word in line for line in shown) == 2                    # one line per flagged joint, no more
    assert sum("NOT TANGENT" in line for line in shown) == (2 if verdict == "not tangent" else 0)


def test_a_hundredth_of_a_millimetre_of_radius_is_inside_the_stated_tolerance():
    """The opposite polarity: a gate that refuses everything is not a gate. A valley drawn 0.01 mm off
    crosses its lobes at 0.16 degrees with a gap of 1e-5 mm: tangent at the default tolerance, and not
    tangent at a tighter stated one."""
    arcs = trefoil_arcs(valley_radius=6.01, broken=0)
    loop = polyline_loop(ring_vertices(arcs))
    assert all(j["verdict"] == "tangent" for j in curves.recover_loop(loop, "z=0")["joints"])
    tight = curves.recover_loop(loop, "z=0", tangent_tol=1e-6)["joints"]
    assert sum(j["verdict"] == "not tangent" for j in tight) == 2


def test_the_vertex_order_and_the_start_do_not_change_the_answer():
    pts = ring_vertices(trefoil_arcs())
    base = curves.recover_loop(polyline_loop(pts), "z=0")["segments"]
    for variant in (list(reversed(pts)), pts[37:] + pts[:37], list(reversed(pts[91:] + pts[:91]))):
        rec = curves.recover_loop(polyline_loop(variant), "z=0")
        assert rec["orientation"] == "ccw"
        key = lambda segs: sorted((round(s["center"][0], 4), round(s["center"][1], 4), round(s["radius"], 4), s["direction"])
                                  for s in segs)
        assert key(rec["segments"]) == key(base)


def test_a_slot_is_two_lines_and_two_end_arcs_with_line_to_arc_tangency():
    pts = slot_vertices()
    rec = curves.recover_loop(polyline_loop(pts), "z=0")
    kinds = sorted(s["kind"] for s in rec["segments"])
    assert kinds == ["arc", "arc", "line", "line"]
    for s in rec["segments"]:
        if s["kind"] == "arc":
            assert abs(s["radius"] - 3.0) < 1e-3 and s["direction"] == "ccw" and s["convex"]
            assert abs(s["sweep_deg"] - 180.0) < 0.5
        else:
            assert abs(s["length"] - 10.0) < 1e-6 and s["rms"] < 1e-9
    assert all(j["verdict"] == "tangent" for j in rec["joints"])
    assert {j["kind"] for j in rec["joints"]} == {"arc-line", "line-arc"}


def test_a_polylined_circle_is_one_full_arc():
    pts = arc_vertices((3.0, -2.0), 7.5, 17.0, 360.0, 3.0)
    rec = curves.recover_loop(polyline_loop(pts), "z=0")
    (s,) = rec["segments"]
    assert s["kind"] == "arc" and abs(s["radius"] - 7.5) < 1e-3 and math.dist(s["center"], (3.0, -2.0)) < 1e-3
    assert abs(s["sweep_deg"] - 360.0) < 1e-6 and s["direction"] == "ccw"
    assert s["p0"] == s["p1"]                                          # a full circle starts and ends at one point
    assert rec["joints"][0]["verdict"] == "tangent"                    # the circle meets itself smoothly


def test_a_rectangle_is_four_lines_and_four_corners_never_an_arc():
    rec = curves.recover_loop(polyline_loop([(0, 0), (20, 0), (20, 10), (0, 10)]), "z=0")
    assert [s["kind"] for s in rec["segments"]] == ["line"] * 4
    assert [j["verdict"] for j in rec["joints"]] == ["corner"] * 4
    assert all(abs(j["kink_deg"] - 90.0) < 1e-6 for j in rec["joints"])


def test_a_regular_octagon_is_eight_lines_because_its_turns_are_corners():
    pts = [(10 * math.cos(rad(45 * k)), 10 * math.sin(rad(45 * k))) for k in range(8)]
    rec = curves.recover_loop(polyline_loop(pts), "z=0")
    assert [s["kind"] for s in rec["segments"]] == ["line"] * 8


def test_noise_leaves_the_structure_and_shows_up_as_rms():
    rng = random.Random(7)
    pts = [(x + rng.gauss(0, 2e-5), y + rng.gauss(0, 2e-5)) for x, y in ring_vertices(trefoil_arcs())]
    rec = curves.recover_loop(polyline_loop(pts), "z=0")
    assert [s["kind"] for s in rec["segments"]] == ["arc"] * 6
    for kind, c, r, a0, sweep in trefoil_arcs():
        s = match(rec["segments"], kind, c, r)
        assert abs(s["radius"] - r) < 5e-3
        assert 5e-6 < s["rms"] < 1e-4
    assert all(j["verdict"] == "tangent" for j in rec["joints"])


def test_the_section_planes_own_axes_decide_the_2d_frame():
    arcs = trefoil_arcs()
    spec = "y=2.5"
    rec = curves.recover_loop(polyline_loop(ring_vertices(arcs), spec=spec), spec)
    assert rec["axes"] == ["x", "z"]                                    # y= keeps (x, z), as the overlay draws it
    for kind, c, r, a0, sweep in arcs:
        s = match(rec["segments"], kind, c, r)
        assert abs(s["radius"] - r) < 1e-6
    assert curves.recover_loop(polyline_loop(ring_vertices(arcs), spec="x=-1"), "x=-1")["axes"] == ["y", "z"]
    assert rec["segments"][0]["p0"] is not None and len(rec["segments"][0]["p0"]) == 2


# --- exact edges ------------------------------------------------------------------------------------

def slot_edges(clockwise=False, spec="z=0"):
    """The slot of a plate as the section records it: two lines and two exact semicircles."""
    ccw = [arc_edge((5, 0), 3, -90, 180, spec), line_edge((5, 3), (-5, 3), spec),
           arc_edge((-5, 0), 3, 90, 180, spec), line_edge((-5, -3), (5, -3), spec)]
    if not clockwise:
        return ccw
    return [arc_edge((5, 0), 3, 90, -180, spec), line_edge((5, -3), (-5, -3), spec),
            arc_edge((-5, 0), 3, -90, -180, spec), line_edge((-5, 3), (5, 3), spec)]


@pytest.mark.parametrize("clockwise", [False, True])
def test_exact_arcs_keep_their_numbers_and_the_loop_is_read_counter_clockwise(clockwise):
    rec = curves.recover_loop(loop_of(slot_edges(clockwise)), "z=0")
    assert rec["orientation"] == "ccw"
    arcs = [s for s in rec["segments"] if s["kind"] == "arc"]
    assert len(arcs) == 2 and all(s["source"] == "edge" and s["rms"] == 0.0 for s in arcs)
    for s in arcs:
        assert s["radius"] == 3.0 and s["direction"] == "ccw" and s["convex"]
        assert abs(s["sweep_deg"] - 180.0) < 1e-9                       # a semicircle: the endpoints cannot say which way
    assert sorted(round(s["center"][0], 6) for s in arcs) == [-5.0, 5.0]
    assert all(j["verdict"] == "tangent" and abs(j["gap"]) < 1e-9 for j in rec["joints"])


def test_a_full_circle_edge_is_read_in_the_loops_direction():
    hole_cw = loop_of([arc_edge((1, 2), 4, 0, -360)])
    hole_ccw = loop_of([arc_edge((1, 2), 4, 0, 360)])
    for loop in (hole_cw, hole_ccw):
        (s,) = curves.recover_loop(loop, "z=0")["segments"]
        assert s["kind"] == "arc" and s["direction"] == "ccw" and abs(s["sweep_deg"] - 360.0) < 1e-9
        assert s["p0"] == s["p1"] and s["radius"] == 4.0


def test_a_half_disc_is_one_fitted_arc_and_the_long_edge_across_it():
    """A polylined semicircle and one long exact line: the run is fitted, the single edge passes through."""
    pts = arc_vertices((0, 0), 5, 0, 180, 2.0) + [(-5.0, 0.0)]
    edges = [line_edge(pts[k], pts[k + 1]) for k in range(len(pts) - 1)]
    edges.append(line_edge((-5, 0), (5, 0)))
    rec = curves.recover_loop(loop_of(edges), "z=0")
    assert sorted(s["kind"] for s in rec["segments"]) == ["arc", "line"]
    arc = [s for s in rec["segments"] if s["kind"] == "arc"][0]
    assert abs(arc["radius"] - 5.0) < 1e-6 and abs(arc["sweep_deg"] - 180.0) < 0.5


# --- what is reported rather than guessed ---------------------------------------------------------------

def test_an_edge_that_is_neither_a_line_nor_an_arc_is_reported_and_its_joints_are_skipped():
    edges = [line_edge((0, 0), (10, 0)),
             {"type": "bspline", "start": [10, 0, 0], "end": [10, 6, 0], "length": 6.4,
              "center": None, "radius": None, "sweep_deg": None, "via": None},
             line_edge((10, 6), (0, 6)), line_edge((0, 6), (0, 0))]
    rec = curves.recover_loop(loop_of(edges), "z=0")
    assert [u["type"] for u in rec["unsupported"]] == ["bspline"]
    assert rec["unsupported"][0]["start"] == [10.0, 0.0] and rec["unsupported"][0]["length"] == 6.4
    assert sorted(s["kind"] for s in rec["segments"]) == ["line", "line", "line", "other"]
    assert curves.joint_counts(rec) == {"tangent": 0, "kinked": 0, "not tangent": 0, "corner": 2, "skipped": 2}
    assert any("bspline" in line and "REPORTED" in line for line in curves.render_arcs(rec))


def test_a_circle_edge_without_a_direction_point_is_reported_not_guessed():
    e = arc_edge((0, 0), 3, 0, 180)
    e["via"] = None
    rec = curves.recover_loop(loop_of([e, line_edge((-3, 0), (3, 0))]), "z=0")
    assert [u["type"] for u in rec["unsupported"]] == ["circle"] and "direction" in rec["unsupported"][0]["why"]


def test_edges_that_do_not_close_are_said_to_be_open():
    rec = curves.recover_loop(polyline_loop([(0, 0), (4, 0), (4, 3)], closed=False), "z=0")
    assert rec["closed"] is False and rec["orientation"] is None
    assert any("open" in n for n in rec["notes"])
    assert [s["kind"] for s in rec["segments"]] == ["line", "line"]
    assert all(s.get("convex") is None for s in rec["segments"])


def test_the_report_names_each_arc_with_its_numbers_and_never_hides_a_cap():
    rec = curves.recover_loop(polyline_loop(ring_vertices(trefoil_arcs())), "z=0")
    text = "\n".join(curves.render_arcs(rec, show=3))
    assert "r 4.0000" in text and "ccw" in text and "cw" in text and "rms" in text and "convex" in text
    assert "3 more segment" in text and "not listed" in text           # six arcs, three shown: the cap is stated
    assert "fit-tol 0.005" in text and "tangent-tol 0.01" in text      # and so are the tolerances


# --- chains -------------------------------------------------------------------------------------------

import ast
import re

from agentcad import probe
from agentcad.engines import get_engine, list_engines

HAS_B123D = "build123d" in list_engines() and get_engine("build123d").available()
needs_build123d = pytest.mark.skipif(not HAS_B123D, reason="build123d backend not available")


def chain_face(chain, plane=None):
    """A Face from a chain literal, the way a program would use one: lines as lines, an arc as a three-point
    arc through its end points and the middle of its sweep, a full circle as a circle."""
    from build123d import Edge, Face, Location, Plane, Wire
    plane = plane or Plane.XY
    edges = []
    for seg in chain:
        if seg[0] == "line":
            edges.append(Edge.make_line(seg[1], seg[2]))
            continue
        _, (cx, cy), r, p0, p1, direction = seg
        if p0 == p1:
            edges.append(Edge.make_circle(r).moved(Location((cx, cy, 0))))
            continue
        a0, a1 = math.atan2(p0[1] - cy, p0[0] - cx), math.atan2(p1[1] - cy, p1[0] - cx)
        sweep = (a1 - a0) % (2 * math.pi) if direction == "ccw" else -((a0 - a1) % (2 * math.pi))
        mid = a0 + sweep / 2
        edges.append(Edge.make_three_point_arc(p0, (cx + r * math.cos(mid), cy + r * math.sin(mid)), p1))
    return Face(Wire(edges)).moved(Location(plane))


def literal_of(text, name="LOOP"):
    """The list a chain literal assigns, parsed (not executed) so the test reads exactly what a program would."""
    tree = ast.parse(text)
    (assign,) = [n for n in tree.body if isinstance(n, ast.Assign) and n.targets[0].id == name]
    return ast.literal_eval(assign.value)


def test_a_chain_literal_is_python_whose_segments_share_end_points_exactly():
    rec = curves.recover_loop(polyline_loop(slot_vertices()), "z=0")
    out = curves.chain_literal(rec, name="SLOT", header="loop 1 of z=0")
    chain = literal_of(out["text"], "SLOT")
    assert sorted(seg[0] for seg in chain) == ["arc", "arc", "line", "line"] and out["complete"]
    end = lambda seg: seg[2] if seg[0] == "line" else seg[4]
    start = lambda seg: seg[1] if seg[0] == "line" else seg[3]
    for k, seg in enumerate(chain):
        assert end(seg) == start(chain[(k + 1) % len(chain)])           # equal as numbers, wrap-around included
    arcs = [s for s in chain if s[0] == "arc"]
    assert all(abs(s[2] - 3.0) < 1e-3 and s[5] == "ccw" for s in arcs) and out["text"].startswith("# loop 1 of z=0")
    assert "Plane.XY" in out["text"]


def test_the_chain_names_the_plane_its_coordinates_belong_to():
    spec = "y=2.5"
    rec = curves.recover_loop(polyline_loop(slot_vertices(), spec=spec), spec)
    assert "Plane.XZ" in curves.chain_literal(rec)["text"]
    spec = "x=-1"
    rec = curves.recover_loop(polyline_loop(slot_vertices(), spec=spec), spec)
    assert "Plane.YZ" in curves.chain_literal(rec)["text"]


@needs_build123d
@pytest.mark.parametrize("make", ["trefoil", "slot", "exact_slot", "circle"])
def test_a_chain_literal_fed_to_build123d_closes_into_a_face_of_the_loops_area(make):
    if make == "trefoil":
        pts = ring_vertices(trefoil_arcs())
        loop, area = polyline_loop(pts), shoelace(pts)
    elif make == "slot":
        pts = slot_vertices()
        loop, area = polyline_loop(pts), shoelace(pts)
    elif make == "circle":
        pts = arc_vertices((3.0, -2.0), 7.5, 17.0, 360.0, 3.0)
        loop, area = polyline_loop(pts), shoelace(pts)
    else:
        loop, area = loop_of(slot_edges(clockwise=True)), math.pi * 9 + 60.0
    rec = curves.recover_loop(loop, "z=0")
    chain = literal_of(curves.chain_literal(rec)["text"])
    face = chain_face(chain)
    assert face.is_valid and abs(face.area - area) / area < 1e-3          # the gate: within 0.1 percent
    assert len(face.wires()) == 1 and face.wire().is_closed


@needs_build123d
def test_the_chain_of_a_plane_other_than_z_lands_on_the_sections_own_coordinates():
    from build123d import Plane
    spec = "y=2.5"
    rec = curves.recover_loop(polyline_loop(slot_vertices(), spec=spec), spec)
    face = chain_face(literal_of(curves.chain_literal(rec)["text"]), Plane.XZ)
    bb = face.bounding_box()
    assert (bb.min.X, bb.max.X) == pytest.approx((-8.0, 8.0), abs=1e-3)
    assert (bb.min.Z, bb.max.Z) == pytest.approx((-3.0, 3.0), abs=1e-3)       # (x, z): the slot lies along x


def chamfered_rectangle(c=0.01):
    """A 20 x 10 rectangle whose four corners each carry a 45 degree chamfer of leg ``c``: four long sides and
    four slivers of length c * sqrt(2)."""
    return [(c, 0), (20 - c, 0), (20, c), (20, 10 - c), (20 - c, 10), (c, 10), (0, 10 - c), (0, c)]


def test_slivers_shorter_than_the_stated_length_are_merged_and_counted():
    rec = curves.recover_loop(polyline_loop(chamfered_rectangle()), "z=0")
    assert len(rec["segments"]) == 8                                    # recovery keeps them: they are edges
    out = curves.chain_literal(rec, min_len=0.02)
    assert len(literal_of(out["text"])) == 4 and len(out["slivers"]) == 4
    assert all(s["length"] < 0.02 and s["kind"] == "line" for s in out["slivers"])
    assert "4 sliver(s) shorter than 0.02 mm merged" in out["text"]
    for k, seg in enumerate(out["segments"]):
        assert seg["p1"] == out["segments"][(k + 1) % 4]["p0"]
    kept = curves.chain_literal(rec, min_len=0.005)
    assert len(literal_of(kept["text"])) == 8 and kept["slivers"] == []


@needs_build123d
def test_a_chain_with_its_slivers_merged_still_makes_the_same_face():
    pts = chamfered_rectangle()
    rec = curves.recover_loop(polyline_loop(pts), "z=0")
    face = chain_face(literal_of(curves.chain_literal(rec, min_len=0.02)["text"]))
    assert abs(face.area - shoelace(pts)) / shoelace(pts) < 1e-3


def test_a_sliver_beside_an_unsupported_edge_is_kept_not_stretched_over_it():
    edges = [line_edge((0, 0), (10, 0)), line_edge((10, 0), (10.005, 0.005)),
             {"type": "bspline", "start": [10.005, 0.005, 0], "end": [10, 6, 0], "length": 6.1,
              "center": None, "radius": None, "sweep_deg": None, "via": None},
             line_edge((10, 6), (0, 6)), line_edge((0, 6), (0, 0))]
    rec = curves.recover_loop(loop_of(edges), "z=0")
    out = curves.chain_literal(rec, min_len=0.02)
    assert [s["length"] < 0.02 for s in out["segments"] if s["kind"] == "line"].count(True) <= 1
    assert out["complete"] is False


def test_an_edge_that_is_neither_a_line_nor_an_arc_is_reported_in_the_chain_and_never_straightened():
    edges = [line_edge((0, 0), (10, 0)),
             {"type": "bspline", "start": [10, 0, 0], "end": [10, 6, 0], "length": 6.4,
              "center": None, "radius": None, "sweep_deg": None, "via": None},
             line_edge((10, 6), (0, 6)), line_edge((0, 6), (0, 0))]
    rec = curves.recover_loop(loop_of(edges), "z=0")
    out = curves.chain_literal(rec)
    chain = literal_of(out["text"])
    assert out["complete"] is False and len(chain) == 3                  # three lines; the spline is NOT one of them
    assert not any(seg[0] == "line" and seg[1] == (10.0, 0.0) and seg[2] == (10.0, 6.0) for seg in chain)
    assert "REPORTED" in out["text"] and "bspline" in out["text"] and "INCOMPLETE" in out["text"]
    notes = curves.chain_notes(out)
    assert any("bspline" in n and "not turned into a line" in n for n in notes)
    gaps = [k for k, seg in enumerate(chain)
            if (seg[2] if seg[0] == "line" else seg[4]) != (chain[(k + 1) % 3][1] if chain[(k + 1) % 3][0] == "line" else chain[(k + 1) % 3][3])]
    assert len(gaps) == 1                                                 # the gap is where the spline was, and only there


def test_an_open_chain_is_emitted_with_the_word_open_and_no_wrap_around():
    rec = curves.recover_loop(polyline_loop([(0, 0), (4, 0), (4, 3)], closed=False), "z=0")
    out = curves.chain_literal(rec)
    assert "OPEN" in out["text"] and out["closed"] is False
    chain = literal_of(out["text"])
    assert chain[0][2] == chain[1][1] and chain[0][1] != chain[-1][2]


# --- the command: probe section --arcs / --chain on real shapes ----------------------------------------------

import json
import subprocess
import sys

from agentcad import cli

SLOT_PLATE = ("from build123d import *\n\n"
              "def build():\n"
              "    return Box(40, 20, 6) - extrude(SlotOverall(16, 6), amount=10, both=True)\n")
POLY_HOLE_PLATE = ("import math\n"
                   "from build123d import *\n\n"
                   "def build(n=120, r=7.5):\n"
                   "    pts = [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n)) for i in range(n)]\n"
                   "    with BuildPart() as hole:\n"
                   "        with BuildSketch():\n"
                   "            Polygon(*pts)\n"
                   "        extrude(amount=10, both=True)\n"
                   "    return Box(40, 30, 6) - hole.part\n")
TILTED_CYLINDER = "from build123d import *\n\ndef build():\n    return Cylinder(5, 30).rotate(Axis.X, 30)\n"
CHAMFERED_BAR = ("from build123d import *\n\n"
                 "def build():\n"
                 "    bar = Box(20, 10, 5)\n"
                 "    return chamfer(bar.edges().filter_by(Axis.Z), 0.01)\n")


@pytest.fixture
def program(tmp_path):
    def write(name, text):
        path = tmp_path / name
        path.write_text(text)
        return str(path)
    return write


@needs_build123d
def test_arcs_on_exact_edges_prints_each_arc_and_judges_its_joints(program, capsys):
    cli.main(["probe", "section", program("slot.py", SLOT_PLATE), "--planes", "z=0", "--arcs"])
    out = capsys.readouterr().out
    assert "z=0 (at 0): 2 loop(s)" in out and "recovered: 2 arc(s), 2 line(s)" in out
    assert len(re.findall(r"arc +ccw +convex +r 3\.0000", out)) == 2 and "exact edge" in out
    assert "joints: 4 tangent, 0 kinked, 0 not tangent" in out and "NOT TANGENT" not in out
    assert "recovered: 0 arc(s), 4 line(s)" in out and "joints: 0 tangent, 0 kinked, 0 not tangent, 4 corner" in out


@needs_build123d
def test_arcs_reads_a_hole_of_120_short_lines_as_one_arc_of_its_radius(program, tmp_path, capsys):
    out_json = tmp_path / "loops.json"
    cli.main(["probe", "section", program("holed.py", POLY_HOLE_PLATE), "--planes", "z=0", "--arcs", "-o", str(out_json)])
    text = capsys.readouterr().out
    assert "120 line" in text and "recovered: 1 arc(s), 0 line(s)" in text
    data = json.loads(out_json.read_text())
    hole = data["planes"][0]["loops"][1]
    (arc,) = hole["arcs"]["segments"]
    assert arc["kind"] == "arc" and abs(arc["radius"] - 7.5) < 1e-3 and abs(arc["sweep_deg"] - 360.0) < 1e-6
    assert math.dist(arc["center"], (0.0, 0.0)) < 1e-6 and arc["source"] == "fit" and arc["n"] >= 120
    assert hole["arcs"]["params"]["fit_tol"] == 0.005 and data["planes"][0]["loops"][0]["arcs"]["segments"][0]["kind"] == "line"


@needs_build123d
def test_the_loop_records_carry_the_point_that_gives_an_arc_its_direction(program, tmp_path, capsys):
    out_json = tmp_path / "loops.json"
    cli.main(["probe", "section", program("slot.py", SLOT_PLATE), "--planes", "z=0", "-o", str(out_json)])
    capsys.readouterr()
    edges = json.loads(out_json.read_text())["planes"][0]["loops"][1]["edges"]
    circles = [e for e in edges if e["type"] == "circle"]
    assert len(circles) == 2 and all(e["via"] is not None for e in circles)
    assert all(e["via"] is None for e in edges if e["type"] == "line")
    assert "arcs" not in json.loads(out_json.read_text())["planes"][0]["loops"][1]      # only asked for with --arcs


@needs_build123d
def test_chain_writes_only_the_literal_to_stdout_and_the_summary_to_stderr(program, capsys):
    rc = cli.main(["probe", "section", program("slot.py", SLOT_PLATE), "--planes", "z=0", "--chain", "2"])
    captured = capsys.readouterr()
    assert rc is None
    ast.parse(captured.out)                                              # stdout is a program, nothing else
    chain = literal_of(captured.out)
    assert sorted(seg[0] for seg in chain) == ["arc", "arc", "line", "line"]
    assert "loop(s)" in captured.err and "loop(s)" not in captured.out
    face = chain_face(chain)
    assert abs(face.area - (math.pi * 9 + 60.0)) / (math.pi * 9 + 60.0) < 1e-3


@needs_build123d
def test_chain_of_a_loop_that_does_not_exist_is_an_error_naming_the_count(program, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["probe", "section", program("slot.py", SLOT_PLATE), "--planes", "z=0", "--chain", "9"])
    assert exc.value.code == 2
    assert "z=0 has 2 loop(s); there is no loop 9" in capsys.readouterr().err


@needs_build123d
def test_chain_of_an_elliptical_section_is_reported_and_fails_instead_of_inventing_lines(program, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["probe", "section", program("tilt.py", TILTED_CYLINDER), "--planes", "z=0", "--chain", "1"])
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "REPORTED" in captured.out and "ellipse" in captured.out and "INCOMPLETE" in captured.out
    assert "not turned into a line" in captured.err
    assert literal_of(captured.out) == []                                # nothing was made up for it


@needs_build123d
def test_min_len_decides_which_slivers_a_chain_merges(program, capsys):
    path = program("bar.py", CHAMFERED_BAR)
    cli.main(["probe", "section", path, "--planes", "z=0", "--chain", "1", "--min-len", "0.02"])
    merged = capsys.readouterr()
    assert len(literal_of(merged.out)) == 4 and "4 sliver(s) shorter than 0.02 mm merged" in merged.out
    assert "merged a line of 0.0141 mm" in merged.err
    cli.main(["probe", "section", path, "--planes", "z=0", "--chain", "1", "--min-len", "0.005"])
    kept = capsys.readouterr()
    assert len(literal_of(kept.out)) == 8 and "0 sliver(s)" in kept.out


@needs_build123d
def test_with_several_planes_each_literal_is_named_for_its_plane(program, capsys):
    cli.main(["probe", "section", program("slot.py", SLOT_PLATE), "--planes", "z=0", "y=0", "--chain", "1"])
    out = capsys.readouterr().out
    assert "LOOP_Z_0 = [" in out and "LOOP_Y_0 = [" in out and "Plane.XZ" in out


@needs_build123d
def test_a_run_without_the_new_options_is_what_it_was(program, capsys):
    cli.main(["probe", "section", program("slot.py", SLOT_PLATE), "--planes", "z=0"])
    out = capsys.readouterr().out
    assert "recovered" not in out and "LOOP" not in out and "loop 2: length" in out


def test_the_tolerance_defaults_in_the_help_are_the_ones_the_code_uses():
    parser = cli.build_parser()
    section = [a for a in parser._actions if hasattr(a, "choices") and a.choices and "probe" in a.choices][0].choices["probe"]
    section = [a for a in section._actions if hasattr(a, "choices") and a.choices and "section" in a.choices][0].choices["section"]
    helps = {a.dest: a.help for a in section._actions}
    assert f"{curves.FIT_TOL:g}" in helps["fit_tol"] and f"{curves.TANGENT_TOL:g}" in helps["tangent_tol"]
    assert f"{curves.MIN_LEN:g}" in helps["min_len"]
