"""Annotations from a program, and the measurements they attribute: features claim findings (with
the file and line that declared them, in the user's file), suppressions and loosened limits are
listed with their reasons, a program can state its print pose, and QC measures bridges and floors."""

import json
import sys
from pathlib import Path

import pytest

from agentcad import annotate, cli, qc
from agentcad.engines import get_engine, list_engines

needs_b3d = pytest.mark.skipif("build123d" not in list_engines() or not get_engine("build123d").available(),
                                reason="build123d backend not available")

FALLBACK = '''try:
    from agentcad.annotate import feature, suppress, print_pose
except ImportError:                       # without agentcad the annotations do nothing
    def feature(*args, **kwargs):
        pass
    suppress = print_pose = feature
'''


@pytest.fixture(autouse=True)
def _clean_registry():
    annotate.reset()
    yield
    annotate.reset()


# --- the API ------------------------------------------------------------------------------------

def test_the_api_records_where_each_call_was_made():
    annotate.feature("rib", box=(1, 0, 0, 0, 2, 3), kind="rib", min_wall_mm=0.8, why="a spring")
    line = sys._getframe().f_lineno - 1
    annotate.suppress("max_overhang", why="supports planned")
    annotate.print_pose(up=(0, -1, 0))
    rec = annotate.records()
    assert [r["type"] for r in rec] == ["feature", "suppress", "pose"]
    assert rec[0]["file"] == __file__ and rec[0]["line"] == line
    assert rec[0]["box"] == [0.0, 0.0, 0.0, 1.0, 2.0, 3.0]            # corners in any order
    annotate.reset()
    assert annotate.records() == []


@pytest.mark.parametrize("call,message", [
    (lambda: annotate.suppress("max_overhang", why=""), "needs its reason"),
    (lambda: annotate.suppress("nonesuch", why="x"), "unknown rule"),
    (lambda: annotate.feature("", box=(0, 0, 0, 1, 1, 1)), "needs a name"),
    (lambda: annotate.feature("a", box=(0, 0, 0, 1, 1)), "six"),
    (lambda: annotate.feature("a", box=(0, 0, 0, 1, 1, 1), min_wal_mm=1), "unknown limit"),
    (lambda: annotate.feature("a", box=(0, 0, 0, 1, 1, 1), min_wall_mm=-1), "positive"),
    (lambda: annotate.print_pose(matrix=[[1, 0, 0], [0, 1, 0], [0, 0, -1]]), "reflection"),
    (lambda: annotate.print_pose(matrix=[[1, 1, 0], [0, 1, 0], [0, 0, 1]]), "not a rotation"),
])
def test_the_api_refuses_what_qc_could_not_use(call, message):
    with pytest.raises(ValueError, match=message):
        call()


def test_a_feature_or_a_pose_is_declared_once():
    annotate.feature("a", box=(0, 0, 0, 1, 1, 1))
    with pytest.raises(ValueError, match="twice"):
        annotate.feature("a", box=(0, 0, 0, 2, 2, 2))
    annotate.print_pose()
    with pytest.raises(ValueError, match="twice"):
        annotate.print_pose(up=(1, 0, 0))


def test_a_program_runs_unchanged_without_agentcad(monkeypatch):
    monkeypatch.setitem(sys.modules, "agentcad.annotate", None)        # the import fails, as without agentcad
    namespace = {}
    exec(compile(FALLBACK + "feature('x', box=(0, 0, 0, 1, 1, 1), kind='wall')\nsuppress('max_wall', why='')\n"
                 "print_pose(up=(1, 0, 0))\nok = True\n", "program.py", "exec"), namespace)
    assert namespace["ok"] and annotate.records() == []


# --- judging with annotations (no kernel needed) ---------------------------------------------------

