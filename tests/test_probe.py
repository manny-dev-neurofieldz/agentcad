"""RECOVER and COMPARE on small exact shapes: section loops, the arc fit,
cylinder axes, and the loop-count gate proved in both polarities.
"""

import json
from pathlib import Path

import pytest

from agentcad.engines import get_engine, list_engines

pytestmark = pytest.mark.skipif("build123d" not in list_engines() or not get_engine("build123d").available(),
                                reason="build123d backend not available")

PLATE = (
    "from build123d import *\n"
    "\n"
    "def build(holes=2, d=4.0):\n"
    "    p = Box(40, 20, 6)\n"
    "    for i in range(holes):\n"
    "        p -= Pos(-10 + 20 * i / max(holes - 1, 1), 0, 0) * Cylinder(d / 2, 10)\n"
    "    return p\n"
)


@pytest.fixture
def plate(tmp_path) -> Path:
    p = tmp_path / "plate.py"
    p.write_text(PLATE)
    return p


def test_section_loops_count_the_outline_and_the_holes(plate):
    from agentcad import probe
    shape = probe.load_shape(plate)
    plane, coord = probe.parse_plane("z=mid", shape)
    loops = probe.section_loops(shape, plane)
    assert coord == pytest.approx(0.0, abs=1e-6)
    assert loops[0]["total_on_plane"] == 3            # outline + two holes
    kinds = sorted(e["type"] for e in loops[0]["edges"])
    assert kinds == ["line"] * 4
    hole = loops[-1]
    assert all(e["type"] == "circle" for e in hole["edges"])
    assert hole["edges"][0]["radius"] == pytest.approx(2.0, abs=1e-6)


def test_the_cap_is_printed_and_recorded_never_silent(plate, capsys):
    from agentcad import probe
    shape = probe.load_shape(plate)
    plane, _ = probe.parse_plane("z=0", shape)
    loops = probe.section_loops(shape, plane, max_loops=1)
    assert len(loops) == 1 and loops[0]["total_on_plane"] == 3
    assert "cap max_loops=1 applied: 3 loops" in capsys.readouterr().err


def test_inventory_reports_cylinder_axes_not_centroids(plate):
    from agentcad import probe
    inv = probe.inventory(probe.load_shape(plate))
    cyl = [c for c in inv["cylinders"] if c["type"] == "cylinder"]
    assert len(cyl) == 2
    for c in cyl:
        assert abs(c["axis_direction"][2]) == pytest.approx(1.0, abs=1e-6)
        assert c["axis_origin"][1] == pytest.approx(0.0, abs=1e-6)
    assert inv["face_census"]["cylinder"] == 2


def test_circle_fit_recovers_a_polylined_arc():
    import math
    from agentcad import probe
    pts = [[3 + 5 * math.cos(a), -2 + 5 * math.sin(a), 0.0] for a in [i * 2 * math.pi / 40 for i in range(40)]]
    fit = probe.fit_circle(pts)
    assert fit["radius"] == pytest.approx(5.0, abs=1e-6)
    assert fit["center"][0] == pytest.approx(3.0, abs=1e-6) and fit["rms"] < 1e-9


def test_loop_gate_is_red_on_a_missing_hole_and_green_on_the_same_part(plate, tmp_path):
    from agentcad import probe
    same = probe.compare(plate, plate, planes=["z=mid"], out_dir=tmp_path / "cmp")
    assert same["gate"] is True and same["planes"][0]["equal"]
    assert same["deviation"]["candidate_to_original"]["max"] == pytest.approx(0.0, abs=1e-9)
    assert (tmp_path / "cmp" / "overlay_z_mid.png").exists()
    one_hole = probe.compare(plate, plate, planes=["z=mid"], defines={"holes": "1"})
    assert one_hole["gate"] is False
    assert (one_hole["planes"][0]["loops_original"], one_hole["planes"][0]["loops_candidate"]) == (3, 2)
    assert one_hole["deviation"]["original_to_candidate"]["max"] > 1.0


