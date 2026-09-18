"""CLI smoke: the commands the contract test mirrors, run through argparse."""

import sys

import pytest

from agentcad.cli import main
from agentcad.engines import get_engine, list_engines

from .conftest import SOURCES


def _run(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["agentcad"] + argv)
    main()


def test_info_lists_every_registered_engine(monkeypatch, capsys):
    _run(monkeypatch, ["info"])
    out = capsys.readouterr().out
    assert "Registered engines" in out
    for name in list_engines():
        assert f"  {name}:" in out
    assert "exports" in out


@pytest.mark.parametrize("engine_name", list_engines())
def test_render_and_export_through_the_cli(engine_name, monkeypatch, capsys, tmp_path):
    engine = get_engine(engine_name)
    if not engine.available() or engine_name not in SOURCES:
        pytest.skip(f"{engine.name} not available")
    src = tmp_path / f"m{engine.file_extension}"
    src.write_text(SOURCES[engine_name])
    out_dir = tmp_path / "out"

    _run(monkeypatch, ["render", str(src), "-e", engine_name, "-o", str(out_dir), "-v", "iso", "-s", "96"])
    assert (out_dir / "m_iso.png").stat().st_size > 0
    assert "Rendered 1 view" in capsys.readouterr().out

    _run(monkeypatch, ["export", str(src), "-e", engine_name, "-o", str(tmp_path / "m.stl"), "-D", "size=12"])
    assert (tmp_path / "m.stl").stat().st_size > 84
    assert "Exported" in capsys.readouterr().out

    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, ["export", str(src), "-e", engine_name, "--format", "xyz"])
    assert exc.value.code == 1
    assert "cannot export 'xyz'" in capsys.readouterr().err


def test_session_lifecycle_through_the_cli(monkeypatch, capsys, tmp_path):
    """start, iterate (with a per-iteration -D), tag, finalize, reopen,
    finalize again, status, a refused start, a forced start that archives,
    and the projects listing -- the loop a design goes through."""
    engine = get_engine("openscad")
    if not engine.available():
        pytest.skip("OpenSCAD not available")
    designs = tmp_path / "designs"
    project = designs / "cube"
    project.mkdir(parents=True)
    (project / "agentcad.toml").write_text(
        f'[project]\nname = "cube"\nengine = "openscad"\n'
        f'[output]\nbase_dir = "{tmp_path}"\nsub_dir = "designs"\nimage_size = 64\ndefault_views = ["iso"]\n'
    )
    src = tmp_path / "cube.scad"
    src.write_text("size = 10;\ncube(size);\n")

    _run(monkeypatch, ["session", "start", str(project)])
    assert "Session started" in capsys.readouterr().out

    _run(monkeypatch, ["session", "iterate", str(project), str(src)])
    out = capsys.readouterr().out
    assert "Iteration v1 recorded" in out and "Report v1" in out and "volume" in out

    _run(monkeypatch, ["session", "iterate", str(project), str(src), "-D", "size=20"])
    out = capsys.readouterr().out
    assert "Iteration v2 recorded" in out and "+700" in out.replace(" ", "")  # 8000 - 1000, printed as +7000

    _run(monkeypatch, ["session", "tag", str(project), "draft1", "--note", "review"])
    assert "Tagged v2 as 'draft1'" in capsys.readouterr().out
    assert (project / "tags" / "draft1" / "TAG.json").exists()
    with pytest.raises(SystemExit):
        _run(monkeypatch, ["session", "tag", str(project), "draft1"])
    capsys.readouterr()

    _run(monkeypatch, ["session", "finalize", str(project)])
    assert "Session finalized." in capsys.readouterr().out
    assert (project / "exports" / "cube_v2.stl").exists()

    _run(monkeypatch, ["session", "reopen", str(project)])
    assert "next iteration is v3" in capsys.readouterr().out
    _run(monkeypatch, ["session", "iterate", str(project), str(src)])
    capsys.readouterr()
    _run(monkeypatch, ["session", "finalize", str(project)])
    capsys.readouterr()
    _run(monkeypatch, ["session", "status", str(project)])
    assert "Iterations: 3/10" in capsys.readouterr().out

    _run(monkeypatch, ["session", "reopen", str(project)])
    capsys.readouterr()
    with pytest.raises(SystemExit):           # an open session refuses a plain start
        _run(monkeypatch, ["session", "start", str(project)])
    assert "Use --force" in capsys.readouterr().err
    _run(monkeypatch, ["session", "start", str(project), "-f"])
    assert "Archived previous session" in capsys.readouterr().out
    archives = list((project / "_work").glob("archive_*"))
    assert len(archives) == 1 and (archives[0] / "session.json").exists()

    monkeypatch.setenv("HOME", str(tmp_path))
    _run(monkeypatch, ["viewer", str(project), "--tag", "draft1"])
    assert (project / "tags" / "draft1" / "index.html").exists()


def test_export_variants_writes_one_file_per_value(monkeypatch, capsys, tmp_path):
    engine = get_engine("openscad")
    if not engine.available():
        pytest.skip("OpenSCAD not available")
    src = tmp_path / "cube.scad"
    src.write_text("size = 10;\ncube(size);\n")
    _run(monkeypatch, ["export", str(src), "-e", "openscad", "-o", str(tmp_path / "cube.stl"), "--variants", "size=8,10.5"])
    out = capsys.readouterr().out
    assert (tmp_path / "cube_size-8.stl").stat().st_size > 0
    assert (tmp_path / "cube_size-10p5.stl").stat().st_size > 0
    assert "size=8" in out and "size=10.5" in out
