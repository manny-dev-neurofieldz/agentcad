"""The CADEngine contract, driven the way the CLI drives it, for every engine.

Each test runs once per registered engine (see conftest) and skips when the
backend is absent. A new engine that registers itself is covered here
without any test changes.
"""

from pathlib import Path

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


def test_metadata_keys_are_documented(engine, source_file, tmp_path):
    """Every key an engine reports is in METADATA_KEYS or is a <key>_error sibling.

    The report layer reads only the documented vocabulary; a number an
    engine wants on the tray must go under one of those names.
    """
    from agentcad.engine import METADATA_KEYS

    result = engine.export(source_file, tmp_path / "m.stl", fmt="stl")
    assert result.success, result.errors
    undocumented = [k for k in result.metadata if k not in METADATA_KEYS and not k.endswith("_error")]
    assert not undocumented, undocumented
    render = engine.render(source_file, tmp_path / "r", views=["iso"], image_size=64)
    undocumented = [k for k in render.metadata if k not in METADATA_KEYS and not k.endswith("_error")]
    assert not undocumented, undocumented


def test_a_relative_source_path_renders(engine, source_file, tmp_path, monkeypatch):
    """The CLI is run from anywhere; a worker-hosted engine must not open the
    source relative to its own working directory."""
    monkeypatch.chdir(source_file.parent)
    result = engine.render(Path(source_file.name), Path("rel_out"), views=["iso"], image_size=64)
    assert result.success, result.errors
    assert (source_file.parent / "rel_out" / f"{source_file.stem}_iso.png").exists()


EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


@pytest.mark.parametrize("example", ["hex_tray", "j_hook"])
def test_repository_examples_render_through_their_engine(example, tmp_path):
    """Two of the shipped examples are contract fixtures: real designs, not toy sources."""
    from agentcad.config import find_project

    folder = EXAMPLES / example
    cfg = find_project(folder)
    assert cfg is not None, folder
    engine = get_engine(cfg.engine, settings=cfg.engine_settings(cfg.engine))
    if not engine.available():
        pytest.skip(f"{engine.name} not available")
    source = next(p for p in (folder / "source").iterdir() if p.suffix == engine.file_extension)
    result = engine.render(source, tmp_path / "out", views=["iso"], image_size=96)
    assert result.success, result.errors
    assert result.metadata.get("volume", 1.0) > 0
