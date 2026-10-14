"""Support contact from the toolpaths: a part printed over a support block, three thin layers up."""
from agentcad.gcode import model as gm, supports as sp


def _layer(z, body):
    return f";LAYER_CHANGE\n;Z:{z}\n;HEIGHT:0.15\nG1 Z{z}\n{body}"


SUPPORT = ";TYPE:Support material\n;WIDTH:0.45\nG1 X0 Y0\nG1 X10 Y0 E1\nG1 X10 Y2 E.2\nG1 X0 Y2 E1\n"
PART = ";TYPE:Bridge infill\n;WIDTH:0.45\nG1 X0 Y1\nG1 X10 Y1 E1\n"
ELSEWHERE = ";TYPE:Perimeter\n;WIDTH:0.45\nG1 X30 Y30\nG1 X40 Y30 E1\n"

TEXT = ("M83\nM486 S0\nM486 Aledge.stl\n"
        + _layer(0.15, SUPPORT + ELSEWHERE) + _layer(0.30, SUPPORT + ELSEWHERE)
        + _layer(0.45, ELSEWHERE) + _layer(0.60, ELSEWHERE)
        + _layer(0.75, PART + ELSEWHERE))        # the ledge: 0.45 mm over the top support layer


def test_a_part_three_thin_layers_above_its_support_is_a_contact():
    bands = sp.find_contacts(gm.parse(TEXT), contact_distance=0.25)
    assert len(bands) == 1
    b = bands[0]
    assert b.object == "ledge.stl" and b.layers == (1, 1) and b.z == (0.30, 0.30)
    assert 0 <= b.xy_min[0] and b.xy_max[0] <= 10.5 and b.area_mm2 > 0
    assert "supports touch ledge.stl at z 0.30-0.30 mm" in b.sentence()


def test_a_window_too_short_for_the_gap_finds_nothing():
    assert sp.find_contacts(gm.parse(TEXT), contact_distance=0.0) == []      # 0.30 window < 0.45 gap


def test_support_beside_the_part_is_not_a_contact():
    text = TEXT.replace(PART, ";TYPE:Bridge infill\n;WIDTH:0.45\nG1 X20 Y1\nG1 X30 Y1 E1\n")
    assert sp.find_contacts(gm.parse(text), contact_distance=0.25) == []


