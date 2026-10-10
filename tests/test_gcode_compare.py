"""gcode compare: two sliced files side by side.

The fixtures (tests/gcode_fixtures.py) are two imaginary slices of one plate, small enough that every number
below was totalled by hand from the G-code, not read back from the code under test:

    A  5 layers of 0.2 mm, top z 1.0, filament 30 mm = 0.09 g, states 1h 2m 3s (3723 s); peg 21 mm with
       4 mm of support held up under its ledge, plug 3 mm, skirt and priming 6 mm; one contact band of 9.1 mm2
    B  3 layers of 0.3 mm, top z 0.9, filament 20 mm = 0.06 g, states 56m 22s (3382 s); no support; peg 11 mm,
       cap 3 mm, skirt and priming 6 mm
"""
import json
import subprocess
import sys

import pytest

from agentcad import cli
from agentcad import policy as pol
from agentcad.gcode import check, compare, sliced, supports
from tests import gcode_fixtures as fx

RUN = [sys.executable, "-c", "import sys; from agentcad.cli import main; sys.exit(main())"]
run_cli = fx.run_cli


@pytest.fixture
def files(tmp_path):
    return fx.write_files(tmp_path)


def record(a, b, **kw):
    return compare.compare(sliced.load(a), sliced.load(b), **kw)


# --- the numbers, by hand -----------------------------------------------------------------------------------

def test_a_fixture_pair_matches_the_hand_computed_deltas(files):
    r = record(files["a"], files["b"])
    a, b, d = r["a"], r["b"], r["delta"]
    assert r["schema"] == "agentcad.gcode.compare/1" and list(r) == ["schema", "a", "b", "delta", "settings"]
    # the printing time each file states: 1h 2m 3s = 3723 s, 56m 22s = 3382 s; B minus A = -341 s
    assert a["estimated_time"] == {"seconds": 3723, "text": "1h 2m 3s"}
    assert b["estimated_time"] == {"seconds": 3382, "text": "56m 22s"}
    assert d["estimated_time"] == {"seconds": -341, "text": "-5m 41s"}
    # layers and height
    assert (a["layers"], b["layers"], d["layers"]) == (5, 3, -2)
    assert (a["top_z"], b["top_z"], d["top_z"]) == (1.0, 0.9, -0.1)
    # filament: the paths add up to what each file states (30 and 20 mm, 0.09 and 0.06 g)
    assert (a["filament"]["used_mm"], b["filament"]["used_mm"], d["filament"]["used_mm"]) == (30.0, 20.0, -10.0)
    assert (a["filament"]["stated_mm"], b["filament"]["stated_mm"], d["filament"]["stated_mm"]) == (30.0, 20.0, -10.0)
    assert (a["filament"]["stated_g"], b["filament"]["stated_g"], d["filament"]["stated_g"]) == (0.09, 0.06, -0.03)
    assert a["filament"]["agrees"] is True and b["filament"]["agrees"] is True
    # support: 2 + 2 mm of 30 mm is 4/30 = 0.1333; none in B
    assert (a["support"]["share"], b["support"]["share"], d["support"]["share"]) == (0.1333, 0.0, -0.1333)
    assert (a["support"]["filament_mm"], b["support"]["filament_mm"], d["support"]["filament_mm"]) == (4.0, 0.0, -4.0)
    # contact: one 20 mm support line under the ledge, 81 cells of 0.45 x 0.25 mm = 9.1 mm2
    assert (a["contacts"]["count"], b["contacts"]["count"], d["contacts"]["count"]) == (1, 0, -1)
    assert (a["contacts"]["area_mm2"], b["contacts"]["area_mm2"], d["contacts"]["area_mm2"]) == (9.1, 0.0, -9.1)
    assert a["contacts"]["smaller"] == {"count": 0, "area_mm2": 0.0} and a["contacts"]["min_area_mm2"] == 1.0
    assert a["contacts"]["contact_distance_mm"] == 0.25
    assert (a["format"], b["format"]) == ("gcode", "gcode") and a["file"].endswith("a.gcode")


