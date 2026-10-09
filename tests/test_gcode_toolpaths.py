"""Packing toolpaths for a viewer: segments per layer and feature, and the layer stride under a budget."""
import base64

import numpy as np

from agentcad.gcode import model as gm, toolpaths as tp

TEXT = "M83\n" + "".join(f";LAYER_CHANGE\n;Z:{0.2 * (i + 1):.1f}\n;HEIGHT:0.2\n;TYPE:Perimeter\nG1 X0 Y0\nG1 X10 Y0 E1\n"
                         for i in range(10))


def test_segments_decode_to_the_moves_printed():
    out = tp.pack(gm.parse(TEXT))
    assert out["stride"] == 1 and len(out["layers"]) == 10
    seg = np.frombuffer(base64.b64decode(out["layers"][0]["features"]["Perimeter"]), dtype=np.float32)
    assert seg.tolist() == [0.0, 0.0, np.float32(0.2), 10.0, 0.0, np.float32(0.2)]


def test_over_budget_keeps_every_nth_layer_and_the_first_and_last():
    out = tp.pack(gm.parse(TEXT), budget_bytes=24 * 3)      # each layer is 24 bytes: 10 layers -> stride 4
    assert out["stride"] == 4
    assert [L["index"] for L in out["layers"]] == [0, 4, 8, 9]


def test_page_embeds_the_layers_and_says_when_layers_were_dropped(tmp_path):
    from agentcad.gcode import view
    p = view.write_page(gm.parse(TEXT), tmp_path / "t.html", title="ten layers")
    html = p.read_text()
    assert "<title>ten layers</title>" in html and '"stride": 1' in html and "every" not in html.split("<script>")[0]
    p = view.write_page(gm.parse(TEXT), tmp_path / "t2.html", budget_mb=72 / 1024 / 1024)
    assert "every 4th layer shown" in p.read_text()


def test_page_carries_contact_cells_when_given(tmp_path):
    from agentcad.gcode import view
    p = view.write_page(gm.parse(TEXT), tmp_path / "c.html", contacts=[(1.0, 2.0, 0.2, "cavity")])
    assert '"contacts": [[1.0, 2.0, 0.2, "cavity"]]' in p.read_text()


def test_page_embeds_a_placed_mesh(tmp_path):
    from agentcad.gcode import view
    tri = ([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)])
    html = view.write_page(gm.parse(TEXT), tmp_path / "m.html", meshes=[tri]).read_text()
    assert '"meshes": [{"p": "' in html
