"""A model of a sliced file: layers, objects and feature-typed extrusion paths.

Built from G-code text (plain, or decoded from .bgcode by ``agentcad.gcode.bgcode``). The structure follows
the conventions PrusaSlicer writes: ``;LAYER_CHANGE`` / ``;Z:`` / ``;HEIGHT:`` for layers, ``;TYPE:`` for the
feature being printed, ``;WIDTH:`` for the line width, and ``M486`` object labels (``S<id>`` selects,
``A<name>`` names the selected id, ``S-1`` leaves every object). Files without these comments still give
layers by Z and extrusion totals; their paths are typed "unknown" and the summary says so.

Extrusion is filament length (the E axis), in absolute (M82) or relative (M83) mode, with G92 resets and
firmware retraction (G10/G11). The slicer's "filament used" excludes a final retraction that is never
primed again; ``filament_used`` does the same, so it can be compared with the file's own total.
"""

import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

DEFAULT_FILAMENT_DIAMETER = 1.75

_WORD = re.compile(r"([A-Z])(-?\d*\.?\d+)")

SUPPORT_FEATURES = ("Support material", "Support material interface")
BRIM_FEATURES = ("Skirt/Brim", "Skirt", "Brim")


@dataclass
class Path:
    """One run of extruding moves with the same layer, object, feature and width."""
    layer: int
    z: float
    object: Optional[str]
    feature: str
    width: Optional[float]
    points: List[Tuple[float, float]] = field(default_factory=list)
    filament: float = 0.0                     # mm of filament pushed along this path
    length: float = 0.0                       # mm travelled while extruding

    def add(self, x0: float, y0: float, x1: float, y1: float, e: float) -> None:
        if not self.points or self.points[-1] != (x0, y0):
            self.points.append((x0, y0))
        self.points.append((x1, y1))
        self.filament += e
        self.length += math.hypot(x1 - x0, y1 - y0)


@dataclass
class Layer:
    index: int
    z: float
    height: Optional[float]


@dataclass
class GCodeModel:
    layers: List[Layer]
    paths: List[Path]
    objects: Dict[int, str]
    filament_net: float                       # all E moves summed
    final_retraction: float                   # a retraction at the end never primed again (<= 0)
    features_known: bool
    unknown_features: Dict[str, int] = field(default_factory=dict)

    @property
    def filament_used(self) -> float:
        """Filament length the way the slicer reports it: net extrusion without the final, unprimed retraction."""
        return self.filament_net - self.final_retraction

    def totals(self, by: str = "feature") -> Dict[Tuple, Dict[str, float]]:
        """Filament and path length summed by ("feature",), ("object",) or ("object", "feature")."""
        keys = {"feature": ("feature",), "object": ("object",), "object_feature": ("object", "feature")}[by]
        out: Dict[Tuple, Dict[str, float]] = {}
        for p in self.paths:
            k = tuple(getattr(p, a) for a in keys)
            t = out.setdefault(k, {"filament": 0.0, "length": 0.0, "paths": 0})
            t["filament"] += p.filament
            t["length"] += p.length
            t["paths"] += 1
        return out

    def layers_with(self, features) -> List[int]:
        return sorted({p.layer for p in self.paths if p.feature in features})


def _arc_points(x0, y0, x1, y1, i, j, clockwise, max_seg=0.5):
    """Points along a G2/G3 arc from (x0, y0) to (x1, y1) about (x0 + i, y0 + j), excluding the start."""
    cx, cy = x0 + i, y0 + j
    r = math.hypot(i, j)
    a0 = math.atan2(y0 - cy, x0 - cx)
    a1 = math.atan2(y1 - cy, x1 - cx)
    sweep = a1 - a0
    if clockwise and sweep >= 0:
        sweep -= 2 * math.pi
    elif not clockwise and sweep <= 0:
        sweep += 2 * math.pi
    n = max(1, int(abs(sweep) * r / max_seg))
    return [(cx + r * math.cos(a0 + sweep * k / n), cy + r * math.sin(a0 + sweep * k / n)) for k in range(1, n)] + [(x1, y1)]


