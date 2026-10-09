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
