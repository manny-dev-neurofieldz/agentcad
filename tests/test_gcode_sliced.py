"""One reader for a sliced file, and the printing time the summary gains from it.

``agentcad.gcode.sliced`` reads a .bgcode or plain G-code once and serves both ``gcode summary`` and
``gcode compare``. The summary record keeps every field and value it had and gains ``estimated_time``: the time
the file states for itself, read, never computed. GOLDEN holds what the unchanged summary printed for the
fixtures (tests/gcode_fixtures.py): its JSON record and its text.
"""
import json
from pathlib import Path

import pytest

from agentcad.gcode import check, sliced
from tests import gcode_fixtures as fx

GOLDEN = json.loads((Path(__file__).resolve().parent / "data" / "gcode_summary_golden.json").read_text())
run_cli = fx.run_cli


@pytest.fixture
def files(tmp_path):
    return fx.write_files(tmp_path)


# --- the summary keeps its record and gains the time ------------------------------------------------------------

# A plain file also gains the filament total it states: the summary reads it from the statistics either format
# carries, so one slice summarizes the same as .gcode and as .bgcode (tests/test_gcode_golden_pair.py).
@pytest.mark.parametrize("key,name,time,gained,states", [
    ("plain_a", "a", {"seconds": 3723, "text": "1h 2m 3s"}, {"filament_used_stated_mm": 30.0}, "30.00"),
    ("plain_b", "b", {"seconds": 3382, "text": "56m 22s"}, {"filament_used_stated_mm": 20.0}, "20.00"),
    ("bgcode_b", "b_bgcode", {"seconds": 3382, "text": "56m 22s"}, {}, None)])
def test_the_summary_keeps_every_old_field_and_value_and_gains_the_time(files, capsys, key, name, time, gained,
                                                                         states):
    rc, out, _ = run_cli(capsys, "gcode", "summary", files[name], "--json")
    assert rc == 0
    new = json.loads(out)
    added = {"estimated_time"} | set(gained)
    assert {k: v for k, v in new.items() if k not in added} == GOLDEN["json"][key]
    assert set(new) - set(GOLDEN["json"][key]) == added
    assert {k: new[k] for k in gained} == gained
    assert new["estimated_time"] == time
    rc, text, _ = run_cli(capsys, "gcode", "summary", files[name])
    first, rest = GOLDEN["text"][key].split("\n", 1)
    expected = first + (f"; the file states {states} mm" if states else "") + "\n" + rest
    assert text == expected       # unchanged, but for the stated total a plain file now shows beside its own


# --- time: read, never computed ---------------------------------------------------------------------------------

@pytest.mark.parametrize("text,seconds", [
    ("1h 2m 3s", 3723), ("56m 22s", 3382), ("4s", 4), ("1d 2h 3m 4s", 93784), ("2h 59m 35s", 10775),
    ("", None), ("soon", None), ("3m 1h", None), ("1 hour", None)])
def test_durations_are_read_the_way_a_slicer_writes_them(text, seconds):
    assert sliced.parse_duration(text) == seconds


@pytest.mark.parametrize("seconds,signed,text", [
    (3723, False, "1h 2m 3s"), (56, False, "56s"), (0, True, "0s"), (93784, False, "1d 2h 3m 4s"),
    (-341, True, "-5m 41s"), (341, True, "+5m 41s"), (341, False, "5m 41s"), (3600, False, "1h 0m 0s")])
def test_durations_are_written_in_the_same_form(seconds, signed, text):
    assert sliced.format_duration(seconds, signed) == text


def test_the_time_is_read_from_whichever_block_states_it(tmp_path):
    for name, kw in (("printer_only", {"print_block": False}), ("print_only", {"printer_block": False})):
        p = tmp_path / f"{name}.bgcode"
        p.write_bytes(fx.bgcode_bytes(fx.BODY_B, fx.CONFIG_B, fx.TIME_B, fx.FILAMENT_B, **kw))
        s = sliced.load(p)
        assert sliced.summary_record(s)["estimated_time"] == {"seconds": 3382, "text": "56m 22s"}, name
        assert sliced.stated_total(s.stated, sliced.FILAMENT_KEY) == 20.0, name


@pytest.mark.parametrize("stated,expected", [
    (None, None),                                            # nothing stated: null, not a number worked out from the paths
    ("soon", {"seconds": None, "text": "soon"})])            # a form this reader does not know is kept as the file wrote it