def test_objects_in_one_file_only_are_named_with_their_extrusion(files):
    r = record(files["a"], files["b"])
    assert r["a"]["objects"] == {"(no object)": {"filament_mm": 6.0, "support_share": 0.0},
                                 "peg.stl": {"filament_mm": 21.0, "support_share": 0.1905},
                                 "plug.stl": {"filament_mm": 3.0, "support_share": 0.0}}
    assert r["b"]["objects"] == {"(no object)": {"filament_mm": 6.0, "support_share": 0.0},
                                 "peg.stl": {"filament_mm": 11.0, "support_share": 0.0},
                                 "cap.stl": {"filament_mm": 3.0, "support_share": 0.0}}
    assert r["delta"]["objects"] == [
        {"name": "cap.stl", "present": "b_only", "filament_mm": 3.0},
        {"name": "peg.stl", "present": "both", "filament_mm": -10.0},
        {"name": "plug.stl", "present": "a_only", "filament_mm": -3.0},
        {"name": "(no object)", "present": "both", "filament_mm": 0.0},      # extrusion of no object comes last
    ]
    # nothing is dropped: the rows add up to the difference in total filament
    assert sum(row["filament_mm"] for row in r["delta"]["objects"]) == pytest.approx(r["delta"]["filament"]["used_mm"])


def test_settings_that_differ_leave_out_statistics_and_name_one_sided_keys(files):
    st = record(files["a"], files["b"])["settings"]
    assert st["differ"] == [{"key": "fill_density", "a": "15%", "b": "20%"},
                            {"key": "layer_height", "a": "0.2", "b": "0.3"},
                            {"key": "support_material", "a": "1", "b": "0"}]
    assert st["only_in_a"] == [{"key": "brim_width", "a": "0", "b": None}]
    assert st["only_in_b"] == [{"key": "infill_anchor", "a": None, "b": "2.5"}]
    # 7 settings between them: 2 alike (temperature, contact distance), 3 that differ, 1 in A only, 1 in B only
    assert (st["compared"], st["same"], st["in_a"], st["in_b"]) == (7, 2, 6, 6)
    # a plain file writes statistics beside its configuration; they are not settings
    listed = {r["key"] for rows in (st["differ"], st["only_in_a"], st["only_in_b"]) for r in rows}
    assert not listed & {"filament used [mm]", "estimated printing time (normal mode)", "objects_info",
                         "external perimeters extrusion width"}


def test_the_text_is_a_table_with_the_settings_beneath(files, capsys):
    rc, out, err = run_cli(capsys, "gcode", "compare", files["a"], files["b"])
    assert rc == 0 and err == ""
    rows = {line.strip().split("  ")[0]: line for line in out.splitlines() if "  " in line}
    assert "1h 2m 3s" in rows["estimated time"] and "56m 22s" in rows["estimated time"] and "-5m 41s" in rows["estimated time"]
    assert rows["layers"].split() == ["layers", "5", "3", "-2"]
    assert rows["filament used (mm)"].split() == ["filament", "used", "(mm)", "30.00", "20.00", "-10.00"]
    assert rows["support share"].split()[2:] == ["13.33%", "0.00%", "-13.33", "pp"]
    assert "only in A" in rows["plug.stl"] and "only in B" in rows["cap.stl"]
    assert "settings that differ: 5 of 7 compared" in out
    assert "layer_height" in out and "0.2 -> 0.3" in out and "only in A:" in out and "brim_width" in out
    assert "estimated printing time" not in out and "objects_info" not in out


# --- mixed inputs ---------------------------------------------------------------------------------------------

def test_a_bgcode_against_a_plain_file_gives_the_deltas_of_two_plain_files(files):
    mixed, plain = record(files["a"], files["b_bgcode"]), record(files["a"], files["b"])
    assert (mixed["a"]["format"], mixed["b"]["format"]) == ("gcode", "bgcode")
    assert mixed["delta"] == plain["delta"]
    assert {k: v for k, v in mixed["b"].items() if k not in ("file", "format")} == \
        {k: v for k, v in plain["b"].items() if k not in ("file", "format")}
    assert mixed["b"]["estimated_time"] == {"seconds": 3382, "text": "56m 22s"}      # from the print metadata block


def test_one_slice_in_two_containers_compares_to_nothing(files, capsys):
    r = record(files["b_dense"], files["b_bgcode"])
    assert (r["a"]["format"], r["b"]["format"]) == ("gcode", "bgcode")
    d = r["delta"]
    assert d["estimated_time"] == {"seconds": 0, "text": "0s"}
    assert (d["layers"], d["top_z"]) == (0, 0.0)
    assert set(d["filament"].values()) == {0.0}
    assert d["support"] == {"share": 0.0, "filament_mm": 0.0} and d["contacts"] == {"count": 0, "area_mm2": 0.0}
    assert all(row["present"] == "both" and row["filament_mm"] == 0.0 for row in d["objects"])
    st = r["settings"]
    assert st["differ"] == st["only_in_a"] == st["only_in_b"] == [] and st["same"] == st["compared"] == 8
    rc, out, _ = run_cli(capsys, "gcode", "compare", files["b_dense"], files["b_bgcode"])
    assert "settings: none differ (8 compared; credentials and local paths are never compared or shown)" in out
    assert [line.split()[-3:] for line in out.splitlines() if line.startswith("layers")] == [["3", "3", "0"]]


