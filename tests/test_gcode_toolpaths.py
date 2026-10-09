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
