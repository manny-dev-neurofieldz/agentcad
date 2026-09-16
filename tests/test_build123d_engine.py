"""build123d engine: behaviour beyond the shared contract.

The contract cases in test_engine_contract.py already cover render, export,
validation, overrides and settings for this engine through the registry.
These tests pin what is specific to a subprocess-hosted B-rep engine: the
timeout, the measured metadata, every export format, independence of the
geometry exports from PyVista, and the import-only dry run in validation.
"""

import time
from pathlib import Path

import pytest

from agentcad.engines import get_engine, list_engines

pytestmark = pytest.mark.skipif("build123d" not in list_engines(), reason="build123d engine not registered")

BOX = (
    "from build123d import Box\n"
    "\n"
    "def build(size=10):\n"
    "    return Box(size, size, size)\n"
)

PART_ONLY = (
    "from build123d import Cylinder\n"
    "part = Cylinder(radius=5, height=10)\n"
)

HANG = "import time\ntime.sleep(60)\n"


@pytest.fixture
def engine():
    eng = get_engine("build123d")
    if not eng.available():
        pytest.skip("build123d backend not available")
    return eng


@pytest.fixture
def box_source(tmp_path) -> Path:
    p = tmp_path / "box.py"
    p.write_text(BOX)
    return p


def test_capabilities(engine):
    assert engine.file_extension == ".py"
    assert engine.supported_export_formats == ("stl", "step", "3mf", "svg")
    assert engine.syntax_language == "python"
    assert isinstance(engine.version(), str)


def test_hanging_source_times_out_as_an_error_result(tmp_path):
    engine = get_engine("build123d", settings={"timeout": 2})
    src = tmp_path / "hang.py"
    src.write_text(HANG)
    t0 = time.monotonic()
    result = engine.render(src, tmp_path / "out", views=["iso"], image_size=64)
    elapsed = time.monotonic() - t0
    assert result.success is False
    assert any("timed out" in e for e in result.errors), result.errors
    assert elapsed < 15, elapsed


def test_override_changes_the_measured_volume(engine, box_source, tmp_path):
    base = engine.export(box_source, tmp_path / "a.step", fmt="step")
    big = engine.export(box_source, tmp_path / "b.step", fmt="step", defines={"size": "20"})
    assert base.success and big.success, (base.errors, big.errors)
    assert base.metadata["volume"] == pytest.approx(1000.0, rel=1e-6)
    assert big.metadata["volume"] == pytest.approx(8000.0, rel=1e-6)
    assert base.metadata["counts"]["faces"] == 6


@pytest.mark.parametrize("fmt", ["stl", "step", "3mf", "svg"])
def test_every_declared_format_produces_a_file(engine, box_source, tmp_path, fmt):
    out = tmp_path / f"box.{fmt}"
    result = engine.export(box_source, out, fmt=fmt)
    assert result.success, result.errors
    assert result.output_path == out and out.stat().st_size > 0
    assert result.format == fmt
    if fmt in ("stl", "3mf"):
        assert result.facet_count >= 12  # a box is at least twelve triangles


def test_geometry_exports_do_not_need_pyvista(engine, box_source, tmp_path, monkeypatch):
    """With PyVista unimportable in the worker, STEP and STL still export; render says why it cannot."""
    shim = tmp_path / "shim" / "pyvista"
    shim.mkdir(parents=True)
    (shim / "__init__.py").write_text("raise ImportError('pyvista disabled for this test')\n")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "shim"))

    step = engine.export(box_source, tmp_path / "box.step", fmt="step")
    stl = engine.export(box_source, tmp_path / "box.stl", fmt="stl")
    assert step.success and stl.success, (step.errors, stl.errors)

    render = engine.render(box_source, tmp_path / "out", views=["iso"], image_size=64)
    assert render.success is False
    assert any("pyvista" in e.lower() for e in render.errors), render.errors


def test_module_level_part_is_harvested_and_overrides_are_reported(engine, tmp_path):
    src = tmp_path / "part.py"
    src.write_text(PART_ONLY)
    plain = engine.export(src, tmp_path / "p.step", fmt="step")
    assert plain.success, plain.errors
    assert plain.metadata["volume"] == pytest.approx(3.14159265 * 25 * 10, rel=1e-4)

    with_defines = engine.render(src, tmp_path / "out", views=["iso"], image_size=64,
                                 defines={"radius": "9"})
    assert any("ignored" in w for w in with_defines.warnings), with_defines.warnings


def test_unnamed_product_is_harvested_by_size_with_a_warning(engine, tmp_path):
    src = tmp_path / "unnamed.py"
    src.write_text(
        "from build123d import Box, Sphere\n"
        "small = Sphere(1)\n"
        "widget = Box(10, 10, 10)\n"
    )
    result = engine.export(src, tmp_path / "u.step", fmt="step")
    assert result.success, result.errors
    assert result.metadata["volume"] == pytest.approx(1000.0, rel=1e-6)
    assert any("'widget'" in w for w in result.warnings), result.warnings


def test_shading_is_a_known_setting_and_both_modes_render(tmp_path):
    """Smooth shading is the default; "flat" is accepted and still renders."""
    src = tmp_path / "box.py"
    src.write_text(BOX)
    smooth = get_engine("build123d")
    if not smooth.available():
        pytest.skip("build123d backend not available")
    assert "shading" in smooth.known_settings
    assert smooth.setting("shading", None) in (None, "smooth")
    flat = get_engine("build123d", settings={"shading": "flat"})
    for eng, tag in ((smooth, "smooth"), (flat, "flat")):
        result = eng.render(src, tmp_path / tag, views=["iso"], image_size=64)
        if result.errors and any("pyvista" in e.lower() for e in result.errors):
            pytest.skip("pyvista unavailable for rendering")
        assert result.success, result.errors
        assert (tmp_path / tag / "box_iso.png").exists()


def test_validate_syntax_runs_an_import_only_dry_run(engine):
    assert engine.validate_syntax(BOX).valid
    bad = engine.validate_syntax("def build(:\n")
    assert not bad.valid and bad.errors
    missing = engine.validate_syntax("import no_such_module_xyz\n\ndef build():\n    return None\n")
    assert not missing.valid
    assert any("no_such_module_xyz" in e for e in missing.errors), missing.errors
