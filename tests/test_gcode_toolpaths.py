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


def test_page_script_runs_in_node_with_contacts_and_a_mesh(tmp_path):
    import json, re, shutil, subprocess
    from pathlib import Path
    node = shutil.which("node")
    assert node, "node is needed to run the page's script"
    pts = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0]], float)
    page = tp_page(tmp_path, contacts=[(1, 1, 0.2, "outside"), (2, 2, 0.4, "cavity")], meshes=[(pts, [[0, 1, 2]])])
    for i, s in enumerate(re.findall(r"<script>(.*?)</script>", page.read_text(), re.S)):
        (tmp_path / f"page_script_{i}.js").write_text(s)
    harness = Path(__file__).parent / "js" / "run_page.js"
    r = subprocess.run([node, str(harness), str(tmp_path), "9"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    # 10 layers of one feature, one mesh, one point cloud per contact kind
    assert out["renders"] >= 1 and out["objects"] == 10 + 1 + 2
    assert out["legend"] == 1 and out["zr"] == "z 0.2-2 mm"


def tp_page(tmp_path, **kw):
    from agentcad.gcode import view
    return view.write_page(gm.parse(TEXT), tmp_path / "p.html", **kw)
