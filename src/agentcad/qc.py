"""QC: design rules judged before a print, as findings.

A rule's limit comes from layers: the printer's process defaults (``agentcad.printers``), then
the project's ``[qc]`` table; a feature's own annotation will be the third. Every finding names
the layer that set its limit. A rule with a limit but no measurement yet is listed as not
measured, never as a finding: QC never fails a part on a number it did not take.

The ``[qc]`` table::

    [qc]
    gate = true                                # finalize holds the manifest back on an error
    printer = "mk4"                            # default: the [print] printer_profile, else mk4
    limits = { min_wall_mm = 1.6 }             # over the printer's process defaults
    severity = { build_volume = "warning" }    # error | warning | off, per rule
    pose = { up = [1, 0, 0], spin_deg = 0 }    # the print pose: the part's direction that points
                                               # up on the bed, then a turn about z

Measured now: ``build_volume``, the part's extent in the print pose against the printer's build
volume. The footprint may turn about z on the bed; a part that fits only turned is a warning
that names the turn, one that fits at no turn (or is too tall) is an error.
"""

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from agentcad import printers
from agentcad.findings import Finding

#: Rules QC measures, with their default severity.
RULES = {"build_volume": "error"}
SEVERITIES = ("error", "warning", "off")


@dataclass
class QCSettings:
    gate: bool = False
    printer: Optional[str] = None
    limits: Dict[str, float] = field(default_factory=dict)
    severity: Dict[str, str] = field(default_factory=dict)
    pose: Optional[Dict[str, Any]] = None

    @classmethod
    def from_table(cls, table: Dict[str, Any]) -> "QCSettings":
        severity = {str(k): str(v).lower() for k, v in (table.get("severity") or {}).items()}
        bad = {k: v for k, v in severity.items() if v not in SEVERITIES}
        if bad:
            raise ValueError(f"[qc] severity: each rule is one of {', '.join(SEVERITIES)}, not {bad}")
        return cls(gate=bool(table.get("gate", False)), printer=table.get("printer"),
                   limits={str(k): float(v) for k, v in (table.get("limits") or {}).items()},
                   severity=severity, pose=dict(table["pose"]) if table.get("pose") else None)


def settings(cfg) -> Optional[QCSettings]:
    """The project's QC settings, or None when it declares no ``[qc]`` table."""
    table = getattr(cfg, "qc", None)
    return QCSettings.from_table(table) if table is not None else None


def printer_for(cfg, qs: QCSettings, override: Optional[str] = None) -> printers.Printer:
    """The printer QC judges against: ``override``, else ``[qc] printer``, else the printer whose
    label is the project's ``[print] printer_profile``, else the MK4."""
    name = override or qs.printer
    if name:
        return printers.get(name, cfg)
    profile = getattr(getattr(cfg, "print", None), "printer_profile", "")
    return printers.by_label(profile, cfg) or printers.get("mk4", cfg)


def limits(printer: printers.Printer, qs: QCSettings) -> Dict[str, Tuple[float, str]]:
    """Each rule's limit and the layer that set it."""
    out = {k: (float(v), printer.defaults_layer()) for k, v in printer.defaults().items()}
    for k, v in qs.limits.items():
        out[k] = (float(v), "project [qc]")
    return out


def pose_rotation(pose: Optional[Dict[str, Any]]):
    """The rotation taking the part to its print pose: ``up`` (default +z) onto +z, then
    ``spin_deg`` about z."""
    import numpy as np
    pose = pose or {}
    up = np.array(pose.get("up", (0.0, 0.0, 1.0)), dtype=float)
    if up.shape != (3,) or not np.linalg.norm(up):
        raise ValueError(f"[qc] pose up must be a non-zero vector [x, y, z], not {pose.get('up')!r}")
    up /= np.linalg.norm(up)
    z = np.array([0.0, 0.0, 1.0])
    axis, c = np.cross(up, z), float(np.dot(up, z))
    if np.linalg.norm(axis) < 1e-12:
        R = np.eye(3) if c > 0 else np.diag([1.0, -1.0, -1.0])        # already up, or upside down
    else:
        k = axis / np.linalg.norm(axis)
        K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
        s = math.sqrt(max(0.0, 1.0 - c * c))
        R = np.eye(3) + s * K + (1 - c) * (K @ K)                     # Rodrigues: up onto z
    a = math.radians(float(pose.get("spin_deg", 0.0)))
    spin = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
    return spin @ R