def test_loops_json_round_trips(plate, tmp_path):
    from agentcad import probe
    shape = probe.load_shape(plate)
    plane, coord = probe.parse_plane("z=mid", shape)
    data = {"source": str(plate), "planes": [{"plane": "z=mid", "coordinate": coord,
                                              "loops": probe.section_loops(shape, plane)}]}
    path = probe.write_json(data, tmp_path / "loops.json")
    back = json.loads(path.read_text())
    assert back["planes"][0]["loops"][0]["edges"][0]["type"] == "line"
    assert len(back["planes"][0]["loops"]) == 3


# --- probe fillet ---------------------------------------------------------------

FILLET_BOX = "from build123d import *\n\npart = Box(20, 20, 20)\nmodel = fillet(part.edges().filter_by(Axis.Z), 1.0)\n"
FILLET_STEP = ("from build123d import *\n\n"
               "part = Box(20, 20, 10) + Pos(0, 5, 5.05) * Box(20, 10, 0.1)   # a 0.1 mm step on half the top\n"
               "model = fillet(part.edges().filter_by(Axis.X).filter_by(lambda e: e.center().Z > 4.9), 1.0)\n")
TWO_CALLS = ("from build123d import *\n\n"
             "part = Box(20, 20, 20)\n"
             "part = fillet(part.edges().filter_by(Axis.Z), 1.0)\n"
             "model = chamfer(part.edges().filter_by(Axis.X), 0.5)\n"
             "model = fillet(model.edges().filter_by(Axis.Y), 0.3)\n")


def test_probe_fillet_on_a_box_takes_every_radius(tmp_path):
    from agentcad import probe
    p = tmp_path / "box.py"
    p.write_text(FILLET_BOX)
    res = probe.fillet_probe(p, radii=(2.0, 1.0, 0.5))
    assert res["n_selected"] == 4 and res["size_in_source"] == 1.0
    assert res["live_part"]["volume"] == pytest.approx(8000.0)   # the part BEFORE the fillet
    assert all(v == "ok" for v in res["whole"].values())
    assert all(row["takes"] == 2.0 for row in res["each"])
    assert res["steps"] == [] and not any(e["short"] for e in res["chain"])
    assert res["watertight"] and res["watertight"]["ok"]
    lines = probe.render_fillet_probe(res)
    assert any("whole selection at 2.0: ok" in line for line in lines)


def test_probe_fillet_across_a_step_refuses_and_names_the_step(tmp_path):
    from agentcad import probe
    p = tmp_path / "step.py"
    p.write_text(FILLET_STEP)
    res = probe.fillet_probe(p, radii=(1.0, 0.25))
    assert res["whole"]["1.0"] != "ok"                            # the chain will not take the radius
    assert res["steps"] and all(s["length"] == pytest.approx(0.1, abs=1e-6) for s in res["steps"])
    assert any(s["touches"] for s in res["steps"])                  # and the step names the edges it touches
    assert any(row["takes"] is not None for row in res["each"])     # the edges away from the step do take it
    assert any("STEP 0.100 mm" in line for line in probe.render_fillet_probe(res))


def test_probe_fillet_captures_the_call_by_index_and_leaves_build123d_intact(tmp_path):
    import build123d
    from agentcad import probe
    real = build123d.fillet
    p = tmp_path / "two.py"
    p.write_text(TWO_CALLS)
    first = probe.capture_call(p, "fillet", 0)
    second = probe.capture_call(p, "fillet", 1)
    cham = probe.capture_call(p, "chamfer", 0)
    assert (first.size, second.size, cham.size) == (1.0, 0.3, 0.5)
    assert len(first.objects) == 4 and len(second.objects) > 4     # the second call sees a chamfered part
    with pytest.raises(LookupError):
        probe.capture_call(p, "fillet", 2)
    assert build123d.fillet is real                                 # restored after every run