# --- credentials never leave ----------------------------------------------------------------------------------

PRIVATE_NAMES = ("printhost_apikey", "printhost_user", "printhost_password", "post_process", "print_host")


@pytest.mark.parametrize("flags", [[], ["--all-settings"], ["--json"]])
@pytest.mark.parametrize("b", ["b", "b_bgcode"])
def test_private_keys_never_reach_the_output(files, capsys, flags, b):
    # the control: these files do carry the secrets, and the plain reader hands them over
    raw = check.embedded_config(files["a"])
    assert raw["printhost_apikey"] == "SECRET_KEY_A" and raw["post_process"] == "secret_post_a.sh"
    assert check.embedded_config(files["b_bgcode"])["printhost_apikey"] == "SECRET_KEY_B"
    rc, out, err = run_cli(capsys, "gcode", "compare", files["a"], files[b], *flags)
    assert rc == 0
    for text in (out, err):
        for secret in fx.SECRET_VALUES:
            assert secret not in text, f"{secret} leaked"
        for name in PRIVATE_NAMES:
            assert name not in text, f"{name} named in the output"


@pytest.mark.parametrize("key,private", [
    ("printhost_apikey", True), ("printhost_password", True), ("printhost_user", True), ("printhost_cafile", True),
    ("post_process", True), ("printhost_port", True), ("print_host", True),
    ("layer_height", False), ("support_material", False), ("binary_gcode", False)])
def test_what_counts_as_private(key, private):
    assert compare.is_private(key) is private
    assert set(check.PRIVATE_KEYS) <= {k for k in check.PRIVATE_KEYS if compare.is_private(k)}   # the base list is covered


# --- time and totals, as the comparison shows them ---------------------------------------------------------

def test_a_file_that_states_no_time_shows_none_and_no_difference(files, tmp_path, capsys):
    silent = tmp_path / "silent.gcode"
    silent.write_text(fx.BODY_B + fx.trailer(None, None, fx.CONFIG_B))
    assert sliced.summary_record(sliced.load(silent))["estimated_time"] is None
    r = record(files["a"], silent)
    assert r["b"]["estimated_time"] is None and r["delta"]["estimated_time"] is None
    assert r["b"]["filament"]["stated_mm"] is None and r["b"]["filament"]["agrees"] is None
    assert r["delta"]["filament"]["stated_mm"] is None and r["delta"]["filament"]["used_mm"] == -10.0
    rc, out, _ = run_cli(capsys, "gcode", "compare", files["a"], silent)
    assert "note: B states no estimated printing time" in out


def test_a_time_in_a_form_this_reader_does_not_know_is_kept_verbatim(files, tmp_path, capsys):
    odd = tmp_path / "odd.gcode"
    odd.write_text(fx.BODY_B + fx.trailer("soon", fx.FILAMENT_B, fx.CONFIG_B, fx.GRAMS_B))
    r = record(files["a"], odd)
    assert r["b"]["estimated_time"] == {"seconds": None, "text": "soon"} and r["delta"]["estimated_time"] is None
    rc, out, _ = run_cli(capsys, "gcode", "compare", files["a"], odd)
    assert "does not know ('soon')" in out


# --- what a file cannot say ---------------------------------------------------------------------------------------

def test_a_file_without_feature_comments_has_unknown_support_not_zero(files, tmp_path, capsys):
    bare = tmp_path / "bare.gcode"
    bare.write_text("M83\nG1 Z.3\nG1 X5 E1\nG1 Z.6\nG1 X0 E1\n" + fx.trailer(None, None, fx.CONFIG_B))
    r = record(files["a"], bare)
    assert r["b"]["features_known"] is False and r["a"]["features_known"] is True
    assert r["b"]["support"] == {"share": None, "filament_mm": None}
    assert r["b"]["contacts"]["count"] is None and r["b"]["contacts"]["smaller"] is None
    assert r["b"]["objects"]["(no object)"]["support_share"] is None
    assert r["delta"]["support"] == {"share": None, "filament_mm": None}
    assert r["delta"]["contacts"] == {"count": None, "area_mm2": None}
    assert (r["b"]["layers"], r["b"]["filament"]["used_mm"]) == (2, 2.0)           # layers and totals still come
    rc, out, _ = run_cli(capsys, "gcode", "compare", files["a"], bare)
    assert "note: B carries no feature comments, so its support figures are unknown" in out


