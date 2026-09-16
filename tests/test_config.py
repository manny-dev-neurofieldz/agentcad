"""Per-engine settings: parsed generically, delivered to the engine, visible in argv."""

from pathlib import Path

import pytest

from agentcad.camera import STANDARD_PRESETS
from agentcad.config import ProjectConfig, generate_config_template
from agentcad.engines import get_engine, list_engines

TOML = """
[project]
name = "cfgtest"
engine = "voxelcad"

[engine.openscad]
fa = 2.0
fs = 1.0
colorscheme = "Tomorrow"

[engine.build123d]
tolerance = 0.01

[engine.voxelcad]
voxel_size = 0.5
"""


@pytest.fixture
def cfg(tmp_path) -> ProjectConfig:
    path = tmp_path / "agentcad.toml"
    path.write_text(TOML)
    return ProjectConfig.load(path)


def test_every_engine_table_is_parsed(cfg):
    assert cfg.engine == "voxelcad"
    assert cfg.engine_settings("openscad") == {"fa": 2.0, "fs": 1.0, "colorscheme": "Tomorrow"}
    assert cfg.engine_settings("build123d") == {"tolerance": 0.01}
    assert cfg.engine_settings("voxelcad") == {"voxel_size": 0.5}
    assert cfg.engine_settings("nonexistent") == {}


def test_engine_settings_returns_a_copy(cfg):
    table = cfg.engine_settings("openscad")
    table["fa"] = 99
    assert cfg.engine_settings("openscad")["fa"] == 2.0


def test_legacy_openscad_dataclass_still_works(cfg):
    osc = cfg.get_openscad_config()
    assert (osc.fa, osc.fs, osc.colorscheme) == (2.0, 1.0, "Tomorrow")
    assert osc.backend == "Manifold"  # untouched default


@pytest.mark.skipif("openscad" not in list_engines(), reason="OpenSCAD engine not registered")
def test_openscad_settings_change_the_render_command(cfg, tmp_path):
    """[engine.openscad] fa/fs/colorscheme land in the argv OpenSCAD is invoked with."""
    engine = get_engine("openscad", settings=cfg.engine_settings("openscad"))
    args = engine.render_args(Path("model.scad"), tmp_path / "iso.png", STANDARD_PRESETS["iso"], 256)
    assert "$fa=2.0" in args and "$fs=1.0" in args
    assert "--colorscheme=Tomorrow" in args
    assert "--projection=ortho" not in args
    ortho = engine.render_args(Path("model.scad"), tmp_path / "front.png", STANDARD_PRESETS["front"], 256)
    assert "--projection=ortho" in ortho
    export = engine.export_args(Path("model.scad"), tmp_path / "m.3mf", fmt="3mf", defines={"w": "5"})
    assert export[-4:-2] == ["-o", str(tmp_path / "m.3mf")] or "-o" in export
    assert "--export-format" in export and "3mf" in export
    assert "w=5" in export


def test_show_lists_every_engine_table(cfg):
    text = cfg.show()
    assert "[engine.openscad]" in text and "[engine.build123d]" in text


def test_template_names_all_three_engines():
    text = generate_config_template("demo", "", "voxelcad")
    assert 'engine = "voxelcad"' in text
    for name in ("openscad", "voxelcad", "build123d"):
        assert f"[engine.{name}]" in text
