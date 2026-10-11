"""QC on a VoxelCAD part: the program's annotations reach QC however many times the worker builds it,
the engine says how fine its mesh is, and QC measures a wall only where the mesh can show one.

The fixture is a small gyroid cube (``tests/data/qc_gyroid.py``) whose sheets are about 0.33 mm thick,
under the 0.45 mm of one line of a 0.4 mm nozzle. At a voxel of 0.1 mm and a marching-cubes stride of
2 the mesh resolves 0.2 mm, fine enough for both wall rules; at 0.25 mm it resolves 0.5 mm, which
cannot show a 0.9 mm wall limit's half, so QC says so instead of reading noise as walls."""

import json
from pathlib import Path

import pytest

from agentcad import annotate, cli
from agentcad.engines import get_engine, list_engines

pytestmark = pytest.mark.skipif("voxelcad" not in list_engines() or not get_engine("voxelcad").available(),
                                reason="voxelcad backend not available")

GYROID = Path(__file__).resolve().parent / "data" / "qc_gyroid.py"


@pytest.fixture(autouse=True)
def _clean_registry():
    annotate.reset()
    yield
    annotate.reset()


def _project(root: Path, voxel_size: float):
    """A started and iterated VoxelCAD project; the program is read from a file elsewhere, the user's."""
    proj = root / "designs" / "lattice"
    proj.mkdir(parents=True)
    (proj / "agentcad.toml").write_text(
        '[project]\nname = "lattice"\nengine = "voxelcad"\n'
        f'[engine.voxelcad]\nvoxel_size = {voxel_size}\nmc_stride = 2\n'
        f'[output]\nbase_dir = "{root}"\nsub_dir = "designs"\nimage_size = 64\ndefault_views = ["iso"]\n'
        '[qc]\nprinter = "mk4"\n')
    source = root / "elsewhere" / "lattice.py"
    source.parent.mkdir()
    source.write_text(GYROID.read_text())
    cli.main(["session", "start", str(proj)])
    cli.main(["session", "iterate", str(proj), str(source)])
    return proj, source


@pytest.fixture(scope="module")
def fine(tmp_path_factory):
    return _project(tmp_path_factory.mktemp("fine"), 0.1)


@pytest.fixture(scope="module")
def coarse(tmp_path_factory):
    return _project(tmp_path_factory.mktemp("coarse"), 0.25)


def _qc(proj, capsys, *flags):
    capsys.readouterr()
    try:
        code = cli.main(["qc", str(proj), *flags]) or 0
    except SystemExit as e:           # main exits only on a failure
        code = e.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _report(proj, capsys, *flags):
    code, out, err = _qc(proj, capsys, "--json", *flags)
    return code, json.loads(out), err


def _walls(report):
    return [f for f in report["findings"] if f["rule"] in ("min_feature", "min_wall")]


# --- the worker declares once, however many times it builds ----------------------------------------------

def test_a_grid_target_build_of_an_annotated_program_declares_each_feature_once(tmp_path):
    """No voxel size set: the worker executes the program at a probe size, at the derived size and
    sometimes a third time, and each execution calls feature(); only the last build's declarations count."""
    result = get_engine("voxelcad", settings={"grid": 32}).export(GYROID, tmp_path / "grid.stl")
    assert result.success, result.errors
    notes = result.metadata["qc_annotations"]
    assert [r["name"] for r in notes if r["type"] == "feature"] == ["lattice"]
    assert notes[0]["file"] == str(GYROID.resolve()) and isinstance(notes[0]["line"], int)


def test_the_worker_starts_each_build_with_an_empty_registry(tmp_path, monkeypatch):
    from agentcad.engines import voxelcad_worker
    import voxelcad.environment as ENV
    monkeypatch.setattr(ENV, "voxel_size", ENV.voxel_size)             # the worker sets it; restored afterwards
    annotate.feature("stale", box=(0, 0, 0, 1, 1, 1))                  # left over from an earlier build
    out = {"errors": [], "warnings": [], "images": {}, "output_path": None, "facet_count": 0, "metadata": {}}
    voxelcad_worker.run({"mode": "export", "source_path": str(GYROID), "defines": {},
                         "resolution": {"voxel_size": 0.1, "grid": 32, "warn_voxels": 0},
                         "surface": {"method": "auto", "mc_stride": 2},
                         "export": {"output_path": str(tmp_path / "w.stl"), "fmt": "stl"}}, out)
    assert [r["name"] for r in out["metadata"]["qc_annotations"]] == ["lattice"]


