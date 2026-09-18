"""soften(): concave joints filleted, convex edges chamfered, exclusions kept sharp,
refusals halved and counted, never swallowed."""

import pytest

from agentcad.engines import get_engine, list_engines

pytestmark = pytest.mark.skipif("build123d" not in list_engines() or not get_engine("build123d").available(),
                                reason="build123d backend not available")


def _census(part):
    from build123d import GeomType
    out = {}
    for f in part.faces():
        out[f.geom_type.name.lower()] = out.get(f.geom_type.name.lower(), 0) + 1
    return out


def test_a_box_gains_twelve_chamfered_edges():
    from build123d import Box
    from agentcad.helpers import soften
    from agentcad.report import render_lines
    box = Box(20, 20, 20)
    out, rep = soften(box, fillet_r=1.0, chamfer_c=0.5)
    assert rep.deltas["fillets"]["candidates"] == 0            # a box has no inside corner
    assert rep.deltas["chamfers"]["applied"] == 12 and rep.deltas["chamfers"]["refused"] == 0
    assert len(out.faces()) == 6 + 12 + 8                        # faces, chamfer strips, corner triangles
    assert out.volume < box.volume
    assert box.volume == pytest.approx(8000.0)                   # the input was not touched
    assert any("chamfers 12/12" in line for line in render_lines(rep))


def test_an_l_bracket_gets_one_concave_fillet_and_convex_chamfers():
    from build123d import Box, Pos
    from agentcad.helpers import edge_sides, soften
    bracket = Box(30, 10, 4) + Pos(-13, 0, 10) * Box(4, 10, 16)   # a plate and an upright: one inside corner
    sides = edge_sides(bracket)
    assert sum(1 for s in sides if not s.convex) == 1
    out, rep = soften(bracket, fillet_r=1.0, chamfer_c=0.4)
    assert rep.deltas["fillets"] == {**rep.deltas["fillets"], "applied": 1, "refused": 0}
    assert "cylinder" in _census(out)                              # the fillet's face
    assert rep.deltas["chamfers"]["applied"] > 12 and rep.deltas["chamfers"]["refused"] == 0
    assert out.is_valid and len(out.solids()) == 1


def test_an_excluded_edge_stays_sharp():
    from build123d import Box
    from agentcad.helpers import soften
    box = Box(20, 20, 20)
    keep = [[-11, -11, 9, 11, 11, 11]]                             # the top face's four edges
    out, rep = soften(box, fillet_r=0, chamfer_c=0.5, exclude=keep)
    assert rep.deltas["chamfers"]["candidates"] == 8 and rep.deltas["chamfers"]["applied"] == 8
    # a chamfer strip along a top edge would have its centre at z = 9.75; none exists, so the
    # top face still meets the sides at a sharp edge (its corners are clipped by the vertical chamfers)
    assert not [f for f in out.faces() if 9.5 < f.center().Z < 10 - 1e-6]
    assert len([f for f in out.faces() if abs(f.center().Z - 10) < 1e-6]) == 1
    by_call, rep2 = soften(box, fillet_r=0, chamfer_c=0.5, exclude=lambda e, p: p.Z > 9)
    assert rep2.deltas["chamfers"]["applied"] == 8


def test_a_refused_radius_is_halved_then_counted():
    from build123d import Box, Pos
    from agentcad.helpers import soften
    # a 0.8 mm step on a plate: a 1.0 mm chamfer cannot build on the step's 0.8 mm tall outer
    # edges but a 0.5 mm one can; a 3 mm one refuses at both sizes on the step's edges
    part = Box(20, 20, 4) + Pos(0, 0, 2.4) * Box(16, 16, 0.8)
    out, rep = soften(part, fillet_r=0, chamfer_c=1.0)
    assert rep.deltas["chamfers"]["by_size"].get(0.5, 0) > 0     # some edges took the half size
    assert out.is_valid
    ch = rep.deltas["chamfers"]
    assert ch["applied"] + ch["refused"] + ch["lost"] == ch["candidates"]   # nothing dropped from the count
    out2, rep2 = soften(part, fillet_r=0, chamfer_c=3.0)
    assert rep2.deltas["chamfers"]["refused"] > 0
    refused = rep2.deltas["refused_edges"]
    assert refused and all({"kind", "length_mm", "midpoint", "sizes_tried", "error"} <= set(r) for r in refused)
    assert any(w.startswith("chamfer refused") for w in rep2.warnings)
    assert out2.is_valid                                           # refusals leave the shape as it was