def test_cli_reads_the_contact_distance_from_the_file(tmp_path):
    import json
    import subprocess
    import sys
    f = tmp_path / "ledge.gcode"
    f.write_text(TEXT + "; prusaslicer_config = begin\n; support_material_contact_distance = 0.25\n"
                        "; prusaslicer_config = end\n")
    run = [sys.executable, "-c", "import sys; from agentcad.cli import main; sys.exit(main())"]
    r = subprocess.run(run + ["gcode", "supports", str(f), "--min-area", "0", "--json"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert [b["object"] for b in json.loads(r.stdout)] == ["ledge.stl"]
    r = subprocess.run(run + ["gcode", "supports", str(f), "--contact-distance", "0", "--min-area", "0"],
                       capture_output=True, text=True)
    assert "no support touches a part" in r.stdout


def test_bands_map_into_the_object_frame_only_with_a_placement(tmp_path):
    import json
    p = tmp_path / "plate.placement.json"
    p.write_text(json.dumps({"schema": "agentcad.placement/1", "objects": [
        {"name": "ledge.stl", "stl": "ledge.stl", "instances": [{"label": "ledge.stl", "bed_offset": [100, 50, 0]}]}]}))
    placement = sp.load_placement(p)
    band = sp.Band("ledge.stl", (1, 1), (0.3, 0.3), (101.0, 52.0), (105.0, 53.0), 2.0, 4)
    o = sp.in_object_frame(band, placement)
    assert o["x"] == (1.0, 5.0) and o["y"] == (2.0, 3.0) and o["z"] == (0.3, 0.3)
    assert sp.in_object_frame(sp.Band("other.stl", (1, 1), (0, 0), (0, 0), (1, 1), 1.0, 1), placement) is None


def test_cli_placement_prints_the_stl_frame_or_says_unknown(tmp_path):
    import json
    import subprocess
    import sys
    f = tmp_path / "ledge.gcode"
    f.write_text(TEXT)
    p = tmp_path / "plate.placement.json"
    p.write_text(json.dumps({"schema": "agentcad.placement/1", "objects": [
        {"name": "ledge.stl", "stl": "ledge.stl", "instances": [{"label": "ledge.stl", "bed_offset": [0, 0, 0]}]}]}))
    run = [sys.executable, "-c", "import sys; from agentcad.cli import main; sys.exit(main())"]
    r = subprocess.run(run + ["gcode", "supports", str(f), "--contact-distance", "0.25", "--min-area", "0",
                              "--placement", str(p)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "in its STL frame: x 10.0..10.2, y 0.8..1.5" in r.stdout          # zero offset: STL frame = bed frame
    p.write_text(json.dumps({"schema": "agentcad.placement/1", "objects": []}))
    r = subprocess.run(run + ["gcode", "supports", str(f), "--contact-distance", "0.25", "--min-area", "0",
                              "--placement", str(p)], capture_output=True, text=True)
    assert "placement unknown" in r.stdout


def test_enclosure_tells_a_bore_from_an_outer_surface():
    import pytest
    pv = pytest.importorskip("pyvista")
    tube = pv.Cylinder(radius=6.0, height=20, direction=(0, 0, 1), capping=False, resolution=64) \
        + pv.Cylinder(radius=4.0, height=20, direction=(0, 0, 1), capping=False, resolution=64)
    assert sp.enclosure((0.31, 0.17, 0.0), tube) == "cavity"        # in the bore (off the mesh's symmetry lines)
    assert sp.enclosure((8.31, 0.17, 0.0), tube) == "outside"       # beside the tube
    assert sp.enclosure((0.31, 0.17, 15.0), tube) == "outside"      # above the open end


def test_cli_reports_a_cavity_contact_as_an_error(tmp_path):
    import json
    import subprocess
    import sys
    import pytest
    pv = pytest.importorskip("pyvista")
    tube = pv.Cylinder(center=(10.0, 1.0, 0.0), radius=6.0, height=4, direction=(0, 0, 1), capping=False,
                       resolution=48) + pv.Cylinder(center=(10.0, 1.0, 0.0), radius=4.0, height=4,
                                                    direction=(0, 0, 1), capping=False, resolution=48)
    tube.save(str(tmp_path / "ledge.stl"))
    f = tmp_path / "ledge.gcode"
    f.write_text(TEXT)
    p = tmp_path / "plate.placement.json"
    p.write_text(json.dumps({"schema": "agentcad.placement/1", "objects": [
        {"name": "ledge.stl", "stl": "ledge.stl", "instances": [{"label": "ledge.stl", "bed_offset": [0, 0, 0]}]}]}))
    run = [sys.executable, "-c", "import sys; from agentcad.cli import main; sys.exit(main())"]
    r = subprocess.run(run + ["gcode", "supports", str(f), "--contact-distance", "0.25", "--min-area", "0",
                              "--placement", str(p)], capture_output=True, text=True)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "ERROR: walled in on every side" in r.stdout


def _ledge_plate(tmp_path, tube_center):
    """The ledge file, its placement, and a tube STL centred at ``tube_center``: at (10, 1) the contact sits in
    the tube's bore, far away it sits on nothing the rays can wall in."""
    import json
    import pytest
    pv = pytest.importorskip("pyvista")
    cx, cy = tube_center
    tube = pv.Cylinder(center=(cx, cy, 0.0), radius=6.0, height=4, direction=(0, 0, 1), capping=False,
                       resolution=48) + pv.Cylinder(center=(cx, cy, 0.0), radius=4.0, height=4,
                                                    direction=(0, 0, 1), capping=False, resolution=48)
    tube.save(str(tmp_path / "ledge.stl"))
    f = tmp_path / "ledge.gcode"
    f.write_text(TEXT)
    p = tmp_path / "plate.placement.json"
    p.write_text(json.dumps({"schema": "agentcad.placement/1", "objects": [
        {"name": "ledge.stl", "stl": "ledge.stl", "instances": [{"label": "ledge.stl", "bed_offset": [0, 0, 0]}]}]}))
    return f, p


def _supports(*words, without=()):
    """``agentcad gcode supports`` in a fresh process; ``without`` names modules it cannot import."""
    import subprocess
    import sys
    run = [sys.executable, "-c", "import sys; sys.modules.update(dict.fromkeys(sys.argv[1].split(',') if sys.argv[1] "
                                 "else [])); from agentcad.cli import main; sys.argv[1:2] = []; sys.exit(main())",
           ",".join(without)]
    return subprocess.run(run + ["gcode", "supports", *map(str, words), "--contact-distance", "0.25",
                                 "--min-area", "0"], capture_output=True, text=True)


def test_json_names_each_contacts_region_and_fails_on_a_cavity_as_the_text_does(tmp_path):
    import json
    f, p = _ledge_plate(tmp_path, (10.0, 1.0))
    r = _supports(f, "--placement", p, "--json")
    assert r.returncode == 1, r.stdout + r.stderr
    bands = json.loads(r.stdout)                       # stdout is the JSON and nothing else
    assert bands and {b["region"] for b in bands} == {"cavity"}, bands
    assert all(b["region_votes"]["cavity"] > 0 for b in bands), bands


def test_json_says_outside_or_not_checked_and_then_exits_0(tmp_path):
    import json
    f, p = _ledge_plate(tmp_path, (100.0, 100.0))
    r = _supports(f, "--placement", p, "--json")
    assert r.returncode == 0, r.stdout + r.stderr
    assert {b["region"] for b in json.loads(r.stdout)} == {"outside"}
    r = _supports(f, "--json")                         # no placement: no region check, and it says so by null
    assert r.returncode == 0, r.stdout + r.stderr
    assert {(b["region"], b["region_votes"], b["region_note"]) for b in json.loads(r.stdout)} == {(None, None, None)}


NO_PYVISTA = "pyvista is not installed: no region check (the build123d extra installs it)"


def test_without_pyvista_json_lists_the_bands_and_says_why_no_region_was_checked(tmp_path):
    import json
    f, p = _ledge_plate(tmp_path, (10.0, 1.0))         # a cavity, had it been checked
    r = _supports(f, "--placement", p, "--json", without=["pyvista"])
    assert r.returncode == 0, r.stdout + r.stderr
    bands = json.loads(r.stdout)
    assert bands and {(b["region"], b["region_votes"], b["region_note"]) for b in bands} == {(None, None, NO_PYVISTA)}


def test_without_pyvista_the_text_says_why_no_region_was_checked(tmp_path):
    f, p = _ledge_plate(tmp_path, (10.0, 1.0))
    r = _supports(f, "--placement", p, without=["pyvista"])
    assert r.returncode == 0 and "Traceback" not in r.stderr, r.stdout + r.stderr
    assert f"      ({NO_PYVISTA})\n" in r.stdout, r.stdout


def test_without_pyvista_png_is_refused_before_any_output_as_a_usage_error(tmp_path):
    """The machine this matters on has no pyvista, so the test needs none either: plain G-code, no placement and no
    STL to build (the refusal comes before anything is read)."""
    f = tmp_path / "ledge.gcode"
    f.write_text(TEXT)
    png = tmp_path / "contacts.png"
    for mode in ((), ("--json",)):
        r = _supports(f, *mode, "--png", png, without=["pyvista"])
        assert r.returncode == 2, (mode, r.stdout + r.stderr)
        assert r.stdout == "" and "Traceback" not in r.stderr, (mode, r.stdout + r.stderr)
        assert "Error: --png needs pyvista (the build123d extra installs it)" in r.stderr, (mode, r.stderr)
        assert not png.exists()


def test_a_contact_distance_that_is_not_a_number_is_one_error_line_naming_the_setting(tmp_path):
    from tests import targetfixtures as tf
    f = tf.write_gcode(tmp_path / "cd.gcode", tf.synthetic_config(support_material_contact_distance="abc"))
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-c", "import sys; from agentcad.cli import main; sys.exit(main())",
                        "gcode", "supports", str(f)], capture_output=True, text=True)
    assert r.returncode == 1 and "Traceback" not in r.stderr, r.stdout + r.stderr
    assert f"Error: {f}: support_material_contact_distance 'abc' is not a number" in r.stderr, r.stderr


def test_a_placed_stl_that_cannot_be_read_is_a_reason_no_region_was_checked_not_a_traceback(tmp_path):
    """pyvista reads a corrupt STL as an empty mesh (it prints an error and raises nothing), and the rays then failed
    deep in the analysis. The band is listed as before, and says why its region was not checked."""
    import pytest
    pytest.importorskip("pyvista")
    f, p = _ledge_plate(tmp_path, (10.0, 1.0))
    (tmp_path / "ledge.stl").write_bytes(b"\x00\x01 not an STL " * 8)
    r = _supports(f, "--placement", p)
    assert r.returncode == 0 and "Traceback" not in r.stderr, r.stdout + r.stderr
    assert "contact band(s)" in r.stdout and "could not be read" in r.stdout and "no region check" in r.stdout, r.stdout


def test_the_picture_draws_the_bands_of_a_part_whose_stl_could_not_be_read_and_skips_the_part(tmp_path, monkeypatch):
    import pytest
    pv = pytest.importorskip("pyvista")
    from agentcad import cli
    f, p = _ledge_plate(tmp_path, (10.0, 1.0))
    bands = sp.find_contacts(gm.parse(TEXT), contact_distance=0.25)
    drawn = []

    class Plotter:
        def __init__(self, *args, **kwargs):
            pass

        def add_mesh(self, *args, **kwargs):
            drawn.append("part")

        def add_points(self, *args, **kwargs):
            drawn.append("band")

        def __getattr__(self, name):
            return lambda *args, **kwargs: None
    monkeypatch.setattr(pv, "Plotter", Plotter)
    meshes = {str(tmp_path / "ledge.stl"): "no triangles in it"}           # as the judging leaves an unreadable STL
    cli._supports_png(tmp_path / "s.png", bands, sp.load_placement(p), meshes, tmp_path,
                      {id(b): (None, None, None, None, "could not be read") for b in bands})
    assert drawn == ["band"] * len(bands), drawn


def test_the_picture_reads_no_stl_the_judging_already_read(tmp_path, monkeypatch):
    import pytest
    pv = pytest.importorskip("pyvista")
    from agentcad import cli
    f, p = _ledge_plate(tmp_path, (10.0, 1.0))
    bands = sp.find_contacts(gm.parse(TEXT), contact_distance=0.25)
    stl = str(tmp_path / "ledge.stl")
    cache = {stl: pv.read(stl)}                        # as the judging leaves it

    class Plotter:                                     # no window and no picture: only the reading is under test
        def __init__(self, *args, **kwargs):
            pass

        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    reads = []
    monkeypatch.setattr(pv, "read", lambda path: reads.append(path))
    monkeypatch.setattr(pv, "Plotter", Plotter)
    cli._supports_png(tmp_path / "s.png", bands, sp.load_placement(p), cache, tmp_path,
                      {id(b): (None, None, None, None, None) for b in bands})
    assert bands and reads == [], reads


def test_the_picture_colours_each_band_by_the_region_already_judged_and_judges_nothing_again(tmp_path, monkeypatch):
    """One judgment, three outputs: the text, the JSON and the picture cannot disagree on a band's region, and the
    picture casts no second set of rays. A band judged a cavity is drawn red even where a judgment now would say
    otherwise (here, nothing is walled in: the tube is far from the contact)."""
    import pytest
    pv = pytest.importorskip("pyvista")
    from agentcad import cli
    f, p = _ledge_plate(tmp_path, (60.0, 60.0))         # the contact sits on nothing the rays can wall in
    bands = sp.find_contacts(gm.parse(TEXT), contact_distance=0.25)
    colours = []

    class Plotter:
        def __init__(self, *args, **kwargs):
            pass

        def add_points(self, cells, color=None, **kwargs):
            colours.append(color)

        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    def judged_again(*args, **kwargs):
        raise AssertionError("the picture judged a band again")
    monkeypatch.setattr(pv, "Plotter", Plotter)
    monkeypatch.setattr(sp, "band_enclosure", judged_again)
    regions = {id(b): (None, None, "cavity", {"cavity": 9}, None) for b in bands}
    cli._supports_png(tmp_path / "s.png", bands, sp.load_placement(p), {}, tmp_path, regions)
    assert bands and colours == ["red"] * len(bands), colours
    regions = {id(b): (None, None, "outside", {"outside": 9}, None) for b in bands}
    colours.clear()
    cli._supports_png(tmp_path / "s.png", bands, sp.load_placement(p), {}, tmp_path, regions)
    assert colours == ["seagreen"] * len(bands), colours
