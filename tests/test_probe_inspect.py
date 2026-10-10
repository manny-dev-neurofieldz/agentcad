"""INSPECT: what a part is made of, along lines and across planes.

Rays (material and void intervals along lines and fans, on a B-rep exactly and
on a mesh to its tessellation), mesh sections, the census that says when its
zeros mean nothing, the comparison detail, and the knob sweep. Every fixture is
synthetic: a block with a through bore whose intervals are known by arithmetic.
"""

import json
import math
from pathlib import Path

import pytest

from agentcad.engines import get_engine, list_engines

pytestmark = pytest.mark.skipif("build123d" not in list_engines() or not get_engine("build123d").available(),
                                reason="build123d backend not available")

# A 40 x 30 x 20 block (x in -20..20, y in -15..15, z in -10..10) with a through bore of
# diameter `bore` along Z at x=5, y=0: every interval below follows from those numbers.
BORE_BLOCK = (
    "from build123d import *\n"
    "\n"
    "def build(bore=10.0):\n"
    "    return Box(40, 30, 20) - Pos(5, 0, 0) * Cylinder(bore / 2, 30)\n"
)


@pytest.fixture(scope="module")
def bore_block(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("inspect") / "bore_block.py"
    path.write_text(BORE_BLOCK)
    return path


@pytest.fixture(scope="module")
def bore_stl(bore_block, tmp_path_factory) -> Path:
    from build123d import export_stl
    from agentcad import probe
    path = tmp_path_factory.mktemp("inspect_stl") / "bore_block.stl"
    export_stl(probe.load_shape(bore_block), str(path), tolerance=0.01, angular_tolerance=0.2)
    return path


@pytest.fixture(scope="module")
def spline_step(bore_block, tmp_path_factory) -> Path:
    """The block with every surface converted to BSpline, through a STEP file: the shape a
    mesh-to-solid or a spline export hands over, whose faces no longer say what they were."""
    from build123d import Solid, export_step
    from OCP.BRepBuilderAPI import BRepBuilderAPI_NurbsConvert
    from agentcad import probe
    converted = Solid(BRepBuilderAPI_NurbsConvert(probe.load_shape(bore_block).wrapped, True).Shape())
    path = tmp_path_factory.mktemp("inspect_spline") / "bore_block_spline.step"
    export_step(converted, str(path))
    return path


def _write_stl(path, tri):
    """A binary STL of (N, 3, 3) triangles (normals left zero: the readers here ignore them)."""
    import struct
    import numpy as np
    tri = np.asarray(tri, dtype=np.float32)
    with open(path, "wb") as fh:
        fh.write(b"\0" * 80 + struct.pack("<I", len(tri)))
        for t in tri:
            fh.write(struct.pack("<12fH", 0, 0, 0, *t.ravel(), 0))
    return path


# --- census honesty ---------------------------------------------------------------------------

def test_census_note_fires_at_ninety_percent_and_not_below():
    from agentcad.report import census_hides_analytic
    census = {"plane": 0, "cylinder": 0, "cone": 0, "sphere": 0, "torus": 0, "bspline": 9, "other": 1}
    note = census_hides_analytic(census)
    assert note and "9 of 10 faces (90%)" in note and "hides analytic types" in note
    assert "zero cylinders" in note
    assert census_hides_analytic(dict(census, bspline=8, plane=1)) is None      # 80%
    assert census_hides_analytic({"plane": 6, "cylinder": 1}) is None            # an analytic part
    assert census_hides_analytic({}) is None                                     # nothing counted, nothing said
    mixed = census_hides_analytic(dict(census, bspline=18, cylinder=2, other=0))
    assert mixed and "2 counted analytic face(s) are a lower bound" in mixed


def test_inventory_says_the_representation_hides_analytic_types(bore_block, spline_step):
    from agentcad import probe
    original = probe.inventory(probe.load_shape(bore_block))
    assert original["face_census"]["cylinder"] == 1 and original["census_notes"] == []
    converted = probe.inventory(probe.load_shape(spline_step))
    assert converted["face_census"]["bspline"] == converted["counts"]["faces"] == 7
    assert converted["cylinders"] == []                                           # the zero is not a finding
    assert len(converted["census_notes"]) == 1 and "hides analytic types" in converted["census_notes"][0]


def test_inventory_checks_each_solid_of_a_compound(bore_block, spline_step):
    """One analytic solid beside one BSpline solid: 7 of 14 faces overall, 7 of 7 in the second."""
    from build123d import Compound, Location
    from agentcad import probe
    pair = Compound(children=[probe.load_shape(bore_block),
                              probe.load_shape(spline_step).moved(Location((100, 0, 0)))])
    inv = probe.inventory(pair)
    assert inv["counts"]["solids"] == 2
    assert len(inv["census_notes"]) == 1 and inv["census_notes"][0].startswith("solid 2 of 2:")


def test_inventory_cli_prints_the_warning_beside_the_zero(spline_step, bore_block, capsys):
    from agentcad import cli
    cli.main(["probe", "inventory", str(spline_step)])
    out = capsys.readouterr().out
    assert "warning:" in out and "hides analytic types" in out
    assert "0 cylindrical/conical face(s) with axes:" not in out                # the bare zero is not printed
    cli.main(["probe", "inventory", str(bore_block)])
    out = capsys.readouterr().out
    assert "warning:" not in out and "1 cylindrical/conical face(s) with axes:" in out


def test_the_tray_reads_the_engines_own_census(bore_block, spline_step):
    """The metadata the build123d engine measures, not a hand-written one: the converted body warns, the original does not."""
    from agentcad import probe
    from agentcad.engines.build123d_worker import _bootstrap, _measure
    from agentcad.report import feature_effect, render_lines
    b3d = _bootstrap()
    original = feature_effect(None, _measure(b3d, probe.load_shape(bore_block)))
    converted = feature_effect(None, _measure(b3d, probe.load_shape(spline_step)))
    assert not any("BSpline" in w for w in original.warnings)
    assert any("7 of 7 faces (100%) are BSpline surfaces" in line for line in render_lines(converted))


def test_inventory_refuses_a_mesh_by_name(bore_stl, capsys):
    from agentcad import cli
    with pytest.raises(SystemExit) as exc:
        cli.main(["probe", "inventory", str(bore_stl)])
    assert exc.value.code == 1 and "probe section and probe rays also read an STL" in capsys.readouterr().err


def test_the_tray_warns_when_the_census_hides_analytic_types():
    from agentcad.report import feature_effect
    md = {"volume": 1.0, "counts": {"solids": 1, "faces": 20},
          "face_census": {"plane": 1, "cylinder": 0, "cone": 0, "sphere": 0, "torus": 0, "bspline": 19, "other": 0}}
    rep = feature_effect(None, md)
    assert any("19 of 20 faces (95%) are BSpline" in w for w in rep.warnings), rep.warnings
    md["face_census"] = {"plane": 14, "cylinder": 6, "bspline": 0}
    assert not any("BSpline" in w for w in feature_effect(None, md).warnings)


# --- rays -------------------------------------------------------------------------------------

def test_a_line_through_the_bore_is_exact_on_the_brep(bore_block):
    from agentcad import rays
    res = rays.probe_rays(bore_block, [rays.parse_line("-30,0,0:1,0,0")])
    assert res["kind"] == "brep" and res["schema"] == rays.SCHEMA
    line = res["lines"][0]
    assert line["range"] == pytest.approx([10.0, 50.0], abs=1e-6) and line["range_from"] == "bounding box"
    assert [i["kind"] for i in line["intervals"]] == ["material", "void", "material"]
    assert [i["length"] for i in line["intervals"]] == pytest.approx([20.0, 10.0, 10.0], abs=1e-3)
    assert [i["entry_point"][0] for i in line["intervals"]] == pytest.approx([-20.0, 0.0, 10.0], abs=1e-3)
    assert line["intervals"][1]["enclosed"] is True
    assert not any(i["clipped_start"] or i["clipped_end"] for i in line["intervals"])   # the part's surface ended each one
    assert line["material"] == pytest.approx(30.0, abs=1e-3) and line["enclosed_void"] == pytest.approx(10.0, abs=1e-3)


def test_lines_along_the_other_axes_read_the_walls(bore_block):
    from agentcad import rays
    res = rays.probe_rays(bore_block, [rays.parse_line("-10,0,-30:0,0,1"), rays.parse_line("5,-40,0:0,1,0")])
    wall, across = res["lines"]
    assert [(i["kind"], i["length"]) for i in wall["intervals"]] == [("material", pytest.approx(20.0, abs=1e-3))]
    assert [i["length"] for i in across["intervals"]] == pytest.approx([10.0, 10.0, 10.0], abs=1e-3)   # wall, bore, wall
    assert [i["kind"] for i in across["intervals"]] == ["material", "void", "material"]


def test_a_tangent_touch_does_not_open_a_gap(bore_block):
    """The line y=5 only touches the bore at x=5: the part is unbroken along it."""
    from agentcad import rays
    line = rays.probe_rays(bore_block, [rays.parse_line("-30,5,0:1,0,0")])["lines"][0]
    assert [(i["kind"], i["length"]) for i in line["intervals"]] == [("material", pytest.approx(40.0, abs=1e-3))]


def test_a_line_through_a_corner_vertex_is_one_run(bore_block):
    from agentcad import rays
    line = rays.probe_rays(bore_block, [rays.parse_line("-30,-25,-20:1,1,1")])["lines"][0]
    assert [i["kind"] for i in line["intervals"]] == ["material"]
    assert line["intervals"][0]["length"] == pytest.approx(20 * math.sqrt(3), abs=1e-3)


def test_a_fan_about_the_bore_axis_reads_the_wall_in_every_direction(bore_block):
    from agentcad import rays
    lines = rays.parse_fan("5,0,0:0,0,1:90", label="F1")
    assert [l["label"] for l in lines] == ["F1@0", "F1@90", "F1@180", "F1@270"]
    res = rays.probe_rays(bore_block, lines)
    by = {l["label"]: l for l in res["lines"]}
    for label, wall in (("F1@0", 10.0), ("F1@90", 10.0), ("F1@180", 20.0), ("F1@270", 10.0)):
        void, material = by[label]["intervals"]
        assert (void["kind"], material["kind"]) == ("void", "material")
        assert void["length"] == pytest.approx(5.0, abs=1e-3)                 # the bore's radius
        assert material["length"] == pytest.approx(wall, abs=1e-3)
        assert void["clipped_start"] and not void["enclosed"]                    # it began in the bore, not at a surface
    assert by["F1@90"]["fan"]["angle_deg"] == 90.0


def test_fan_angles_follow_the_right_hand_rule_and_can_be_partial():
    from agentcad import rays
    e1, e2 = rays.fan_basis([0, 0, 1])
    assert e1 == pytest.approx([1, 0, 0]) and e2 == pytest.approx([0, 1, 0])
    e1, e2 = rays.fan_basis([1, 0, 0])
    assert e1 == pytest.approx([0, 1, 0]) and e2 == pytest.approx([0, 0, 1])
    half = rays.parse_fan("0,0,0:0,0,1:45:0:90")
    assert [l["fan"]["angle_deg"] for l in half] == [0.0, 45.0, 90.0]
    assert half[1]["direction"] == pytest.approx([math.sqrt(0.5), math.sqrt(0.5), 0.0])
    assert len(rays.parse_fan("0,0,0:0,0,1:60")) == 6                       # a full turn does not repeat its first ray


def test_the_range_is_recorded_and_a_cut_interval_says_so(bore_block):
    from agentcad import rays
    short = rays.probe_rays(bore_block, [rays.parse_line("-30,0,0:1,0,0:15")])["lines"][0]
    assert short["range"] == [0.0, 15.0] and short["range_from"] == "length"
    assert [(i["kind"], round(i["length"], 3)) for i in short["intervals"]] == [("void", 10.0), ("material", 5.0)]
    assert short["intervals"][0]["clipped_start"] and short["intervals"][1]["clipped_end"]
    inside = rays.probe_rays(bore_block, [rays.parse_line("-10,0,0:1,0,0")])["lines"][0]   # starts inside the wall
    assert inside["intervals"][0]["clipped_start"] and inside["intervals"][0]["length"] == pytest.approx(10.0, abs=1e-3)
    miss = rays.probe_rays(bore_block, [rays.parse_line("-30,50,0:1,0,0"), rays.parse_line("30,0,0:1,0,0")])["lines"]
    assert all(m["intervals"] == [] and "misses" in m["note"] for m in miss)


def test_a_line_beyond_the_part_is_one_open_void_and_a_tiny_range_says_so(bore_block, bore_stl):
    from agentcad import rays
    for source in (bore_block, bore_stl):
        far, tiny = rays.probe_rays(source, [rays.parse_line("-30,50,0:1,0,0:100"), rays.parse_line("-30,0,0:1,0,0:1e-9")])["lines"]
        assert [(i["kind"], i["length"], i["clipped_start"], i["clipped_end"], i["enclosed"]) for i in far["intervals"]] \
            == [("void", 100.0, True, True, False)]
        assert tiny["intervals"] == [] and "shorter than the tolerance" in tiny["note"]


def test_a_malformed_line_or_fan_is_a_named_error():
    from agentcad import rays
    for bad in ("1,2:0,0,1", "1,2,3", "0,0,0:0,0,0", "0,0,0:1,0,0:-3", "0,0,0:1,0,0:x", "a,b,c:1,0,0"):
        with pytest.raises(ValueError, match="line spec"):
            rays.parse_line(bad)
    for bad in ("0,0,0:0,0,1", "0,0,0:0,0,1:0", "0,0,0:0,0,1:30:90:10", "0,0,0:0,0,1:x"):
        with pytest.raises(ValueError, match="fan spec|direction"):
            rays.parse_fan(bad)
    with pytest.raises(ValueError, match="build123d program, a STEP file or an STL"):
        rays.load_target(Path("part.scad"))


def test_a_shape_without_a_solid_has_no_inside(tmp_path):
    from agentcad import rays
    plate = tmp_path / "face.py"
    plate.write_text("from build123d import *\npart = Rectangle(10, 10).face()\n")
    with pytest.raises(ValueError, match="need a solid"):
        rays.load_target(plate)


def test_rays_read_a_step_file_and_a_spline_body_as_the_program_reads_them(bore_block, spline_step, tmp_path):
    """A STEP file is read as a program is, and a body whose every face is a BSpline (where the census cannot
    say what its faces were) still shows its bore to a fan of rays: constant radius, every direction."""
    from build123d import export_step
    from agentcad import probe, rays
    step = tmp_path / "bore_block.step"
    export_step(probe.load_shape(bore_block), str(step))
    fan = rays.parse_fan("5,0,0:0,0,1:45", label="F")
    exact = rays.probe_rays(bore_block, fan)
    for source in (step, spline_step):
        res = rays.probe_rays(source, fan)
        assert res["kind"] == "brep" and len(res["lines"]) == 8
        for a, b in zip(exact["lines"], res["lines"]):
            assert [i["kind"] for i in b["intervals"]] == ["void", "material"]
            assert [i["length"] for i in b["intervals"]] == pytest.approx([i["length"] for i in a["intervals"]], abs=0.01)
        assert {round(l["intervals"][0]["length"], 2) for l in res["lines"]} == {5.0}          # the bore's radius, all round


def test_the_stl_agrees_with_the_brep_within_the_tessellation(bore_block, bore_stl):
    """Lines through mesh vertices and along triangle edges (the bore's seam, the rectangle diagonals
    of the end faces at their centre) are where a careless crossing count double-counts, and lines
    lying in a face are on the boundary, which both readings count as material."""
    from agentcad import rays
    specs = ["-30,0,0:1,0,0", "-10,0,-30:0,0,1", "5,-40,0:0,1,0", "-30,5,0:1,0,0", "-30,-25,-20:1,1,1",
             "-30,-15,-10:1,0,0",     # along an edge of the block
             "-30,-8,10:1,0,0",       # in the top face
             "-30,0,10:1,0,0"]        # in the top face, across the mouth of the bore
    exact = rays.probe_rays(bore_block, [rays.parse_line(s) for s in specs])
    mesh = rays.probe_rays(bore_stl, [rays.parse_line(s) for s in specs])
    assert mesh["kind"] == "mesh" and mesh["winding"] == "outward" and mesh["triangles"] > 100
    for a, b in zip(exact["lines"], mesh["lines"]):
        assert [i["kind"] for i in a["intervals"]] == [i["kind"] for i in b["intervals"]], a["label"]
        assert [i["length"] for i in b["intervals"]] == pytest.approx([i["length"] for i in a["intervals"]], abs=0.02)
        assert not b["warnings"]


def test_a_fan_on_the_stl_matches_and_a_flipped_mesh_reads_the_same(bore_block, bore_stl, tmp_path):
    from agentcad import rays
    from agentcad.meshmeasure import read_stl
    V, _ = read_stl(bore_stl)
    flipped = _write_stl(tmp_path / "flipped.stl", V.reshape(-1, 3, 3)[:, ::-1, :])   # every triangle wound the other way
    fan = rays.parse_fan("5,0,0:0,0,1:45", label="F")
    a = rays.probe_rays(bore_stl, fan)
    b = rays.probe_rays(flipped, fan)
    assert b["winding"] == "inward"
    exact = rays.probe_rays(bore_block, fan)
    for ea, ma, mb in zip(exact["lines"], a["lines"], b["lines"]):
        assert [i["kind"] for i in ma["intervals"]] == [i["kind"] for i in ea["intervals"]] == [i["kind"] for i in mb["intervals"]]
        assert [i["length"] for i in ma["intervals"]] == pytest.approx([i["length"] for i in ea["intervals"]], abs=0.02)
        assert [i["length"] for i in mb["intervals"]] == pytest.approx([i["length"] for i in ma["intervals"]], abs=1e-6)


def test_an_open_mesh_warns_instead_of_guessing(bore_stl, tmp_path):
    """Remove the top face's triangles: a line down through the hole sees an odd number of crossings."""
    import numpy as np
    from agentcad import rays
    from agentcad.meshmeasure import read_stl
    V, _ = read_stl(bore_stl)
    tri = V.reshape(-1, 3, 3)
    keep = ~np.all(np.abs(tri[:, :, 2] - 10.0) < 1e-6, axis=1)               # drop every triangle lying on z=+10
    path = _write_stl(tmp_path / "open.stl", tri[keep])
    line = rays.probe_rays(path, [rays.parse_line("-10,0,30:0,0,-1")])["lines"][0]
    assert line["warnings"] and "not closed" in line["warnings"][0]


def test_rays_text_names_the_range_and_caps_what_it_prints(bore_block):
    from agentcad import rays
    res = rays.probe_rays(bore_block, [rays.parse_line("-30,0,0:1,0,0")])
    text = "\n".join(rays.render_rays(res))
    assert "L1: from (-30.000, 0.000, 0.000)" in text and "(bounding box)" in text
    assert "material" in text and "enclosed" in text and "material 30.0000 in 2 run(s)" in text
    miss = rays.probe_rays(bore_block, [rays.parse_line("-30,50,0:1,0,0")])
    assert "the line misses the part's bounding box" in "\n".join(rays.render_rays(miss))
    capped = "\n".join(rays.render_rays(res, show=1))
    assert "2 more interval(s) (cap --show 1; the JSON has all)" in capped


def test_probe_rays_through_the_cli(bore_block, tmp_path, capsys):
    from agentcad import cli
    out = tmp_path / "rays.json"
    cli.main(["probe", "rays", str(bore_block), "--line", "-30,0,0:1,0,0", "--fan", "5,0,0:0,0,1:90", "-o", str(out)])
    text = capsys.readouterr().out
    assert "L1: from" in text and "F1@0: from" in text and "F1@270: from" in text and f"rays.json: {out}" in text
    data = json.loads(out.read_text())
    assert data["schema"] == "agentcad.probe.rays/1" and [l["label"] for l in data["lines"]] == ["L1", "F1@0", "F1@90", "F1@180", "F1@270"]
    assert data["lines"][0]["intervals"][1]["length"] == pytest.approx(10.0, abs=1e-3)


def test_a_coordinate_list_may_begin_with_a_minus_sign_either_way(bore_block, cylinder_stl, capsys):
    """argparse reads a bare -30,0,0:1,0,0 as an option unless the parser says a leading minus is a number."""
    from agentcad import cli
    outs = []
    for argv in (["--line", "-30,0,0:1,0,0"], ["--line=-30,0,0:1,0,0"]):
        cli.main(["probe", "rays", str(bore_block)] + argv)
        outs.append(capsys.readouterr().out)
    assert outs[0] == outs[1] and "L1: from (-30.000, 0.000, 0.000)" in outs[0]
    cli.main(["probe", "rays", str(bore_block), "--fan", "-5,0,0:0,0,1:180"])
    assert "F1@0: from (-5.000, 0.000, 0.000)" in capsys.readouterr().out
    cli.main(["probe", "section", str(cylinder_stl), "--axis-center", "-5,0"])
    assert "through (-5, 0)" in capsys.readouterr().out
    cli.main(["probe", "rays", str(bore_block), "--line", "-30,0,0:1,0,0", "--show", "1"])         # an option after it still parses
    assert "more interval(s)" in capsys.readouterr().out


def test_probe_rays_reads_a_parameter_override_and_an_stl(bore_block, bore_stl, capsys):
    from agentcad import cli
    cli.main(["probe", "rays", str(bore_block), "--line=-30,0,0:1,0,0", "-D", "bore=4"])
    assert "void     t   33.0000 ->   37.0000  length    4.0000" in capsys.readouterr().out      # the bore is 4 wide
    cli.main(["probe", "rays", str(bore_stl), "--line=-30,0,0:1,0,0", "-D", "bore=4"])
    out = capsys.readouterr().out
    assert "mesh" in out and "-D ['bore'] ignored: a mesh has no parameters" in out


def test_probe_rays_names_what_is_missing_or_wrong(bore_block, tmp_path, capsys):
    from agentcad import cli
    for argv, code, words in ((["probe", "rays", str(bore_block)], 2, "at least one --line or --fan"),
                              (["probe", "rays", str(bore_block), "--line", "1,2:3"], 2, "line spec"),
                              (["probe", "rays", str(bore_block), "--fan", "0,0,0:0,0,1:0"], 2, "fan spec"),
                              (["probe", "rays", str(tmp_path / "part.scad"), "--line", "0,0,0:1,0,0"], 1, "STL mesh")):
        with pytest.raises(SystemExit) as exc:
            cli.main(argv)
        assert exc.value.code == code
        assert words in capsys.readouterr().err


def test_an_empty_mesh_and_a_zero_direction_are_named_errors(tmp_path):
    import numpy as np
    from agentcad import meshprobe
    empty = _write_stl(tmp_path / "empty.stl", np.empty((0, 3, 3)))
    with pytest.raises(ValueError, match="no triangles"):
        meshprobe.load_mesh(empty)
    with pytest.raises(ValueError, match="direction"):
        meshprobe.basis([0, 0, 0])


# --- sections of a mesh -----------------------------------------------------------------------

@pytest.fixture(scope="module")
def cylinder_stl(tmp_path_factory) -> Path:
    """A cylinder of radius 5 and height 20 on the origin, z from -10 to 10, meshed."""
    from build123d import Cylinder, export_stl
    path = tmp_path_factory.mktemp("inspect_cyl") / "cylinder.stl"
    export_stl(Cylinder(5, 20), str(path), tolerance=0.01, angular_tolerance=0.2)
    return path


def test_a_meshed_cylinder_section_is_one_polylined_circle(cylinder_stl):
    from agentcad import meshprobe, probe
    mesh = meshprobe.load_mesh(cylinder_stl)
    rec = probe.mesh_section_plane(mesh, "z=mid")
    assert rec["plane"] == "z=mid" and rec["coordinate"] == pytest.approx(0.0, abs=1e-6) and rec["n_loops"] == 1
    loop = rec["loops"][0]
    assert loop["closed"] and loop["n_edges"] >= 12 and {e["type"] for e in loop["edges"]} == {"line"}
    assert loop["total_on_plane"] == 1 and loop["length"] == pytest.approx(2 * math.pi * 5.0, rel=5e-3)
    assert loop["fit"]["radius"] == pytest.approx(5.0, abs=0.01) and loop["fit"]["rms"] < 0.01    # the polyline reads as a circle
    ex = loop["extents"]
    assert ex["axis"] == "z" and ex["center"] == pytest.approx([0.0, 0.0], abs=0.01)    # the middle of the bounding box, a sagitta off
    assert ex["radial"] == pytest.approx([5.0, 5.0], abs=0.01) and ex["axial"] == pytest.approx([0.0, 0.0], abs=1e-6)
    assert rec["extents"]["radial"] == ex["radial"]


def test_a_mesh_section_through_the_axis_reads_the_profile(cylinder_stl):
    """The plane y=0 contains the cylinder's axis: a rectangle, 10 wide and 20 tall, whose radial extent runs
    from the axis to the wall and whose axial extent is the height. Flat faces cut by many triangles give
    one straight edge each, not a segment per triangle."""
    from agentcad import meshprobe, probe
    mesh = meshprobe.load_mesh(cylinder_stl)
    rec = probe.mesh_section_plane(mesh, "y=0", axis="z")
    loop = rec["loops"][0]
    assert rec["n_loops"] == 1 and loop["closed"] and loop["n_edges"] == 4
    assert sorted(round(e["length"], 3) for e in loop["edges"]) == pytest.approx([10.0, 10.0, 20.0, 20.0], abs=0.02)
    assert loop["fit"] is None                                                   # four edges are not a polylined arc
    assert loop["extents"]["radial"] == pytest.approx([0.0, 5.0], abs=0.01)
    assert loop["extents"]["axial"] == pytest.approx([-10.0, 10.0], abs=1e-6)
    assert probe.mesh_section_plane(mesh, "z=50")["n_loops"] == 0                # a plane past the mesh cuts nothing


def test_a_plane_in_the_lowest_and_highest_face_gives_that_face_s_outline(cylinder_stl):
    """A part standing on z=0 and cut at z=0 is cut in its bottom face; the exact kernel gives the outline
    there, and so does the mesh, at either end."""
    from agentcad import meshprobe, probe
    mesh = meshprobe.load_mesh(cylinder_stl)
    for spec in ("z=-10", "z=10"):
        rec = probe.mesh_section_plane(mesh, spec)
        assert rec["n_loops"] == 1 and rec["loops"][0]["closed"], spec
        assert rec["loops"][0]["fit"]["radius"] == pytest.approx(5.0, abs=0.01), spec


def test_mesh_loops_carry_the_keys_of_exact_loops(bore_block, cylinder_stl):
    from agentcad import meshprobe, probe
    exact_plane, _ = probe.parse_plane("z=mid", probe.load_shape(bore_block))
    exact = probe.section_loops(probe.load_shape(bore_block), exact_plane)[0]
    mesh = probe.mesh_section_plane(meshprobe.load_mesh(cylinder_stl), "z=mid")["loops"][0]
    assert set(exact) - {"total_on_plane"} <= set(mesh) and set(exact["edges"][0]) == set(mesh["edges"][0])


def test_the_axis_defaults_to_the_middle_of_the_mesh_and_can_be_named(tmp_path):
    from build123d import Cylinder, Pos, export_stl
    from agentcad import meshprobe, probe
    off = tmp_path / "off.stl"
    export_stl(Pos(30, 0, 0) * Cylinder(5, 20), str(off), tolerance=0.01, angular_tolerance=0.2)
    mesh = meshprobe.load_mesh(off)
    own = probe.mesh_section_plane(mesh, "z=mid")["loops"][0]["extents"]
    assert own["center"] == pytest.approx([30.0, 0.0], abs=0.01) and own["radial"] == pytest.approx([5.0, 5.0], abs=0.02)
    origin = probe.mesh_section_plane(mesh, "z=mid", center=[0.0, 0.0])["loops"][0]["extents"]
    assert origin["radial"] == pytest.approx([25.0, 35.0], abs=0.02)


def test_a_mesh_with_a_hole_gives_open_chains_and_the_cap_is_printed(cylinder_stl, bore_stl, tmp_path, capsys):
    import numpy as np
    from agentcad import meshprobe, probe
    from agentcad.meshmeasure import read_stl
    V, _ = read_stl(cylinder_stl)
    tri = V.reshape(-1, 3, 3)
    keep = ~np.all(np.abs(tri[:, :, 2] - 10.0) < 1e-6, axis=1)                  # no top cap
    open_mesh = meshprobe.load_mesh(_write_stl(tmp_path / "open_cyl.stl", tri[keep]))
    chain = probe.mesh_section_plane(open_mesh, "y=0", axis="z")["loops"][0]
    assert chain["closed"] is False and chain["n_edges"] == 3                    # bottom and two walls: a U
    plate = meshprobe.load_mesh(bore_stl)
    capped = probe.mesh_section_plane(plate, "z=mid", max_loops=1)
    assert len(capped["loops"]) == 1 and capped["loops"][0]["total_on_plane"] == 2 and capped["n_loops"] == 2
    assert "cap max_loops=1 applied: 2 loops" in capsys.readouterr().err


def test_probe_section_of_a_program_prints_what_it_always_did(bore_block, tmp_path, capsys):
    """The exact path is unchanged: the same lines, and a record that is not a mesh record."""
    from agentcad import cli
    out = tmp_path / "loops.json"
    cli.main(["probe", "section", str(bore_block), "--planes", "z=mid", "y=0", "-o", str(out)])
    lines = capsys.readouterr().out.splitlines()
    assert lines[:6] == ["z=mid (at 0): 2 loop(s)", "  loop 1: length 140, 4 line", "  loop 2: length 31.42, 1 circle",
                         "y=0 (at 0): 2 loop(s)", "  loop 1: length 80, 4 line", "  loop 2: length 60, 4 line"]
    data = json.loads(out.read_text())
    assert set(data) == {"source", "planes"} and "extents" not in data["planes"][0]["loops"][0]


def test_probe_section_takes_an_stl_through_the_cli(cylinder_stl, tmp_path, capsys):
    from agentcad import cli
    out = tmp_path / "loops.json"
    cli.main(["probe", "section", str(cylinder_stl), "--planes", "z=mid", "y=0", "--axis", "z", "--axis-center", "0,0",
              "-o", str(out)])
    text = capsys.readouterr().out
    assert "mesh" in text and "tessellation" in text
    assert "z=mid (at 0): 1 loop(s)" in text and "fits a circle r 5" in text
    assert "extents about axis z through (0, 0): radial 0 .. 5" in text and "axial -10 .. 10" in text
    data = json.loads(out.read_text())
    assert data["kind"] == "mesh" and [p["plane"] for p in data["planes"]] == ["z=mid", "y=0"]
    assert data["planes"][1]["loops"][0]["n_edges"] == 4
    cli.main(["probe", "section", str(cylinder_stl), "--axis-center", "10,0", "-D", "x=1"])
    captured = capsys.readouterr()
    assert "radial 5 .. 15" in captured.out and "ignored: a mesh has no parameters" in captured.err
    for bad in ("10", "a,b"):
        with pytest.raises(SystemExit) as exc:
            cli.main(["probe", "section", str(cylinder_stl), "--axis-center", bad])
        assert exc.value.code == 2 and "--axis-center" in capsys.readouterr().err


def test_plane_specs_name_what_is_wrong_and_degenerate_polylines_survive():
    import numpy as np
    from agentcad import meshprobe, probe
    assert probe.plane_spec("z=mid", (1.0, 2.0, 3.0)) == ("z", 3.0) and probe.plane_spec("X=-4") == ("x", -4.0)
    with pytest.raises(ValueError, match="expected x=|y=|z="):
        probe.plane_spec("q=3")
    with pytest.raises(ValueError, match="'mid' needs a shape"):
        probe.plane_spec("z=mid")
    back_and_forth = np.array([[0.0, 0, 0], [1.0, 0, 0], [0.0, 0, 0]])           # a chain that returns on itself
    assert [(a.tolist(), b.tolist()) for a, b in meshprobe._runs(back_and_forth, 1e-6)] \
        == [([0, 0, 0], [1, 0, 0]), ([1, 0, 0], [0, 0, 0])]


# --- compare detail ---------------------------------------------------------------------------

# A 40 x 20 x 6 plate with two holes (x=-10 and x=+10) that can be shifted: dz moves the whole plate, dx only the left hole.
SHIFTED_PLATE = (
    "from build123d import *\n"
    "\n"
    "def build(dx=0.0, dz=0.0, d=6.0):\n"
    "    plate = Box(40, 20, 6) - Pos(-10 + dx, 0, 0) * Cylinder(d / 2, 10) - Pos(10, 0, 0) * Cylinder(d / 2, 10)\n"
    "    return Pos(0, 0, dz) * plate\n"
)


@pytest.fixture(scope="module")
def shifted_plate(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("inspect_cmp") / "plate.py"
    path.write_text(SHIFTED_PLATE)
    return path


def test_the_deviation_of_a_known_offset_reads_as_that_offset(shifted_plate):
    """The whole plate 0.5 higher: every sampled point is 0.5 from its twin, so p50, rms and max are all 0.5."""
    from agentcad import probe
    res = probe.compare(shifted_plate, shifted_plate, defines={"dz": "0.5"})
    for way in ("candidate_to_original", "original_to_candidate"):
        dev = res["deviation"][way]
        assert dev["p50"] == pytest.approx(0.5, abs=1e-6) and dev["max"] == pytest.approx(0.5, abs=1e-6)
        assert dev["rms"] == pytest.approx(0.5, abs=1e-6)
        assert {"p50", "p95", "max", "n"} <= set(dev)                              # the existing fields stay


def test_rms_agrees_with_an_independent_nearest_neighbour_computation(shifted_plate):
    from scipy.spatial import cKDTree
    from agentcad import probe
    a = probe.sample_points(shifted_plate)["points"]
    b = probe.sample_points(shifted_plate, defines={"dx": "2.0"})["points"]
    d = cKDTree(a).query(b)[0]
    dev = probe.compare(shifted_plate, shifted_plate, defines={"dx": "2.0"})["deviation"]["candidate_to_original"]
    assert dev["rms"] == pytest.approx(math.sqrt(float((d ** 2).mean())), rel=1e-9)


def test_the_worst_five_percent_lie_where_the_hole_moved(shifted_plate):
    from agentcad import probe
    res = probe.compare(shifted_plate, shifted_plate, defines={"dx": "2.0"})
    for way in ("candidate_to_original", "original_to_candidate"):
        dev = res["deviation"][way]
        worst = dev["worst5"]
        assert worst["fraction"] == 0.05 and worst["n"] >= 1          # 5% of the points, plus any tied with the last
        assert worst["threshold"] <= dev["max"] and worst["threshold"] > 0
        assert worst["bbox_max"][0] < -3.0 and worst["bbox_min"][0] > -15.0          # the left hole's side of the plate
        assert -4.0 < worst["bbox_min"][1] and worst["bbox_max"][1] < 4.0
        assert worst["clusters"] and worst["n_clusters"] >= len(worst["clusters"])
        assert worst["clusters"][0]["max"] == pytest.approx(dev["max"])                # sorted by worst distance
        assert all(c["center"][0] < -3.0 for c in worst["clusters"])
        assert sum(c["n"] for c in worst["clusters"]) <= worst["n"] and worst["cell"] > 0
        assert "cells" in worst["method"]                                               # the clustering rule is stated


def test_identical_parts_have_no_worst_region(shifted_plate):
    from agentcad import probe
    dev = probe.compare(shifted_plate, shifted_plate)["deviation"]["candidate_to_original"]
    assert dev["rms"] == pytest.approx(0.0, abs=1e-12)
    assert dev["worst5"]["n"] == 0 and "no deviation above zero" in dev["worst5"]["note"]


def test_each_window_gets_a_zoomed_overlay(shifted_plate, tmp_path, monkeypatch):
    import matplotlib.figure as mf
    from agentcad import probe
    limits = []
    real = mf.Figure.savefig

    def spy(self, *args, **kwargs):
        limits.append((tuple(self.axes[0].get_xlim()), tuple(self.axes[0].get_ylim())))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(mf.Figure, "savefig", spy)
    res = probe.compare(shifted_plate, shifted_plate, planes=["z=mid"], defines={"dx": "2.0"},
                        windows={"hole": (-14.0, -4.0, -4.0, 4.0), "far corner": (15.0, 5.0, 20.0, 10.0)},
                        out_dir=tmp_path / "cmp")
    entry = res["planes"][0]
    assert Path(entry["overlay"]).name == "overlay_z_mid.png"                               # the whole-section image stays
    hole, corner = entry["windows"]["hole"], entry["windows"]["far corner"]
    assert Path(hole["overlay"]).name == "overlay_z_mid_hole.png" and Path(hole["overlay"]).stat().st_size > 1000
    assert Path(corner["overlay"]).name == "overlay_z_mid_far_corner.png"
    import matplotlib.image as mpimg
    pixels = mpimg.imread(hole["overlay"])[..., :3] * 255                                    # the candidate's circle is drawn in the window
    red = ((pixels[..., 0] > 200) & (pixels[..., 1] < 120) & (pixels[..., 2] < 140)).sum()
    assert red > 400, f"the zoomed window shows {red} candidate-coloured pixels: it is blank"
    assert {"p95", "max", "n_original", "n_candidate"} <= set(hole)                         # the existing fields stay
    assert ((-14.0, -4.0), (-4.0, 4.0)) in limits and ((15.0, 20.0), (5.0, 10.0)) in limits   # zoomed to the window
    assert len(limits) == 3
    quiet = probe.compare(shifted_plate, shifted_plate, planes=["z=mid"], windows={"hole": (-14.0, -4.0, -4.0, 4.0)})
    assert "overlay" not in quiet["planes"][0]["windows"]["hole"]                            # no directory, no images


def test_compare_prints_the_detail_and_writes_it(shifted_plate, tmp_path, capsys):
    from agentcad import cli
    out = tmp_path / "cmp"
    cli.main(["compare", str(shifted_plate), str(shifted_plate), "--planes", "z=mid", "--window", "hole=-14,-4,-4,4",
              "-D", "dx=2.0", "-o", str(out)])
    text = capsys.readouterr().out
    assert "deviation candidate->original p95" in text                                       # the existing line, unchanged
    assert "candidate->original: rms " in text and "worst 5%" in text and "bbox (" in text and "cluster" in text
    assert "window hole: p95" in text and "overlay_z_mid_hole.png" in text
    data = json.loads((out / "compare.json").read_text())
    assert data["deviation"]["candidate_to_original"]["worst5"]["clusters"]
    assert data["planes"][0]["windows"]["hole"]["overlay"].endswith("overlay_z_mid_hole.png")
    cli.main(["compare", str(shifted_plate), str(shifted_plate), "--planes", "z=mid", "--window", "hole=-14,-4,-4,4"])
    assert "window images are written only with -o" in capsys.readouterr().err


def test_overlays_draw_whole_circles_and_the_right_half_of_a_half_circle(tmp_path):
    """The curve points behind the overlays and the window distances: a full circle whose start sits a hair
    below its end must still be drawn round, and an arc must run the way the part is, whichever way its edge points."""
    from agentcad import probe
    program = tmp_path / "shapes.py"
    program.write_text(
        "from build123d import *\n"
        "\n"
        "def build(kind='ring'):\n"
        "    if kind == 'ring':\n"
        "        return Box(20, 20, 4) - Cylinder(3, 10)\n"
        "    if kind == 'half':\n"
        "        return Cylinder(5, 4) & (Pos(2.5, 0, 0) * Box(5, 10, 4))\n"
        "    return Cylinder(5, 4) & (Pos(2.5, 2.5, 0) * Box(5, 5, 4))\n")

    def section(kind):
        shape = probe.load_shape(program, {"kind": kind})
        plane, _ = probe.parse_plane("z=mid", shape)
        return probe.section_loops(shape, plane)

    def arc_points(kind):
        return [p for L in section(kind) for e in L["edges"] if e["type"] == "circle"
                for p in probe._loop_points_2d([{"edges": [e]}], "z=mid", 40)]

    hole = [L for L in section("ring") if all(e["type"] == "circle" for e in L["edges"])]
    pts = probe._loop_points_2d(hole, "z=mid", 60)
    assert len(pts) == 61 and all(abs(math.hypot(x, y) - 3.0) < 1e-9 for x, y in pts)
    assert min(x for x, _ in pts) < -2.99 and max(x for x, _ in pts) > 2.99 and min(y for _, y in pts) < -2.99     # all the way round
    half = arc_points("half")
    assert half and all(x > -1e-6 and abs(math.hypot(x, y) - 5.0) < 1e-6 for x, y in half)                          # the side with the part
    quarter = arc_points("quarter")
    assert quarter and all(x > -1e-6 and y > -1e-6 for x, y in quarter)
    root = math.sqrt(12.5)
    for start, end in (([5, 0, 0], [0, 5, 0]), ([0, 5, 0], [5, 0, 0])):                  # the same quarter arc, run either way
        arc = {"type": "circle", "start": start, "end": end, "center": [0, 0, 0], "radius": 5.0, "sweep_deg": 90.0,
               "midpoint": [root, root, 0]}
        run = probe._loop_points_2d([{"edges": [arc]}], "z=mid", 8)
        assert run[0] == pytest.approx(tuple(start[:2])) and run[-1] == pytest.approx(tuple(end[:2]), abs=1e-9)
        assert run[4] == pytest.approx((root, root), abs=1e-9) and all(x > -1e-9 and y > -1e-9 for x, y in run)   # through the midpoint
    old = {"type": "circle", "start": [5, 0, 0], "end": [0, 5, 0], "center": [0, 0, 0], "radius": 5.0, "sweep_deg": 90.0}   # no midpoint recorded
    legacy = probe._loop_points_2d([{"edges": [old]}], "z=mid", 8)
    assert legacy[0] == pytest.approx((5.0, 0.0)) and legacy[-1] == pytest.approx((0.0, 5.0), abs=1e-9) and legacy[4][0] > 0


# --- knobs ------------------------------------------------------------------------------------

# width and height reach the geometry; label is accepted and never used; lip is clamped to 4, so raising it does nothing.
KNOB_PART = (
    "from build123d import *\n"
    "\n"
    "def build(width=20.0, height=10.0, label=5.0, lip=4.0, count=3):\n"
    "    lip = min(lip, 4.0)\n"
    "    part = Box(width, 20, height)\n"
    "    return part + Pos(0, 0, height / 2 + lip / 2) * Box(width, 4, lip)\n"
)


@pytest.fixture(scope="module")
def knob_part(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("inspect_knobs") / "knob_part.py"
    path.write_text(KNOB_PART)
    return path


def test_a_sweep_flags_the_dead_and_the_saturated_knob(knob_part):
    from agentcad import knobs
    res = knobs.knob_sweep(knob_part, ["width=2", "height=1", "label=1", "lip=1"])
    assert res["schema"] == knobs.SCHEMA and res["runs"] == 9                        # one base and two per knob
    by = {k["name"]: k for k in res["knobs"]}
    assert res["base"]["volume"] == pytest.approx(20 * 20 * 10 + 20 * 4 * 4) and res["base"]["solids"] == 1
    assert by["width"]["verdict"] == "live" and by["height"]["verdict"] == "live"
    assert by["label"]["verdict"] == "dead"
    assert by["label"]["plus"]["status"] == by["label"]["minus"]["status"] == "unchanged"
    assert by["lip"]["verdict"] == "saturated" and by["lip"]["saturated"] == "plus"     # raising it does nothing
    assert by["lip"]["plus"]["status"] == "unchanged" and by["lip"]["minus"]["status"] == "changed"
    # the arithmetic of the live knob: widening by 2 adds 2 * (20 * 10 + 4 * 4) of volume and 2 to the x size
    assert by["width"]["plus"]["volume"] == pytest.approx(2 * (20 * 10 + 4 * 4)) and by["width"]["minus"]["volume"] == pytest.approx(-2 * 216)
    assert by["width"]["plus"]["bbox_size"] == pytest.approx([2.0, 0.0, 0.0]) and by["width"]["plus"]["solids"] == 0
    assert by["width"]["plus"]["volume_pct"] == pytest.approx(100.0 * 432 / 4320)


def test_a_sweep_is_bounded_and_reads_overrides_and_percentages(knob_part):
    from agentcad import knobs
    res = knobs.knob_sweep(knob_part, ["width=10%", "count=2"], defines={"width": "30"})
    assert res["runs"] == 5 and res["defines"] == {"width": "30"}
    width, count = res["knobs"]
    assert width["base"] == 30.0 and width["delta"] == pytest.approx(3.0) and width["relative"] and width["percent"] == 10.0
    assert (width["plus"]["value"], width["minus"]["value"]) == (33.0, 27.0)
    assert count["verdict"] == "dead" and isinstance(count["base"], int) and (count["plus"]["value"], count["minus"]["value"]) == (5, 1)


def test_a_side_that_does_not_build_is_named_not_hidden(tmp_path):
    from agentcad import knobs
    program = tmp_path / "limit.py"
    program.write_text("from build123d import *\n\ndef build(r=5.0):\n    if r <= 0:\n        raise ValueError('radius must be positive')\n"
                       "    return Cylinder(r, 10)\n")
    res = knobs.knob_sweep(program, ["r=5"])                                   # minus 5 is a radius of 0
    cut = res["knobs"][0]
    assert cut["verdict"] == "partial" and cut["minus"]["status"] == "refused" and "radius must be positive" in cut["minus"]["error"]
    assert cut["plus"]["status"] == "changed" and knobs.knob_sweep(program, ["r=1"])["knobs"][0]["verdict"] == "live"
    both = tmp_path / "both.py"
    both.write_text("from build123d import *\n\ndef build(r=5.0):\n    if r != 5.0:\n        raise RuntimeError('only the base builds')\n"
                    "    return Cylinder(r, 10)\n")
    assert knobs.knob_sweep(both, ["r=1"])["knobs"][0]["verdict"] == "refused"
    assert any("REFUSED" in line for line in knobs.render_knobs(res))


def test_a_sweep_names_what_it_cannot_run(knob_part, tmp_path):
    from agentcad import knobs
    for knob_args, words in ((["nope=1"], "no parameter 'nope'"), (["width"], "knob spec"), (["width=0"], "above 0"), (["=3"], "knob spec"),
                             (["width=x"], "not a number"), ([], "at least one"), (["width=1", "width=2"], "given twice"),
                             (["count=0.5"], "whole number")):
        with pytest.raises(ValueError, match=words):
            knobs.knob_sweep(knob_part, knob_args)
    flag = tmp_path / "flag.py"
    flag.write_text("from build123d import *\n\ndef build(label='x', on=True, n=0, **extra):\n    return Box(5, 5, 5)\n")
    for knob_args, defines, words in ((["label=1"], None, "not a number"), (["on=1"], None, "bool"), (["n=10%"], None, "is 0"),
                                      (["size=1"], None, "give -D size=VALUE")):
        with pytest.raises(ValueError, match=words):
            knobs.knob_sweep(flag, knob_args, defines)
    with pytest.raises(ValueError, match="build123d program"):
        knobs.knob_sweep(tmp_path / "part.step", ["a=1"])
    plain = tmp_path / "plain.py"
    plain.write_text("from build123d import *\npart = Box(5, 5, 5)\n")
    with pytest.raises(ValueError, match="knobs need a parametric build"):
        knobs.knob_sweep(plain, ["a=1"])
    broken = tmp_path / "broken.py"
    broken.write_text("from build123d import *\n\ndef build(a=1.0):\n    raise RuntimeError('does not build')\n")
    with pytest.raises(RuntimeError, match="the base run does not build: RuntimeError: does not build"):
        knobs.knob_sweep(broken, ["a=1"])
    quiet = tmp_path / "quiet.py"
    quiet.write_text("from build123d import *\n\ndef build(a=1.0):\n    raise RuntimeError()\n")
    assert knobs._build(quiet, {})["error"] == "RuntimeError"


def test_probe_knobs_through_the_cli(knob_part, tmp_path, capsys):
    from agentcad import cli
    out = tmp_path / "knobs.json"
    cli.main(["probe", "knobs", str(knob_part), "--knob", "width=2", "--knob", "label=1", "--knob", "lip=1", "-o", str(out)])
    text = capsys.readouterr().out
    assert "7 builds (1 base + 2 per knob)" in text and "knob width: base 20, delta 2" in text
    assert "live: both sides change the part" in text
    assert "DEAD: no change in volume, area, bounding box or solid count either way" in text
    assert "SATURATED: increasing it changes nothing, decreasing it does" in text
    data = json.loads(out.read_text())
    assert [k["verdict"] for k in data["knobs"]] == ["live", "dead", "saturated"]
    cli.main(["probe", "knobs", str(knob_part), "--knob", "width=10%", "-D", "width=30"])
    assert "(10% of the base)" in capsys.readouterr().out
    for argv, code, words in ((["probe", "knobs", str(knob_part)], 2, "at least one --knob"),
                              (["probe", "knobs", str(knob_part), "--knob", "nope=1"], 2, "no parameter 'nope'")):
        with pytest.raises(SystemExit) as exc:
            cli.main(argv)
        assert exc.value.code == code and words in capsys.readouterr().err
    broken = tmp_path / "broken.py"
    broken.write_text("from build123d import *\n\ndef build(a=1.0):\n    raise RuntimeError('does not build')\n")
    with pytest.raises(SystemExit) as exc:
        cli.main(["probe", "knobs", str(broken), "--knob", "a=1"])
    assert exc.value.code == 1 and "the base run does not build" in capsys.readouterr().err


def test_equal_deviations_are_never_split_by_sort_order():
    """Three holes that each moved 0.2 are three clusters, even when 5% of the points is fewer than
    the points at 0.2 (the cut once fell inside the tie and dropped a hole)."""
    import numpy as np
    from agentcad.probe import worst_region
    rng = np.random.default_rng(1)
    flat = rng.uniform([-30, -10, -3], [30, 10, 3], size=(900, 3))
    holes = np.concatenate([np.c_[np.full(40, x), rng.uniform(-2, 2, 40), rng.uniform(-3, 3, 40)] for x in (-15, 0, 15)])
    P = np.concatenate([flat, holes])
    d = np.concatenate([np.zeros(len(flat)), np.full(len(holes), 0.2)])
    w = worst_region(P, d)
    assert w["n"] == 120 and w["n_clusters"] == 3          # 5% of 1020 is 51: the tie brings in all 120
    assert sorted(round(c["center"][0]) for c in w["clusters"]) == [-15, 0, 15]
