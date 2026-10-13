"""The prusaslicer target: a project 3MF from a job over a base configuration the user supplies.

The configuration, the sliced files and the printer here are invented (tests/targetfixtures.py); the
credentials in them are placeholders that must never reach a project. The tests state the properties the
target promises: the settings read back from a written project equal what was intended, nothing private is
written, a placement keeps its turn, an off-bed placement is refused before a file exists, and the same job
writes the same bytes. Each refusal is shown beside the case it lets through.
"""

import json
import zipfile
from pathlib import Path

import pytest

from agentcad import cli, printers, targets
from agentcad.gcode import check
from agentcad.gcode.bgcode import BGCodeError
from agentcad.targets import Job, JobPart, TargetError
from agentcad.targets import prusaslicer as ps
from agentcad.targets import prusaslicer_3mf as p3mf
from agentcad.targets import prusaslicer_config as pconfig
from agentcad.targets.generic import from_3mf, instances, read_plate, to_3mf
from tests import targetfixtures as tf
from tests.gcode_fixtures import run_cli
from tests.test_qc import FakeBoxEngine
from tests.test_target_contract import _box_stl, _turn_z

PRUSA = "prusaslicer"


@pytest.fixture(autouse=True)
def private_config_folder(tmp_path, monkeypatch):
    """The user config folder is the test's own: a developer's real targets.toml never reaches a test."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    return tmp_path / "xdg" / "agentcad"


@pytest.fixture
def stl(tmp_path):
    return _box_stl(tmp_path / "bar.stl")                    # 10 x 4 x 2


@pytest.fixture
def base(tmp_path):
    """A base configuration that also carries every credential and the post-processing script."""
    return tf.write_ini(tmp_path / "base.ini", tf.synthetic_config(**tf.PRIVATE))


def job_for(stl, base, offset=(100.0, 60.0, 0.0), deg=30.0, **fields):
    job = Job("plate", [JobPart("bar", stl, copies=1, transform=_turn_z(deg, offset))], options={"base_config": base})
    for name, value in fields.items():
        setattr(job, name, value)
    return job


def write(job, folder):
    """(the project 3MF, the sidecar) a job writes, through the registry."""
    written = targets.get_target(PRUSA).write_job(job, folder)
    return next(p for p in written if str(p).endswith(".3mf")), next(p for p in written if str(p).endswith(".json"))


# --- the base configuration -----------------------------------------------------------------------------

def test_one_configuration_reads_the_same_from_an_ini_a_sliced_file_and_a_project(tmp_path, stl):
    config = tf.synthetic_config()
    ini, gcode = tf.write_ini(tmp_path / "a.ini", config), tf.write_gcode(tmp_path / "a.gcode", config)
    bgcode = tf.write_bgcode(tmp_path / "a.bgcode", config)
    project, _ = write(job_for(stl, ini), tmp_path / "out")
    unzipped = tmp_path / "Slic3r_PE.config"                  # the member of a project, taken out as a file
    unzipped.write_bytes(zipfile.ZipFile(project).read(check.THREEMF_CONFIG))
    for source in (ini, gcode, bgcode, project, unzipped):
        assert pconfig.load(source) == config, source.name
    assert "filament used [mm]" not in pconfig.load(gcode), "a statistic beside the block is not a setting"
    assert pconfig.parse_ini("# header\n\nlayer_height = 0.2\nstart_gcode = M1 ; a = b\nnotes =\n") == {
        "layer_height": "0.2", "start_gcode": "M1 ; a = b", "notes": ""}


@pytest.mark.parametrize("make, said", [
    (lambda d: _write(d / "bundle.ini", "[print:Mine]\nlayer_height = 0.2\n"), "config bundle"),
    (lambda d: tf.write_ini(d / "fragment.ini", {"layer_height": "0.2", "perimeters": "2"}), "lacks printer_technology"),
    (lambda d: tf.write_ini(d / "resin.ini", tf.synthetic_config(printer_technology="SLA")), "SLA"),
    (lambda d: _write(d / "prose.txt", "nothing to see here\n"), "carries no PrusaSlicer settings"),
    (lambda d: _zip(d / "other.3mf", {"3D/3dmodel.model": "<model/>"}), "without Metadata/Slic3r_PE.config"),
    (lambda d: _bytes(d / "broken.bgcode", b"GCDE\x01\x00\x00\x00\x01\x00junk"), "broken.bgcode"),
    (lambda d: d / "missing.ini", "cannot read"),
])
def test_a_bundle_a_fragment_a_resin_or_missing_configuration_is_refused_in_a_sentence(tmp_path, stl, make, said):
    source = make(tmp_path)
    job = job_for(stl, source)
    with pytest.raises(TargetError, match=said) as e:
        targets.get_target(PRUSA).write_job(job, tmp_path / "out")
    assert "\n" not in str(e.value), "one line"
    assert not (tmp_path / "out").exists(), "a refused job leaves nothing behind"


def _write(path, text):
    path.write_text(text)
    return path


def _bytes(path, data):
    path.write_bytes(data)
    return path


def _zip(path, members):
    with zipfile.ZipFile(path, "w") as z:
        for name, text in members.items():
            z.writestr(name, text)
    return path


def test_a_job_with_no_base_configuration_says_how_to_supply_one(tmp_path, stl, private_config_folder):
    job = job_for(stl, None)
    job.options = {}
    with pytest.raises(TargetError, match=r"--base-config PATH.*targets\.toml") as e:
        targets.get_target(PRUSA).write_job(job, tmp_path / "out")
    assert str(private_config_folder) in str(e.value), "it names the folder the default is looked for in"


def test_the_users_default_base_configuration_comes_from_targets_toml(tmp_path, stl, base, private_config_folder):
    folder = private_config_folder
    folder.mkdir(parents=True)
    (folder / "targets.toml").write_text('[prusaslicer]\nbase_config = "mine/base.ini"\n')
    (folder / "mine").mkdir()
    (folder / "mine" / "base.ini").write_bytes(base.read_bytes())
    assert ps.user_base_config() == folder / "mine" / "base.ini", "a relative path is relative to the folder"
    job = job_for(stl, None)
    job.options = {}
    project, _ = write(job, tmp_path / "out")                  # no option given: the default is used
    assert targets.get_target(PRUSA).read_settings(project)["layer_height"] == "0.25"
    other = tf.write_ini(tmp_path / "other.ini", tf.synthetic_config(layer_height="0.3"))
    job.options = {"base_config": other}
    project, _ = write(job, tmp_path / "out2")                 # the option wins over the default
    assert targets.get_target(PRUSA).read_settings(project)["layer_height"] == "0.3"
    for text, said in [('[prusaslicer]\nbase = "x"\n', "unknown setting"), ('prusaslicer = 3\n', "must be a table"),
                       ('[prusaslicer]\nbase_config = 4\n', "must be a path"), ('[prusaslicer\n', "cannot parse")]:
        (folder / "targets.toml").write_text(text)
        with pytest.raises(TargetError, match=said):
            ps.user_base_config()
    (folder / "targets.toml").write_text('[prusaslicer]\n')
    assert ps.user_base_config() is None, "a table without the key names no default"
    (folder / "targets.toml").unlink()
    assert ps.user_base_config() is None, "no file, no default"


# --- the neutral intent, mapped ---------------------------------------------------------------------------

def test_the_intent_maps_to_prusaslicer_settings_and_the_rest_says_why():
    mapped, notes = ps.map_intent({"layer_height": 0.15, "walls": 3, "infill_percent": 25, "supports": True,
                                   "material": "PETG", "print_orientation": "flat", "printer_profile": "p",
                                   "filament_profile": "f", "target": PRUSA, "notes": "n", "wibble": 1})
    assert mapped == {"layer_height": "0.15", "perimeters": "3", "fill_density": "25%",
                      "support_material": "1", "support_material_auto": "1"}
    assert set(mapped) <= set(tf.SYNTHETIC), "every mapped setting is one a configuration carries"
    assert [n.split(":")[0] for n in notes] == sorted(["material", "print_orientation", "printer_profile",
                                                       "filament_profile", "target", "notes", "wibble"])
    assert all(n.split(": ", 1)[1] for n in notes), "each unmapped key says why"
    assert "placement" in dict(n.split(": ", 1) for n in notes)["print_orientation"]
    assert ps.map_intent({"supports": False, "infill_percent": 12.5, "layer_height": 1})[0] == {
        "support_material": "0", "fill_density": "12.5%", "layer_height": "1"}
    assert ps.map_intent({}) == ({}, [])


@pytest.mark.parametrize("intent, key", [({"layer_height": 0}, "layer_height"), ({"layer_height": "thin"}, "layer_height"),
                                         ({"walls": 2.5}, "walls"), ({"walls": True}, "walls"),
                                         ({"infill_percent": 120}, "infill_percent"), ({"supports": "yes"}, "supports")])
def test_an_unusable_intent_value_is_refused_naming_its_key(intent, key):
    with pytest.raises(TargetError, match=f"\\[print\\] {key}"):
        ps.map_intent(intent)


# --- the settings a job writes ------------------------------------------------------------------------------

def test_settings_read_back_from_a_written_project_equal_the_intent(tmp_path, stl, base):
    """The round trip: a base configuration, the intent mapped, then native overrides, written and read back
    through the target. The expectation is built here from the pieces, not by the code under test."""
    job = job_for(stl, base,
                  intent={"layer_height": 0.15, "walls": 3, "infill_percent": 25, "supports": True,
                          "material": "PLA", "print_orientation": "flat", "target": PRUSA},
                  native={"fill_pattern": "honeycomb", "support_material_style": {"value": "snug", "why": "clean tips"},
                          "temperature": {"min": 195, "max": 210, "why": "layer bond"}, "brim_width": 4})
    project, _ = write(job, tmp_path / "out")
    got = targets.get_target(PRUSA).read_settings(project)
    want = {k: v for k, v in tf.synthetic_config(**tf.PRIVATE).items() if k not in tf.PRIVATE}
    want.update({"layer_height": "0.15", "perimeters": "3", "fill_density": "25%", "support_material": "1",
                 "support_material_auto": "1", "fill_pattern": "honeycomb", "support_material_style": "snug",
                 "brim_width": "4", "post_process": ""})
    assert got == want                                         # the range states a check, so temperature stays 200
    resolved = ps.resolve(job, pconfig.load(base))
    assert resolved.conflicts == [], "nothing was stated twice"
    assert any("temperature" in n and "not written" in n for n in resolved.notes)


def test_values_are_spelled_the_way_a_configuration_file_spells_them(tmp_path, stl, base):
    assert [targets.canonical(v) for v in (True, False, 0.2, 3.0, 12.5, 7, "25%", [200, 205.5], (1, True))] == [
        "1", "0", "0.2", "3", "12.5", "7", "25%", "200,205.5", "1,1"]
    job = job_for(stl, base, native={"temperature": [200, 205.5], "support_material_threshold": 40.0})
    project, _ = write(job, tmp_path / "out")
    written = targets.get_target(PRUSA).read_settings(project)
    assert (written["temperature"], written["support_material_threshold"]) == ("200,205.5", "40")


def test_a_native_value_over_the_intent_wins_and_is_reported_with_both_values(tmp_path, stl, base):
    intent = {"layer_height": 0.15, "supports": True, "walls": 3}
    native = {"layer_height": 0.2, "support_material": True, "perimeters": 3.0}
    job = job_for(stl, base, intent=intent, native=native)
    resolved = ps.resolve(job, pconfig.load(base))
    assert resolved.settings["layer_height"] == "0.2" and resolved.settings["perimeters"] == "3"
    assert len(resolved.conflicts) == 1, "true and 1, 3 and 3.0 are one statement each, not a conflict"
    assert "layer_height" in resolved.conflicts[0] and "'0.15'" in resolved.conflicts[0] and "0.2" in resolved.conflicts[0]
    project, _ = write(job, tmp_path / "out")
    assert targets.get_target(PRUSA).read_settings(project)["layer_height"] == "0.2"


def test_a_key_the_base_does_not_carry_is_refused_by_name_and_nothing_is_written(tmp_path, stl, base):
    cases = [
        ({"native": {"perimeterz": 3}}, r"perimeterz.*did you mean perimeters"),
        ({"intent": {"supports": True}, "base": tf.synthetic_config(support_material_auto=None)}, "support_material_auto"),
        ({"native": {"post_process": "x.sh"}}, "post_process is never written"),
        ({"native": {"printhost_apikey": "k"}}, "printhost_apikey is never written"),
        ({"native": {"start_gcode": "G28\nG29"}}, "start_gcode has a line break"),
    ]
    for fields, said in cases:
        source = tf.write_ini(tmp_path / "special.ini", fields.pop("base")) if "base" in fields else base
        job = job_for(stl, source, **fields)
        with pytest.raises(TargetError, match=said):
            targets.get_target(PRUSA).write_job(job, tmp_path / "out")
    assert not (tmp_path / "out").exists()
    job = job_for(stl, base)                                   # the same job without the fault is written
    job.native = {"perimeters": 3}
    assert write(job, tmp_path / "out")[0].is_file()


def test_post_process_is_empty_and_no_print_host_key_is_written(tmp_path, stl, base):
    assert pconfig.load(base)["post_process"] == tf.PRIVATE["post_process"], "the base configuration sets them all"
    assert all(k in pconfig.load(base) for k in tf.PRIVATE)
    project, sidecar = write(job_for(stl, base), tmp_path / "out")
    read = targets.get_target(PRUSA).read_settings(project)
    assert read["post_process"] == ""
    assert not [k for k in read if k.startswith("printhost_") or k == "print_host"]
    with zipfile.ZipFile(project) as z:
        everything = b"".join(z.read(n) for n in z.namelist()) + sidecar.read_bytes()
    for value in tf.PRIVATE.values():
        assert value.encode() not in everything, f"{value} reached the project"
    notes = targets.get_target(PRUSA).write_job(job_for(stl, base), tmp_path / "again").notes
    assert any("post_process" in n and "written empty" in n for n in notes)
    assert any("left out" in n and "printhost_apikey" in n and "synthetic-password" not in n for n in notes)


# --- the project file ------------------------------------------------------------------------------------

def test_the_project_keeps_every_placement_in_the_row_vector_convention(tmp_path, stl, base):
    other = _box_stl(tmp_path / "flat.stl", size=(7.0, 3.0, 1.0))
    job = Job("plate", [JobPart("bar", stl, copies=2, transform=_turn_z(30.0, (100.0, 60.0, 0.0))),
                        JobPart("flat", other, copies=1, transform=_turn_z(-110.0, (40.0, 120.0, 0.0)))],
              options={"base_config": base})
    project, sidecar = write(job, tmp_path / "out")
    items = read_plate(project)
    want = instances(job)
    assert [i["objectid"] for i in items] == ["1", "1", "2"] and len(want) == 3
    for item, inst in zip(items, want):
        for r in range(3):
            assert item["transform"][r] == pytest.approx(inst["transform"][r], abs=1e-6)
    # the corner (10, 0, 0) of the bar lands where a turn of 30 degrees about z puts it, not where the transpose does
    got = items[0]["transform"]
    corner = [sum(got[i][j] * v for j, v in enumerate((10.0, 0.0, 0.0, 1.0))) for i in range(3)]
    assert corner[:2] == pytest.approx([100 + 10 * 0.8660254, 60 + 10 * 0.5], abs=1e-6)
    T = want[0]["transform"]
    turned_the_other_way = [[T[0][0], T[1][0], T[2][0], T[0][3]], [T[0][1], T[1][1], T[2][1], T[1][3]],
                            [T[0][2], T[1][2], T[2][2], T[2][3]], [0.0, 0.0, 0.0, 1.0]]
    assert from_3mf(to_3mf(turned_the_other_way))[0][1] != pytest.approx(got[0][1]), "the transpose is another placement"
    # the second copy sits one posed width and a gap from the first, along the bed's x
    assert items[1]["transform"][0][3] - items[0]["transform"][0][3] == pytest.approx(10 * 0.8660254 + 4 * 0.5 + 5.0, abs=1e-6)
    with zipfile.ZipFile(project) as z:
        assert z.namelist() == ["[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model", check.THREEMF_CONFIG,
                                p3mf.MODEL_CONFIG]
        assert f'transform="{to_3mf(want[0]["transform"])}" printable="1"' in z.read(p3mf.MODEL).decode()


def test_objects_are_named_and_carry_their_own_settings(tmp_path, stl, base):
    other = _box_stl(tmp_path / "second.stl", size=(7.0, 3.0, 1.0))
    odd = 'R&D "bracket" <1>'
    job = Job("plate", [JobPart("bar", stl, copies=2, settings={"perimeters": 4, "fill_density": "30%"}),
                        JobPart(odd, other)], options={"base_config": base})
    project, _ = write(job, tmp_path / "out")
    objects = p3mf.read_model_config(project)
    assert {o["name"] for o in objects.values()} == {"bar", odd}, "names with markup survive"
    assert [name for name in (i["name"] for i in read_plate(project))] == ["bar", "bar", odd]
    bar = objects["1"]
    assert bar["instances"] == 2 and bar["settings"] == {"perimeters": "4", "fill_density": "30%"}
    assert bar["volumes"] == [{"first": 0, "last": 11, "name": "bar", "type": "ModelPart"}], "one volume, every triangle"
    assert objects["2"]["settings"] == {} and objects["2"]["instances"] == 1
    # PrusaSlicer reads an object's keys against its own list: a key outside it is refused, in or out of the base
    job.parts[0].settings = {"temperature": 220}
    with pytest.raises(TargetError, match="bar: temperature cannot be set for one object"):
        targets.get_target(PRUSA).write_job(job, tmp_path / "again")
    with pytest.raises(TargetError, match="no readable Metadata/Slic3r_PE_model.config"):
        p3mf.read_model_config(tmp_path / "base.ini")
    assert ps.PER_OBJECT_KEYS <= set(tf.SYNTHETIC), "every per-object key is one a configuration carries"


def test_the_same_job_writes_the_same_bytes_and_the_sidecar_is_placement_2(tmp_path, stl, base):
    one, side_one = write(job_for(stl, base), tmp_path / "a")
    two, side_two = write(job_for(stl, base), tmp_path / "b")
    assert one.read_bytes() == two.read_bytes() and side_one.read_bytes() == side_two.read_bytes()
    changed, _ = write(job_for(stl, base, native={"perimeters": 5}), tmp_path / "c")
    assert changed.read_bytes() != one.read_bytes(), "equal bytes are not the result of ignoring the job"
    sidecar = json.loads(side_one.read_text())
    assert sidecar["schema"] == "agentcad.placement/2" and "row vector" in sidecar["convention"]
    inst = sidecar["instances"][0]
    assert inst["target"] == PRUSA and inst["part"] == "bar" and len(inst["sha256"]) == 64
    assert inst["transform"][0][3] == pytest.approx(100.0)
    assert {i.date_time for i in zipfile.ZipFile(one).infolist()} == {(1980, 1, 1, 0, 0, 0)}


@pytest.mark.parametrize("offset, said", [((195.0, 60.0, 0.0), "off the bed"), ((100.0, 178.0, 0.0), "off the bed"),
                                          ((-1.0, 60.0, 0.0), "off the bed"), ((100.0, 60.0, 149.5), "mm high"),
                                          ((100.0, 60.0, -1.0), "below the bed")])
def test_a_placement_that_leaves_the_bed_is_refused_and_nothing_is_written(tmp_path, stl, base, offset, said):
    target = targets.get_target(PRUSA)
    with pytest.raises(TargetError, match=said) as e:
        target.write_job(job_for(stl, base, offset=offset, deg=0.0), tmp_path / "out")
    assert "bar" in str(e.value) and "SYNTHPRINTER" in str(e.value), "it names the part and the printer"
    assert not (tmp_path / "out").exists()
    # the same part just inside the same edges is written
    inside = {(195.0, 60.0, 0.0): (190.0, 60.0, 0.0), (100.0, 178.0, 0.0): (100.0, 176.0, 0.0),
              (-1.0, 60.0, 0.0): (0.0, 60.0, 0.0), (100.0, 60.0, 149.5): (100.0, 60.0, 148.0),
              (100.0, 60.0, -1.0): (100.0, 60.0, 0.0)}[offset]
    assert target.write_job(job_for(stl, base, offset=inside, deg=0.0), tmp_path / "ok")[0].is_file()


def test_the_bed_check_follows_the_outline_and_names_how_many_copies_do_not_fit(tmp_path, stl, base):
    triangle = tf.write_ini(tmp_path / "triangle.ini", tf.synthetic_config(bed_shape="0x0,200x0,0x200"))
    target = targets.get_target(PRUSA)
    assert target.write_job(job_for(stl, triangle, offset=(20.0, 20.0, 0.0), deg=0.0), tmp_path / "in")[0].is_file()
    with pytest.raises(TargetError, match="off the bed"):      # inside the bounding box, past the slanted edge
        target.write_job(job_for(stl, triangle, offset=(150.0, 150.0, 0.0), deg=0.0), tmp_path / "out")
    many = Job("plate", [JobPart("bar", stl, copies=30, transform=_turn_z(0.0, (5.0, 60.0, 0.0)))],
               options={"base_config": base})
    with pytest.raises(TargetError, match=r"bar \(copy 14\).*and \d+ more"):
        target.write_job(many, tmp_path / "many")
    odd = tf.write_ini(tmp_path / "odd.ini", tf.synthetic_config(bed_shape="0x0,200x0"))
    with pytest.raises(TargetError, match="bed_shape"):
        target.write_job(job_for(stl, odd), tmp_path / "odd")
    with pytest.raises(TargetError, match="no bed_shape"):
        ps.bed_of({})
    assert not (tmp_path / "out").exists() and not (tmp_path / "many").exists()
    # a corner exactly on the slanted edge (110 + 90 = 200) is on the bed; a hair past it is not
    assert target.write_job(job_for(stl, triangle, offset=(100.0, 86.0, 0.0), deg=0.0), tmp_path / "edge")[0].is_file()
    with pytest.raises(TargetError, match="off the bed"):
        target.write_job(job_for(stl, triangle, offset=(100.0, 86.1, 0.0), deg=0.0), tmp_path / "past")


def test_a_job_that_cannot_be_written_is_refused_in_a_sentence(tmp_path, stl, base, monkeypatch, private_config_folder):
    target = targets.get_target(PRUSA)
    empty = _bytes(tmp_path / "empty.stl", bytes(80) + (0).to_bytes(4, "little"))
    cases = [
        (Job("plate", [], options={"base_config": base}), "has no parts"),
        (Job("plate", [JobPart("bar", stl), JobPart("bar", stl)], options={"base_config": base}), "two parts are named bar"),
        (Job("plate", [JobPart("gone", tmp_path / "gone.stl")], options={"base_config": base}), "cannot read the mesh of gone"),
        (Job("plate", [JobPart("cut", _bytes(tmp_path / "cut.stl", bytes(80) + b"\x05"))], options={"base_config": base}),
         "cannot read the mesh of cut"),
        (Job("plate", [JobPart("none", empty)], options={"base_config": base}), "has no triangles"),
    ]
    for job, said in cases:
        with pytest.raises(TargetError, match=said):
            target.write_job(job, tmp_path / "out")
    assert not (tmp_path / "out").exists()
    in_the_way = _write(tmp_path / "a_file", "not a folder\n")               # the output folder is a file
    with pytest.raises(TargetError, match="cannot write the project to"):
        target.write_job(job_for(stl, base), in_the_way)
    private_config_folder.mkdir(parents=True)
    (private_config_folder / "targets.toml").write_text('[prusaslicer]\nbase_config = "x.ini"\n')
    monkeypatch.setattr("agentcad.config.tomllib", None)
    with pytest.raises(TargetError, match="no TOML reader"):
        ps.user_base_config()


def test_an_ini_with_a_byte_order_mark_and_windows_line_ends_reads_like_any_other():
    assert pconfig.parse_ini("\ufeff# generated\r\nlayer_height = 0.2\r\n\r\nperimeters = 3\r\n") == {
        "layer_height": "0.2", "perimeters": "3"}


# --- reading and the printer --------------------------------------------------------------------------------

def test_the_target_reads_all_three_kinds_of_output_and_describes_the_printer(tmp_path, stl, base):
    target = targets.get_target(PRUSA)
    config = tf.synthetic_config(layer_height="0.31")
    project, _ = write(job_for(stl, tf.write_ini(tmp_path / "b.ini", config)), tmp_path / "out")
    for source in (tf.write_gcode(tmp_path / "s.gcode", config), tf.write_bgcode(tmp_path / "s.bgcode", config), project):
        assert target.read_settings(source)["layer_height"] == "0.31", source.name
    printer = target.printer(base)
    assert printer == printers.from_slicer_config(pconfig.load(base), name="base", source="base.ini"), \
        "the registry's reading of a bed"
    assert (printer.build_volume, printer.nozzle_mm, printer.process) == ((200.0, 180.0, 150.0), 0.5, "fdm")
    assert (printer.bed_origin, printer.bed_centre(), printer.source) == ((0.0, 0.0), (100.0, 90.0), "base.ini")
    assert target.job_printer({"base_config": base}) == printer, "a job is placed on its base configuration's bed"
    centred = target.printer(tf.write_ini(tmp_path / "c.ini", tf.synthetic_config(bed_shape="-100x-90,100x-90,100x90,-100x90")))
    assert (centred.build_volume[:2], centred.bed_origin, centred.bed_centre()) == ((200.0, 180.0), (-100.0, -90.0), (0.0, 0.0))
    assert target.printer(project).build_volume == (200.0, 180.0, 150.0)
    with pytest.raises(TargetError, match="no bed_shape"):
        target.printer(tf.write_ini(tmp_path / "nobed.ini", tf.synthetic_config(bed_shape=None)))
    with pytest.raises(TargetError, match="not understood"):
        target.printer(tf.write_ini(tmp_path / "badbed.ini", tf.synthetic_config(bed_shape="a,b,c")))


def test_gcode_check_reads_a_projects_configuration_and_the_json_is_unchanged(tmp_path, stl, base, capsys):
    project, _ = write(job_for(stl, base, intent={"layer_height": 0.15, "walls": 3}), tmp_path / "out")
    (tmp_path / "intent.toml").write_text('[slice]\nlayer_height = 0.15\nperimeters = 4\nbrim_width = { max = 3 }\n'
                                          'printhost_apikey = "x"\n')
    rc, out, err = run_cli(capsys, "gcode", "check", project, "--intent", tmp_path / "intent.toml")
    assert rc == 1 and "ERROR: perimeters is 3" in out and "layer_height = 0.15, as intent.toml [slice] asks" in out
    rc, out, err = run_cli(capsys, "gcode", "check", project, "--intent", tmp_path / "intent.toml", "--json")
    findings = json.loads(out)
    assert [f["key"] for f in findings] == ["layer_height", "perimeters", "brim_width"], "a private key is never checked"
    assert {"key", "severity", "found", "intended", "why", "source", "sentence"} <= set(findings[0])
    assert "SYNTHETIC" not in out
    bare = _zip(tmp_path / "other.3mf", {"3D/3dmodel.model": "<model/>"})
    with pytest.raises(ValueError, match="without Metadata/Slic3r_PE.config"):
        check.embedded_config(bare)
    with pytest.raises(ValueError, match="not a readable 3MF"):
        check.config_from_3mf(tmp_path / "base.ini")


# --- stage ---------------------------------------------------------------------------------------------------

SMALL_PRINTER = ('[printers.synth]\nlabel = "Synthetic printer"\nprocess = "fdm"\nbuild_volume = [200, 180, 150]\n'
                 'nozzle_mm = 0.5\n')


def staged_project(tmp_path, monkeypatch, capsys, extra=""):
    """A finalized one-part project, exported as a 20 x 10 x 40 box, for the synthetic 200 x 180 mm printer."""
    monkeypatch.setattr(cli, "_engine_for", lambda name, cfg: FakeBoxEngine())
    proj = tmp_path / "designs" / "bar"
    proj.mkdir(parents=True)
    (proj / "agentcad.toml").write_text(
        f'[project]\nname = "bar"\nengine = "fake"\n[output]\nbase_dir = "{tmp_path}"\nsub_dir = "designs"\n'
        'default_views = ["iso"]\n' + SMALL_PRINTER + '[qc]\nprinter = "synth"\npose = { up = [1, 0, 0] }\n' + extra)
    (proj / "bar.fake").write_text("volume = 10\nsize = 20, 10, 40\n")
    for argv in (["session", "start", str(proj)], ["session", "iterate", str(proj), str(proj / "bar.fake")],
                 ["session", "finalize", str(proj)]):
        cli.main(argv)
    capsys.readouterr()
    return proj


def test_stage_writes_a_project_and_reports_conflicts_and_what_it_did_not_map(tmp_path, monkeypatch, capsys, base):
    proj = staged_project(tmp_path, monkeypatch, capsys,
                          '[print]\nmaterial = "PETG"\nlayer_height = 0.15\nwalls = 3\nprint_orientation = "on its side"\n'
                          '[slice.prusaslicer]\nlayer_height = 0.2\nfill_pattern = "honeycomb"\n')
    rc, out, err = run_cli(capsys, "stage", proj, "--target", PRUSA, "--base-config", base, "-o", tmp_path / "staged")
    assert rc == 0 and err == ""
    assert "staged bar for prusaslicer on SYNTHPRINTER (its bed from base.ini): 1 part(s), 1 instance(s)" in out
    assert "note: QC judged" not in out                          # the QC printer and the base configuration agree
    assert "conflict: layer_height: [print] maps to '0.15', the native table says 0.2 (native kept)" in out
    assert "not mapped: material:" in out and "not mapped: print_orientation:" in out
    assert "note: base configuration: base.ini" in out and "note: material: [print] says PETG" in out
    assert not [v for v in tf.PRIVATE.values() if v in out], "no credential is printed"
    project = tmp_path / "staged" / "bar.3mf"
    settings = targets.get_target(PRUSA).read_settings(project)
    assert (settings["layer_height"], settings["perimeters"], settings["fill_pattern"]) == ("0.2", "3", "honeycomb")
    (item,) = read_plate(project)
    corners = [[sum(item["transform"][i][j] * v for j, v in enumerate((x, y, z, 1.0))) for i in range(3)]
               for x in (0, 20) for y in (0, 10) for z in (0, 40)]
    assert min(c[2] for c in corners) == pytest.approx(0.0, abs=1e-6)
    assert [(min(c[i] for c in corners) + max(c[i] for c in corners)) / 2 for i in (0, 1)] == pytest.approx([100.0, 90.0])
    rc, out, err = run_cli(capsys, "targets")
    assert "prusaslicer" in out and "write_job, slice, read_output, map_intent, printer_config" in out


def test_stage_writes_an_assembly_as_named_objects_with_their_quantities(tmp_path, monkeypatch, capsys, base):
    from agentcad.gcode import supports
    monkeypatch.setattr(cli, "_engine_for", lambda name, cfg: FakeBoxEngine())
    parent = tmp_path / "designs" / "asm"
    parent.mkdir(parents=True)
    (parent / "agentcad.toml").write_text(
        f'[project]\nname = "asm"\nengine = "fake"\nparts = ["parts/*"]\n[output]\nbase_dir = "{tmp_path}"\n'
        'sub_dir = "designs"\n' + SMALL_PRINTER + '[qc]\nprinter = "synth"\n[print]\nlayer_height = 0.15\n')
    for part, size, quantity in (("lid", "30, 20, 5", 1), ("peg", "8, 8, 20", 3)):
        folder = parent / "parts" / part
        folder.mkdir(parents=True)
        (folder / "agentcad.toml").write_text(
            f'[project]\nname = "{part}"\nengine = "fake"\nquantity = {quantity}\n'
            f'[output]\nbase_dir = "{parent}"\nsub_dir = "parts"\ndefault_views = ["iso"]\n')
        (folder / f"{part}.fake").write_text(f"volume = 10\nsize = {size}\n")
        for argv in (["session", "start", str(folder)], ["session", "iterate", str(folder), str(folder / f"{part}.fake")],
                     ["session", "finalize", str(folder)]):
            cli.main(argv)
    capsys.readouterr()
    rc, out, err = run_cli(capsys, "stage", parent, "--target", PRUSA, "--base-config", base, "-o", tmp_path / "staged")
    assert rc == 0 and "2 part(s), 4 instance(s)" in out, err
    objects = p3mf.read_model_config(tmp_path / "staged" / "asm.3mf")
    assert [(o["name"], o["instances"]) for o in objects.values()] == [("lid", 1), ("peg", 3)]
    assert [i["name"] for i in read_plate(tmp_path / "staged" / "asm.3mf")] == ["lid", "peg", "peg", "peg"]
    assert sorted(supports.load_placement(tmp_path / "staged" / "asm.placement.json")) == ["lid", "peg", "peg (2)", "peg (3)"]


def test_stage_refuses_in_one_line_and_exit_status_2(tmp_path, monkeypatch, capsys, base):
    proj = staged_project(tmp_path, monkeypatch, capsys, '[slice.prusaslicer]\nperimeterz = 3\n')
    out_dir = tmp_path / "staged"
    refusals = [
        (["--target", PRUSA, "-o", out_dir], "no base configuration: pass --base-config PATH"),
        (["--target", PRUSA, "--base-config", base, "-o", out_dir], "perimeterz is not a setting of the base configuration"),
        (["--target", PRUSA, "--base-config", tmp_path / "missing.ini", "-o", out_dir], "cannot read"),
        (["--target", "generic", "--base-config", base, "-o", out_dir], "takes no base configuration"),
    ]
    typo_fixed = (proj / "agentcad.toml").read_text().replace("perimeterz", "perimeters")
    for fix, argv, said in [(False,) + r for r in refusals] + [
            (True, ["--target", PRUSA, "--base-config", base, "--copies", "30", "-o", out_dir],
             "does not fit the bed of SYNTHPRINTER")]:
        if fix:
            (proj / "agentcad.toml").write_text(typo_fixed)
        rc, out, err = run_cli(capsys, "stage", proj, *argv)
        assert rc == 2 and out == "", argv
        assert err.startswith("Error: ") and said in err and len(err.strip().splitlines()) == 1, err
        assert "Traceback" not in err
    assert not out_dir.exists(), "no refused job wrote a file"
    rc, out, err = run_cli(capsys, "stage", proj, "--target", PRUSA, "--base-config", base, "-o", out_dir)
    assert rc == 0, err                                        # the same project, with fewer copies, stages


def test_stage_refuses_an_unknown_target_one_that_writes_no_job_and_an_unusable_intent(tmp_path, monkeypatch, capsys, base):
    class Reader(targets.OutputTarget):
        name = "reader"
        capabilities = frozenset({"read_output"})

    proj = staged_project(tmp_path, monkeypatch, capsys, '[print]\nlayer_height = 0\n')
    targets.register_target("reader", Reader)
    try:
        for argv, said in [(["--target", "nope"], "unknown output target"),
                           (["--target", "reader"], "does not write a job"),
                           (["--target", PRUSA, "--base-config", base], "[print] layer_height must be a number over 0")]:
            rc, out, err = run_cli(capsys, "stage", proj, *argv)
            assert rc == 2 and said in err and err.startswith("Error: "), err
    finally:
        targets.unregister_target("reader")
    fresh = tmp_path / "designs" / "fresh"
    fresh.mkdir(parents=True)
    (fresh / "agentcad.toml").write_text(
        f'[project]\nname = "fresh"\nengine = "fake"\n[output]\nbase_dir = "{tmp_path}"\nsub_dir = "designs"\n')
    cli.main(["session", "start", str(fresh)])
    capsys.readouterr()
    rc, out, err = run_cli(capsys, "stage", fresh, "--target", PRUSA, "--base-config", base)
    assert rc == 2 and err == "Error: fresh has no export of its latest iteration: finalize it first\n", err


def test_stage_uses_the_users_default_base_configuration(tmp_path, monkeypatch, capsys, base, private_config_folder):
    proj = staged_project(tmp_path, monkeypatch, capsys, '[print]\nlayer_height = 0.15\n')
    private_config_folder.mkdir(parents=True)
    (private_config_folder / "targets.toml").write_text(f'[prusaslicer]\nbase_config = "{base}"\n')
    rc, out, err = run_cli(capsys, "stage", proj, "--target", PRUSA, "-o", tmp_path / "staged")
    assert rc == 0 and "note: base configuration: base.ini" in out and err == ""
    assert targets.get_target(PRUSA).read_settings(tmp_path / "staged" / "bar.3mf")["layer_height"] == "0.15"


def _placed_centre(project, size=(20.0, 10.0, 40.0)):
    """The bed x and y of the centre of a one-part plate's posed box (the part as staged_project exports it)."""
    (item,) = read_plate(project)
    corners = [[sum(item["transform"][i][j] * v for j, v in enumerate((x, y, z, 1.0))) for i in range(3)]
               for x in (0, size[0]) for y in (0, size[1]) for z in (0, size[2])]
    return [(min(c[i] for c in corners) + max(c[i] for c in corners)) / 2 for i in (0, 1)]


