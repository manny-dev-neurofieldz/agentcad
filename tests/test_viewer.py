"""Viewer plumbing is engine-neutral: extensions and languages come from the engine."""

import json
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


# --- assembly meshes, the embed cap, the artifact fragment, camera presets ---

def _project_with_meshes(tmp_path, sizes):
    from agentcad.config import OutputConfig
    from agentcad.output import DesignProject
    proj = DesignProject("asm", OutputConfig(base_dir=tmp_path, sub_dir="designs"))
    proj.setup()
    v = proj.add_variant("v1 (latest)")
    for i, size in enumerate(sizes):
        p = proj.exports_dir / f"part{i}_v1.stl"
        p.write_bytes(b"\x00" * 84 + b"\x00" * size)
        v.add_mesh(f"part{i}", p, quantity=i + 1)
    (proj.renders_dir / "asm_v1_iso.png").write_bytes(b"\x89PNG")
    v.renders["iso"] = proj.renders_dir / "asm_v1_iso.png"
    return proj


def test_a_variant_with_several_meshes_gets_one_block_per_part(tmp_path):
    from agentcad.viewer import generate_html
    html = generate_html(_project_with_meshes(tmp_path, [50, 50, 50]))
    assert html.count('class="mesh-data"') == 3
    assert 'data-name="part1"' in html and "Download part2 x3" in html
    assert "loadVariantMeshes(" in html and "mesh-tree" in html
    assert "cycleSpin" in html and "setView('bottom')" in html


def test_meshes_over_the_embed_cap_are_linked_with_a_badge(tmp_path):
    from agentcad.viewer import generate_html
    proj = _project_with_meshes(tmp_path, [4000, 4000])
    small = generate_html(proj, embed_mb=1.0)
    assert 'class="mesh-badge"' not in small and small.count("data-src=") == 0
    capped = generate_html(proj, embed_mb=0.005)          # 5 kB cap, 8 kB of meshes
    assert "over the 0 MB embed cap" in capped or "embed cap" in capped
    # each mesh is either a decimated inline preview or a link; never dropped
    assert capped.count('class="mesh-data"') == 2


def test_artifact_fragment_has_no_document_shell_and_inlines_every_mesh(tmp_path):
    from agentcad.viewer import write_artifact
    proj = _project_with_meshes(tmp_path, [50])
    older = proj.add_variant("v0")
    older.add_mesh("old", proj.exports_dir / "part0_v1.stl")
    out = write_artifact(proj, tmp_path / "art", title="Asm rev z")
    html = out.read_text()
    for tag in ("<!DOCTYPE", "<html", "<head>", "<body>"):
        assert tag not in html
    assert "<title>Asm rev z</title>" in html and "<style>" in html
    assert "data-src=" not in html                       # no mesh is served as a file
    assert "not included in the artifact" in html         # the older variant says so
    assert 'href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js' not in html
    files = json.loads((tmp_path / "art" / "files.json").read_text())
    assert files and all(k.endswith(".png") for k in files)
    assert (tmp_path / "art" / "renders" / "asm_v1_iso.png").exists()


def test_bottom_and_left_presets_look_where_they_say():
    from agentcad.camera import MULTI_VIEW_DEFAULT, STANDARD_PRESETS
    from agentcad.config import OutputConfig
    assert STANDARD_PRESETS["bottom"].eye[2] < -0.99 and STANDARD_PRESETS["bottom"].orthographic
    assert STANDARD_PRESETS["left"].eye[0] < -0.99
    assert STANDARD_PRESETS["top"].eye[2] > 0.99
    assert OutputConfig().default_views == MULTI_VIEW_DEFAULT


# --- the gallery ---

def _example_project(root: Path, name: str, engine: str = "openscad", with_render: bool = True) -> Path:
    d = root / name
    (d / "renders").mkdir(parents=True)
    (d / "_work").mkdir()
    (d / "agentcad.toml").write_text(f'[project]\nname = "{name}"\nengine = "{engine}"\ndescription = "a {name}"\n')
    (d / "index.html").write_text(f'<html><body><img src="renders/{name}_v1_iso.png"></body></html>')
    if with_render:
        (d / "renders" / f"{name}_v1_iso.png").write_bytes(b"\x89PNG")
    (d / "_work" / "session.json").write_text(json.dumps({
        "schema": 2, "iterations": [{"number": 1, "timestamp": "t", "metadata": {"volume": 12.5, "counts": {"solids": 1}}}],
        "project_metadata": {"finalized": "2026-09-18T16:00:00"}}))
    return d


def test_gallery_build_copies_viewers_and_check_passes(tmp_path):
    from agentcad.gallery import build, check
    a = _example_project(tmp_path / "ex", "alpha")
    b = _example_project(tmp_path / "ex", "beta", engine="build123d")
    page = build([a, b], tmp_path / "site", title="test gallery")
    html = page.read_text()
    assert html.count('<div class="card">') == 2
    assert 'href="alpha/index.html"' in html and "volume 12.5" in html and "solids 1" in html
    assert (tmp_path / "site" / "beta" / "renders" / "beta_v1_iso.png").exists()
    assert check(tmp_path / "site") == []


def test_gallery_check_names_a_missing_thumbnail_and_an_absolute_link(tmp_path):
    from agentcad.gallery import build, check
    a = _example_project(tmp_path / "ex", "alpha")
    build([a], tmp_path / "site")
    (tmp_path / "site" / "alpha" / "renders" / "alpha_v1_iso.png").unlink()
    problems = check(tmp_path / "site")
    assert any("missing" in p for p in problems), problems
    page = tmp_path / "site" / "index.html"
    page.write_text(page.read_text().replace('href="alpha/index.html"', 'href="/abs/alpha/index.html"', 1))
    assert any("absolute" in p for p in check(tmp_path / "site"))


def test_gallery_budget_skips_a_project_that_does_not_fit(tmp_path):
    from agentcad.gallery import build
    big = _example_project(tmp_path / "ex", "big")
    (big / "renders" / "big_v1_iso.png").write_bytes(b"\x00" * 3_000_000)
    small = _example_project(tmp_path / "ex", "small")
    page = build([big, small], tmp_path / "site", max_mb=1.0)
    html = page.read_text()
    assert "not copied" in html and 'href="small/index.html"' in html
    assert not (tmp_path / "site" / "big").exists()
