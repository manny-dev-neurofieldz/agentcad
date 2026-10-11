"""The output-target contract, for every registered target.

A target declares its capabilities; each declared one works on a small fixture (tests/targetfixtures.py
holds one builder per target, and a registered target with capabilities and no builder fails the suite),
and each it does not declare raises NotSupported naming the target. A stub with no capabilities registers
and is reported as such. The generic target's plate keeps every placement through a round trip: an
asymmetric turn and offset come back as written, so a transposed matrix cannot pass.
"""

import json
import math
from pathlib import Path

import pytest

from agentcad import printers, targets
from agentcad.targets import CAPABILITIES, Job, JobPart, NotSupported, OutputTarget
from tests import targetfixtures


def _box_stl(path: Path, size=(10.0, 4.0, 2.0)) -> Path:
    x, y, z = size
    c = [(0, 0, 0), (x, 0, 0), (x, y, 0), (0, y, 0), (0, 0, z), (x, 0, z), (x, y, z), (0, y, z)]
    faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
             (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    lines = ["solid box"]
    for f in faces:
        lines += ["facet normal 0 0 0", "outer loop"] + [f"vertex {c[i][0]} {c[i][1]} {c[i][2]}" for i in f]
        lines += ["endloop", "endfacet"]
    path.write_text("\n".join(lines + ["endsolid box"]) + "\n")
    return path


def _turn_z(deg, offset):
    a = math.radians(deg)
    return [[math.cos(a), -math.sin(a), 0.0, offset[0]], [math.sin(a), math.cos(a), 0.0, offset[1]],
            [0.0, 0.0, 1.0, offset[2]], [0.0, 0.0, 0.0, 1.0]]


@pytest.fixture
def job(tmp_path) -> Job:
    stl = _box_stl(tmp_path / "bar.stl")
    return Job(name="plate", parts=[JobPart("bar", stl, copies=1, transform=_turn_z(30.0, (100.0, 60.0, 0.0)))])


def exercise(name, job, tmp_path):
    """Every capability the target declares, run on its fixture, and every one it does not declare, refused by
    name. A target that declares a capability and has no fixture raises MissingFixture."""
    target = targets.get_target(name)
    assert isinstance(target, OutputTarget) and target.name == name
    assert set(target.capabilities) <= set(CAPABILITIES)
    calls = {"write_job": lambda: target.write_job(job, tmp_path / name),
             "slice": lambda: target.slice(tmp_path / "none.3mf", tmp_path / name),
             "read_output": lambda: target.read_settings(tmp_path / "none.gcode"),
             "map_intent": lambda: target.map_intent({}),
             "printer_config": lambda: target.printer(tmp_path / "none.ini")}
    for capability, call in calls.items():
        if capability not in target.capabilities:
            with pytest.raises(NotSupported, match=name):
                call()
    if not target.capabilities:
        return
    case = targetfixtures.case_for(name, tmp_path)
    written = []
    if "write_job" in target.capabilities:
        job.options = dict(case.options)
        written = target.write_job(job, tmp_path / name)
        assert written and all(Path(p).is_file() and Path(p).stat().st_size > 0 for p in written)
        if case.readback:
            kept = [p for p in written if str(p).endswith(case.readback)]
            assert kept and target.read_settings(kept[0]), "what the target wrote, the target reads back"
    if "read_output" in target.capabilities:
        read = target.read_settings(case.sliced)
        assert read and all(isinstance(k, str) and isinstance(v, str) for k, v in read.items())
        assert {k: read.get(k) for k in case.expect} == case.expect
    if "map_intent" in target.capabilities:
        mapped, notes = target.map_intent(dict(case.intent))
        assert isinstance(mapped, dict) and all(isinstance(n, str) for n in notes)
        assert target.map_intent(dict(case.intent)) == (mapped, notes), "the same intent maps the same way"
        assert target.map_intent({}) == ({}, []), "no stated intent maps to nothing"
    if "printer_config" in target.capabilities:
        printer = target.printer(case.config)
        assert isinstance(printer, printers.Printer) and all(v > 0 for v in printer.build_volume)
    placed_on = target.job_printer(dict(case.options))
    assert placed_on is None or (isinstance(placed_on, printers.Printer) and "printer_config" in target.capabilities), \
        "a job is placed on a printer the target describes, or the target names none"
    if "slice" in target.capabilities:
        if not target.available():                  # declared, and nothing to slice with here: said, not passed
            pytest.skip(f"target {name!r} slices, but its slicer is not installed here")
        project = case.project or next((Path(p) for p in written if str(p).endswith(".3mf")), None)
        assert project is not None, "a target that slices needs a project: the fixture's, or the job it wrote"
        assert Path(target.slice(project, tmp_path / "sliced")).is_file()


@pytest.mark.parametrize("name", targets.list_targets())
def test_every_capability_is_declared_and_kept(name, job, tmp_path):
    exercise(name, job, tmp_path)


def test_a_registered_target_with_capabilities_and_no_fixture_fails_the_suite(job, tmp_path):
    class Bare(OutputTarget):
        name = "bare"
        capabilities = frozenset({"map_intent"})

        def map_intent(self, intent):
            return {}, []

    targets.register_target("bare", Bare)
    try:
        assert "bare" in targets.list_targets() and "bare" not in targetfixtures.BUILDERS
        with pytest.raises(targetfixtures.MissingFixture, match="bare"):
            exercise("bare", job, tmp_path)
        targetfixtures.BUILDERS["bare"] = lambda tmp: targetfixtures.TargetCase(intent={"layer_height": 0.2})
        exercise("bare", job, tmp_path)                    # with a builder it passes: the check discriminates
    finally:
        targets.unregister_target("bare")
        targetfixtures.BUILDERS.pop("bare", None)


def test_the_suite_runs_slice_for_a_target_that_declares_it_and_fails_one_that_returns_nothing(job, tmp_path):
    """The suite exercises slice for any target that declares it, and fails one that returns no file."""
    class Slicer(OutputTarget):
        name = "slicer"
        capabilities = frozenset({"slice"})
        produce = True

        def slice(self, project_file, out_dir):
            out = Path(out_dir) / "out.gcode"
            if self.produce:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text("G1 X1\n")
            return out

    targets.register_target("slicer", Slicer)
    targetfixtures.BUILDERS["slicer"] = lambda tmp: targetfixtures.TargetCase(project=tmp / "project.3mf")
    try:
        exercise("slicer", job, tmp_path)                       # a file comes back: it passes
        Slicer.produce = False
        with pytest.raises(AssertionError):
            exercise("slicer", job, tmp_path / "again")         # a path to nothing: it fails
    finally:
        targets.unregister_target("slicer")
        targetfixtures.BUILDERS.pop("slicer", None)


def test_a_stub_with_no_capabilities_registers_and_says_so(tmp_path):
    class Stub(OutputTarget):
        name = "stub"

    targets.register_target("stub", Stub)
    try:
        listed = {t["name"]: t for t in targets.describe()}
        assert listed["stub"]["capabilities"] == []
        with pytest.raises(NotSupported, match="stub"):
            Stub().write_job(Job("p", []), tmp_path)
    finally:
        targets.unregister_target("stub")


def test_the_generic_plate_keeps_an_asymmetric_placement(job, tmp_path):
    from agentcad.targets.generic import read_plate
    target = targets.get_target("generic")
    written = target.write_job(job, tmp_path / "out")
    plate = next(p for p in written if str(p).endswith(".3mf"))
    sidecar = json.loads(next(p for p in written if str(p).endswith(".placement.json")).read_text())
    assert sidecar["schema"] == "agentcad.placement/2" and "row vector" in sidecar["convention"]
    want = job.parts[0].transform
    (got,) = [item["transform"] for item in read_plate(plate)]
    for r in range(3):
        assert got[r] == pytest.approx(want[r], abs=1e-6)
    inst = sidecar["instances"][0]
    assert all(r == pytest.approx(w) for r, w in zip(inst["transform"], want)) and len(inst["sha256"]) == 64
    # the transposed matrix would turn the part the other way: the corner (10, 0, 0) proves which
    corner = [sum(got[i][j] * v for j, v in enumerate((10.0, 0.0, 0.0, 1.0))) for i in range(3)]
    assert corner[0] == pytest.approx(100 + 10 * math.cos(math.radians(30)), abs=1e-6)
    assert corner[1] == pytest.approx(60 + 10 * math.sin(math.radians(30)), abs=1e-6)


def test_copies_of_a_turned_part_are_spaced_by_the_width_it_has_on_the_bed(tmp_path):
    """Copies sit one posed width and a gap apart along the bed's x: a part turned a quarter is 4 mm wide
    there, not the 10 mm its mesh is long, and straight it is 10."""
    from agentcad.targets.generic import instances
    stl = _box_stl(tmp_path / "bar.stl")                          # 10 x 4 x 2
    turned = instances(Job("p", [JobPart("bar", stl, copies=2, transform=_turn_z(90.0, (50.0, 50.0, 0.0)))]))
    straight = instances(Job("p", [JobPart("bar", stl, copies=2, transform=_turn_z(0.0, (50.0, 50.0, 0.0)))]))
    assert turned[1]["transform"][0][3] - turned[0]["transform"][0][3] == pytest.approx(4.0 + 5.0)
    assert straight[1]["transform"][0][3] - straight[0]["transform"][0][3] == pytest.approx(10.0 + 5.0)


def test_the_generic_target_reads_a_plain_gcode_configuration(tmp_path):
    g = tmp_path / "part.gcode"
    g.write_text("G1 X1 E1\n; prusaslicer_config = begin\n; layer_height = 0.2\n; prusaslicer_config = end\n")
    assert targets.get_target("generic").read_settings(g)["layer_height"] == "0.2"


def test_the_same_job_writes_the_same_bytes(job, tmp_path):
    target = targets.get_target("generic")
    first = [p.read_bytes() for p in target.write_job(job, tmp_path / "a")]
    second = [p.read_bytes() for p in target.write_job(job, tmp_path / "b")]
    assert first == second


def test_the_print_intent_reaches_the_manifest(tmp_path):
    """[print] states the neutral intent; finalize carries it into the manifest, typed fields filled
    from what it states, every key kept verbatim (the manifest used to carry the class defaults)."""
    from agentcad.config import ProjectConfig
    from agentcad.manifest import PrintManifest
    from agentcad.session import DesignSession
    from tests.test_session import FakeEngine
    proj = tmp_path / "designs" / "bracket"
    proj.mkdir(parents=True)
    (proj / "agentcad.toml").write_text(
        f'[project]\nname = "bracket"\n[output]\nbase_dir = "{tmp_path}"\nsub_dir = "designs"\ndefault_views = ["iso"]\n'
        '[print]\nmaterial = "PETG"\nlayer_height = 0.15\nwalls = 4\ntarget = "generic"\n')
    session = DesignSession("bracket", FakeEngine(), config=ProjectConfig.load(proj / "agentcad.toml"))
    session.iterate("volume = 10\n")
    session.finalize()
    m = PrintManifest.load(proj / "exports" / "bracket.print.json")
    assert (m.material, m.layer_height) == ("PETG", 0.15)
    assert m.print_intent == {"material": "PETG", "layer_height": 0.15, "walls": 4, "target": "generic"}
    assert m.infill_percent == 20                      # not stated: the default stays, and print_intent does not claim it


def test_native_tables_override_the_mapped_intent_and_report_conflicts(tmp_path):
    from agentcad.config import ProjectConfig
    (tmp_path / "agentcad.toml").write_text(
        '[project]\nname = "p"\n[print]\ntarget = "prusaslicer"\n'
        '[slice]\nlayer_height = 0.2\ntemperature = { min = 270, max = 275, why = "layer bond" }\n'
        '[slice.generic]\nnote = "plain plate"\n')
    cfg = ProjectConfig.load(tmp_path / "agentcad.toml")
    assert set(cfg.slice_intent) == {"layer_height", "temperature"}       # a setting's table is not a target's
    assert cfg.slice_targets == {"generic": {"note": "plain plate"}}
    settings, conflicts = targets.native_settings(cfg, "prusaslicer", mapped={"layer_height": 0.15, "perimeters": 3})
    assert settings["layer_height"] == 0.2 and settings["perimeters"] == 3      # native wins, the rest is mapped
    assert len(conflicts) == 1 and "layer_height" in conflicts[0] and "0.15" in conflicts[0]
    assert targets.native_settings(cfg, "generic")[0] == {"note": "plain plate"}   # not the default: [slice] is not its


def test_support_bands_are_placed_through_a_placement_2_turn(job, tmp_path):
    """gcode supports reads placement/2: a band on the bed comes back in the part's own frame through
    the full transform, not just an offset (a /1 sidecar still reads as before)."""
    from agentcad.gcode import supports
    written = targets.get_target("generic").write_job(job, tmp_path / "out")
    placed = supports.load_placement(next(p for p in written if str(p).endswith(".placement.json")))
    entry = placed["bar"]
    corner_on_bed = [100 + 10 * math.cos(math.radians(30)), 60 + 10 * math.sin(math.radians(30)), 0.0]
    back = supports.to_part(entry, corner_on_bed)
    assert back == pytest.approx([10.0, 0.0, 0.0], abs=1e-6)
    (tmp_path / "old.json").write_text(json.dumps({"schema": "agentcad.placement/1", "objects": [
        {"stl": "a.stl", "instances": [{"label": "a", "bed_offset": [5, 6, 0]}]}]}))
    old = supports.load_placement(tmp_path / "old.json")["a"]
    assert supports.to_part(old, [6, 8, 1]) == pytest.approx([1, 2, 1])


def test_stage_writes_a_posed_part_centred_on_the_bed(tmp_path, monkeypatch, capsys):
    from agentcad import cli
    from agentcad.targets.generic import read_plate
    from tests.test_qc import FakeBoxEngine
    monkeypatch.setattr(cli, "_engine_for", lambda name, cfg: FakeBoxEngine())
    proj = tmp_path / "designs" / "bar"
    proj.mkdir(parents=True)
    (proj / "agentcad.toml").write_text(
        f'[project]\nname = "bar"\nengine = "fake"\n[output]\nbase_dir = "{tmp_path}"\nsub_dir = "designs"\n'
        'default_views = ["iso"]\n[print]\nmaterial = "PETG"\n[qc]\nprinter = "mk4"\npose = { up = [1, 0, 0] }\n')
    (proj / "bar.fake").write_text("volume = 10\nsize = 20, 10, 40\n")
    for argv in (["session", "start", str(proj)], ["session", "iterate", str(proj), str(proj / "bar.fake")],
                 ["session", "finalize", str(proj)]):
        cli.main(argv)
    capsys.readouterr()
    cli.main(["stage", str(proj), "--target", "generic", "--copies", "2", "-o", str(tmp_path / "staged")])
    out = capsys.readouterr().out
    plate = tmp_path / "staged" / "bar.3mf"
    assert plate.exists() and "generic" in out
    items = read_plate(plate)
    assert len(items) == 2
    T = items[0]["transform"]
    # posed on its side (x up): the 40 mm length lies along the bed, the part's lowest point at z = 0
    corners = [[sum(T[i][j] * v for j, v in enumerate((x, y, z, 1.0))) for i in range(3)]
               for x in (0, 20) for y in (0, 10) for z in (0, 40)]
    assert min(c[2] for c in corners) == pytest.approx(0.0, abs=1e-6)
    assert max(c[2] for c in corners) == pytest.approx(20.0, abs=1e-6)
    assert (min(c[1] for c in corners) + max(c[1] for c in corners)) / 2 == pytest.approx(105.0, abs=1e-6)