def test_stage_centres_on_the_bed_the_target_checks_and_says_whose_it_is(tmp_path, monkeypatch, capsys):
    proj = staged_project(tmp_path, monkeypatch, capsys)        # the QC printer: synthetic, 200 x 180 x 150
    smaller = tf.write_ini(tmp_path / "smaller.ini", tf.synthetic_config(bed_shape="0x0,180x0,180x180,0x180"))
    rc, out, err = run_cli(capsys, "stage", proj, "--target", PRUSA, "--base-config", smaller, "-o", tmp_path / "staged")
    assert rc == 0, err
    assert _placed_centre(tmp_path / "staged" / "bar.3mf") == pytest.approx([90.0, 90.0])   # not the QC bed's (100, 90)
    assert "staged bar for prusaslicer on SYNTHPRINTER (its bed from smaller.ini): 1 part(s), 1 instance(s)" in out
    assert ("note: QC judged the parts against Synthetic printer (200 x 180 x 150 mm); they are placed on "
            "SYNTHPRINTER (180 x 180 x 150 mm), whose width differs\n") in out


def test_stage_notes_which_dimension_of_the_build_volume_differs(tmp_path, monkeypatch, capsys):
    proj = staged_project(tmp_path, monkeypatch, capsys)        # the QC printer: synthetic, 200 x 180 x 150
    lower = tf.write_ini(tmp_path / "lower.ini", tf.synthetic_config(max_print_height="120"))
    rc, out, err = run_cli(capsys, "stage", proj, "--target", PRUSA, "--base-config", lower, "-o", tmp_path / "a")
    assert rc == 0, err                                          # the same bed: only its height differs
    assert ("note: QC judged the parts against Synthetic printer (200 x 180 x 150 mm); they are placed on "
            "SYNTHPRINTER (200 x 180 x 120 mm), whose height differs\n") in out
    other = tf.write_ini(tmp_path / "other.ini",
                         tf.synthetic_config(bed_shape="0x0,190x0,190x170,0x170", max_print_height="120"))
    rc, out, err = run_cli(capsys, "stage", proj, "--target", PRUSA, "--base-config", other, "-o", tmp_path / "b")
    assert rc == 0, err
    assert "SYNTHPRINTER (190 x 170 x 120 mm), whose width, depth and height differ\n" in out