def test_a_filament_total_that_contradicts_the_files_own_is_flagged(files, tmp_path, capsys):
    liar = tmp_path / "liar.gcode"
    liar.write_text(fx.BODY_B + fx.trailer(fx.TIME_B, 25.0, fx.CONFIG_B, fx.GRAMS_B))   # says 25 mm, the paths add to 20
    r = record(files["a"], liar)
    assert r["b"]["filament"]["agrees"] is False and r["a"]["filament"]["agrees"] is True
    rc, out, _ = run_cli(capsys, "gcode", "compare", files["a"], liar)
    assert "note: B's own filament total (20.00 mm) and the total the file states (25.00 mm) disagree" in out


@pytest.mark.parametrize("stated,agrees", [(20.4, True), (20.5, True), (20.6, False), (19.4, False)])
def test_the_tolerance_on_the_files_own_total_is_half_a_millimetre(tmp_path, stated, agrees):
    f = tmp_path / "t.gcode"
    f.write_text(fx.BODY_B + fx.trailer(fx.TIME_B, stated, fx.CONFIG_B))
    assert compare.describe(sliced.load(f))["filament"]["agrees"] is agrees


def test_small_contact_bands_are_counted_apart_not_dropped(files, capsys):
    r = record(files["a"], files["b"], min_area=10.0)                  # A's one band is 9.1 mm2
    assert r["a"]["contacts"]["count"] == 0 and r["a"]["contacts"]["area_mm2"] == 0.0
    assert r["a"]["contacts"]["smaller"] == {"count": 1, "area_mm2": 9.1}
    assert r["delta"]["contacts"] == {"count": 0, "area_mm2": 0.0}
    rc, out, _ = run_cli(capsys, "gcode", "compare", files["a"], files["b"], "--min-area", 10)
    assert "note: contact bands under 10 mm2 are not counted above: 1 in A (9.1 mm2)" in out
    assert "(--min-area 0 counts them)" in out
    assert record(files["a"], files["b"], min_area=0.0)["a"]["contacts"]["count"] == 1


def test_a_file_with_no_configuration_says_there_is_nothing_to_compare(files, tmp_path, capsys):
    bare = tmp_path / "noconfig.gcode"
    bare.write_text(fx.BODY_B)
    st = record(files["a"], bare)["settings"]
    assert (st["in_a"], st["in_b"]) == (6, 0) and len(st["only_in_a"]) == 6
    rc, out, _ = run_cli(capsys, "gcode", "compare", files["a"], bare)
    assert "settings: B carries no slicer configuration, so there is nothing to compare (6 settings in A, 0 in B)" in out
    assert "none differ" not in out
    rc, out, _ = run_cli(capsys, "gcode", "compare", bare, bare)
    assert "settings: A and B carry no slicer configuration, so there is nothing to compare (0 settings in A, 0 in B)" in out


def test_the_default_band_size_is_the_one_gcode_supports_uses():
    parser = cli.build_parser()
    both = (parser.parse_args(["gcode", "compare", "a", "b"]).min_area, parser.parse_args(["gcode", "supports", "a"]).min_area)
    assert both == (compare.DEFAULT_MIN_AREA, compare.DEFAULT_MIN_AREA) == (1.0, 1.0)


# --- the settings list ----------------------------------------------------------------------------------------

def test_the_text_lists_twenty_settings_and_counts_the_rest_while_json_carries_all(tmp_path, capsys):
    many_a, many_b = {f"setting_{i:02d}": "1" for i in range(30)}, {f"setting_{i:02d}": "2" for i in range(30)}
    a, b = tmp_path / "many_a.gcode", tmp_path / "many_b.gcode"
    a.write_text(fx.BODY_A + fx.trailer(None, None, many_a))
    b.write_text(fx.BODY_B + fx.trailer(None, None, many_b))
    rc, out, _ = run_cli(capsys, "gcode", "compare", a, b)
    assert "settings that differ: 30 of 30 compared" in out
    assert out.count("1 -> 2") == 20 and "setting_19" in out and "setting_20" not in out
    assert "... and 10 more (--all-settings lists every one; --json carries them all)" in out
    rc, out, _ = run_cli(capsys, "gcode", "compare", a, b, "--all-settings")
    assert out.count("1 -> 2") == 30 and "more" not in out
    rc, out, _ = run_cli(capsys, "gcode", "compare", a, b, "--json")
    assert len(json.loads(out)["settings"]["differ"]) == 30


