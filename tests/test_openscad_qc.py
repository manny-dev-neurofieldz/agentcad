"""QC on an OpenSCAD part: the program declares its features with echo, the engine reads the lines back from
OpenSCAD's output, and QC attributes its findings to them, naming the .scad file (an echo carries no line).

The fixture (``tests/data/qc_pin_hole.scad``) is a plate with a pin hole through it: round, its roof faces down
past the 45 degree limit and QC flags it as an overhang of the "pin hole" feature; as a teardrop, two flats at
exactly 45 degrees meet over the hole and it passes. These tests need OpenSCAD and skip without it; rendering
needs a display, so a machine without one runs them under xvfb-run."""

import json
from pathlib import Path

import pytest

from agentcad import cli, qc
from agentcad.config import OutputConfig, ProjectConfig
from agentcad.engine import METADATA_KEYS
from agentcad.engines import get_engine, list_engines
from agentcad.session import DesignSession

pytestmark = pytest.mark.skipif("openscad" not in list_engines(), reason="openscad engine not registered")

PLATE = Path(__file__).resolve().parent / "data" / "qc_pin_hole.scad"


@pytest.fixture
def scad():
    engine = get_engine("openscad")
    if not engine.available():
        pytest.skip("OpenSCAD backend not available")
    return engine


def _overhangs(scad, source, tmp_path, name, defines=None):
    """The program's declarations and QC's overhang findings for its exported mesh."""
    result = scad.export(source, tmp_path / f"{name}.stl", defines=defines)
    assert result.success, result.errors
    assert not [k for k in result.metadata if k not in METADATA_KEYS and not k.endswith("_error")]
    assert "resolution_mm" not in result.metadata and "mesh_offset" not in result.metadata      # a CSG mesh is exact, and where it was built
    notes = result.metadata.get("qc_annotations", [])
    report = qc.run(None, result.output_path, qc.QCSettings(), printer_override="mk4", annotations=notes)
    return notes, [f for f in report["findings"] if f["rule"] == "max_overhang"]


def test_a_round_hole_is_flagged_through_its_echo_and_a_teardrop_passes(scad, tmp_path):
    notes, overhangs = _overhangs(scad, PLATE, tmp_path, "round")
    assert [(n["type"], n["name"], n["file"], n["line"]) for n in notes] == [("feature", "pin hole", str(PLATE), None)]
    (hole,) = overhangs
    assert (hole["feature"], hole["source"]) == ("pin hole", str(PLATE))                  # the feature and the file
    assert "'pin hole'" in hole["sentence"] and f"({PLATE})" in hole["sentence"] and ":None" not in hole["sentence"]
    assert float(hole["found"].split()[0]) > 40.0 and "84 deg" in hole["found"]            # the roof: ~50 mm2 at 84 deg

    notes, overhangs = _overhangs(scad, PLATE, tmp_path, "teardrop", defines={"teardrop": "true"})
    assert [n["name"] for n in notes] == ["pin hole"]                                      # still declared
    assert overhangs == []                                                                 # flats at exactly the limit pass


LEDGE = "union() { cube([10, 10, 20]); translate([10, 0, 18]) cube([20, 10, 2]); }\n"       # its underside faces down


def test_a_pose_and_a_suppression_declared_in_openscad_take_effect_and_name_the_file_alone(scad, tmp_path):
    def judge(name, declarations):
        source = tmp_path / f"{name}.scad"
        source.write_text(declarations + LEDGE)
        result = scad.export(source, tmp_path / f"{name}.stl")
        assert result.success, result.errors
        report = qc.run(None, result.output_path, qc.QCSettings(), printer_override="mk4",
                        annotations=result.metadata.get("qc_annotations"))
        return source, report, [f for f in report["findings"] if f["rule"] == "max_overhang"]

    _, bare, overhangs = judge("bare", "")
    assert len(overhangs) == 1 and bare["pose_from"] == "as modelled"                      # the ledge, as modelled
    source, upside_down, overhangs = judge("posed", 'echo("AGENTCAD_QC", "pose", up=[0, 0, -1]);\n')
    assert overhangs == [] and upside_down["pose_from"] == f"annotation at {source}"       # its top is on the bed
    source, accepted, overhangs = judge(
        "suppressed", 'echo("AGENTCAD_QC", "suppress", rule="max_overhang", why="planned supports");\n')
    assert overhangs == []
    (item,) = accepted["suppressed"]
    assert (item["rule"], item["why"], item["source"]) == ("max_overhang", "planned supports", str(source))


ECHOES = '''echo("AGENTCAD_QC", "feature", name="boss", box=[0, 0, 0, 5, 5, 5], kind="boss");
echo("AGENTCAD_QC", "suppress", rule="max_overhang", why="WARNING: the supports are planned");
echo("a note", "AGENTCAD_QC");
echo("AGENTCAD_QC", "feature", name="boss", box=[0, 0, 0, 5, 5, 5], kind="boss");
echo("AGENTCAD_QC", "feature", name="rod \\"A\\"", box=[1, 1, 1, 2, 2, 2]);
cube(5);
'''