def test_stage_asks_for_finalized_parts_before_the_targets_configuration(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_engine_for", lambda name, cfg: FakeBoxEngine())
    fresh = tmp_path / "designs" / "fresh"
    fresh.mkdir(parents=True)
    (fresh / "agentcad.toml").write_text(
        f'[project]\nname = "fresh"\nengine = "fake"\n[output]\nbase_dir = "{tmp_path}"\nsub_dir = "designs"\n')
    cli.main(["session", "start", str(fresh)])
    capsys.readouterr()
    rc, out, err = run_cli(capsys, "stage", fresh, "--target", PRUSA)          # and no base configuration either
    assert rc == 2 and err == "Error: fresh has no export of its latest iteration: finalize it first\n", err


def test_stage_centres_on_a_bed_whose_origin_is_not_a_corner(tmp_path, monkeypatch, capsys):
    proj = staged_project(tmp_path, monkeypatch, capsys)
    centred = tf.write_ini(tmp_path / "centred.ini", tf.synthetic_config(bed_shape="-100x-90,100x-90,100x90,-100x90"))
    rc, out, err = run_cli(capsys, "stage", proj, "--target", PRUSA, "--base-config", centred, "-o", tmp_path / "staged")
    assert rc == 0, err                                          # it was refused as off the bed
    assert _placed_centre(tmp_path / "staged" / "bar.3mf") == pytest.approx([0.0, 0.0])
    assert "note: QC judged" not in out                          # the same bed, only placed elsewhere


def test_stage_on_a_target_without_a_printer_of_its_own_centres_on_the_qc_printer(tmp_path, monkeypatch, capsys):
    proj = staged_project(tmp_path, monkeypatch, capsys)
    rc, out, err = run_cli(capsys, "stage", proj, "--target", "generic", "-o", tmp_path / "staged")
    assert rc == 0, err
    assert "staged bar for generic on Synthetic printer (the QC printer's bed): 1 part(s), 1 instance(s)" in out
    assert _placed_centre(tmp_path / "staged" / "bar.3mf") == pytest.approx([100.0, 90.0])


# --- slicing in the loop ------------------------------------------------------------------------------------

def fake_slicer(tmp_path, monkeypatch, writes=b"; generated by PrusaSlicer\nG1 X1 E1\n", exit_code=0, said=""):
    """A stand-in for prusa-slicer, named by AGENTCAD_PRUSASLICER: it writes `writes` to its --output and exits
    with `exit_code`, printing `said` on stderr; each call's arguments are kept in calls.txt beside it."""
    script = tmp_path / "fake-prusa-slicer"
    data = tmp_path / "fake-output.bin"
    data.write_bytes(writes)
    script.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{tmp_path / "calls.txt"}"\n'
        'out=""; prev=""\n'
        'for a in "$@"; do [ "$prev" = "--output" ] && out="$a"; prev="$a"; done\n'
        f'[ -n "$out" ] && cp "{data}" "$out"\n'
        f'[ -n "{said}" ] && echo "{said}" >&2\n'
        f"exit {exit_code}\n")
    script.chmod(0o755)
    monkeypatch.setenv("AGENTCAD_PRUSASLICER", str(script))
    return script