def _footprint(P, deg: float):
    import numpy as np
    a = math.radians(deg)
    xy = P[:, :2] @ np.array([[math.cos(a), math.sin(a)], [-math.sin(a), math.cos(a)]])
    return xy.max(axis=0) - xy.min(axis=0)


def check_build_volume(vertices, printer: printers.Printer, pose: Optional[Dict[str, Any]] = None,
                       severity: str = "error") -> Finding:
    """The part's extent in the print pose against the printer's build volume."""
    import numpy as np
    P = np.asarray(vertices, dtype=float) @ pose_rotation(pose).T
    ext = P.max(axis=0) - P.min(axis=0)
    X, Y, Z = printer.build_volume
    eps = 1e-6 * max(1.0, float(ext.max()))
    found = f"{ext[0]:.1f} x {ext[1]:.1f} x {ext[2]:.1f} mm"
    intended = f"within {X:g} x {Y:g} x {Z:g} mm ({printer.label})"
    layer = f"printer {printer.name} ({printer.label}, {printer.source})"

    def finding(sev: str, message: str, fix: str = "") -> Finding:
        if sev == "error" and severity == "warning":
            sev = "warning"
        return Finding("extent", sev, found, intended, "a part that does not fit the build volume cannot print",
                       f"[qc] on {printer.name}", rule="build_volume", layer=layer, fix=fix, message=message)

    if ext[2] > Z + eps:
        return finding("error", f"{found} in the print pose: {ext[2]:.1f} mm tall against the {printer.label}'s "
                                f"{Z:g} mm; no turn about z helps",
                       "lay the part down (a [qc] pose up direction), split it, or choose a printer with more height")
    fits = lambda w: w[0] <= X + eps and w[1] <= Y + eps
    if fits(ext):
        return finding("ok", f"{found} in the print pose fits the {printer.label}'s {X:g} x {Y:g} x {Z:g} mm")
    for deg in [90] + [d for d in range(1, 180) if d != 90]:      # a quarter turn first, then the smallest that fits
        if fits(_footprint(P, deg)):
            return finding("warning", f"{found} in the print pose fits the {X:g} x {Y:g} mm bed only spun {deg} "
                                      f"degrees about z", f"set [qc] pose spin_deg = {deg}, and place it so on the bed")
    return finding("error", f"{found} in the print pose: the footprint fits the {X:g} x {Y:g} mm bed at no turn about z",
                   "re-pose the part, split it, or choose a printer with a larger bed")


def mesh_vertices(stl: Optional[Path]):
    """The vertices of an STL, or None when it is missing or unreadable (QC then measures nothing)."""
    if stl is None or not Path(stl).is_file():
        return None
    try:
        from agentcad.meshmeasure import read_stl
        V, _ = read_stl(Path(stl))
        return V if len(V) else None
    except Exception:
        return None


def run(cfg, vertices, qs: QCSettings, printer_override: Optional[str] = None) -> Dict[str, Any]:
    """Judge one part: the printer, every limit with its layer, the findings, and the rules not
    measured (with why)."""
    printer = printer_for(cfg, qs, printer_override)
    found: List[Finding] = []
    not_measured: Dict[str, str] = {}
    for rule, default in RULES.items():
        severity = qs.severity.get(rule, default)
        if severity == "off":
            not_measured[rule] = "turned off in [qc] severity"
        elif vertices is None:
            not_measured[rule] = "no mesh of the part to measure"
        else:
            found.append(check_build_volume(vertices, printer, qs.pose, severity))
    lim = limits(printer, qs)
    for rule in lim:
        not_measured.setdefault(rule, "no measurement for this rule yet")
    return {"printer": printer.to_dict(), "pose": qs.pose or {"up": [0, 0, 1], "spin_deg": 0}, "gate": qs.gate,
            "limits": {k: {"value": v, "layer": layer} for k, (v, layer) in lim.items()},
            "findings": [f.to_dict() for f in found], "not_measured": not_measured}


def errors(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [f for f in report.get("findings", []) if f.get("severity") == "error"]
