"""Settings check: a sliced file's configuration against the project's declared [slice] intent."""
import subprocess
import sys

from agentcad.config import ProjectConfig
from agentcad.gcode import check
from agentcad.manifest import PrintManifest

PLAIN = """G1 X1 E1
; prusaslicer_config = begin
; layer_height = 0.2
; temperature = 280
; support_material_buildplate_only = 0
; printhost_apikey = secret
; prusaslicer_config = end
"""

INTENT = """[slice]
layer_height = 0.2
temperature = { min = 270, max = 275, why = "layer bond" }
support_material_buildplate_only = { value = true, why = "supports must not grow inside the bores" }
brim_width = 5
"""


def test_findings_say_what_differs_and_why(tmp_path):
    g = tmp_path / "part.gcode"
    g.write_text(PLAIN)
    t = tmp_path / "agentcad.toml"
    t.write_text(INTENT)
    cfg = check.embedded_config(g)
    assert cfg["temperature"] == "280" and "printhost_apikey" in cfg
    by = {f.key: f for f in check.check(cfg, check.load_intent(t), "agentcad.toml [slice]")}
    assert by["layer_height"].severity == "ok"
    assert by["temperature"].severity == "warning"                 # outside the declared range
    f = by["support_material_buildplate_only"]
    assert f.severity == "error" and f.found == "0" and f.intended == "1"
    assert "asks for 1" in f.sentence() and "supports must not grow inside the bores" in f.sentence()
    assert by["brim_width"].severity == "warning" and "not in the file" in by["brim_width"].sentence()


def test_private_keys_are_never_checked_or_echoed():
    findings = check.check({"printhost_apikey": "secret"}, {"printhost_apikey": "x"}, "t")
    assert findings == []


def test_slice_intent_travels_with_the_project_and_the_manifest(tmp_path):
    (tmp_path / "agentcad.toml").write_text('[project]\nname = "p"\n' + INTENT)
    cfg = ProjectConfig.load(tmp_path / "agentcad.toml")
    assert cfg.slice_intent["layer_height"] == 0.2
    (tmp_path / "old").mkdir()
    (tmp_path / "old" / "agentcad.toml").write_text('[project]\nname = "old"\n')
    assert ProjectConfig.load(tmp_path / "old" / "agentcad.toml").slice_intent == {}      # old projects unchanged
    m = PrintManifest(part_name="p", slice_intent=cfg.slice_intent)
    m.save(tmp_path / "p.print.json")
    assert PrintManifest.load(tmp_path / "p.print.json").slice_intent["brim_width"] == 5


def test_cli_exits_1_on_an_error_and_reports_without_intent(tmp_path):
    g = tmp_path / "part.gcode"
    g.write_text(PLAIN)
    (tmp_path / "agentcad.toml").write_text(INTENT)
    run = [sys.executable, "-c", "import sys; from agentcad.cli import main; sys.exit(main())"]
    r = subprocess.run(run + ["gcode", "check", str(g), "--project", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 1 and "ERROR: support_material_buildplate_only is 0" in r.stdout
    r = subprocess.run(run + ["gcode", "check", str(g)], capture_output=True, text=True)
    assert r.returncode == 0 and "no [slice] intent declared" in r.stdout and "secret" not in r.stdout
