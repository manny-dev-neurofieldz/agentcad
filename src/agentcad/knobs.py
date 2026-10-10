"""KNOBS: which parameters of a program move the part, and which do nothing.

A parametric program is a function of its parameters, but not every parameter
reaches the geometry: one is clamped before it is used, one is read by a branch
that never runs, one was left over from an earlier design. A sweep finds out by
building: the program runs at its base values and, for each knob, at the base
plus and minus a delta, which is two builds per knob and one for the base and
never more. Each run is measured (volume, area, bounding-box size, solid count)
and each side is compared with the base:

``live``       both sides change the part.
``saturated``  one side changes it and the other does nothing: the knob is at a
               limit (a clamp, a minimum) in that direction.
``dead``       neither side changes anything measurable.
``partial``    one side would not build (its error is recorded) and the other
               built; ``refused`` is both sides.

"Nothing measurable" is exactly that: a knob that only moves a feature the four
measures cannot see (the colour of an engraving, a hole of equal volume moved
along a wall) reads as dead, so a dead verdict names a measure and not a
certainty. The record is schema ``agentcad.probe.knobs/1``.
"""

import inspect
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

SCHEMA = "agentcad.probe.knobs/1"
_SAME = 1e-9    # relative: a change smaller than this share of the base value is no change


def parse_knob(spec: str) -> Tuple[str, float, bool]:
    """``NAME=DELTA`` or ``NAME=P%`` as (name, delta, relative): an amount, or a percentage of the base."""
    name, _, text = spec.partition("=")
    name, text = name.strip(), text.strip()
    if not name.isidentifier() or not text:
        raise ValueError(f"knob spec {spec!r}: expected NAME=DELTA or NAME=PERCENT% (for example width=2 or width=10%)")
    relative = text.endswith("%")
    try:
        delta = float(text[:-1] if relative else text)
    except ValueError:
        raise ValueError(f"knob spec {spec!r}: {text!r} is not a number")
    if not delta > 0:
        raise ValueError(f"knob spec {spec!r}: the delta must be above 0")
    return name, delta, relative


def _base_values(build, names: Sequence[str], defines: Dict[str, str]) -> Dict[str, Any]:
    """The base value of each knob: its ``-D`` override if given, else the default of ``build``."""
    from agentcad.params import coerce_to_type_of

    sig = inspect.signature(build)
    kwargs_ok = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    out: Dict[str, Any] = {}
    for name in names:
        if name in sig.parameters:
            default = sig.parameters[name].default
            exemplar = None if default is inspect.Parameter.empty else default
        elif kwargs_ok:
            exemplar = None
        else:
            raise ValueError(f"build() has no parameter '{name}' (accepts: {', '.join(sig.parameters) or 'none'})")
        if name in defines:
            value = coerce_to_type_of(defines[name], exemplar)
        elif exemplar is None:
            raise ValueError(f"knob '{name}' has no default to start from: give -D {name}=VALUE")
        else:
            value = exemplar
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"knob '{name}' is a {type(value).__name__}, not a number: a knob is a number the part depends on")
        out[name] = value
    return out


def _measure(shape) -> Dict[str, Any]:
    bb = shape.bounding_box()
    return {"volume": float(shape.volume), "area": float(shape.area),
            "bbox_size": [float(bb.size.X), float(bb.size.Y), float(bb.size.Z)], "solids": len(shape.solids())}


def _build(source: Path, defines: Dict[str, str]) -> Dict[str, Any]:
    """One run, measured; a build that fails is a result (its error), not an exception."""
    from agentcad.probe import load_shape

    try:
        return {"ok": True, **_measure(load_shape(source, defines))}
    except Exception as e:  # noqa: BLE001 - a knob value can break the program in any way; the error is the finding
        message = str(e).splitlines()[0][:160] if str(e) else ""
        return {"ok": False, "error": f"{type(e).__name__}: {message}" if message else type(e).__name__}


def _side(base: Dict[str, Any], run: Dict[str, Any], value: float) -> Dict[str, Any]:
    """One side of a knob against the base: what changed, and whether that is a change at all."""
    if not run["ok"]:
        return {"value": value, "status": "refused", "error": run["error"]}
    dv, da = run["volume"] - base["volume"], run["area"] - base["area"]
    dbox = [r - b for r, b in zip(run["bbox_size"], base["bbox_size"])]
    dsolids = run["solids"] - base["solids"]
    scale = lambda x: _SAME * max(1.0, abs(x))
    changed = (abs(dv) > scale(base["volume"]) or abs(da) > scale(base["area"]) or dsolids != 0
               or any(abs(d) > scale(b) for d, b in zip(dbox, base["bbox_size"])))
    return {"value": value, "status": "changed" if changed else "unchanged", "volume": dv,
            "volume_pct": (100.0 * dv / base["volume"]) if base["volume"] else None, "area": da,
            "area_pct": (100.0 * da / base["area"]) if base["area"] else None, "bbox_size": dbox, "solids": dsolids}


