"""QC: the printer registry and its process defaults, the [qc] limits and the layer that set each,
the build-volume rule in the declared print pose, the qc and printers commands, and the opt-in
gate at finalize (the viewer still written, no manifest, a non-zero exit)."""

import json
from pathlib import Path

import pytest

from agentcad import printers, qc
from agentcad.config import OutputConfig, ProjectConfig
from agentcad.engine import ExportResult
from agentcad.session import DesignSession
from tests.test_session import FakeEngine


def _box_stl(path: Path, size) -> Path:
    """An ASCII STL of the box from the origin to ``size``."""
    x, y, z = size
    c = [(0, 0, 0), (x, 0, 0), (x, y, 0), (0, y, 0), (0, 0, z), (x, 0, z), (x, y, z), (0, y, z)]
    faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
             (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    lines = ["solid box"]
    for f in faces:
        lines += ["facet normal 0 0 0", "outer loop"] + [f"vertex {c[i][0]} {c[i][1]} {c[i][2]}" for i in f]
        lines += ["endloop", "endfacet"]
    path.write_text("\n".join(lines + ["endsolid box"]) + "\n")
    return path


def _box_vertices(size):
    import numpy as np
    x, y, z = size
    return np.array([(a, b, c) for a in (0, x) for b in (0, y) for c in (0, z)], dtype=float)


class FakeBoxEngine(FakeEngine):
    """Exports a real box: a ``size = x, y, z`` line in the source sets its extents."""

    def export(self, source_path, output_path, fmt="stl", defines=None):
        size = (10.0, 10.0, 10.0)
        for line in Path(source_path).read_text().splitlines():
            if line.startswith("size"):
                size = tuple(float(v) for v in line.split("=")[1].split(","))
        _box_stl(Path(output_path), size)
        return ExportResult(output_path=Path(output_path), format=fmt, metadata=self._measure(source_path))


def test_the_registry_names_each_printers_process_volume_and_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    reg = printers.registry()
    mk4, form3 = reg["mk4"], reg["form3"]
    assert (mk4.process, mk4.build_volume, mk4.nozzle_mm) == ("fdm", (250.0, 210.0, 220.0), 0.4)
    assert (form3.process, form3.build_volume) == ("resin", (145.0, 145.0, 185.0))
    assert mk4.defaults()["min_wall_mm"] == pytest.approx(0.9) and form3.defaults()["min_wall_mm"] == 0.4
    # a user file adds a printer, and a project's table replaces one by name
    (tmp_path / "cfg" / "agentcad").mkdir(parents=True)
    (tmp_path / "cfg" / "agentcad" / "printers.toml").write_text(
        '[printers.xl]\nlabel = "Large FDM"\nprocess = "fdm"\nbuild_volume = [360, 360, 360]\nnozzle_mm = 0.6\n')
    (tmp_path / "agentcad.toml").write_text(
        '[project]\nname = "p"\n[printers.mk4]\nlabel = "MK4, short Z"\nprocess = "fdm"\n'
        'build_volume = [250, 210, 180]\nnozzle_mm = 0.4\n')
    reg = printers.registry(ProjectConfig.load(tmp_path / "agentcad.toml"))
    assert reg["xl"].source.endswith("printers.toml") and reg["xl"].defaults()["min_feature_mm"] == pytest.approx(0.675)
    assert reg["mk4"].build_volume[2] == 180 and reg["mk4"].source.endswith("agentcad.toml")
    with pytest.raises(KeyError, match="form3"):
        printers.get("nope", ProjectConfig.load(tmp_path / "agentcad.toml"))


def test_a_slicer_configuration_describes_its_printer():
    p = printers.from_slicer_config({"bed_shape": "0x0,250x0,250x210,0x210", "max_print_height": "220",
                                     "nozzle_diameter": "0.4,0.4"})
    assert p.process == "fdm" and p.build_volume == (250.0, 210.0, 220.0) and p.nozzle_mm == 0.4


def test_a_part_taller_than_the_mk4_is_flagged_and_lies_down_clean():
    mk4 = printers.registry()["mk4"]
    tall = _box_vertices((20, 20, 230))
    standing = qc.check_build_volume(tall, mk4)
    assert (standing.rule, standing.severity) == ("build_volume", "error")
    assert "230" in standing.found and "220" in standing.intended and "mk4" in standing.layer
    assert qc.check_build_volume(tall, mk4, pose={"up": [1, 0, 0]}).severity == "ok"
    # long along y as built: the bed fits it only turned a quarter about z, which the finding names
    long_y = qc.check_build_volume(_box_vertices((15, 240, 10)), mk4)
    assert long_y.severity == "warning" and "spin" in long_y.sentence() and "90" in long_y.sentence()


def test_the_same_part_on_the_form3_is_judged_by_its_volume_and_resin_defaults():
    form3 = printers.registry()["form3"]
    tall = _box_vertices((20, 20, 230))
    assert qc.check_build_volume(tall, form3).severity == "error"
    assert qc.check_build_volume(tall, form3, pose={"up": [1, 0, 0]}).severity == "error"   # 230 > the bed's diagonal
    limits = qc.limits(form3, qc.QCSettings())
    assert limits["min_wall_mm"] == (0.4, "process default (resin)")
    layered = qc.limits(printers.registry()["mk4"], qc.QCSettings(limits={"min_wall_mm": 1.6}))
    assert layered["min_wall_mm"] == (1.6, "project [qc]")
    assert layered["min_feature_mm"][1] == "process default (fdm, 0.4 mm nozzle)"


def _session(tmp_path, qc_table, size):
    cfg = ProjectConfig(output=OutputConfig(base_dir=tmp_path, sub_dir="designs", default_views=["iso"]))
    cfg.qc = qc_table
    s = DesignSession("tall", FakeBoxEngine(), config=cfg)
    s.iterate(f"volume = 10\nsize = {size}\n")
    return s


def test_the_gate_holds_back_the_manifest_and_marks_the_viewer(tmp_path):
    held = _session(tmp_path / "a", {"gate": True}, "20, 20, 230")
    html = held.finalize().read_text()
    assert held.qc_failed and not (held.project.exports_dir / "tall.print.json").exists()
    assert not held._finalized                                    # held, not finalized: iterate on without reopening
    assert "QC gate failed" in html and "build_volume" in html
    lying = _session(tmp_path / "b", {"gate": True, "pose": {"up": [1, 0, 0]}}, "20, 20, 230")
    lying.finalize()
    assert not lying.qc_failed and (lying.project.exports_dir / "tall.print.json").exists()
    shown = _session(tmp_path / "c", {}, "20, 20, 230")          # a [qc] table without the gate: shown, not held
    html = shown.finalize().read_text()
    assert not shown.qc_failed and (shown.project.exports_dir / "tall.print.json").exists()
    assert "build_volume" in html and "QC gate failed" not in html
    plain = _session(tmp_path / "d", None, "20, 20, 230")         # no [qc] table: nothing runs
    html = plain.finalize().read_text()
    assert not plain.qc_failed and "build_volume" not in html


def test_qc_and_printers_commands(tmp_path, monkeypatch, capsys):
    from agentcad import cli
    proj = tmp_path / "designs" / "tall"
    proj.mkdir(parents=True)
    (proj / "agentcad.toml").write_text(f'[project]\nname = "tall"\nengine = "fake"\n'
                                        f'[output]\nbase_dir = "{tmp_path}"\nsub_dir = "designs"\ndefault_views = ["iso"]\n'
                                        '[qc]\nprinter = "mk4"\n')
    monkeypatch.setattr(cli, "_engine_for", lambda name, cfg: FakeBoxEngine())
    (proj / "tall.fake").write_text("volume = 10\nsize = 20, 20, 230\n")
    cli.main(["session", "start", str(proj)])
    cli.main(["session", "iterate", str(proj), str(proj / "tall.fake")])
    capsys.readouterr()
    with pytest.raises(SystemExit) as e:
        cli.main(["qc", str(proj), "--json"])
    assert e.value.code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["printer"]["name"] == "mk4" and report["findings"][0]["rule"] == "build_volume"
    assert "max_bridge_mm" in report["not_measured"] and "min_wall_mm" not in report["not_measured"]
    cli.main(["printers", "--json"])
    names = {p["name"] for p in json.loads(capsys.readouterr().out)}
    assert {"mk4", "form3"} <= names


def test_finalize_all_exits_non_zero_when_a_part_is_held(tmp_path, monkeypatch, capsys):
    from agentcad import cli
    monkeypatch.setattr(cli, "_engine_for", lambda name, cfg: FakeBoxEngine())
    asm = tmp_path / "designs" / "asm"
    (asm / "parts").mkdir(parents=True)
    out = 'default_views = ["iso"]\n'
    (asm / "agentcad.toml").write_text(f'[project]\nname = "asm"\nengine = "fake"\nparts = ["parts/*"]\n'
                                       f'[output]\nbase_dir = "{tmp_path}"\nsub_dir = "designs"\n{out}')
    for name, size in (("short", "20, 20, 20"), ("tall", "20, 20, 230")):
        d = asm / "parts" / name
        d.mkdir()
        (d / "agentcad.toml").write_text(f'[project]\nname = "{name}"\nengine = "fake"\n'
                                         f'[output]\nbase_dir = "{asm}"\nsub_dir = "parts"\n{out}[qc]\ngate = true\n')
        (d / f"{name}.fake").write_text(f"volume = 10\nsize = {size}\n")
        cli.main(["session", "start", str(d)])
        cli.main(["session", "iterate", str(d), str(d / f"{name}.fake")])
    (asm / "asm.fake").write_text("volume = 10\n")
    cli.main(["session", "start", str(asm)])
    cli.main(["session", "iterate", str(asm), str(asm / "asm.fake")])
    with pytest.raises(SystemExit) as e:
        cli.main(["session", "finalize", str(asm), "--all"])
    assert e.value.code == 1
    assert (asm / "parts" / "short" / "exports" / "short.print.json").exists()        # the other part still finalized
    assert not (asm / "parts" / "tall" / "exports" / "tall.print.json").exists()
    assert "tall" in capsys.readouterr().err
