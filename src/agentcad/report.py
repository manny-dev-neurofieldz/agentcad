"""The tray: a feature-effect report from engine metadata.

Every iteration of a design session carries the measured facts its engine
reported (see ``agentcad.engine.METADATA_KEYS``). This module turns two
such records, the previous iteration's and the current one's, into the
deltas a designer needs to see after each edit and the warnings that name
the failures this project has met:

* a body count other than the one expected (a part in three pieces renders
  whole from every angle);
* edges shorter than the short-edge threshold (a skim ridge no fillet can
  cross);
* an invalid B-rep;
* a twisted free-form face (a loft whose sections rotated against each other);
* and no measurable change when the source did change, which is how a
  chamfer inside a swallowed exception shipped through eight iterations.

The report is engine-neutral text over engine-supplied numbers. A key the
engine did not report prints as "n/a"; nothing is guessed.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from agentcad.findings import Finding

_CENSUS_ORDER = ("plane", "cylinder", "cone", "sphere", "torus", "bspline", "other")
_ANALYTIC_CURVED = ("cylinder", "cone", "sphere", "torus")
_COUNT_ORDER = ("solids", "faces", "edges", "vertices")
_ZERO_CHANGE_REL = 1e-9
_TWIST_AREA_FRAC = 0.02   # a twisted face smaller than this share of the part is a thread flank, not a loft
BSPLINE_HIDES_FRACTION = 0.9   # at or above this share of BSpline faces the census cannot see analytic types


@dataclass
class Report:
    """Deltas and warnings for one iteration; ``lines`` is the printable form.

    ``findings`` are the warnings as structured findings (rule, the layer that set the limit,
    the fix); ``warnings`` keeps their sentences for readers of the plain list."""
    lines: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    deltas: Dict[str, Any] = field(default_factory=dict)
    changed: Optional[bool] = None  # None when there is no previous record to compare
    findings: List[Finding] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"lines": list(self.lines), "warnings": list(self.warnings),
                "deltas": dict(self.deltas), "changed": self.changed}

    def warn(self, rule: str, key: str, found: Any, intended: str, message: str, *, why: str = "",
             fix: str = "", layer: str = "default", feature: str = "", location: str = "") -> None:
        """Record one tray warning both ways: the sentence and the finding."""
        self.warnings.append(message)
        self.findings.append(Finding(key, "warning", None if found is None else str(found), intended, why,
                                     source="the tray", rule=rule, layer=layer, feature=feature,
                                     location=location, fix=fix, message=message))


def _fmt(value: Any, unit: str = "") -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4g}{unit}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_fmt(v) for v in value) + "]"
    return f"{value}{unit}"


def _delta_scalar(prev: Optional[float], cur: Optional[float]) -> Tuple[str, Optional[float]]:
    if cur is None:
        return "n/a", None
    if prev is None:
        return _fmt(float(cur)), None
    d = float(cur) - float(prev)
    pct = (d / float(prev) * 100.0) if prev else None
    text = f"{_fmt(float(cur))} ({'+' if d >= 0 else ''}{d:.4g}"
    text += f", {'+' if d >= 0 else ''}{pct:.2f}%)" if pct is not None else ")"
    return text, d


def census_hides_analytic(census: Optional[Mapping[str, int]], threshold: float = BSPLINE_HIDES_FRACTION) -> Optional[str]:
    """A sentence when the face census cannot be read for analytic types, else None.

    A STEP converted to splines, a mesh-to-solid result and many swept or lofted bodies describe
    every surface as a BSpline, so a census of zero cylinders, cones, spheres and tori is the
    representation talking, not the part. The census reports ``threshold`` (90 percent) or more
    BSpline faces; below it the analytic counts are reported as they stand.
    """
    census = census or {}
    total = sum(int(v) for v in census.values())
    bspline = int(census.get("bspline", 0))
    if total <= 0 or bspline < threshold * total:
        return None
    analytic = sum(int(census.get(k, 0)) for k in _ANALYTIC_CURVED)
    reading = ("zero cylinders, cones, spheres and tori is not evidence that the part has none" if not analytic
               else f"the {analytic} counted analytic face(s) are a lower bound")
    return (f"{bspline} of {total} faces ({100.0 * bspline / total:.0f}%) are BSpline surfaces: "
            f"the representation hides analytic types, so {reading}")


def feature_effect(prev: Optional[Dict[str, Any]], cur: Dict[str, Any], *,
                   source_changed: Optional[bool] = None,
                   expected_solids: Optional[int] = None,
                   short_edge_mm: float = 0.25,
                   limits_from: Optional[Mapping[str, str]] = None) -> Report:
    """Compare the current iteration's metadata with the previous one's.

    ``source_changed`` says whether the source text differs from the previous
    iteration's (None when unknown); ``expected_solids`` overrides the value
    echoed in the metadata. ``limits_from`` names the layer that set each limit
    (``expected_solids``, ``short_edge_mm``); a limit it does not name is a default.
    """
    layer_of = dict(limits_from or {})
    rep = Report()
    prev = prev or {}
    have_prev = bool(prev)

    # --- scalars ------------------------------------------------------------
    changed_any = False
    for key, unit in (("volume", " mm^3"), ("area", " mm^2")):
        text, d = _delta_scalar(prev.get(key), cur.get(key))
        rep.lines.append(f"{key:<10} {text}")
        if d is not None:
            rep.deltas[key] = d
            if abs(d) > _ZERO_CHANGE_REL * max(1.0, abs(float(prev.get(key) or 0.0))):
                changed_any = True

    size = cur.get("bbox_size")
    psize = prev.get("bbox_size")
    if size is not None:
        line = f"{'bbox':<10} {_fmt(size)}"
        if psize is not None:
            dd = [float(a) - float(b) for a, b in zip(size, psize)]
            rep.deltas["bbox_size"] = dd
            if any(abs(v) > 1e-9 for v in dd):
                changed_any = True
                line += " (" + ", ".join(f"{'+' if v >= 0 else ''}{v:.4g}" for v in dd) + ")"
        rep.lines.append(line)
    else:
        rep.lines.append(f"{'bbox':<10} n/a")

    # --- counts -------------------------------------------------------------
    counts = cur.get("counts") or {}
    pcounts = prev.get("counts") or {}
    parts = []
    for name in _COUNT_ORDER:
        if name in counts:
            v = int(counts[name])
            if name in pcounts:
                d = v - int(pcounts[name])
                rep.deltas[f"counts.{name}"] = d
                if d:
                    changed_any = True
                parts.append(f"{name} {v} ({'+' if d >= 0 else ''}{d})")
            else:
                parts.append(f"{name} {v}")
    rep.lines.append(f"{'counts':<10} " + (", ".join(parts) if parts else "n/a"))

    # --- census -------------------------------------------------------------
    census = cur.get("face_census")
    pcensus = prev.get("face_census") or {}
    if census:
        parts = []
        for name in _CENSUS_ORDER:
            v = int(census.get(name, 0))
            if pcensus:
                d = v - int(pcensus.get(name, 0))
                rep.deltas[f"census.{name}"] = d
                if d:
                    changed_any = True
                if v or d:
                    parts.append(f"{name} {v} ({'+' if d >= 0 else ''}{d})")
            elif v:
                parts.append(f"{name} {v}")
        rep.lines.append(f"{'census':<10} " + (", ".join(parts) if parts else "no faces"))
    else:
        rep.lines.append(f"{'census':<10} n/a")

    # --- edges, validity, grid --------------------------------------------
    if "short_edges" in cur:
        rep.lines.append(f"{'edges':<10} shortest {_fmt(cur.get('min_edge_mm'))} mm, "
                         f"{cur['short_edges']} under {short_edge_mm:g} mm")
    if "is_valid" in cur:
        rep.lines.append(f"{'valid':<10} {cur['is_valid']}")
    if "grid_resolution" in cur:
        rep.lines.append(f"{'grid':<10} {_fmt(cur['grid_resolution'])} at {_fmt(cur.get('voxel_size'))}")
    if "runtime_s" in cur:
        rep.lines.append(f"{'runtime':<10} {_fmt(cur['runtime_s'])} s")

    # --- warnings -----------------------------------------------------------
    solids = counts.get("solids")
    expect = expected_solids if expected_solids is not None else cur.get("expected_solids")
    if solids is not None and expect is not None and int(solids) != int(expect):
        rep.warn("solid_count", "solids", solids, str(expect),
                 f"solids {solids} != expected {expect}: the part is in pieces (or joined to another)",
                 why="a part that renders whole can be several bodies", layer=layer_of.get("expected_solids", "default"),
                 fix="join the bodies (or separate them), or set expected_solids for a multi-body part")
    if cur.get("short_edges"):
        rep.warn("short_edge", "short_edges", cur["short_edges"], f"none under {short_edge_mm:g} mm",
                 f"{cur['short_edges']} edge(s) shorter than {short_edge_mm:g} mm "
                 f"(shortest {_fmt(cur.get('min_edge_mm'))}): skins, slivers or a skim ridge",
                 why="slivers break fillets and slicers", layer=layer_of.get("short_edge_mm", "default"),
                 fix="find the step that left them (a section or a fillet probe) and remove what made it")
    if cur.get("is_valid") is False:
        rep.warn("valid_shape", "is_valid", False, "True", "kernel reports the shape invalid",
                 fix="rebuild the last feature on its own and check it before the next")
    hidden = census_hides_analytic(census)
    if hidden:
        rep.warn("census_hides", "face_census", f"{int((census or {}).get('bspline', 0))} BSpline faces",
                 f"under {BSPLINE_HIDES_FRACTION:.0%} BSpline faces", hidden,
                 why="a census of splines cannot count cylinders, cones, spheres or tori",
                 fix="measure the features with probe section or probe rays instead of reading the census")
    if cur.get("twisted_faces"):
        # warn about faces that are a body of the part, not thread slivers
        detail = [d for d in (cur.get("twisted_faces_detail") or [])
                  if d.get("area_frac") is None or d["area_frac"] >= _TWIST_AREA_FRAC]
        if detail:
            where = "; ".join(f"{d.get('type')} at {_fmt(d.get('center'))} turns {d.get('max_turn_deg')} deg "
                              f"({100 * (d.get('area_frac') or 0):.0f}% of the area)" for d in detail[:3])
            rep.warn("twisted_face", "twisted_faces", len(detail), "none",
                     f"{len(detail)} twisted free-form face(s): {where}",
                     fix="align the loft's sections so they do not rotate against each other")
    for key in sorted(cur):
        if key.endswith("_error"):
            rep.warn("measured", key[:-6], None, "a measurement", f"{key[:-6]} not measured: {cur[key]}")

    if have_prev:
        rep.changed = changed_any
        if source_changed and not changed_any:
            rep.warn("no_change", "source", "changed", "a measurable change",
                     "source changed but nothing measurable did: volume, bbox, counts and census "
                     "are identical to the previous iteration (a feature that did not build?)",
                     fix="check the feature built: a volume, face census or solid count delta")
    return rep


def rejudge(records: Sequence[Mapping[str, Any]], *, expected_solids: Optional[int] = None,
            short_edge_mm: float = 0.25, limits_from: Optional[Mapping[str, str]] = None) -> List[Optional[Report]]:
    """The reports of a run of iteration records (each with ``metadata`` and ``source_hash``),
    judged against the given rules: what a stored session says under today's settings. A record
    without metadata (written before measurements were kept) gets None."""
    reports: List[Optional[Report]] = []
    prev = None
    for rec in records:
        meta = rec.get("metadata") or {}
        if not meta:
            reports.append(None)
            prev = None
            continue
        changed = None
        if prev is not None and prev.get("source_hash") and rec.get("source_hash"):
            changed = prev["source_hash"] != rec["source_hash"]
        reports.append(feature_effect(prev.get("metadata") if prev else None, meta, source_changed=changed,
                                      expected_solids=expected_solids, short_edge_mm=short_edge_mm,
                                      limits_from=limits_from))
        prev = rec
    return reports


def render_lines(rep: Report, indent: str = "  ") -> List[str]:
    """The report as printable lines: the tray, then the warnings."""
    out = [f"{indent}{line}" for line in rep.lines]
    for w in rep.warnings:
        out.append(f"{indent}warning: {w}")
    return out