# --- the engine says how fine its mesh is -----------------------------------------------------------------

def test_the_engine_reports_the_finest_feature_its_mesh_can_show(tmp_path):
    from agentcad.engine import METADATA_KEYS
    assert "resolution_mm" in METADATA_KEYS
    for settings, expected in (({"voxel_size": 0.1, "mc_stride": 2}, 0.2),         # a cell edge times the stride
                               ({"voxel_size": 0.1, "mc_stride": 1}, 0.1),
                               ({"voxel_size": 0.1, "mc_stride": 2, "surface_method": "cdt"}, 0.2)):
        result = get_engine("voxelcad", settings=settings).export(GYROID, tmp_path / f"{expected}.stl")
        assert result.success, result.errors
        assert result.metadata["resolution_mm"] == pytest.approx(expected), settings
    render = get_engine("voxelcad", settings={"voxel_size": 0.1, "mc_stride": 2}).render(
        GYROID, tmp_path / "r", views=["iso"], image_size=64)
    assert render.success, render.errors
    assert render.metadata["resolution_mm"] == pytest.approx(0.2)         # a render reports it as an export does


def test_a_resolution_of_exactly_half_a_limit_reads_as_that_and_both_wall_rules_measure(tmp_path):
    """The grid keeps float32 edges (0.075 is 0.07500000298..., and three of them 0.22500000894), so the product is
    rounded to six digits; unrounded, a mesh at exactly half the 0.45 mm feature limit would read as a hair over it
    and lose the rule."""
    from agentcad import qc
    result = get_engine("voxelcad", settings={"voxel_size": 0.075, "mc_stride": 3}).export(GYROID, tmp_path / "edge.stl")
    assert result.success, result.errors
    assert result.metadata["resolution_mm"] == 0.225
    report = qc.run(None, result.output_path, qc.QCSettings(), printer_override="mk4",
                    resolution_mm=result.metadata["resolution_mm"], grid=qc.mesh_facts(result.metadata))
    assert report["not_measured"] == {} and report["sampled"]["walls"]["sections"] > 0


AWAY = ("from voxelcad import Cube\n"
        "def build():\n"
        "    return Cube(size=[4, 6, 8]).translate([10, 20, 30])\n")


def test_the_engine_says_where_its_mesh_sits_in_the_frame_the_program_built_in(tmp_path):
    """VoxelCAD writes a mesh from the corner of its grid, so a part built at (10, 20, 30) comes out near the
    origin; mesh_offset is the corner, and the mesh plus it is the part, to within the mesh's resolution."""
    import numpy as np
    from agentcad import qc
    source = tmp_path / "away.py"
    source.write_text(AWAY)
    for settings in ({"voxel_size": 0.2, "mc_stride": 2}, {"voxel_size": 0.2, "mc_stride": 1},
                     {"voxel_size": 0.2, "surface_method": "cdt"}):
        result = get_engine("voxelcad", settings=settings).export(source, tmp_path / "away.stl")
        assert result.success, result.errors
        md = result.metadata
        assert md["mesh_offset"] == pytest.approx(md["bbox_min"]) and md["mesh_offset"][0] == pytest.approx(9.8)
        mesh = qc.load_mesh(tmp_path / "away.stl")
        assert mesh.lo.max() < 1.0, "the mesh starts at the grid's corner, not at the part"
        for found, wanted in ((mesh.lo, (10, 20, 30)), (mesh.hi, (14, 26, 38))):
            assert np.abs(found + md["mesh_offset"] - wanted).max() <= 2 * md["resolution_mm"], settings


# --- QC measures a wall only where the mesh can show one -----------------------------------------------------

