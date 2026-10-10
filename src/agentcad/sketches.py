"""RECOVER, drawn intent: the sketches, parameters and timeline of a design dump.

A design dump is a JSON record of a parametric-CAD design (see the policy ``probe-recover``
for the schema). Its sketches say what was DRAWN, which a finished solid does not: a
construction circle that never reaches the part, a radius that a later feature changed, a
line whose angle was a drawn endpoint and not a stated one. This module reads the dump
and, given the part itself, says which drawn dimensions the part still APPLIES.

Two labels, never mixed: every number read from the dump is ``DRAWN``; a drawn dimension is
also ``APPLIED`` only when the part's section on the sketch's plane carries it (a circular
edge of that radius, a line of that length, an arc of that sweep) within a stated tolerance.
A dimension the section does not carry is still ``DRAWN``; it is reported as absent, not
called wrong. Reading the dump needs no CAD backend (standard library only); the section
needs build123d and is skipped, with a stated message, without it.

Geometry in the dump is in centimetres and is returned in millimetres; ``parameters`` are
kept as the dump states them (their ``expression`` is the authority, not their numeric value).
"""

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

CM_TO_MM = 10.0
PLANE_TOL = 1e-6        # how close to an axis a sketch's normal must be for its plane to be cut as x=, y= or z=
_RAW_CHARS = 160


class DumpError(ValueError):
    """The dump, the sketch filter or the part could not be read; the message says why."""


def load_dump(path: Path) -> Dict[str, Any]:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise DumpError(f"{path}: cannot be read ({e.strerror or e})")
    try:
        dump = json.loads(text)
    except json.JSONDecodeError as e:
        raise DumpError(f"{path}: not valid JSON ({e})")
    if not isinstance(dump, dict) or not isinstance(dump.get("sketches"), list):
        raise DumpError(f"{path}: not a design dump (expected a JSON object with a 'sketches' list)")
    return dump


# --- reading ---------------------------------------------------------------------------------------

def _mm(v: Sequence[float], n: int = 3) -> List[float]:
    return [round(float(x) * CM_TO_MM, 6) for x in list(v)[:n]]


def _dimension(name: str, value: float, unit: str) -> Dict[str, Any]:
    return {"name": name, "value": round(value, 6), "unit": unit, "labels": ["DRAWN"], "applied_in": [],
            "compared": False}


def _curve(c: Dict[str, Any], index: int) -> Dict[str, Any]:
    kind_of = {"SketchCircle": "circle", "SketchArc": "arc", "SketchLine": "line"}
    out: Dict[str, Any] = {"index": index, "type": str(c.get("type")), "kind": "other",
                           "construction": bool(c.get("isConstruction")), "dimensions": []}
    try:
        kind = kind_of.get(out["type"])
        if kind in ("circle", "arc"):
            out.update(center=_mm(c["center"], 2))
            out["radius"] = round(float(c["radius"]) * CM_TO_MM, 6)
            out["dimensions"].append(_dimension("radius", out["radius"], "mm"))
        if kind == "arc":
            out.update(start=_mm(c["start"], 2), end=_mm(c["end"], 2))
            a0 = math.atan2(out["start"][1] - out["center"][1], out["start"][0] - out["center"][0])
            a1 = math.atan2(out["end"][1] - out["center"][1], out["end"][0] - out["center"][0])
            sweep = math.degrees((a1 - a0) % (2 * math.pi))
            out["sweep_deg"] = round(sweep if sweep > 1e-9 else 360.0, 6)       # arcs run counter-clockwise start to end
            out["dimensions"].append(_dimension("sweep", out["sweep_deg"], "deg"))
        if kind == "line":
            out.update(start=_mm(c["start"], 2), end=_mm(c["end"], 2))
            dx, dy = out["end"][0] - out["start"][0], out["end"][1] - out["start"][1]
            out["length"] = round(math.hypot(dx, dy), 6)
            out["angle_deg"] = round(math.degrees(math.atan2(dy, dx)), 4)
            out["dimensions"].append(_dimension("length", out["length"], "mm"))
        if kind:
            out["kind"] = kind
            return out
    except (KeyError, TypeError, ValueError, IndexError):
        pass
    out["kind"] = "other"
    out["dimensions"] = []
    out["raw"] = json.dumps({k: v for k, v in c.items() if k not in ("type", "isConstruction")})[:_RAW_CHARS]
    return out


