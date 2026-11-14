"""Settings check: a sliced file's configuration against the project's declared [slice] intent."""
import json
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


def test_a_quoted_string_setting_is_read_the_way_the_slicer_writes_it():
    """PrusaSlicer writes a string setting quoted, with a quote or backslash inside escaped: the value below is what
    2.9.6 wrote back for filament_notes = 'say "hi" and a\\b'. Read with its quotes merely stripped it differed
    from the text asked for, and stage --slice reported an error on a setting written correctly."""
    found = {"filament_notes": '"say \\"hi\\" and a\\\\b"', "filament_settings_id": '"Generic PLA"', "notes": ""}
    intent = {"filament_notes": 'say "hi" and a\\b', "filament_settings_id": "Generic PLA", "notes": ""}
    by = {f.key: f.severity for f in check.check(found, intent, "t")}
    assert by == {"filament_notes": "ok", "filament_settings_id": "ok", "notes": "ok"}
    assert check.check({"filament_notes": '"say \\"hi\\""'}, {"filament_notes": 'say "ho"'}, "t")[0].severity == "error"
    # a single string keeps its quotes (see the test below), so quotes the text asked for lacks are a difference
    assert check.check({"start_gcode": '"M104 S200\\nG28"'}, {"start_gcode": "M104 S200\nG28"}, "t")[0].severity == "error"


#: printer_notes as PrusaSlicer 2.9.6 wrote it into the golden pair's slice (tests/data/golden_pair/peg.bgcode): a single
#: string setting, written bare, its line breaks escaped.
PRINTER_NOTES_AS_WRITTEN = (
    r"""Don't remove the following keywords! These keywords are used in the "compatible printer" condition of the """
    r"""print and filament profiles to link the particular print and filament profiles to this printer profile.\n"""
    r"""PRINTER_MODEL_MK4IS\nPG""")


def test_a_bare_string_setting_is_read_the_way_the_slicer_writes_it_too():
    """A single string setting (start_gcode, printer_notes) is written without quotes but with the same escapes, so
    the text asked for, with real line breaks, matches the value as the slicer wrote it. What is asked for stays
    plain text: a backslash in it is a backslash."""
    asked = ("Don't remove the following keywords! These keywords are used in the \"compatible printer\" condition of "
             "the print and filament profiles to link the particular print and filament profiles to this printer "
             "profile.\nPRINTER_MODEL_MK4IS\nPG")
    found = {"printer_notes": PRINTER_NOTES_AS_WRITTEN, "start_gcode": r"M17 ; enable steppers\nG28",
             "post_process_notes": r"C:\\tools\\run.bat"}
    intent = {"printer_notes": asked, "start_gcode": "M17 ; enable steppers\nG28", "post_process_notes": r"C:\tools\run.bat"}
    assert {f.key: f.severity for f in check.check(found, intent, "t")} == {
        "printer_notes": "ok", "start_gcode": "ok", "post_process_notes": "ok"}
    assert check.check({"start_gcode": r"M17\nG28"}, {"start_gcode": "M17\nG29"}, "t")[0].severity == "error"


def test_a_single_string_setting_keeps_its_quotes():
    """PrusaSlicer 2.9.6 held end_gcode = "; MARK3 quoted whole" with its quotes: a real slice emitted both. A file
    holding the quoted text is not the text asked for without them; asking for exactly what the file holds is ok.
    A list of strings (filament_notes) still has its quotes read as the item's."""
    held = '"; MARK3 quoted whole"'
    assert check.check({"end_gcode": held}, {"end_gcode": "; MARK3 quoted whole"}, "t")[0].severity == "error"
    assert check.check({"end_gcode": held}, {"end_gcode": held}, "t")[0].severity == "ok"
    assert check.check({"end_gcode": "; MARK3 quoted whole"}, {"end_gcode": held}, "t")[0].severity == "error"
    assert check.check({"end_gcode": "; MARK3 quoted whole"}, {"end_gcode": "; MARK3 quoted whole"}, "t")[0].severity == "ok"
    assert check.check({"end_gcode": '"a\\nb"'}, {"end_gcode": '"a\nb"'}, "t")[0].severity == "ok"
    assert check.check({"filament_notes": '"x y"'}, {"filament_notes": "x y"}, "t")[0].severity == "ok"


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
    assert r.returncode == 0 and "no print or slice intent declared" in r.stdout and "secret" not in r.stdout


# --- intent as the slicer's target sees it: [print] mapped, then [slice], then [slice.<target>] ---------------

SLICED = """G1 X1 E1
; prusaslicer_config = begin
; layer_height = 0.15
; perimeters = 2
; fill_density = 15%
; support_material = 1
; support_material_auto = 1
; brim_width = 3
; prusaslicer_config = end
"""

