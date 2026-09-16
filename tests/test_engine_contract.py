"""The CADEngine contract, driven the way the CLI drives it, for every engine.

Each test runs once per registered engine (see conftest) and skips when the
backend is absent. A new engine that registers itself is covered here
without any test changes.
"""

import pytest

from agentcad.camera import MULTI_VIEW_DEFAULT
from agentcad.engine import CADEngine, ExportResult, RenderResult, ValidationResult
from agentcad.engines import get_engine

from .conftest import BAD_SOURCES, SOURCES, stl_extent


def test_identity_and_capabilities(engine):
    """The static facts the CLI, config and viewer rely on."""
    assert isinstance(engine, CADEngine)
    assert engine.file_extension.startswith(".")
    assert engine.supported_export_formats and "stl" in engine.supported_export_formats
    assert isinstance(engine.syntax_language, str) and engine.syntax_language
    version = engine.version()
    assert version is None or isinstance(version, str)


def test_render_four_views(engine, source_file, tmp_path):
    """Rendering the default view set yields one non-empty PNG per view."""
    out = tmp_path / "renders"
    result = engine.render(source_file, out, views=MULTI_VIEW_DEFAULT, image_size=128)
    assert isinstance(result, RenderResult)
    assert result.success, result.errors
    assert set(result.images) == set(MULTI_VIEW_DEFAULT)
    for view, path in result.images.items():
        assert path.exists() and path.stat().st_size > 0, view
    assert isinstance(result.metadata, dict)


def test_export_stl(engine, source_file, tmp_path):
    """STL export produces a real mesh file and reports its format."""
    out = tmp_path / "fixture.stl"
    result = engine.export(source_file, out, fmt="stl")
    assert isinstance(result, ExportResult)
    assert result.success, result.errors
    assert result.format == "stl"
    assert result.output_path == out and out.stat().st_size > 84
    assert result.stl_path == out  # compatibility alias
    extent = stl_extent(out)
    assert all(8.0 < e < 12.0 for e in extent), extent


def test_export_stl_wrapper_matches_export(engine, source_file, tmp_path):
    """The legacy export_stl entry point is the same operation as export(fmt='stl')."""
    result = engine.export_stl(source_file, tmp_path / "wrapped.stl")
    assert result.success, result.errors
    assert result.format == "stl"


def test_unsupported_format_is_an_error_result(engine, source_file, tmp_path):
    """An unknown format comes back as a failed ExportResult, never an exception."""
    result = engine.export(source_file, tmp_path / "fixture.xyz", fmt="xyz")
    assert isinstance(result, ExportResult)
    assert result.success is False
    assert result.format == "xyz"
    assert result.errors and "xyz" in result.errors[0]
    assert not (tmp_path / "fixture.xyz").exists()


def test_validate_syntax(engine, engine_name):
    """Good source validates; broken source reports at least one error."""
    good = engine.validate_syntax(SOURCES[engine_name])
    assert isinstance(good, ValidationResult)
    assert good.valid, good.errors
    bad = engine.validate_syntax(BAD_SOURCES[engine_name])
    assert not bad.valid
    assert bad.errors


def test_defines_reach_the_model(engine, source_file, tmp_path):
    """A `-D size=20` override doubles the exported extent of the fixture."""
    base = engine.export(source_file, tmp_path / "base.stl", fmt="stl")
    doubled = engine.export(source_file, tmp_path / "doubled.stl", fmt="stl", defines={"size": "20"})
    assert base.success and doubled.success, (base.errors, doubled.errors)
    e0 = stl_extent(tmp_path / "base.stl")
    e1 = stl_extent(tmp_path / "doubled.stl")
    for a, b in zip(e0, e1):
        assert 1.8 < b / a < 2.2, (e0, e1)


def test_unknown_setting_is_announced(engine_name, capsys):
    """A misspelled [engine.<name>] key is reported on stderr, not silently dropped."""
    eng = get_engine(engine_name, settings={"bogus_setting": 1})
    err = capsys.readouterr().err
    assert "bogus_setting" in err and eng.name in err
    assert eng.setting("bogus_setting") is None