def test_the_target_slices_and_names_the_output_by_its_first_bytes_not_its_extension(tmp_path, stl, base, monkeypatch):
    project, _ = write(job_for(stl, base), tmp_path / "out")
    fake_slicer(tmp_path, monkeypatch, writes=b"GCDE\x01\x00\x00\x00\x01\x00rest")
    target = targets.get_target(PRUSA)
    assert target.available() and "slice" in target.capabilities
    sliced = target.slice(project, tmp_path / "sliced")
    assert sliced == tmp_path / "sliced" / "plate.bgcode" and sliced.read_bytes().startswith(b"GCDE")
    fake_slicer(tmp_path, monkeypatch)                           # plain text this time: the same call, another name
    sliced = target.slice(project, tmp_path / "sliced")
    assert sliced == tmp_path / "sliced" / "plate.gcode" and not (tmp_path / "sliced" / "plate.bgcode").exists()
    assert "--export-gcode" in (tmp_path / "calls.txt").read_text() and str(project) in (tmp_path / "calls.txt").read_text()


def test_a_slicer_that_fails_or_writes_nothing_is_refused_in_a_sentence(tmp_path, stl, base, monkeypatch):
    project, _ = write(job_for(stl, base), tmp_path / "out")
    target = targets.get_target(PRUSA)
    fake_slicer(tmp_path, monkeypatch, exit_code=1, said="Objects could not fit on the bed")
    with pytest.raises(TargetError, match=r"PrusaSlicer could not slice plate\.3mf .*Objects could not fit on the bed"):
        target.slice(project, tmp_path / "sliced")
    fake_slicer(tmp_path, monkeypatch, writes=b"")
    with pytest.raises(TargetError, match="wrote nothing"):
        target.slice(project, tmp_path / "sliced")
    assert not [p for p in (tmp_path / "sliced").iterdir() if p.suffix in (".gcode", ".bgcode")]


