"""QC on a mesh that cannot show everything: a width is read only where the mesh resolves at most half the
smallest limit in force for its rule, a rule the mesh is too coarse for is listed as not measured (with the
resolution and the limit), the walls and floors that are read carry the resolution as their uncertainty, and a
mesh written from the corner of a grid is put back where the program built the part before its boxes are set
against it. The meshes are boxes: a 20 x 0.3 x 10 mm wall standing on edge, and a 20 x 20 x 0.3 mm plate."""

import re

import pytest

from agentcad import qc
from tests.test_qc import _box_stl

MK4 = "mk4"             # min_feature 0.45 mm (one line of a 0.4 mm nozzle), min_wall 0.9 mm


@pytest.fixture
def wall(tmp_path):
    return _box_stl(tmp_path / "wall.stl", (20.0, 0.3, 10.0))


@pytest.fixture
def plate(tmp_path):
    return _box_stl(tmp_path / "plate.stl", (20.0, 20.0, 0.3))


def _thin(report):
    return [f for f in report["findings"] if f["rule"] in ("min_feature", "min_wall")]


def _run(stl, **kw):
    settings = kw.pop("settings", qc.QCSettings())
    return qc.run(None, stl, settings, printer_override=MK4, **kw)


def test_with_no_resolution_the_walls_are_measured_exactly_as_before(wall):
    report = _run(wall)
    (finding,) = _thin(report)
    assert (finding["rule"], finding["uncertainty"]) == ("min_feature", 0.0)       # exact on the polygons
    assert "resolution" not in report and "min_feature" not in report["not_measured"]
    assert "mesh resolves" not in finding["sentence"]


def test_a_mesh_fine_enough_for_both_rules_reads_both_and_states_its_doubt(wall, plate):
    report = _run(wall, resolution_mm=0.1)
    (finding,) = _thin(report)
    assert (finding["rule"], finding["uncertainty"]) == ("min_feature", pytest.approx(0.1))
    assert "the mesh resolves 0.10 mm" in finding["sentence"]
    assert report["resolution"] == {"mm": pytest.approx(0.1)} and report["not_measured"] == {}
    floor = _thin(_run(plate, resolution_mm=0.1))                                   # a thin floor, read the same way
    assert [f["key"] for f in floor] == ["floor"] and floor[0]["uncertainty"] == pytest.approx(0.1)


def test_a_mesh_too_coarse_for_the_feature_rule_is_judged_against_the_wall_rule_alone(wall, plate):
    grid = {"voxel_mm": 0.2, "stride": 2}
    report = _run(wall, resolution_mm=0.4, grid=grid)
    (finding,) = _thin(report)
    assert (finding["rule"], finding["uncertainty"]) == ("min_wall", pytest.approx(0.4))      # 0.3 mm < 0.9 mm
    assert report["not_measured"] == {"min_feature": (
        "the mesh resolves 0.40 mm (voxel 0.2 mm x stride 2); a 0.45 mm limit needs 0.225 mm or finer")}
    assert report["resolution"] == {"mm": pytest.approx(0.4), "voxel_mm": 0.2, "stride": 2}
    assert [f["rule"] for f in _thin(_run(plate, resolution_mm=0.4))] == ["min_wall"]         # floors follow the rule
    # without the grid's facts the reason still names the resolution and the limit
    plain = _run(wall, resolution_mm=0.4)
    assert plain["not_measured"]["min_feature"] == "the mesh resolves 0.40 mm; a 0.45 mm limit needs 0.225 mm or finer"


def test_a_mesh_too_coarse_for_both_rules_measures_no_wall_or_floor(wall, plate):
    for stl in (wall, plate):
        report = _run(stl, resolution_mm=0.5, grid={"voxel_mm": 0.25, "stride": 2})
        assert _thin(report) == [] and "walls" not in report["sampled"] and "floors" not in report["sampled"]
        assert report["not_measured"]["min_wall"] == (
            "the mesh resolves 0.50 mm (voxel 0.25 mm x stride 2); a 0.9 mm limit needs 0.45 mm or finer")
        assert "0.225 mm or finer" in report["not_measured"]["min_feature"]
        assert "build_volume" in [f["rule"] for f in report["findings"]]            # what does not depend on it is judged