def test_the_smallest_box_claims_and_suppressions_name_their_reason():
    records = [
        {"type": "feature", "name": "body", "kind": "feature", "box": [0, 0, 0, 100, 100, 100], "limits": {}, "why": "",
         "file": "copy.py", "line": 3},
        {"type": "feature", "name": "rib", "kind": "rib", "box": [10, 10, 0, 12, 20, 5], "limits": {"min_wall_mm": 0.5},
         "why": "", "file": "copy.py", "line": 4},
        {"type": "suppress", "rule": "max_overhang", "why": "planned supports", "box": None, "file": "copy.py", "line": 5},
    ]
    ann = qc.Annotated.from_records(records, {"copy.py": "/work/mine.py"})
    assert ann.claim([11, 15, 1], 0.05)["name"] == "rib"
    assert ann.claim([50, 50, 50], 0.05)["name"] == "body"
    assert ann.claim([500, 0, 0], 0.05) is None
    assert ann.features[1]["source"] == "/work/mine.py:4"
    lim = {"min_wall_mm": (0.9, "process default")}
    assert qc.Annotated.limit(ann.features[1], "min_wall_mm", lim) == (0.5, "feature 'rib' (/work/mine.py:4)")
    listed, warned = qc._loosened(ann, lim)
    assert listed[0]["feature"] == "rib" and listed[0]["below"] == 0.9
    assert warned and "without a reason" in warned[0].message
    from agentcad.findings import Finding
    overhang = Finding("overhang", "warning", "x", "y", "z", "[qc]", rule="max_overhang")
    wall = Finding("wall", "warning", "x", "y", "z", "[qc]", rule="min_wall")
    kept, suppressed = qc._apply_suppressions([(overhang, [1, 1, 1]), (wall, [1, 1, 1])], ann, 0.05)
    assert kept == [(wall, [1, 1, 1])] and suppressed[0]["why"] == "planned supports"
    assert suppressed[0]["source"] == "/work/mine.py:5"


