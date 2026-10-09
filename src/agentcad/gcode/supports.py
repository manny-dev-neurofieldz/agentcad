"""Where supports touch the part: contact found from the toolpaths themselves.

The feature type is not enough: organic supports under a sloped surface end in tips with no
"Support material interface" paths at all (measured on a real MK4 file), so a contact is any support
extrusion at layer L that lies under the object's own extrusion at one of the next layers, within the
object's line half-width. Contacts are grouped into bands (connected across neighbouring cells and layers),
each with its object, Z range, bed-frame extent and an area estimate. Everything here is in the bed frame;
mapping a band back into the model's frame is the placement step's job.
"""

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from agentcad.gcode.model import SUPPORT_FEATURES, GCodeModel

Cell = Tuple[int, int]


@dataclass
class Band:
    object: Optional[str]
    layers: Tuple[int, int]
    z: Tuple[float, float]
    xy_min: Tuple[float, float]
    xy_max: Tuple[float, float]
    area_mm2: float
    points: int

    def sentence(self) -> str:
        who = self.object or "the part"
        return (f"supports touch {who} at z {self.z[0]:.2f}-{self.z[1]:.2f} mm, about {self.area_mm2:.0f} mm2, "
                f"over bed x {self.xy_min[0]:.1f}-{self.xy_max[0]:.1f}, y {self.xy_min[1]:.1f}-{self.xy_max[1]:.1f}")


def _samples(points: List[Tuple[float, float]], step: float):
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
        for k in range(n):
            t = k / n
            yield x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
    if points:
        yield points[-1]


def find_contacts(model: GCodeModel, contact_distance: float = 0.25, cell: float = 0.25) -> List[Band]:
    """Contact bands between support extrusion and the object printed directly above it. "Directly above" is a
    Z window, not a layer count: the slicer leaves ``contact_distance`` (its support_material_contact_distance)
    between support and part and rounds it to layers, so a part's first layer over a support can be three or
    more thin layers up. The window is that distance plus two layer heights."""
    zs_list = [L.z for L in model.layers]
    occupied: Dict[int, Dict[Cell, Optional[str]]] = {}
    for p in model.paths:
        if p.layer < 0 or p.feature in SUPPORT_FEATURES or p.object is None:
            continue
        r = max(1, int(round(((p.width or 0.45) / 2) / cell)))
        layer = occupied.setdefault(p.layer, {})
        for x, y in _samples(p.points, cell):
            cx, cy = int(math.floor(x / cell)), int(math.floor(y / cell))
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    layer[(cx + dx, cy + dy)] = p.object
    hits: Dict[Tuple[int, int, int], Tuple[Optional[str], float]] = {}
    for p in model.paths:
        if p.feature not in SUPPORT_FEATURES or p.layer < 0:
            continue
        w = p.width or 0.45
        for x, y in _samples(p.points, cell):
            c = (int(math.floor(x / cell)), int(math.floor(y / cell)))
            z0 = zs_list[p.layer]
            h = model.layers[p.layer].height or 0.2
            k = 1
            while p.layer + k < len(zs_list) and zs_list[p.layer + k] - z0 <= contact_distance + 2 * h + 1e-6:
                above = occupied.get(p.layer + k)
                if above and c in above:
                    hits[(p.layer, c[0], c[1])] = (above[c], w)
                    break
                k += 1
    # bands: connected components over (layer +-1, cell +-1)
    seen: Set[Tuple[int, int, int]] = set()
    bands: List[Band] = []
    zs = {L.index: L.z for L in model.layers}
    for start in hits:
        if start in seen:
            continue
        stack, comp = [start], []
        seen.add(start)
        while stack:
            cur = stack.pop()
            comp.append(cur)
            L, cx, cy = cur
            for dL in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nb = (L + dL, cx + dx, cy + dy)
                        if nb in hits and nb not in seen:
                            seen.add(nb)
                            stack.append(nb)
        objs = [hits[c][0] for c in comp]
        layers = [c[0] for c in comp]
        xs = [c[1] * cell for c in comp]
        ys = [c[2] * cell for c in comp]
        bands.append(Band(max(set(objs), key=objs.count), (min(layers), max(layers)),
                          (zs.get(min(layers), 0.0), zs.get(max(layers), 0.0)),
                          (min(xs), min(ys)), (max(xs) + cell, max(ys) + cell),
                          round(sum(hits[c][1] for c in comp) * cell, 1), len(comp)))
    bands.sort(key=lambda b: (b.object or "", b.z[0]))
    return bands