JOB = """[job]
date = "2026-10-10"

[print]
material = "CF-PLA"
layer_height = 0.15
walls = 3
infill_percent = 15
supports = true

[slice.prusaslicer]
brim_width = { value = 3, why = "a long rail warps at its ends" }
"""


def _sliced(tmp_path, text=SLICED):
    g = tmp_path / "part.gcode"
    g.write_text(text)
    return check.embedded_config(g)


def test_print_intent_is_checked_as_the_target_maps_it_and_native_tables_are_settings(tmp_path):
    (tmp_path / "job.toml").write_text(JOB)
    intent, notes, conflicts = check.intent_for(tmp_path / "job.toml")
    assert "prusaslicer" not in intent                       # a target's table is not a setting of that name
    by = {f.key: f for f in check.check(_sliced(tmp_path), intent, "job.toml [slice]")}
    assert by["layer_height"].severity == "ok" and by["fill_density"].severity == "ok"
    assert by["support_material"].severity == "ok" and by["brim_width"].severity == "ok"
    walls = by["perimeters"]
    assert walls.severity == "error" and walls.found == "2" and walls.intended == "3"
    assert "[print] walls" in walls.sentence()               # the setting names the neutral key it came from
    assert conflicts == []
    assert notes == ["material: the filament profile in the base configuration carries the material"]


def test_a_native_value_overrides_the_mapped_one_and_the_conflict_is_reported(tmp_path):
    (tmp_path / "job.toml").write_text(JOB.replace("brim_width =", "layer_height = 0.2\nbrim_width ="))
    intent, _, conflicts = check.intent_for(tmp_path / "job.toml")
    assert intent["layer_height"] == 0.2
    assert conflicts == ["layer_height: [print] maps to '0.15', the native table says 0.2 (native kept)"]
    by = {f.key: f for f in check.check(_sliced(tmp_path), intent, "job.toml [slice]")}
    assert by["layer_height"].severity == "error"


def test_a_bare_slice_table_belongs_to_the_default_target_only(tmp_path):
    (tmp_path / "a.toml").write_text('[slice]\nbrim_width = 5\n')
    assert check.intent_for(tmp_path / "a.toml")[0] == {"brim_width": 5}
    (tmp_path / "b.toml").write_text('[print]\ntarget = "generic"\n[slice]\nbrim_width = 5\n'
                                     '[slice.prusaslicer]\nskirts = 0\n')
    assert check.intent_for(tmp_path / "b.toml")[0] == {"skirts": 0}


def test_with_json_stdout_carries_only_the_findings_and_the_rest_goes_to_stderr(tmp_path):
    g = tmp_path / "part.gcode"
    g.write_text(SLICED)
    (tmp_path / "job.toml").write_text(JOB.replace("brim_width =", "layer_height = 0.2\nbrim_width ="))
    run = [sys.executable, "-c", "import sys; from agentcad.cli import main; sys.exit(main())"]
    r = subprocess.run(run + ["gcode", "check", str(g), "--intent", str(tmp_path / "job.toml"), "--json"],
                       capture_output=True, text=True)
    findings = json.loads(r.stdout)
    assert findings and all("sentence" in f for f in findings)
    assert "conflict: layer_height" in r.stderr and "not checked: [print] material" in r.stderr
    (tmp_path / "none.toml").write_text('[job]\ndate = "2026-10-10"\n')
    r = subprocess.run(run + ["gcode", "check", str(g), "--intent", str(tmp_path / "none.toml"), "--json"],
                       capture_output=True, text=True)
    assert r.returncode == 0 and json.loads(r.stdout) == []
    assert "no print or slice intent declared" in r.stderr


def test_cli_reports_conflicts_and_unmapped_keys_and_refuses_an_unusable_print_value(tmp_path):
    g = tmp_path / "part.gcode"
    g.write_text(SLICED)
    (tmp_path / "job.toml").write_text(JOB)
    run = [sys.executable, "-c", "import sys; from agentcad.cli import main; sys.exit(main())"]
    r = subprocess.run(run + ["gcode", "check", str(g), "--intent", str(tmp_path / "job.toml")],
                       capture_output=True, text=True)
    assert r.returncode == 1
    assert "not checked: [print] material: the filament profile" in r.stdout
    assert "ERROR: perimeters is 2" in r.stdout
    (tmp_path / "bad.toml").write_text('[print]\nwalls = 2.5\n')
    r = subprocess.run(run + ["gcode", "check", str(g), "--intent", str(tmp_path / "bad.toml")],
                       capture_output=True, text=True)
    assert r.returncode == 2 and "Error:" in r.stderr and "walls" in r.stderr
    (tmp_path / "none.toml").write_text('[job]\ndate = "2026-10-10"\n')
    r = subprocess.run(run + ["gcode", "check", str(g), "--intent", str(tmp_path / "none.toml")],
                       capture_output=True, text=True)
    assert r.returncode == 0 and "no print or slice intent declared" in r.stdout