def test_a_pose_matrix_is_a_rotation():
    R = qc.pose_rotation({"matrix": [[0, -1, 0], [1, 0, 0], [0, 0, 1]]})
    assert R.tolist() == [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
    with pytest.raises(ValueError, match="rotation"):
        qc.pose_rotation({"matrix": [[1, 0, 0], [0, 1, 0], [0, 0, -1]]})


# --- measurement: bridges and floors ------------------------------------------------------------------

def _b3d():
    from agentcad.fit import _b3d as load
    return load()


def _mesh(tmp_path, name, shape):
    path = tmp_path / f"{name}.stl"
    _b3d().export_stl(shape, str(path), tolerance=0.01, angular_tolerance=0.05)
    return qc.load_mesh(path)


def _beam(gap: float):
    """Two 5 x 5 x 10 pillars, ``gap`` apart, joined by a 2 mm slab on top: its underside between the
    pillars is a bridge of span ``gap``, 5 mm wide."""
    b3d = _b3d()
    low = (b3d.Align.MIN, b3d.Align.MIN, b3d.Align.MIN)
    return (b3d.Box(5, 5, 10, align=low) + b3d.Pos(5 + gap, 0, 0) * b3d.Box(5, 5, 10, align=low)
            + b3d.Pos(0, 0, 10) * b3d.Box(10 + gap, 5, 2, align=low))


@needs_b3d
def test_a_long_bridge_is_measured_by_its_span_and_a_cantilever_is_not_a_bridge(tmp_path):
    long = qc.measure_bridges(_mesh(tmp_path, "long", _beam(20.0)))
    assert len(long["bridges"]) == 1
    assert long["bridges"][0]["span_mm"] == pytest.approx(20.0, abs=0.05)       # the gap, not the 5 mm width
    assert long["bridges"][0]["width_mm"] == pytest.approx(5.0, abs=0.05)
    assert qc.measure_bridges(_mesh(tmp_path, "short", _beam(6.0)))["bridges"][0]["span_mm"] == pytest.approx(6.0, abs=0.05)
    b3d = _b3d()
    low = (b3d.Align.MIN, b3d.Align.MIN, b3d.Align.MIN)
    shelf = b3d.Box(5, 5, 10, align=low) + b3d.Pos(5, 0, 8) * b3d.Box(6, 5, 2, align=low)
    assert qc.measure_bridges(_mesh(tmp_path, "shelf", shelf))["bridges"] == []      # held at one end only


@needs_b3d
def test_a_thin_floor_is_measured_and_its_rim_is_not(tmp_path):
    b3d = _b3d()
    low = (b3d.Align.MIN, b3d.Align.MIN, b3d.Align.MIN)
    cup = b3d.Box(20, 20, 10, align=low) - b3d.Pos(1, 1, 0.3) * b3d.Box(18, 18, 10, align=low)
    floors = qc.measure_floors(_mesh(tmp_path, "cup", cup), 0.9)
    assert len(floors["regions"]) == 1
    region = floors["regions"][0]
    assert region["thickness_mm"] == pytest.approx(0.3, abs=0.01)
    assert region["area_mm2"] > 200 and region["z_range"][1] < 0.5
    thick = b3d.Box(20, 20, 10, align=low) - b3d.Pos(1, 1, 2) * b3d.Box(18, 18, 10, align=low)
    assert qc.measure_floors(_mesh(tmp_path, "thick", thick), 0.9)["regions"] == []


@needs_b3d
def test_bridges_are_judged_against_the_process_and_planned_supports(tmp_path):
    stl = tmp_path / "beam.stl"
    _b3d().export_stl(_beam(20.0), str(stl), tolerance=0.01, angular_tolerance=0.05)
    rep = qc.run(None, stl, qc.QCSettings(), printer_override="mk4")
    bridges = [f for f in rep["findings"] if f["rule"] == "max_bridge"]
    assert len(bridges) == 1 and bridges[0]["found"].startswith("20.0 mm")
    assert not [f for f in rep["findings"] if f["rule"] == "max_overhang"], "a bridge is not an overhang"

    class Planned:
        print_intent = {"supports": True}

    rep = qc.run(Planned(), stl, qc.QCSettings(), printer_override="mk4")
    assert not [f for f in rep["findings"] if f["rule"] == "max_bridge"]
    assert rep["sampled"]["bridges"][0]["verdict"] == "supports planned"


# --- end to end: a program's annotations through a session --------------------------------------

TUBE = FALLBACK + '''
from build123d import Align, Cylinder


def build(wall=0.4, r=5.0, h=10.0, annotated=True, loosen=False):
    low = (Align.CENTER, Align.CENTER, Align.MIN)
    part = Cylinder(r, h, align=low) - Cylinder(r - wall, h + 2, align=low)
    if annotated:
        limits = {"min_feature_mm": 0.3, "min_wall_mm": 0.3} if loosen else {}
        feature("tube wall", box=(-r - 1, -r - 1, -1, r + 1, r + 1, h + 1), kind="wall",
                why="a flexure" if loosen else "", **limits)
    return part
'''


def _project(tmp_path):
    proj = tmp_path / "designs" / "tube"
    proj.mkdir(parents=True)
    (proj / "agentcad.toml").write_text(
        '[project]\nname = "tube"\nengine = "build123d"\n'
        f'[output]\nbase_dir = "{tmp_path}"\nsub_dir = "designs"\nimage_size = 64\ndefault_views = ["iso"]\n'
        '[qc]\nprinter = "mk4"\n')
    source = tmp_path / "elsewhere" / "tube.py"
    source.parent.mkdir()
    source.write_text(TUBE)
    return proj, source


def _qc(proj, capsys):
    capsys.readouterr()
    try:
        code = cli.main(["qc", str(proj), "--json"]) or 0
    except SystemExit as e:           # main exits only on a failure
        code = e.code
    return code, json.loads(capsys.readouterr().out)


@needs_b3d
def test_an_annotated_thin_wall_is_an_error_at_its_line_in_the_users_file(tmp_path, capsys):
    proj, source = _project(tmp_path)
    line = TUBE.splitlines().index('        feature("tube wall", box=(-r - 1, -r - 1, -1, r + 1, r + 1, h + 1), kind="wall",') + 1
    cli.main(["session", "start", str(proj)])
    cli.main(["session", "iterate", str(proj), str(source)])
    code, report = _qc(proj, capsys)
    walls = [f for f in report["findings"] if f["rule"] in ("min_feature", "min_wall")]
    assert code == 1 and len(walls) == 1
    assert walls[0]["rule"] == "min_feature" and walls[0]["severity"] == "error"     # claimed: may be an error
    assert walls[0]["feature"] == "tube wall"
    assert walls[0]["source"] == f"{source.resolve()}:{line}"                         # the user's file, not the copy
    assert report["annotations"]["features"][0]["source"] == f"{source.resolve()}:{line}"

    cli.main(["session", "iterate", str(proj), str(source), "-D", "annotated=False"])
    code, report = _qc(proj, capsys)
    walls = [f for f in report["findings"] if f["rule"] in ("min_feature", "min_wall")]
    assert code == 0 and walls[0]["severity"] == "warning" and walls[0]["feature"] == ""

    cli.main(["session", "iterate", str(proj), str(source), "-D", "loosen=True"])
    code, report = _qc(proj, capsys)
    assert not [f for f in report["findings"] if f["rule"] in ("min_feature", "min_wall")]
    assert {item["limit"] for item in report["loosened"]} == {"min_feature_mm", "min_wall_mm"}
    assert all(item["why"] == "a flexure" for item in report["loosened"])


@needs_b3d
def test_a_build_declares_only_its_own_annotations(tmp_path):
    from agentcad.engines import build123d_worker
    annotate.feature("stale", box=(0, 0, 0, 1, 1, 1))                  # left over from an earlier build
    src = tmp_path / "tube.py"
    src.write_text(TUBE)
    out = {"errors": [], "warnings": [], "images": {}, "output_path": None, "facet_count": 0, "metadata": {}}
    build123d_worker.run({"mode": "export", "source_path": str(src),
                          "export": {"output_path": str(tmp_path / "t.stl"), "fmt": "stl"}}, out)
    names = [r["name"] for r in out["metadata"]["qc_annotations"] if r["type"] == "feature"]
    assert names == ["tube wall"]


@needs_b3d
def test_a_bridge_whose_ends_are_filleted_into_its_pillars_is_still_a_bridge(tmp_path):
    b3d = _b3d()
    part = _beam(20.0)
    corners = [e for e in part.edges().filter_by(b3d.Axis.Y)
               if abs(e.center().Z - 10.0) < 1e-6 and min(abs(e.center().X - 5.0), abs(e.center().X - 25.0)) < 1e-6]
    assert len(corners) == 2, "the two concave edges where the slab meets the pillars' inner faces"
    filleted = b3d.fillet(corners, 1.5)
    bridges = qc.measure_bridges(_mesh(tmp_path, "filleted", filleted))["bridges"]
    # 20 less the two fillets, plus the strip of each fillet within CEILING_DEG of facing down (r sin 5 deg)
    import math
    edge = 1.5 * math.sin(math.radians(qc.CEILING_DEG))
    assert len(bridges) == 1 and 17.0 - 0.01 <= bridges[0]["span_mm"] <= 17.0 + 2 * edge + 0.01


# --- fixes by sensitivity ------------------------------------------------------------------------

KNOBBED = FALLBACK + '''
from build123d import Align, Cylinder


def build(wall=0.4, r=5.0, h=10.0, unused=1.0):
    low = (Align.CENTER, Align.CENTER, Align.MIN)
    part = Cylinder(r, h, align=low) - Cylinder(r - wall, h + 2, align=low)
    feature("tube wall", box=(-r - 1, -r - 1, -1, r + 1, r + 1, h + 1), kind="wall",
            knobs=("wall=0.1", "unused=0.5", "h=2"))
    return part
'''


def test_a_knob_spec_is_checked_where_it_is_declared():
    annotate.feature("a", box=(0, 0, 0, 1, 1, 1), knobs=("wall", "r=0.2", "h=10%"))
    assert annotate.records()[0]["knobs"] == ["wall=10%", "r=0.2", "h=10%"]
    with pytest.raises(ValueError, match="knob"):
        annotate.feature("b", box=(0, 0, 0, 1, 1, 1), knobs=("wall=-1",))


@needs_b3d
def test_fixes_name_the_knob_that_moves_the_wall_and_the_ones_that_do_nothing(tmp_path, capsys):
    proj, source = _project(tmp_path)
    source.write_text(KNOBBED)
    cli.main(["session", "start", str(proj)])
    cli.main(["session", "iterate", str(proj), str(source)])
    capsys.readouterr()
    try:
        cli.main(["qc", str(proj), "--json", "--fixes"])
    except SystemExit:
        pass
    report = json.loads(capsys.readouterr().out)
    (rec,) = report["sensitivity"]
    assert rec["feature"] == "tube wall" and rec["base"]["value"] == pytest.approx(0.4, abs=0.01)
    knobs = {k["name"]: k for k in rec["knobs"]}
    assert knobs["wall"]["verdict"] == "live"
    assert knobs["wall"]["plus"]["value"] == pytest.approx(0.5, abs=0.01)
    assert knobs["wall"]["minus"]["change"] == pytest.approx(-0.1, abs=0.01)
    assert knobs["unused"]["verdict"] == "dead" and knobs["h"]["verdict"] == "dead"   # h moves the part, not this wall
    assert knobs["h"]["plus"]["knob"] == 12.0 and knobs["h"]["plus"]["value"] == pytest.approx(0.4, abs=0.01)
    fix = report["findings"][rec["finding"]]["fix"]
    assert "wall +0.1 gives 0.500 mm" in fix and "(passes)" in fix and "unused moves nothing here" in fix

    capsys.readouterr()
    try:
        cli.main(["qc", str(proj), "--json", "--fixes", "--max-runs", "3"])
    except SystemExit:
        pass
    (rec,) = json.loads(capsys.readouterr().out)["sensitivity"]
    assert [k["verdict"] for k in rec["knobs"]] == ["live", "untried", "untried"]


POCKET = FALLBACK + '''
from build123d import Align, Box, Pos


def build(reach=9.6):
    low = (Align.CENTER, Align.CENTER, Align.MIN)
    block = Box(20, 20, 10, align=low)
    pocket = Pos((reach - 6.0) / 2.0, 0, -1) * Box(reach + 6.0, 8, 12, align=low)     # x -6 to reach, through
    feature("end wall", box=(8, -6, -1, 12, 6, 11), kind="wall", knobs=("reach=2",))
    return block - pocket
'''


@needs_b3d
def test_fixes_tell_a_wall_made_thick_from_a_wall_cut_away(tmp_path, capsys):
    """reach -2 leaves the end wall 2.4 mm thick and reach +2 runs the pocket out through the face: on both
    builds nothing near the place is thin, and only the line across the place tells them apart."""
    proj, source = _project(tmp_path)
    source.write_text(POCKET)
    cli.main(["session", "start", str(proj)])
    cli.main(["session", "iterate", str(proj), str(source)])
    capsys.readouterr()
    try:
        cli.main(["qc", str(proj), "--json", "--fixes"])
    except SystemExit:
        pass
    report = json.loads(capsys.readouterr().out)
    walls = [c for c in report["claimed"] if c["kind"] == "wall"]
    assert walls and all(c["normal"] is not None and sum(v * v for v in c["normal"]) == pytest.approx(1.0)
                         for c in walls), walls       # each wall claim carries the line across it, or "gone" is unsaid
    (rec,) = report["sensitivity"]
    assert rec["feature"] == "end wall" and rec["base"]["value"] == pytest.approx(0.4, abs=0.01)
    (k,) = rec["knobs"]
    assert k["verdict"] == "live" and k["plus"].get("gone") is True, k
    assert k["minus"].get("clear") is True and k["minus"]["across_mm"] == pytest.approx(2.4, abs=0.01), k
    fix = report["findings"][rec["finding"]]["fix"]
    assert "reach +2 leaves no material across the place: the material there is gone (a failure, not a fix)" in fix, fix
    assert "reach -2 leaves no wall under" in fix and "near it: cleared (2.400 mm across the place)" in fix, fix
    assert "cleared, or the material there is gone" not in fix, fix


def test_a_fix_that_leaves_thin_material_across_the_place_says_look():
    """The line across the place finds material that no wall region near it reported, still under the limit:
    neither cleared nor gone, so the fix says to look (rare on a real build, so pinned on a record)."""
    rec = {"rule": "min_wall", "kind": "wall", "threshold": 0.8, "base": {"value": 0.4},
           "knobs": [{"name": "reach", "delta": 2, "verdict": "live", "plus": {"clear": True, "across_mm": 0.3},
                      "minus": {"value": 0.5, "change": 0.1}}]}
    assert qc._fix_sentence(rec, "thicken") == (
        "thicken; measured at 0.400 mm: reach +2 leaves no wall under 1.6 mm near it, and 0.300 mm across the "
        "place, under the limit: look, reach -2 gives 0.500 mm (+0.100)")


@needs_b3d
def test_an_annotated_program_builds_again_in_process(tmp_path):
    from agentcad.probe import load_shape
    src = tmp_path / "tube.py"
    src.write_text(KNOBBED)
    first, second = load_shape(src), load_shape(src, {"wall": "0.5"})      # a second build declares afresh
    assert second.volume > first.volume
    assert [r["name"] for r in annotate.records()] == ["tube wall"]
