"""QC measurement on a part's mesh: in-layer wall width exact on the section polygons, and
overhangs from the faces in the print pose."""

from pathlib import Path

import pytest

from agentcad import printers, qc
from agentcad.engines import get_engine, list_engines

pytestmark = pytest.mark.skipif("build123d" not in list_engines() or not get_engine("build123d").available(),
                                reason="build123d backend not available")


def _stl(tmp_path: Path, name: str, shape) -> Path:
    from agentcad.fit import _b3d
    path = tmp_path / f"{name}.stl"
    _b3d().export_stl(shape, str(path), tolerance=0.01, angular_tolerance=0.05)
    return path


def _tube(wall: float):
    from agentcad.fit import _b3d
    b3d = _b3d()
    return b3d.Cylinder(5.0, 10.0, align=(b3d.Align.CENTER, b3d.Align.CENTER, b3d.Align.MIN)) - \
        b3d.Cylinder(5.0 - wall, 12.0, align=(b3d.Align.CENTER, b3d.Align.CENTER, b3d.Align.MIN))


def _ledge():
    """A 10 x 10 x 20 post with a 20 x 10 x 2 ledge at its top: the ledge's underside faces straight down."""
    from agentcad.fit import _b3d
    b3d = _b3d()
    low = (b3d.Align.MIN, b3d.Align.MIN, b3d.Align.MIN)
    return b3d.Box(10, 10, 20, align=low) + b3d.Pos(10, 0, 18) * b3d.Box(20, 10, 2, align=low)


def _report(stl, **qc_table):
    return qc.run(None, stl, qc.QCSettings.from_table(qc_table), printer_override="mk4")


def test_a_wall_thinner_than_a_line_is_an_error_and_a_thick_one_passes(tmp_path):
    thin = _report(_stl(tmp_path, "thin", _tube(0.3)))
    walls = [f for f in thin["findings"] if f["rule"] in ("min_feature", "min_wall")]
    assert len(walls) == 1 and walls[0]["rule"] == "min_feature"
    assert walls[0]["severity"] == "warning"            # unattributed: no annotation names the feature yet
    assert float(walls[0]["found"].split()[0]) == pytest.approx(0.3, abs=0.01)     # exact on the polygons
    assert "process default" in walls[0]["layer"] and walls[0]["uncertainty"] is not None
    thick = _report(_stl(tmp_path, "thick", _tube(1.0)))
    assert not [f for f in thick["findings"] if f["rule"] in ("min_feature", "min_wall")]
    assert "min_wall_mm" not in thick["not_measured"]


def test_a_project_limit_turns_a_printable_wall_into_a_warning(tmp_path):
    rep = _report(_stl(tmp_path, "tube", _tube(1.0)), limits={"min_wall_mm": 1.6})
    walls = [f for f in rep["findings"] if f["rule"] == "min_wall"]
    assert len(walls) == 1 and walls[0]["severity"] == "warning" and walls[0]["layer"] == "project [qc]"


def test_an_overhang_ledge_is_flagged_in_pose_and_clean_upside_down(tmp_path):
    stl = _stl(tmp_path, "ledge", _ledge())
    as_built = [f for f in _report(stl)["findings"] if f["rule"] == "max_overhang"]
    assert len(as_built) == 1 and as_built[0]["severity"] == "warning"
    assert "200" in as_built[0]["found"]                                     # the 20 x 10 underside
    flipped = [f for f in _report(stl, pose={"up": [0, 0, -1]})["findings"] if f["rule"] == "max_overhang"]
    assert flipped == []                                                     # its top now sits on the bed


def test_the_bed_face_is_never_an_overhang(tmp_path):
    from agentcad.fit import _b3d
    rep = _report(_stl(tmp_path, "box", _b3d().Box(20, 20, 5)))
    assert not [f for f in rep["findings"] if f["rule"] == "max_overhang"]
