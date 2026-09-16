"""Viewer plumbing is engine-neutral: extensions and languages come from the engine."""

import re
from pathlib import Path

import pytest

import agentcad
from agentcad.config import ProjectConfig
from agentcad.engines import list_engines
from agentcad.output import DesignProject
from agentcad.viewer import _scan_versioned_files, regenerate_from_project_dir, version_pattern


def test_version_pattern_is_built_from_given_extensions():
    pat = version_pattern([".py", "stl"])
    assert pat.match("part_v3_iso.py")
    assert pat.match("part_v3.STL")
    assert not pat.match("part_v3.scad")
    assert not pat.match("part_3.py")


def test_scan_only_matches_requested_extension(tmp_path):
    (tmp_path / "a_v1.py").write_text("")
    (tmp_path / "a_v2.py").write_text("")
    (tmp_path / "a_v2.scad").write_text("")
    found = _scan_versioned_files(tmp_path, ".py")
    assert sorted(found) == [1, 2]
    assert found[2]["files"][""].name == "a_v2.py"


def test_save_source_requires_an_extension(tmp_path):
    from agentcad.config import OutputConfig
    project = DesignProject("p", OutputConfig(base_dir=str(tmp_path), sub_dir="d"))
    variant = project.add_variant("v1")
    with pytest.raises(ValueError):
        project.save_source(variant, "x")
    project.source_extension = ".py"
    out = project.save_source(variant, "x")
    assert out.name == "v1.py"


@pytest.mark.skipif("voxelcad" not in list_engines(), reason="VoxelCAD engine not registered")
def test_regenerate_uses_the_project_engine_for_sources(tmp_path):
    """A .py project regenerates from .py sources and highlights as python."""
    designs = tmp_path / "designs"
    proj = designs / "regen"
    (proj / "source").mkdir(parents=True)
    (proj / "renders").mkdir()
    (proj / "exports").mkdir()
    (proj / "agentcad.toml").write_text(
        f'[project]\nname = "regen"\nengine = "voxelcad"\n'
        f'[output]\nbase_dir = "{tmp_path}"\nsub_dir = "designs"\n'
    )
    (proj / "source" / "regen_v1.py").write_text("model = None\n")
    (proj / "source" / "regen_v1.scad").write_text("cube(1);\n")  # must be ignored
    (proj / "renders" / "regen_v1_iso.png").write_bytes(b"\x89PNG")
    (proj / "exports" / "regen_v1.stl").write_bytes(b"\0" * 84)

    html_path = regenerate_from_project_dir(proj, cfg=ProjectConfig.load(proj / "agentcad.toml"))
    html = html_path.read_text()
    assert "v1 (latest)" in html
    assert "language-python" in html
    assert "cube(1)" not in html
    assert "model = None" in html


def test_no_scad_literal_outside_the_openscad_engine():
    """The only module allowed to know about `.scad` is the OpenSCAD engine."""
    root = Path(agentcad.__file__).parent
    offenders = []
    for path in root.rglob("*.py"):
        if path.name == "openscad.py" and path.parent.name == "engines":
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r"\.scad\b", line):
                offenders.append(f"{path.relative_to(root)}:{lineno}: {line.strip()}")
    assert not offenders, "\n".join(offenders)