def test_with_no_slicer_found_the_target_is_unavailable_and_says_how_to_name_one(tmp_path, stl, base, monkeypatch):
    project, _ = write(job_for(stl, base), tmp_path / "out")
    monkeypatch.setenv("AGENTCAD_PRUSASLICER", str(tmp_path / "no-such-slicer"))
    target = targets.get_target(PRUSA)
    assert not target.available()
    with pytest.raises(TargetError, match="AGENTCAD_PRUSASLICER"):
        target.slice(project, tmp_path / "sliced")


def test_stage_slice_slices_the_staged_project_and_checks_what_came_out(tmp_path, monkeypatch, capsys, base):
    proj = staged_project(tmp_path, monkeypatch, capsys, '[print]\nlayer_height = 0.25\n')
    sliced_config = tf.synthetic_config()                        # the base's settings: layer_height 0.25
    fake_slicer(tmp_path, monkeypatch, writes=tf.write_gcode(tmp_path / "made.gcode", sliced_config).read_bytes())
    rc, out, err = run_cli(capsys, "stage", proj, "--target", PRUSA, "--base-config", base, "-o", tmp_path / "staged",
                           "--slice")
    assert rc == 0, err
    assert f"sliced: {tmp_path / 'staged' / 'bar.gcode'}" in out
    assert "bar.gcode: 1 intended settings, 0 error(s), 0 warning(s)" in out
    assert "support" in out                                      # the support map ran on it too


