"""VoxelCAD engine: behaviour beyond the shared contract.

The contract cases in test_engine_contract.py cover render, export,
validation, overrides and settings through the registry. These tests pin
what is specific to a subprocess-hosted voxel engine: the resolution
settings actually reaching the model (a grid target by default, an explicit
voxel size when given), the oversize-grid warning, the timeout, and the
measured metadata (volume from the occupied count, solids by connectivity).
"""

import time
from pathlib import Path

import pytest

from agentcad.engines import get_engine, list_engines

pytestmark = pytest.mark.skipif("voxelcad" not in list_engines(), reason="voxelcad engine not registered")

CUBE = (
    "from voxelcad import Cube\n"
    "\n"
    "def build(size=10):\n"
    "    return Cube(size=size, center=True)\n"
)

TWO_CUBES = (
    "from voxelcad import Cube\n"
    "\n"
    "def build(size=4, gap=6):\n"
    "    a = Cube(size=size, center=True)\n"
    "    b = Cube(size=size, center=True).translate([size + gap, 0, 0])\n"
    "    return a | b\n"
)

MODEL_ONLY = (
    "from voxelcad import Sphere\n"
    "model = Sphere(r=5)\n"
)

HANG = "import time\ntime.sleep(60)\n"


@pytest.fixture
def engine():
    eng = get_engine("voxelcad")
    if not eng.available():
        pytest.skip("voxelcad backend not available")
    return eng


@pytest.fixture
def cube_source(tmp_path) -> Path:
    p = tmp_path / "cube.py"
    p.write_text(CUBE)
    return p


def test_capabilities(engine):
    assert engine.file_extension == ".py"
    assert engine.supported_export_formats == ("stl",)
    assert engine.syntax_language == "python"
    assert isinstance(engine.version(), str)
    for key in ("voxel_size", "grid", "warn_voxels", "timeout", "export_timeout"):
        assert key in engine.known_settings, key


def test_default_grid_target_sizes_the_model(engine, cube_source, tmp_path):
    """With no voxel_size given, the longest side of the model spans about `grid` voxels."""
    result = engine.export(cube_source, tmp_path / "cube.stl")
    assert result.success, result.errors
    md = result.metadata
    assert md["grid_target"] == 256
    longest = max(md["grid_resolution"])
    assert 250 <= longest <= 262, md["grid_resolution"]
    assert md["voxel_size"][0] == pytest.approx(10.0 / 256, rel=0.05)


def test_explicit_voxel_size_is_applied_and_an_oversize_grid_warns(cube_source, tmp_path):
    eng = get_engine("voxelcad", settings={"voxel_size": 0.1, "warn_voxels": 100_000})
    if not eng.available():
        pytest.skip("voxelcad backend not available")
    result = engine_export = eng.export(cube_source, tmp_path / "cube.stl")
    assert result.success, result.errors
    res = result.metadata["grid_resolution"]
    assert all(98 <= r <= 102 for r in res), res
    assert any("voxels" in w and "0.1" in w for w in result.warnings), result.warnings
    del engine_export


def test_hanging_source_times_out_as_an_error_result(tmp_path):
    engine = get_engine("voxelcad", settings={"timeout": 2})
    if not engine.available():
        pytest.skip("voxelcad backend not available")
    src = tmp_path / "hang.py"
    src.write_text(HANG)
    t0 = time.monotonic()
    result = engine.render(src, tmp_path / "out", views=["iso"], image_size=64)
    elapsed = time.monotonic() - t0
    assert result.success is False
    assert any("timed out" in e for e in result.errors), result.errors
    assert elapsed < 15, elapsed


def test_override_changes_the_measured_volume(engine, cube_source, tmp_path):
    base = engine.export(cube_source, tmp_path / "a.stl")
    big = engine.export(cube_source, tmp_path / "b.stl", defines={"size": "20"})
    assert base.success and big.success, (base.errors, big.errors)
    assert base.metadata["volume"] == pytest.approx(1000.0, rel=0.03)
    assert big.metadata["volume"] == pytest.approx(8000.0, rel=0.03)
    assert base.metadata["counts"]["solids"] == 1
    assert base.metadata["bbox_size"] == pytest.approx([10.0, 10.0, 10.0], abs=0.2)


def test_two_separated_bodies_count_as_two_solids(engine, tmp_path):
    src = tmp_path / "two.py"
    src.write_text(TWO_CUBES)
    result = engine.export(src, tmp_path / "two.stl")
    assert result.success, result.errors
    assert result.metadata["counts"]["solids"] == 2
    assert result.metadata["volume"] == pytest.approx(2 * 64.0, rel=0.05)


def test_module_level_model_is_harvested_and_overrides_are_reported(engine, tmp_path):
    src = tmp_path / "model.py"
    src.write_text(MODEL_ONLY)
    plain = engine.export(src, tmp_path / "m.stl")
    assert plain.success, plain.errors
    assert plain.metadata["volume"] == pytest.approx(4.0 / 3.0 * 3.14159265 * 125, rel=0.03)

    with_defines = engine.render(src, tmp_path / "out", views=["iso"], image_size=64,
                                 defines={"r": "9"})
    assert any("ignored" in w for w in with_defines.warnings), with_defines.warnings
