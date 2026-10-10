"""The output-target contract, for every registered target.

A target declares its capabilities; each declared one works on a small fixture, and each it does
not declare raises NotSupported naming the target. A stub with no capabilities registers and is
reported as such. The generic target's plate keeps every placement through a round trip: an
asymmetric turn and offset come back as written, so a transposed matrix cannot pass.
"""

import json
import math
from pathlib import Path

import pytest

from agentcad import targets
from agentcad.targets import CAPABILITIES, Job, JobPart, NotSupported, OutputTarget


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


@pytest.mark.parametrize("name", targets.list_targets())
def test_every_capability_is_declared_and_kept(name, job, tmp_path):
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
    if "write_job" in target.capabilities:
        written = target.write_job(job, tmp_path / name)
        assert written and all(Path(p).exists() for p in written)


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
