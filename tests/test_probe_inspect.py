"""INSPECT: what a part is made of, along lines and across planes.

Rays (material and void intervals along lines and fans, on a B-rep exactly and
on a mesh to its tessellation), mesh sections, the census that says when its
zeros mean nothing, the comparison detail, and the knob sweep. Every fixture is
synthetic: a block with a through bore whose intervals are known by arithmetic.
"""

import json
import math
from pathlib import Path

import pytest

from agentcad.engines import get_engine, list_engines

pytestmark = pytest.mark.skipif("build123d" not in list_engines() or not get_engine("build123d").available(),
                                reason="build123d backend not available")

# A 40 x 30 x 20 block (x in -20..20, y in -15..15, z in -10..10) with a through bore of
# diameter `bore` along Z at x=5, y=0: every interval below follows from those numbers.
BORE_BLOCK = (
    "from build123d import *\n"
    "\n"
    "def build(bore=10.0):\n"
    "    return Box(40, 30, 20) - Pos(5, 0, 0) * Cylinder(bore / 2, 30)\n"
)


@pytest.fixture(scope="module")
def bore_block(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("inspect") / "bore_block.py"
    path.write_text(BORE_BLOCK)
    return path


@pytest.fixture(scope="module")
def bore_stl(bore_block, tmp_path_factory) -> Path:
    from build123d import export_stl
    from agentcad import probe
    path = tmp_path_factory.mktemp("inspect_stl") / "bore_block.stl"
    export_stl(probe.load_shape(bore_block), str(path), tolerance=0.01, angular_tolerance=0.2)
    return path


@pytest.fixture(scope="module")
def spline_step(bore_block, tmp_path_factory) -> Path:
    """The block with every surface converted to BSpline, through a STEP file: the shape a
    mesh-to-solid or a spline export hands over, whose faces no longer say what they were."""
    from build123d import Solid, export_step
    from OCP.BRepBuilderAPI import BRepBuilderAPI_NurbsConvert
    from agentcad import probe
    converted = Solid(BRepBuilderAPI_NurbsConvert(probe.load_shape(bore_block).wrapped, True).Shape())
    path = tmp_path_factory.mktemp("inspect_spline") / "bore_block_spline.step"
    export_step(converted, str(path))
    return path


# --- census honesty ---------------------------------------------------------------------------

def test_census_note_fires_at_ninety_percent_and_not_below():
    from agentcad.report import census_hides_analytic
    census = {"plane": 0, "cylinder": 0, "cone": 0, "sphere": 0, "torus": 0, "bspline": 9, "other": 1}
    note = census_hides_analytic(census)
    assert note and "9 of 10 faces (90%)" in note and "hides analytic types" in note
    assert "zero cylinders" in note
    assert census_hides_analytic(dict(census, bspline=8, plane=1)) is None      # 80%
    assert census_hides_analytic({"plane": 6, "cylinder": 1}) is None            # an analytic part
    assert census_hides_analytic({}) is None                                     # nothing counted, nothing said
    mixed = census_hides_analytic(dict(census, bspline=18, cylinder=2, other=0))
    assert mixed and "2 counted analytic face(s) are a lower bound" in mixed


def test_inventory_says_the_representation_hides_analytic_types(bore_block, spline_step):
    from agentcad import probe
    original = probe.inventory(probe.load_shape(bore_block))
    assert original["face_census"]["cylinder"] == 1 and original["census_notes"] == []
    converted = probe.inventory(probe.load_shape(spline_step))
    assert converted["face_census"]["bspline"] == converted["counts"]["faces"] == 7
    assert converted["cylinders"] == []                                           # the zero is not a finding
    assert len(converted["census_notes"]) == 1 and "hides analytic types" in converted["census_notes"][0]


def test_inventory_checks_each_solid_of_a_compound(bore_block, spline_step):
    """One analytic solid beside one BSpline solid: 7 of 14 faces overall, 7 of 7 in the second."""
    from build123d import Compound, Location
    from agentcad import probe
    pair = Compound(children=[probe.load_shape(bore_block),
                              probe.load_shape(spline_step).moved(Location((100, 0, 0)))])
    inv = probe.inventory(pair)
    assert inv["counts"]["solids"] == 2
    assert len(inv["census_notes"]) == 1 and inv["census_notes"][0].startswith("solid 2 of 2:")


def test_inventory_cli_prints_the_warning_beside_the_zero(spline_step, bore_block, capsys):
    from agentcad import cli
    cli.main(["probe", "inventory", str(spline_step)])
    out = capsys.readouterr().out
    assert "warning:" in out and "hides analytic types" in out
    assert "0 cylindrical/conical face(s) with axes:" not in out                # the bare zero is not printed
    cli.main(["probe", "inventory", str(bore_block)])
    out = capsys.readouterr().out
    assert "warning:" not in out and "1 cylindrical/conical face(s) with axes:" in out


def test_the_tray_warns_when_the_census_hides_analytic_types():
    from agentcad.report import feature_effect
    md = {"volume": 1.0, "counts": {"solids": 1, "faces": 20},
          "face_census": {"plane": 1, "cylinder": 0, "cone": 0, "sphere": 0, "torus": 0, "bspline": 19, "other": 0}}
    rep = feature_effect(None, md)
    assert any("19 of 20 faces (95%) are BSpline" in w for w in rep.warnings), rep.warnings
    md["face_census"] = {"plane": 14, "cylinder": 6, "bspline": 0}
    assert not any("BSpline" in w for w in feature_effect(None, md).warnings)
