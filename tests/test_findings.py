"""One finding type wherever agentcad judges something.

The settings check keeps every field its JSON had; the tray's findings say
which rule judged, which layer set the limit and how to fix it; a session
stores its measurements apart from its judgments and re-judges them against
the current rules when it loads; the viewer shows the findings.
"""

import json
from pathlib import Path

import pytest

from agentcad import cli
from agentcad.findings import Finding
from agentcad.report import feature_effect

DATA = Path(__file__).resolve().parent / "data"

PLAIN = ("G1 X1 E1\n; prusaslicer_config = begin\n; layer_height = 0.2\n; temperature = 280\n"
         "; support_material_buildplate_only = 0\n; printhost_apikey = secret\n; prusaslicer_config = end\n")
INTENT = ('[slice]\nlayer_height = 0.2\ntemperature = { min = 270, max = 275, why = "layer bond" }\n'
          'support_material_buildplate_only = { value = true, why = "supports must not grow inside the bores" }\n'
          'brim_width = 5\n')


def test_gcode_check_json_keeps_every_field_it_had(tmp_path, capsys):
    (tmp_path / "part.gcode").write_text(PLAIN)
    (tmp_path / "intent.toml").write_text(INTENT)
    with pytest.raises(SystemExit) as e:
        cli.main(["gcode", "check", str(tmp_path / "part.gcode"), "--intent", str(tmp_path / "intent.toml"), "--json"])
    assert e.value.code == 1
    got = json.loads(capsys.readouterr().out)
    golden = json.loads((DATA / "gcode_check_golden.json").read_text())   # captured before findings grew
    assert len(got) == len(golden)
    for before, now in zip(golden, got):
        assert {k: now[k] for k in before} == before
    assert {f["rule"] for f in got} == {"slice_setting"}
    assert all(f["fix"] for f in got if f["severity"] != "ok") and not any(f["fix"] for f in got if f["severity"] == "ok")


def test_a_tray_finding_names_its_rule_the_layer_that_set_the_limit_and_a_fix():
    meta = {"volume": 10.0, "counts": {"solids": 3}, "short_edges": 2, "min_edge_mm": 0.01}
    rep = feature_effect(None, meta, expected_solids=2, short_edge_mm=0.25,
                         limits_from={"expected_solids": "project [engine] expected_solids"})
    by_rule = {f.rule: f for f in rep.findings}
    solids = by_rule["solid_count"]
    assert (solids.found, solids.intended, solids.severity) == ("3", "2", "warning")
    assert solids.layer == "project [engine] expected_solids" and solids.fix
    assert by_rule["short_edge"].layer == "default"
    assert [f.sentence() for f in rep.findings][:1] and len(rep.warnings) == len(rep.findings)


def test_a_finding_round_trips_and_never_invents_a_severity():
    f = Finding("solids", "warning", "3", "1", "parts in pieces", "default", rule="solid_count", fix="join them")
    assert Finding.from_dict(f.to_dict()) == f
    with pytest.raises(ValueError, match="severity"):
        Finding("solids", "critical", "3", "1", "", "default")
