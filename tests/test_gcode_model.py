"""The sliced-file model: layers, objects, feature types and the filament the slicer would report."""
import json
import math
import subprocess
import sys

import pytest

from agentcad.gcode import model as gm

SLICED = """M83
M486 S0
M486 Apeg.stl
M486 S-1
;TYPE:Custom
G1 X0 Y-3 E5 F1000
;LAYER_CHANGE
;Z:0.2
;HEIGHT:0.2
G1 Z.2
;TYPE:Skirt/Brim
;WIDTH:0.5
G1 X10 Y0 E1
M486 S0
;TYPE:Support material
G1 X10 Y10 E.5
;TYPE:External perimeter
G1 X0 Y10 E2
G1 E-.7
G1 E.7
;LAYER_CHANGE
;Z:0.4
;HEIGHT:0.2
G1 Z.4
;TYPE:Perimeter
G1 X0 Y0 E2
G1 E-.7
M486 S-1
;TYPE:Custom
G1 Z10
"""


def test_layers_objects_features_and_the_slicers_filament_total():
    m = gm.parse(SLICED)
    assert [(L.index, L.z, L.height) for L in m.layers] == [(0, 0.2, 0.2), (1, 0.4, 0.2)]
    assert m.objects == {0: "peg.stl"}
    by = m.totals("object_feature")
    assert by[("peg.stl", "Support material")]["filament"] == pytest.approx(0.5)
    assert by[(None, "Skirt/Brim")]["filament"] == pytest.approx(1.0)
    assert by[(None, "Custom")]["filament"] == pytest.approx(5.0)      # priming before the first layer
    assert [p.layer for p in m.paths if p.feature == "Custom"] == [-1]
    assert m.filament_net == pytest.approx(10.5 - 0.7)                  # the final retraction is never primed
    assert m.final_retraction == pytest.approx(-0.7)
    assert m.filament_used == pytest.approx(10.5)


def test_absolute_extrusion_with_g92_resets():
    m = gm.parse("M82\nG92 E0\nG1 X10 E2\nG1 X20 E5\nG92 E0\nG1 X30 E1\n")
    assert m.filament_used == pytest.approx(6.0)
    assert sum(p.length for p in m.paths) == pytest.approx(30.0)


def test_arcs_are_followed_not_cut_short():
    m = gm.parse("M83\nG1 X10 Y0\nG3 X0 Y10 I-10 J0 E1\n")          # a quarter circle of radius 10
    assert sum(p.length for p in m.paths) == pytest.approx(math.pi * 10 / 2, rel=0.01)


def test_files_without_feature_comments_still_give_layers_and_totals():
    m = gm.parse("M83\nG1 Z.3\nG1 X5 E1\nG1 Z.6\nG1 X0 E1\n")
    assert not m.features_known
    assert len(m.layers) == 2 and m.filament_used == pytest.approx(2.0)
    assert {p.feature for p in m.paths} == {"unknown"}


def test_summary_record_and_cli(tmp_path):
    s = gm.summary(gm.parse(SLICED), density=1.24)
    assert s["schema"] == "agentcad.gcode.summary/1"
    assert s["support"]["first_layer"] == 0 and s["support"]["first_z"] == 0.2
    assert s["by_object"]["peg.stl"]["support_share"] == pytest.approx(0.5 / 4.5, abs=1e-3)
    assert s["brim_area_mm2"] == pytest.approx(math.hypot(10, 3) * 0.5, abs=0.05)   # from where the purge ended
    assert "mass_g" in s["filament_used"]
    f = tmp_path / "peg.gcode"
    f.write_text(SLICED)
    run = [sys.executable, "-c", "import sys; from agentcad.cli import main; sys.exit(main())"]
    r = subprocess.run(run + ["gcode", "summary", str(f), "--json"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["layers"] == 2
    r = subprocess.run(run + ["gcode", "summary", str(f)], capture_output=True, text=True)
    assert "supports:" in r.stdout and "peg.stl" in r.stdout
