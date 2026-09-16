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