def test_stage_slice_exits_1_when_the_sliced_file_disagrees_with_the_intent(tmp_path, monkeypatch, capsys, base):
    proj = staged_project(tmp_path, monkeypatch, capsys, '[print]\nlayer_height = 0.1\n')
    fake_slicer(tmp_path, monkeypatch, writes=tf.write_gcode(tmp_path / "made.gcode", tf.synthetic_config()).read_bytes())
    rc, out, err = run_cli(capsys, "stage", proj, "--target", PRUSA, "--base-config", base, "-o", tmp_path / "staged",
                           "--slice")
    assert rc == 1 and "ERROR" in out and "layer_height" in out


def test_stage_copies_below_one_is_refused_by_name_and_writes_nothing(tmp_path, monkeypatch, capsys):
    """0 once read as "not given" and staged the project's quantity in silence; -1 staged and printed -1 instances."""
    proj = staged_project(tmp_path, monkeypatch, capsys)
    for n in ("0", "-1"):
        rc, out, err = run_cli(capsys, "stage", proj, "--target", "generic", "--copies", n, "-o", tmp_path / "staged")
        assert rc == 2 and f"--copies {n}: " in err and "at least 1" in err, (n, out, err)
        assert not (tmp_path / "staged").exists(), n


def test_stage_slice_on_a_target_that_cannot_slice_says_so_and_writes_nothing(tmp_path, monkeypatch, capsys):
    proj = staged_project(tmp_path, monkeypatch, capsys)
    rc, out, err = run_cli(capsys, "stage", proj, "--target", "generic", "-o", tmp_path / "staged", "--slice")
    assert rc == 2 and "target 'generic' does not slice" in err
    assert not (tmp_path / "staged").exists()