def test_a_time_the_file_does_not_state_is_null_and_one_it_cannot_read_is_kept(tmp_path, stated, expected):
    f = tmp_path / "t.gcode"
    f.write_text(fx.BODY_B + fx.trailer(stated, fx.FILAMENT_B, fx.CONFIG_B, fx.GRAMS_B))
    assert sliced.summary_record(sliced.load(f))["estimated_time"] == expected


def test_a_per_extruder_nil_or_a_two_extruder_total_does_not_stop_the_summary(tmp_path):
    f = tmp_path / "odd.bgcode"
    f.write_bytes(fx.bgcode_bytes(fx.BODY_B, fx.CONFIG_B, fx.TIME_B, fx.FILAMENT_B, fx.GRAMS_B,
                                  extra_config={"filament_density": "nil", "filament_diameter": "1.75,nil"}))
    rec = sliced.summary_record(sliced.load(f))
    assert "mass_g" not in rec["filament_used"] and rec["filament_used"]["volume_cm3"] == 0.048     # density unknown, 1.75 mm
    f.write_bytes(fx.bgcode_bytes(fx.BODY_B, fx.CONFIG_B, fx.TIME_B, "12.5,7.5"))
    assert sliced.summary_record(sliced.load(f))["filament_used_stated_mm"] == 20.0                 # extruders are added up


@pytest.mark.parametrize("raw,total", [("100.5", 100.5), ("100.0, 50.5", 150.5), ("x", None), (None, None), ("", None)])
def test_a_stated_total_adds_up_extruders(raw, total):
    stated = {} if raw is None else {sliced.FILAMENT_KEY: raw}
    assert sliced.stated_total(stated, sliced.FILAMENT_KEY) == total


# --- settings, and what only looks like one ---------------------------------------------------------------------

@pytest.mark.parametrize("key,setting", [
    ("layer_height", True), ("first_layer_temperature", True), ("filament used [mm]", False),
    ("estimated printing time (normal mode)", False), ("total layers count", False),
    ("external perimeters extrusion width", False), ("objects_info", False), ("max_layer_z", False)])
def test_a_setting_is_told_from_a_statistic_by_its_name(key, setting):
    assert sliced.is_setting_key(key) is setting


def test_with_a_configuration_block_the_settings_are_the_blocks_alone(tmp_path):
    f = tmp_path / "block.gcode"
    f.write_text(fx.BODY_B + "; stray_result = 1\n; prusaslicer_config = begin\n; layer_height = 0.3\n"
                 "; prusaslicer_config = end\n; late_result = 2\n")
    assert sliced.load(f).config == {"layer_height": "0.3"}
    assert check.config_block(fx.plain_a())["layer_height"] == "0.2" and "max_layer_z" not in check.config_block(fx.plain_a())
    assert check.config_block(fx.BODY_A) is None                                      # no block in the text


def test_without_a_block_results_written_like_settings_are_still_not_settings(tmp_path):
    """A real body ends with '; max_layer_z = 14.45' and a metadata block holds '; objects_info = {...}': results
    named like settings. Between two slices of different heights they would read as a setting that differs."""
    f = tmp_path / "noblock.gcode"
    f.write_text(fx.BODY_B + "; max_layer_z = 0.9\n; objects_info = {}\n; layer_height = 0.3\n; filament used [mm] = 20.00\n")
    config = sliced.load(f).config
    assert {k for k in config if sliced.is_setting_key(k)} == {"layer_height"}


def test_statistics_written_after_the_configuration_block_are_still_read(tmp_path):
    late = tmp_path / "late.gcode"
    late.write_text(fx.BODY_B + "; prusaslicer_config = begin\n; layer_height = 0.3\n; prusaslicer_config = end\n"
                    "; filament used [mm] = 20.00\n; estimated printing time (normal mode) = 56m 22s\n; late_setting = 1\n")
    s = sliced.load(late)
    assert sliced.stated_time(s.stated) == {"seconds": 3382, "text": "56m 22s"}
    assert sliced.stated_total(s.stated, sliced.FILAMENT_KEY) == 20.0
    assert s.config == {"layer_height": "0.3"}                # settings are the block's, not what follows it


def test_config_from_text_is_what_embedded_config_reads_and_stops_at_the_blocks_end(files):
    text = fx.plain_a()
    assert check.config_from_text(text) == check.embedded_config(files["a"])
    assert "late_key" not in check.config_from_text(text + "; late_key = 1\n")       # nothing after the block counts
    assert check.config_from_text(text + "; late_key = 1\n", whole=True)["late_key"] == "1"   # unless asked for