def test_a_features_own_limit_counts_when_it_is_the_smallest_in_force(wall):
    flexure = {"type": "feature", "name": "flexure", "kind": "wall", "box": [-1, -1, -1, 21, 2, 11],
               "limits": {"min_feature_mm": 0.3}, "why": "a spring", "file": "part.py", "line": 7, "knobs": []}
    report = _run(wall, resolution_mm=0.2, annotations=[flexure])
    # the layered 0.45 mm limit would be readable at 0.2 mm; the flexure's 0.3 mm limit needs 0.15 mm
    assert report["not_measured"]["min_feature"].endswith("a 0.3 mm limit needs 0.15 mm or finer")
    assert [f["rule"] for f in _thin(report)] == ["min_wall"] and _thin(report)[0]["feature"] == "flexure"


def test_a_project_limit_can_leave_only_the_feature_rule_readable(wall):
    narrow = qc.QCSettings(limits={"min_wall_mm": 0.3})         # the wall rule now needs 0.15 mm; the feature rule 0.225
    report = _run(wall, resolution_mm=0.2, settings=narrow)
    assert [f["rule"] for f in _thin(report)] == ["min_feature"] and "min_wall" in report["not_measured"]


def test_half_the_limit_is_enough_and_a_hair_more_is_not(wall):
    """The edge of the rule, both ways: 0.225 mm is half of the feature limit 0.45 mm, 0.45 mm half of the wall limit."""
    assert _run(wall, resolution_mm=0.225)["not_measured"] == {}
    assert list(_run(wall, resolution_mm=0.2251)["not_measured"]) == ["min_feature"]
    assert list(_run(wall, resolution_mm=0.45)["not_measured"]) == ["min_feature"]
    assert sorted(_run(wall, resolution_mm=0.4501)["not_measured"]) == ["min_feature", "min_wall"]


def test_a_resolution_that_is_not_a_positive_number_is_refused(wall):
    for bad in (0, -0.1, float("nan"), "fine"):
        with pytest.raises(ValueError, match="resolution_mm"):
            _run(wall, resolution_mm=bad)


def test_a_mesh_written_from_the_grids_corner_is_put_back_where_the_program_built_the_part(wall):
    """The wall stands at the mesh's origin; the program built it at (100, 50, 0). A feature box in the
    program's frame claims the finding only once the grid's corner is added to the mesh."""
    rib = {"type": "feature", "name": "rib", "kind": "wall", "box": [99, 49, -1, 121, 52, 11], "limits": {}, "why": "",
           "file": "part.py", "line": 3, "knobs": []}
    shifted = _run(wall, resolution_mm=0.1, annotations=[rib], grid={"offset": [100.0, 50.0, 0.0]})
    (found,) = _thin(shifted)
    assert (found["feature"], found["severity"]) == ("rib", "error")             # claimed: may be an error
    x, y, _ = (float(v) for v in re.match(r"\(([-\d.]+), ([-\d.]+), ([-\d.]+)\)", found["location"]).groups())
    assert 100.0 <= x <= 120.0 and 50.0 <= y <= 51.0                              # reported in the program's frame
    lost = _run(wall, resolution_mm=0.1, annotations=[rib])
    assert _thin(lost)[0]["feature"] == "" and _thin(lost)[0]["severity"] == "warning"


def test_the_facts_of_a_grid_engines_mesh_come_from_the_iterations_metadata():
    md = {"voxel_size": [0.1, 0.1, 0.12], "surface": {"mc_stride": 2, "method": "auto"}, "mesh_offset": [1, -2, 3.5]}
    assert qc.mesh_facts(md) == {"voxel_mm": pytest.approx(0.12), "stride": 2, "offset": [1.0, -2.0, 3.5]}
    assert qc.mesh_facts({}) is None and qc.mesh_facts(None) is None
    assert qc.mesh_facts({"voxel_size": "junk", "surface": {"mc_stride": True}, "mesh_offset": [1, 2]}) is None
