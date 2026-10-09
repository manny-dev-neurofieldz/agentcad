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