def _verdict(plus: Dict[str, Any], minus: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    sides = (("plus", plus), ("minus", minus))
    built = [(n, s) for n, s in sides if s["status"] != "refused"]
    if not built:
        return "refused", None
    if len(built) == 1:
        return "partial", None
    moved = [n for n, s in built if s["status"] == "changed"]
    if len(moved) == 2:
        return "live", None
    if not moved:
        return "dead", None
    return "saturated", "plus" if moved == ["minus"] else "minus"


def knob_sweep(source: Path, knobs: Sequence[str], defines: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Run ``source`` at its base values and at +/- each knob's delta; the record, with ``runs`` = 2 per knob + 1.

    ``knobs`` are ``NAME=DELTA`` or ``NAME=PERCENT%`` strings; ``defines`` are ``-D`` overrides that move
    the base (as strings, as everywhere). The program must define ``build(**params)``.
    """
    from agentcad.engines.build123d_worker import _execute

    source = Path(source)
    if source.suffix.lower() != ".py":
        raise ValueError(f"{source}: probe knobs reads a build123d program with a build(**params) function")
    parsed = [parse_knob(k) for k in knobs]
    names = [n for n, _, _ in parsed]
    if not parsed:
        raise ValueError("give at least one --knob NAME=DELTA")
    if len(set(names)) != len(names):
        raise ValueError(f"a knob is given twice: {sorted(n for n in set(names) if names.count(n) > 1)}")
    defines = dict(defines or {})
    build = _execute(str(source)).get("build")
    if not callable(build):
        raise ValueError(f"{source}: knobs need a parametric build(**params); this source defines none")
    bases = _base_values(build, names, defines)

    base = _build(source, defines)
    if not base["ok"]:
        raise RuntimeError(f"the base run does not build: {base['error']}")
    res: Dict[str, Any] = {"schema": SCHEMA, "source": str(source), "defines": defines, "base": base, "knobs": [],
                           "runs": 1 + 2 * len(parsed)}
    for name, amount, relative in parsed:
        value = bases[name]
        delta = abs(value) * amount / 100.0 if relative else amount
        if relative and value == 0:
            raise ValueError(f"knob '{name}' is 0, so {amount:g}% of it is 0: give an absolute delta")
        if isinstance(value, int):
            if abs(delta - round(delta)) > 1e-9:
                raise ValueError(f"knob '{name}' is an integer: its delta must be a whole number, not {delta:g}")
            delta = int(round(delta))
        sides = {}
        for tag, sign in (("plus", 1), ("minus", -1)):
            moved = value + sign * delta
            sides[tag] = _side(base, _build(source, {**defines, name: repr(moved)}), moved)
        verdict, which = _verdict(sides["plus"], sides["minus"])
        rec = {"name": name, "base": value, "delta": delta, "relative": relative, "plus": sides["plus"],
               "minus": sides["minus"], "verdict": verdict}
        if relative:
            rec["percent"] = amount
        if which:
            rec["saturated"] = which
        res["knobs"].append(rec)
    return res


def _signed(x: float) -> str:
    return f"{x:+.4g}"


def _side_text(side: Dict[str, Any], sign: str, delta: Any) -> str:
    head = f"  {sign}{delta:g} -> {side['value']:.6g}: "
    if side["status"] == "refused":
        return head + f"REFUSED, the program does not build ({side['error']})"
    pct = lambda p: f" ({_signed(p)}%)" if p is not None else ""
    box = " ".join(_signed(d) for d in side["bbox_size"])
    return (head + f"volume {_signed(side['volume'])}{pct(side['volume_pct'])}, area {_signed(side['area'])}{pct(side['area_pct'])}, "
            f"bbox {box}, solids {side['solids']:+d}" + ("" if side["status"] == "changed" else "  (no change)"))


def render_knobs(res: Dict[str, Any]) -> List[str]:
    """The sweep as text: the base, then each knob's two sides and its verdict."""
    b = res["base"]
    out = [f"{res['source']}: base volume {b['volume']:.6g}, area {b['area']:.6g}, bbox "
           f"{' x '.join(f'{x:.4g}' for x in b['bbox_size'])}, {b['solids']} solid(s); "
           f"{res['runs']} builds (1 base + 2 per knob)"]
    words = {"live": "live: both sides change the part",
             "dead": "DEAD: no change in volume, area, bounding box or solid count either way",
             "partial": "partial: one side does not build, so the knob has a limit there",
             "refused": "REFUSED: neither side builds"}
    for k in res["knobs"]:
        percent = f" ({k['percent']:g}% of the base)" if k["relative"] else ""
        out.append(f"knob {k['name']}: base {k['base']:.6g}, delta {k['delta']:g}{percent}")
        out.append(_side_text(k["plus"], "+", k["delta"]))
        out.append(_side_text(k["minus"], "-", k["delta"]))
        if k["verdict"] == "saturated":
            other = "decreasing" if k["saturated"] == "plus" else "increasing"
            out.append(f"  SATURATED: {'increasing' if k['saturated'] == 'plus' else 'decreasing'} it changes nothing, "
                       f"{other} it does (the knob is at a limit)")
        else:
            out.append("  " + words[k["verdict"]])
    return out
