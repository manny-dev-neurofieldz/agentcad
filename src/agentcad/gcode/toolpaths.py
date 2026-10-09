"""Toolpaths packed for a viewer: line segments per layer and feature, within a byte budget.

Each layer becomes, per feature, a flat float32 array of segment endpoints (x0, y0, z, x1, y1, z, ...),
base64-encoded for embedding in a page. When the whole print exceeds the budget, every Nth layer is kept
(N reported, so the page can say so); the first and last layers are always kept.
"""

import base64
from typing import Dict, List

from agentcad.gcode.model import GCodeModel


def pack(model: GCodeModel, budget_bytes: int = 8 * 1024 * 1024) -> Dict:
    """{"stride": N, "layers": [{"index", "z", "features": {name: base64 float32}}], "bytes": total}."""
    import numpy as np

    per_layer: Dict[int, Dict[str, List[float]]] = {}
    for p in model.paths:
        if p.layer < 0 or len(p.points) < 2:
            continue
        seg = per_layer.setdefault(p.layer, {}).setdefault(p.feature, [])
        for (x0, y0), (x1, y1) in zip(p.points, p.points[1:]):
            seg += [x0, y0, p.z, x1, y1, p.z]
    total = sum(len(v) * 4 for f in per_layer.values() for v in f.values())
    stride = max(1, -(-total // budget_bytes)) if budget_bytes > 0 else 1
    keys = sorted(per_layer)
    keep = [k for i, k in enumerate(keys) if i % stride == 0 or k in (keys[0], keys[-1])] if keys else []
    layers, used = [], 0
    for k in keep:
        feats = {}
        for name, vals in per_layer[k].items():
            raw = np.asarray(vals, dtype=np.float32).tobytes()
            used += len(raw)
            feats[name] = base64.b64encode(raw).decode("ascii")
        layers.append({"index": k, "z": model.layers[k].z, "features": feats})
    return {"stride": stride, "layers": layers, "bytes": used}