def _plane(origin: Optional[Sequence[float]], xd: Optional[Sequence[float]], yd: Optional[Sequence[float]]) -> Dict[str, Any]:
    """The sketch plane: its origin and normal in mm, and, when the normal lies along an axis, the section
    plane (``z=10``) that cuts a part where the sketch lies; otherwise why there is none."""
    try:
        o = _mm(origin)
        x, y = [float(v) for v in list(xd)[:3]], [float(v) for v in list(yd)[:3]]
        n = [x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0]]
        length = math.sqrt(sum(v * v for v in n))
        n = [v / length for v in n]
    except (TypeError, ValueError, IndexError, ZeroDivisionError):
        return {"origin": None, "x_direction": None, "y_direction": None, "normal": None, "spec": None,
                "why": "the sketch carries no usable origin and directions"}
    plane: Dict[str, Any] = {"origin": o, "x_direction": x, "y_direction": y,
                             "normal": [round(v, 6) for v in n], "spec": None, "why": None}
    for axis, i in (("x", 0), ("y", 1), ("z", 2)):
        if abs(abs(n[i]) - 1.0) < PLANE_TOL:
            plane["spec"] = f"{axis}={o[i]:.9g}"
            return plane
    plane["why"] = "not axis-aligned (a section is cut on x=, y= or z= planes)"
    return plane


def _sketch(s: Dict[str, Any], k: int) -> Dict[str, Any]:
    plane = _plane(s.get("origin"), s.get("xDirection"), s.get("yDirection"))
    return {"name": str(s.get("name", f"sketch {k + 1}")), "profiles": s.get("profileCount"), "plane": plane,
            "curves": [_curve(c, i) for i, c in enumerate(s.get("curves") or []) if isinstance(c, dict)],
            "section": None}


def describe(dump: Dict[str, Any], only: Optional[str] = None) -> Dict[str, Any]:
    """The dump as a record in millimetres: design, parameters, timeline and the (filtered) sketches.
    ``only`` keeps the sketches whose name contains that text, ignoring case."""
    sketches = [_sketch(s, k) for k, s in enumerate(dump["sketches"]) if isinstance(s, dict)]
    shown = sketches
    if only is not None:
        shown = [s for s in sketches if only.lower() in s["name"].lower()]
        if not shown:
            raise DumpError(f"no sketch matches {only!r} (the dump has: {', '.join(s['name'] for s in sketches) or 'none'})")
    parameters = [dict(p, labels=["DRAWN"]) for p in dump.get("parameters") or [] if isinstance(p, dict)]
    timeline = [t for t in dump.get("timeline") or [] if isinstance(t, dict)]
    return {"design": {"name": dump.get("designName"), "type": dump.get("designType")},
            "parameters": parameters, "timeline": timeline, "sketches": shown, "n_sketches": len(sketches),
            "filter": only, "against": None, "notes": []}


# --- the part --------------------------------------------------------------------------------------

def _features(shape, spec: str) -> List[Dict[str, Any]]:
    """The lines and arcs of every section loop of ``shape`` on ``spec``, as :mod:`agentcad.curves` reads them."""
    from agentcad import curves, probe

    plane, _ = probe.parse_plane(spec, shape)
    found: List[Dict[str, Any]] = []
    for i, loop in enumerate(probe.section_loops(shape, plane)):
        rec = curves.recover_loop(loop, spec)
        for j, seg in enumerate(rec["segments"]):
            if seg["kind"] == "arc":
                found.append({"loop": i + 1, "segment": j, "kind": "arc", "radius": seg["radius"], "sweep_deg": seg["sweep_deg"]})
            elif seg["kind"] == "line":
                found.append({"loop": i + 1, "segment": j, "kind": "line", "length": seg["length"]})
    return found


def _match(dim: Dict[str, Any], curve: Dict[str, Any], features: List[Dict[str, Any]], tol: float) -> List[Dict[str, Any]]:
    hits = []
    for f in features:
        if dim["name"] == "radius" and f["kind"] == "arc" and abs(f["radius"] - dim["value"]) <= tol:
            hits.append(f)
        elif dim["name"] == "length" and f["kind"] == "line" and abs(f["length"] - dim["value"]) <= tol:
            hits.append(f)
        elif dim["name"] == "sweep" and f["kind"] == "arc" and abs(f["radius"] - curve["radius"]) <= tol \
                and abs(f["sweep_deg"] - dim["value"]) <= max(0.01, math.degrees(tol / curve["radius"])):
            hits.append(f)
    return [{"loop": h["loop"], "segment": h["segment"]} for h in hits]