def test_a_thin_lattice_sheet_is_named_at_its_declaring_line_with_the_resolution_as_uncertainty(fine, capsys):
    proj, source = fine
    line = next(n for n, text in enumerate(source.read_text().splitlines(), 1) if text.lstrip().startswith('feature("lattice"'))
    code, report, _ = _report(proj, capsys)
    walls = _walls(report)
    assert walls, report["findings"]
    wall = walls[0]
    assert (wall["rule"], wall["severity"], wall["feature"]) == ("min_feature", "error", "lattice")
    assert wall["source"] == f"{source.resolve()}:{line}"                # the user's file, not the session's copy
    assert 0.2 < float(wall["found"].split()[0]) < 0.45             # about a third of a millimetre, under the 0.45 limit
    assert wall["uncertainty"] == pytest.approx(0.2)                      # the mesh resolves 0.2 mm, not exactly
    resolution = report["resolution"]
    assert (resolution["mm"], resolution["voxel_mm"], resolution["stride"]) == (
        pytest.approx(0.2), pytest.approx(0.1), 2)
    assert len(resolution["offset"]) == 3                                  # the mesh was put back in the program's frame
    assert "min_wall" not in report["not_measured"] and "min_feature" not in report["not_measured"]
    assert report["annotations"]["features"][0]["source"] == f"{source.resolve()}:{line}"
    assert code == 1                                                      # a claimed wall under the limit is an error


def test_a_coarse_voxel_leaves_the_walls_unmeasured_and_says_why(coarse, capsys):
    proj, _ = coarse
    code, report, _ = _report(proj, capsys)
    assert _walls(report) == [] and code == 0                             # no number was taken, so none is failed
    assert report["not_measured"]["min_feature"] == (
        "the mesh resolves 0.50 mm (voxel 0.25 mm x stride 2); a 0.45 mm limit needs 0.225 mm or finer")
    assert report["not_measured"]["min_wall"] == (
        "the mesh resolves 0.50 mm (voxel 0.25 mm x stride 2); a 0.9 mm limit needs 0.45 mm or finer")
    assert "walls" not in report["sampled"] and "floors" not in report["sampled"]
    assert report["pose_from"] == "as modelled"
    _, text, _ = _qc(proj, capsys)
    assert "not measured: min_feature (the mesh resolves 0.50 mm" in text
    assert "mesh resolution: 0.50 mm (voxel 0.25 mm x stride 2)" in text


def test_a_mesh_exported_for_qc_alone_is_judged_by_the_resolution_it_has_now(tmp_path, capsys):
    """The iteration was built at 0.2 mm; the project's voxel size was made coarser since, and qc exports the
    mesh again with today's settings, so it is the new mesh's resolution that says what can be read."""
    proj, _ = _project(tmp_path, 0.1)
    settings = proj / "agentcad.toml"
    settings.write_text(settings.read_text().replace("voxel_size = 0.1", "voxel_size = 0.25"))
    _, report, _ = _report(proj, capsys)
    assert report["resolution"]["mm"] == pytest.approx(0.5) and report["resolution"]["voxel_mm"] == pytest.approx(0.25)
    assert "min_feature" in report["not_measured"] and _walls(report) == []


def test_finalize_judges_the_latest_iteration_by_its_declarations_and_its_resolution(tmp_path):
    from agentcad.config import OutputConfig, ProjectConfig
    from agentcad.session import DesignSession
    cfg = ProjectConfig(output=OutputConfig(base_dir=tmp_path, sub_dir="designs", default_views=["iso"], image_size=64))
    cfg.qc = {}
    session = DesignSession("lattice", get_engine("voxelcad", settings={"voxel_size": 0.1}), config=cfg)
    iteration = session.iterate(GYROID.read_text(), origin=GYROID)
    assert iteration.metadata["resolution_mm"] == pytest.approx(0.2)
    assert iteration.metadata["mesh_offset"] == pytest.approx(iteration.metadata["bbox_min"])
    session.finalize()
    wall = next(f for f in session.qc_report["findings"] if f["rule"] in ("min_feature", "min_wall"))
    assert (wall["feature"], wall["severity"]) == ("lattice", "error")
    assert wall["source"].startswith(str(GYROID.resolve()) + ":") and wall["uncertainty"] == pytest.approx(0.2)
    assert not session.qc_failed                                     # the gate is not on


# --- --fixes belongs to build123d ------------------------------------------------------------------------------

def test_fixes_refuses_a_project_whose_engine_is_not_build123d_and_names_the_engine(fine, capsys):
    """A VoxelCAD program is a .py file too; turning its knobs with build123d would build nothing."""
    proj, _ = fine
    code, report, err = _report(proj, capsys, "--fixes")
    assert "VoxelCAD" in err and "--fixes" in err and "build123d" in err
    assert "sensitivity" not in report                                   # nothing was run
    assert _walls(report) and code == 1                                  # the report itself is unchanged