@pytest.mark.parametrize("step, failure", [("load_placement", OSError("placement unreadable")),
                                           ("load_placement", ValueError("not a placement")),
                                           ("gcode_text", BGCodeError("unknown block type 9", 60, 2))],
                         ids=["os", "value", "bgcode"])
def test_stage_slice_says_so_in_a_sentence_when_the_support_map_cannot_be_read(tmp_path, monkeypatch, capsys, base,
                                                                              step, failure):
    from agentcad.gcode import bgcode, supports
    proj = staged_project(tmp_path, monkeypatch, capsys, '[print]\nlayer_height = 0.25\n')
    fake_slicer(tmp_path, monkeypatch, writes=tf.write_gcode(tmp_path / "made.gcode", tf.synthetic_config()).read_bytes())

    def unreadable(*a, **k):
        raise failure
    monkeypatch.setattr(supports if step == "load_placement" else bgcode, step, unreadable)
    rc, out, err = run_cli(capsys, "stage", proj, "--target", PRUSA, "--base-config", base, "-o", tmp_path / "staged",
                           "--slice")
    assert rc == 1                                               # never 0: exit 0 means everything was read
    assert "0 error(s)" in out                                   # the settings check still ran and is reported
    assert f"the support map of {tmp_path / 'staged' / 'bar.gcode'} could not be read: {failure}" in err
    assert "Traceback" not in err