def parse(text: str) -> GCodeModel:
    """The model of one sliced file's G-code text."""
    x = y = z = 0.0
    e_abs = 0.0
    relative_e = False
    layer_idx = -1
    layer_z: Optional[float] = None
    layer_h: Optional[float] = None
    pending_layer = False
    layers: List[Layer] = []
    feature = "unknown"
    features_known = False
    width: Optional[float] = None
    obj_id: Optional[int] = None
    objects: Dict[int, str] = {}
    last_selected: Optional[int] = None
    paths: List[Path] = []
    current: Optional[Path] = None
    net = 0.0
    trailing_retraction = 0.0                 # retraction since the last positive extrusion
    retract_len = 0.0                          # firmware retraction length when declared by the file (G10/G11)
    unknown: Dict[str, int] = {}
    has_layer_comments = ";LAYER_CHANGE" in text   # then extrusion before the first one is priming, layer -1

    def start_layer(zv: Optional[float], h: Optional[float]) -> None:
        nonlocal layer_idx, current
        layer_idx += 1
        layers.append(Layer(layer_idx, zv if zv is not None else z, h))
        current = None

    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line[0] == ";":
            if line.startswith(";LAYER_CHANGE"):
                pending_layer = True
                layer_z = layer_h = None
            elif line.startswith(";Z:"):
                layer_z = float(line[3:])
                if pending_layer:
                    start_layer(layer_z, layer_h)
                    pending_layer = False
            elif line.startswith(";HEIGHT:"):
                layer_h = float(line[8:])
                if layers:
                    layers[-1].height = layer_h
            elif line.startswith(";TYPE:"):
                feature = line[6:]
                features_known = True
                current = None
            elif line.startswith(";WIDTH:"):
                width = float(line[7:])
                current = None
            continue
        code = line.split(";", 1)[0].strip()
        if not code:
            continue
        head = code.split(None, 1)[0].upper()
        if head == "M82":
            relative_e = False
        elif head == "M83":
            relative_e = True
        elif head == "M486":
            rest = code[4:].lstrip()
            if rest.startswith("A"):
                if last_selected is not None:
                    objects[last_selected] = rest[1:]
            else:
                m = re.search(r"S(-?\d+)", code)
                if m:
                    sid = int(m.group(1))
                    obj_id = None if sid < 0 else sid
                    if sid >= 0:
                        last_selected = sid
                    current = None
        elif head == "G92":
            words = dict((k, float(v)) for k, v in _WORD.findall(code[3:]))
            if "E" in words:
                e_abs = words["E"]
        elif head in ("G10", "G11"):
            de = -retract_len if head == "G10" else retract_len
            net += de
            trailing_retraction = trailing_retraction + de if head == "G10" else 0.0
        elif head in ("G0", "G1", "G2", "G3"):
            words = dict((k, float(v)) for k, v in _WORD.findall(code[len(head):]))
            nx, ny, nz = words.get("X", x), words.get("Y", y), words.get("Z", z)
            de = 0.0
            if "E" in words:
                if relative_e:
                    de = words["E"]
                else:
                    de = words["E"] - e_abs
                    e_abs = words["E"]
            net += de
            if de > 0:
                trailing_retraction = 0.0
            elif de < 0:
                trailing_retraction += de
            z = nz
            moved = (nx, ny) != (x, y)
            if de > 0 and moved:
                if not layers and not has_layer_comments:     # no layer comments: layers by Z
                    start_layer(z, None)
                elif layer_idx >= 0 and not features_known and abs(layers[-1].z - z) > 1e-6 and not pending_layer:
                    start_layer(z, None)
                obj_name = objects.get(obj_id) if obj_id is not None else None
                key = (layer_idx, obj_name, feature, width)
                if current is None or (current.layer, current.object, current.feature, current.width) != key:
                    current = Path(layer_idx, layers[-1].z if layers else z, obj_name, feature, width)   # -1: priming
                    paths.append(current)
                    if feature not in _KNOWN and features_known:
                        unknown[feature] = unknown.get(feature, 0) + 1
                if head in ("G2", "G3") and ("I" in words or "J" in words):
                    pts = _arc_points(x, y, nx, ny, words.get("I", 0.0), words.get("J", 0.0), head == "G2")
                    share = de / len(pts)
                    px, py = x, y
                    for qx, qy in pts:
                        current.add(px, py, qx, qy, share)
                        px, py = qx, qy
                else:
                    current.add(x, y, nx, ny, de)
            elif moved:
                current = None
            x, y = nx, ny
    return GCodeModel(layers, paths, objects, net, trailing_retraction, features_known, unknown)