def test_each_declaration_is_made_once_however_many_views_render_and_other_echoes_are_ignored(scad, tmp_path):
    source = tmp_path / "echoes.scad"
    source.write_text(ECHOES)                                   # two views are two processes, and one repeats a line
    render = scad.render(source, tmp_path / "views", views=["iso", "front"], image_size=64)
    assert render.success, render.errors
    assert [(r["type"], r.get("name") or r["rule"]) for r in render.metadata["qc_annotations"]] == [
        ("feature", "boss"), ("suppress", "max_overhang"), ("feature", 'rod "A"')]       # the quote OpenSCAD may not escape
    assert not [w for w in render.warnings if "planned" in w or "AGENTCAD" in w]          # a reason is not a diagnostic
    export = scad.export(source, tmp_path / "echoes.stl")
    assert export.success and [r["type"] for r in export.metadata["qc_annotations"]] == ["feature", "suppress", "feature"]


@pytest.mark.parametrize("declaration,message", [
    ('echo("AGENTCAD_QC", "feature", name="a", box=[0, 0, 0, 1, 1, 1], colour="red");', "unknown argument 'colour'"),
    ('echo("AGENTCAD_QC", "suppress", rule="max_overhang", why=" ");', "needs its reason"),
    ('echo("AGENTCAD_QC", "feature", name="a", box=[0, 0, 0, 1, 1]);', "six"),
    ('echo("AGENTCAD_QC", "feature", name="a", box=[0, 0, 0, 1, 1, 1]);\n'
     'echo("AGENTCAD_QC", "feature", name="a", box=[0, 0, 0, 2, 2, 2]);', "declared twice"),
    ('echo("AGENTCAD_QC", "feature", name="a", box=[0 : 5]);', "expected , or ]"),
])
def test_a_declaration_that_cannot_be_read_or_is_refused_fails_the_export_and_names_the_line(scad, tmp_path, declaration, message):
    source = tmp_path / "bad.scad"
    source.write_text(declaration + "\ncube(5);\n")
    result = scad.export(source, tmp_path / "bad.stl")
    assert not result.success and "qc_annotations" not in result.metadata
    assert any(message in e and "AGENTCAD_QC" in e and "bad.scad" in e for e in result.errors), result.errors


def test_a_declaration_the_validator_refuses_fails_the_render_too(scad, tmp_path):
    source = tmp_path / "bad.scad"
    source.write_text('echo("AGENTCAD_QC", "suppress", rule="nonesuch", why="x");\ncube(5);\n')
    render = scad.render(source, tmp_path / "bad_views", views=["iso"], image_size=64)
    assert not render.success and any("unknown rule" in e for e in render.errors), render.errors
    assert "qc_annotations" not in render.metadata


def _plate_project(root: Path):
    proj = root / "designs" / "plate"
    proj.mkdir(parents=True)
    (proj / "agentcad.toml").write_text(
        '[project]\nname = "plate"\nengine = "openscad"\n'
        f'[output]\nbase_dir = "{root}"\nsub_dir = "designs"\nimage_size = 64\ndefault_views = ["iso"]\n'
        '[qc]\nprinter = "mk4"\n')
    source = root / "elsewhere" / "plate.scad"                  # the user's file, not the session's copy
    source.parent.mkdir()
    source.write_text(PLATE.read_text())
    return proj, source


def _report(proj, capsys, *flags):
    capsys.readouterr()
    try:
        code = cli.main(["qc", str(proj), "--json", *flags]) or 0
    except SystemExit as e:           # main exits only on a failure
        code = e.code
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.err


def test_a_session_keeps_the_declarations_and_finalize_judges_by_them(scad, tmp_path):
    cfg = ProjectConfig(output=OutputConfig(base_dir=tmp_path, sub_dir="designs", default_views=["iso"], image_size=64))
    cfg.qc = {}
    source = tmp_path / "elsewhere" / "plate.scad"
    source.parent.mkdir()
    source.write_text(PLATE.read_text())
    session = DesignSession("plate", scad, config=cfg)
    iteration = session.iterate(source.read_text(), origin=source)
    notes = iteration.metadata["qc_annotations"]
    assert [(n["name"], n["file"]) for n in notes] == [("pin hole", str(iteration.source_path))]    # the session's copy
    session.finalize()
    (hole,) = [f for f in session.qc_report["findings"] if f["rule"] == "max_overhang"]
    assert (hole["feature"], hole["source"]) == ("pin hole", str(source.resolve()))                 # mapped to the user's


def test_agentcad_qc_flags_the_hole_at_the_users_file_and_the_teardrop_passes_and_fixes_is_refused(scad, tmp_path, capsys):
    proj, source = _plate_project(tmp_path)
    cli.main(["session", "start", str(proj)])
    cli.main(["session", "iterate", str(proj), str(source)])
    code, report, _ = _report(proj, capsys)
    (hole,) = [f for f in report["findings"] if f["rule"] == "max_overhang"]
    assert (hole["feature"], hole["severity"], hole["source"]) == ("pin hole", "warning", str(source.resolve()))
    assert report["annotations"]["features"] == [{"name": "pin hole", "kind": "hole", "source": str(source.resolve())}]
    assert "resolution" not in report and code == 0

    _, with_fixes, err = _report(proj, capsys, "--fixes")
    assert "OpenSCAD" in err and "--fixes" in err and "sensitivity" not in with_fixes

    cli.main(["session", "iterate", str(proj), str(source), "-D", "teardrop=true"])
    code, report, _ = _report(proj, capsys)
    assert not [f for f in report["findings"] if f["rule"] == "max_overhang"] and code == 0
    assert report["annotations"]["features"][0]["name"] == "pin hole"