def apply_part(record: Dict[str, Any], source: Path, tol: float) -> None:
    """Label as ``APPLIED`` every drawn dimension that the part at ``source`` (a STEP file or a build123d
    program) carries in its section on the sketch's plane, within ``tol`` mm (degrees follow from it for a
    sweep). Construction curves are never matched. Sets ``record["against"]`` and appends to
    ``record["notes"]``; without the build123d backend it says so there and changes no label."""
    from agentcad import probe

    source = Path(source)
    against: Dict[str, Any] = {"source": str(source), "tol": tol, "available": True}
    record["against"] = against
    try:
        shape = probe.load_shape(source)
    except ImportError:
        against["available"] = False
        record["notes"].append('--against needs the build123d backend (pip install "agentcad[build123d]"): '
                               "APPLIED labels were not computed, every dimension stays DRAWN only")
        return
    except FileNotFoundError:
        raise DumpError(f"{source}: no such file")
    except ValueError as e:
        raise DumpError(str(e))
    if not shape.solids() and not shape.faces():
        raise DumpError(f"{source}: no geometry could be read from it")

    sections: Dict[str, Optional[List[Dict[str, Any]]]] = {}
    for sketch in record["sketches"]:
        spec = sketch["plane"]["spec"]
        if spec is None:
            record["notes"].append(f"sketch {sketch['name']!r}: {sketch['plane']['why']}; its dimensions stay DRAWN only")
            continue
        if spec not in sections:
            sections[spec] = _features(shape, spec)
            if not sections[spec]:
                record["notes"].append(f"section {spec}: the part has no loops there (the plane does not cut it)")
        features = sections[spec]
        sketch["section"] = {"spec": spec, "features": len(features)}
        for curve in sketch["curves"]:
            if curve["construction"]:
                continue
            for dim in curve["dimensions"]:
                dim["compared"] = True
                hits = _match(dim, curve, features, tol)
                if hits:
                    dim["labels"].append("APPLIED")
                    dim["applied_in"] = hits[:4]


# --- reading the result --------------------------------------------------------------------------

def _pt(p: Sequence[float]) -> str:
    return "(" + ", ".join(f"{v:.4f}" for v in p) + ")"


def _tag(dim: Dict[str, Any]) -> str:
    if "APPLIED" in dim["labels"]:
        loops = sorted({h["loop"] for h in dim["applied_in"]})
        return "[DRAWN APPLIED loop " + ",".join(str(n) for n in loops) + "]"
    return "[DRAWN, absent from the section]" if dim["compared"] else "[DRAWN]"


def _curve_line(c: Dict[str, Any]) -> str:
    flag = "  C " if c["construction"] else "    "
    dims = {d["name"]: d for d in c["dimensions"]}
    if c["kind"] == "circle":
        return f"{flag}circle  center {_pt(c['center'])}  r {c['radius']:.4f} {_tag(dims['radius'])}"
    if c["kind"] == "arc":
        return (f"{flag}arc     center {_pt(c['center'])}  r {c['radius']:.4f} {_tag(dims['radius'])}  "
                f"{_pt(c['start'])} -> {_pt(c['end'])}  sweep {c['sweep_deg']:.2f} deg {_tag(dims['sweep'])}")
    if c["kind"] == "line":
        return (f"{flag}line    {_pt(c['start'])} -> {_pt(c['end'])}  length {c['length']:.4f} {_tag(dims['length'])}"
                f"  angle {c['angle_deg']:.2f} deg")
    return f"{flag}{c['type']}  (not read: no dimensions) {c['raw']}"


def render(record: Dict[str, Any]) -> List[str]:
    """Lines for the terminal; every dimension carries its label, and a cut-off, if any, is stated."""
    d = record["design"]
    lines = [f"design {d['name']}" + (f" ({d['type']})" if d["type"] else "")
             + "; geometry in the dump is centimetres, printed here in millimetres"]
    lines.append(f"parameters: {len(record['parameters'])}")
    for p in record["parameters"]:
        extra = "  ".join(x for x in (p.get("role"), p.get("comment")) if x)
        lines.append(f"  {p.get('name')} = {p.get('expression')}  [DRAWN]" + (f"  {extra}" if extra else ""))
    lines.append(f"timeline: {len(record['timeline'])} feature(s)")
    for t in record["timeline"]:
        bits = [str(t.get("operation") or ""), "suppressed" if t.get("isSuppressed") else ""]
        lines.append(f"  {t.get('index')} {t.get('name')} [{t.get('entityType')}]" + "".join(f" {b}" for b in bits if b))
    shown = f", {len(record['sketches'])} shown (--sketch {record['filter']!r})" if record["filter"] is not None else ""
    lines.append(f"sketches: {record['n_sketches']} in the dump{shown}")
    for s in record["sketches"]:
        pl = s["plane"]
        if pl["origin"] is None:
            where = f"plane unknown ({pl['why']})"
        else:
            where = (f"origin {_pt(pl['origin'])} mm  normal ({', '.join(f'{v:.2f}' for v in pl['normal'])})  "
                     + (f"plane {pl['spec']}" if pl["spec"] else f"plane {pl['why']}"))
        n_con = sum(c["construction"] for c in s["curves"])
        lines.append(f"== {s['name']}  {where}  profiles {s['profiles']}  curves {len(s['curves'])} ({n_con} construction)")
        lines += [_curve_line(c) for c in s["curves"]]
    return lines