_KNOWN = {
    "Perimeter", "External perimeter", "Overhang perimeter", "Internal infill", "Solid infill", "Top solid infill",
    "Bridge infill", "Internal bridge infill", "Gap fill", "Skirt/Brim", "Skirt", "Brim", "Support material",
    "Support material interface", "Wipe tower", "Ironing", "Custom", "Mixed", "unknown",
}


def summary(model: GCodeModel, filament_diameter: float = DEFAULT_FILAMENT_DIAMETER,
            density: Optional[float] = None) -> Dict:
    """The numbers ``gcode summary`` prints, as a JSON-ready dict (see the README for the schema)."""
    area = math.pi * (filament_diameter / 2) ** 2

    def amounts(fil: float) -> Dict[str, float]:
        d = {"filament_mm": round(fil, 2), "volume_cm3": round(fil * area / 1000.0, 3)}
        if density:
            d["mass_g"] = round(fil * area / 1000.0 * density, 2)
        return d

    by_feature = {k[0]: dict(amounts(v["filament"]), length_mm=round(v["length"], 1), paths=v["paths"])
                  for k, v in sorted(model.totals("feature").items(), key=lambda kv: -kv[1]["filament"])}
    by_object: Dict[str, Dict] = {}
    for (obj, feat), v in model.totals("object_feature").items():
        o = by_object.setdefault(obj or "(no object)", {"filament_mm": 0.0, "features": {}})
        o["filament_mm"] = round(o["filament_mm"] + v["filament"], 2)
        o["features"][feat] = amounts(v["filament"])
    for o in by_object.values():
        sup = sum(f["filament_mm"] for k, f in o["features"].items() if k in SUPPORT_FEATURES)
        o["support_share"] = round(sup / o["filament_mm"], 4) if o["filament_mm"] else 0.0
    total_ext = sum(p.filament for p in model.paths)
    sup_total = sum(p.filament for p in model.paths if p.feature in SUPPORT_FEATURES)
    sup_layers = model.layers_with(SUPPORT_FEATURES)
    brim = [p for p in model.paths if p.feature in BRIM_FEATURES]
    return {
        "schema": "agentcad.gcode.summary/1",
        "layers": len(model.layers),
        "top_z": model.layers[-1].z if model.layers else None,
        "filament_used": amounts(model.filament_used),
        "features_known": model.features_known,
        "unknown_features": model.unknown_features,
        "objects": {str(k): v for k, v in sorted(model.objects.items())},
        "by_object": by_object,
        "by_feature": by_feature,
        "support": {
            "share": round(sup_total / total_ext, 4) if total_ext else 0.0,
            "first_layer": sup_layers[0] if sup_layers else None,
            "last_layer": sup_layers[-1] if sup_layers else None,
            "first_z": model.layers[sup_layers[0]].z if sup_layers else None,
            "last_z": model.layers[sup_layers[-1]].z if sup_layers else None,
        },
        "brim_area_mm2": round(sum(p.length * (p.width or 0.0) for p in brim), 1) if brim else 0.0,
    }