def test_a_long_value_is_clipped_in_the_text_and_whole_in_the_record(tmp_path, capsys):
    long_value = "x" * 100
    a, b = tmp_path / "long_a.gcode", tmp_path / "long_b.gcode"
    a.write_text(fx.BODY_A + fx.trailer(None, None, {"start_gcode": long_value}))
    b.write_text(fx.BODY_B + fx.trailer(None, None, {"start_gcode": "short"}))
    rc, out, _ = run_cli(capsys, "gcode", "compare", a, b)
    assert "x" * 33 + "... -> short" in out and long_value not in out
    rc, out, _ = run_cli(capsys, "gcode", "compare", a, b, "--json")
    assert json.loads(out)["settings"]["differ"] == [{"key": "start_gcode", "a": long_value, "b": "short"}]


def test_the_contact_distance_comes_from_the_files_own_configuration():
    f = supports.contact_distance_from
    assert f({"support_material_contact_distance": "0.2"}) == 0.2
    assert f({"support_material_contact_distance": "0.2,0.3"}) == 0.2                # the first extruder's
    assert f({"support_material_contact_distance": "0"}) == 0.0                      # "none" is a value, not a gap
    assert f({}) == 0.25 and f({"support_material_contact_distance": ""}) == 0.25
    assert f({"support_material_contact_distance": "soluble"}) == 0.25               # unreadable: the default


# --- the command ------------------------------------------------------------------------------------------------

def test_exit_codes_and_messages(files, tmp_path):
    def run(*argv):
        return subprocess.run(RUN + ["gcode", "compare", *[str(a) for a in argv]], capture_output=True, text=True)

    ok = run(files["a"], files["b"])
    assert ok.returncode == 0 and "estimated time" in ok.stdout and ok.stderr == ""
    assert run(files["a"]).returncode == 2                                           # a usage error
    assert run(files["a"], files["b"], "--no-such-flag").returncode == 2
    assert run(files["a"], files["b"], "--min-area", "wide").returncode == 2
    missing = run(files["a"], tmp_path / "nope.gcode")                               # a file that is not there
    assert missing.returncode == 1 and missing.stdout == ""
    assert "Error: cannot read B (" in missing.stderr and "nope.gcode" in missing.stderr
    both = run(tmp_path / "x.gcode", tmp_path / "y.gcode")
    assert both.returncode == 1 and "cannot read A" in both.stderr and "cannot read B" in both.stderr
    assert run(files["a"], tmp_path).returncode == 1                                 # a directory
    damaged = bytearray(fx.bgcode_b())
    damaged[-6] ^= 0x01                                                              # one bit in the G-code block
    (tmp_path / "damaged.bgcode").write_bytes(bytes(damaged))
    bad = run(files["a"], tmp_path / "damaged.bgcode")
    assert bad.returncode == 1 and bad.stdout == "" and "cannot read B" in bad.stderr and "CRC32" in bad.stderr


def test_a_file_with_nothing_to_print_is_warned_about_not_refused(files, tmp_path, capsys):
    empty = tmp_path / "empty.gcode"
    empty.write_text("; nothing sliced here\n")
    rc, out, err = run_cli(capsys, "gcode", "compare", files["a"], empty)
    assert rc == 0 and "Warning: B (" in err and "has no extrusion in it; is it a sliced file?" in err
    r = json.loads(run_cli(capsys, "gcode", "compare", files["a"], empty, "--json")[1])
    assert r["b"]["layers"] == 0 and r["b"]["top_z"] is None and r["delta"]["top_z"] is None
    assert r["delta"]["layers"] == -5


def test_the_json_option_prints_only_the_record(files, capsys):
    rc, out, err = run_cli(capsys, "gcode", "compare", files["a"], files["b"], "--json")
    assert rc == 0 and err == ""
    assert json.loads(out) == record(files["a"], files["b"])


def test_the_policy_governs_the_command_and_explains_what_it_reports():
    p = pol.get_policy("gcode")
    assert ("gcode", "compare") in p.commands
    _, lines = pol.section(p.text, "7")
    body = "\n".join(lines)
    for phrase in ("agentcad gcode compare", "agentcad.gcode.compare/1", "--all-settings", "--min-area", "exits 0"):
        assert phrase in body, phrase