def test_stage_slice_reads_the_contact_distance_with_the_file_and_names_a_malformed_one(tmp_path, monkeypatch, capsys,
                                                                                       base):
    proj = staged_project(tmp_path, monkeypatch, capsys, '[print]\nlayer_height = 0.25\n')
    made = tf.write_gcode(tmp_path / "made.gcode", tf.synthetic_config(support_material_contact_distance="abc"))
    fake_slicer(tmp_path, monkeypatch, writes=made.read_bytes())
    rc, out, err = run_cli(capsys, "stage", proj, "--target", PRUSA, "--base-config", base, "-o", tmp_path / "staged",
                           "--slice")
    assert rc == 1 and "Traceback" not in err, (out, err)
    assert "could not be read: support_material_contact_distance 'abc' is not a number" in err, err


def test_stage_slice_lets_a_failure_in_the_support_analysis_surface_rather_than_call_the_file_unreadable(
        tmp_path, monkeypatch, capsys, base):
    from agentcad.gcode import supports
    proj = staged_project(tmp_path, monkeypatch, capsys, '[print]\nlayer_height = 0.25\n')
    fake_slicer(tmp_path, monkeypatch, writes=tf.write_gcode(tmp_path / "made.gcode", tf.synthetic_config()).read_bytes())

    def broken(*a, **k):
        raise ValueError("a bug in the analysis")
    monkeypatch.setattr(supports, "find_contacts", broken)
    with pytest.raises(ValueError, match="a bug in the analysis"):
        run_cli(capsys, "stage", proj, "--target", PRUSA, "--base-config", base, "-o", tmp_path / "staged", "--slice")
    assert "could not be read" not in capsys.readouterr().err


def test_stage_slice_with_no_slicer_installed_is_refused_before_anything_is_written(tmp_path, monkeypatch, capsys,
                                                                                    base):
    proj = staged_project(tmp_path, monkeypatch, capsys)
    monkeypatch.setenv("AGENTCAD_PRUSASLICER", str(tmp_path / "no-such-slicer"))
    monkeypatch.setattr(ps.shutil, "which", lambda name: None)
    rc, out, err = run_cli(capsys, "stage", proj, "--target", PRUSA, "--base-config", base, "-o", tmp_path / "staged",
                           "--slice")
    assert rc == 2 and "no PrusaSlicer to slice with" in err and "AGENTCAD_PRUSASLICER" in err
    assert not (tmp_path / "staged").exists()


@pytest.mark.skipif(not targets.get_target(PRUSA).available(), reason="no PrusaSlicer installed here")
def test_stage_slice_with_the_real_slicer_writes_a_file_the_check_and_the_supports_read(tmp_path, monkeypatch, capsys, base):
    monkeypatch.delenv("AGENTCAD_PRUSASLICER", raising=False)
    proj = staged_project(tmp_path, monkeypatch, capsys, '[print]\nlayer_height = 0.25\n')
    rc, out, err = run_cli(capsys, "stage", proj, "--target", PRUSA, "--base-config", base, "-o", tmp_path / "staged",
                           "--slice")
    assert rc == 0, out + err
    made = [p for p in (tmp_path / "staged").iterdir() if p.suffix in (".gcode", ".bgcode")]
    assert len(made) == 1 and check.embedded_config(made[0])["layer_height"] == "0.25"
    assert "0 error(s)" in out
