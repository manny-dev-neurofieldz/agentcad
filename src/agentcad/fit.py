"""Fit: pose two parts and measure whether they mate.

A mate stated in one program is a hypothesis; only a check with both bodies
tests it. ``fit`` loads two exact shapes (STEP or build123d sources, each
with its own defines), poses the second by an optional transform, and
reports:

* ``interference_mm3``: the volume of their intersection (zero is the only
  passing value for parts that must not touch);
* ``clearance_mm``: the minimum distance between the bodies (line-to-line
  mates read 0.000 here while every single-part instrument passes);
* per named window, the minimum distance between the two surfaces inside
  an axis-aligned box, so a key tip and a flange are read separately;
* an insertion sweep along an axis: the interference at each step of the
  second body sliding in, so a part that binds on the way in is seen.

Declared mates come from a ``[mates]`` table in the project's
``agentcad.toml`` (name -> window box and optional nominal clearance);
``--map`` gives the pose when no declaration exists. Renders through the
build123d engine's camera presets show the pair assembled and exploded.
"""

import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


def _b3d():
    from agentcad.engines.build123d_worker import _bootstrap
    return _bootstrap()


def pose(shape, offset: Sequence[float] = (0, 0, 0), spin_deg: float = 0.0, axis: str = "z"):
    """The shape moved by ``offset`` after a rotation of ``spin_deg`` about ``axis``."""
    b3d = _b3d()
    rot = {"x": (spin_deg, 0, 0), "y": (0, spin_deg, 0), "z": (0, 0, spin_deg)}[axis.lower()]
    return b3d.Pos(*offset) * (b3d.Rot(*rot) * shape)


def interference(a, b) -> float:
    try:
        common = a & b
        return float(common.volume) if common is not None else 0.0
    except Exception as e:  # a failed boolean is reported, never read as zero
        print(f"agentcad fit: intersection failed ({e}); interference unknown", file=sys.stderr)
        return float("nan")


def clearance(a, b) -> float:
    try:
        return float(a.distance_to(b))
    except Exception as e:
        print(f"agentcad fit: distance failed ({e})", file=sys.stderr)
        return float("nan")


def _points(shape, tol: float):
    import numpy as np
    verts, _ = shape.tessellate(tolerance=tol, angular_tolerance=0.1)
    return np.array([[v.X, v.Y, v.Z] for v in verts])


def window_clearances(a, b, windows: Dict[str, Sequence[float]], tol: Optional[float] = None) -> Dict[str, Any]:
    """Minimum surface-to-surface distance inside each window box (x0,y0,z0,x1,y1,z1), both ways."""
    import numpy as np
    from scipy.spatial import cKDTree

    bb = a.bounding_box()
    diag = math.sqrt(bb.size.X ** 2 + bb.size.Y ** 2 + bb.size.Z ** 2)
    tol = tol or diag / 2000.0
    A, B = _points(a, tol), _points(b, tol)
    out: Dict[str, Any] = {}
    for name, box in windows.items():
        lo, hi = np.array(box[:3], dtype=float), np.array(box[3:], dtype=float)
        ia = A[np.all((A >= lo) & (A <= hi), axis=1)]
        ib = B[np.all((B >= lo) & (B <= hi), axis=1)]
        if len(ia) == 0 or len(ib) == 0:
            out[name] = {"note": "one side has no surface in this window", "n_a": int(len(ia)), "n_b": int(len(ib))}
            continue
        d_ab = cKDTree(ib).query(ia)[0]
        d_ba = cKDTree(ia).query(ib)[0]
        out[name] = {"min_mm": float(min(d_ab.min(), d_ba.min())), "p05_mm": float(np.percentile(np.concatenate([d_ab, d_ba]), 5)),
                     "n_a": int(len(ia)), "n_b": int(len(ib))}
    return out


def insertion_sweep(a, b, axis: str = "z", travel: float = 10.0, steps: int = 10) -> List[Dict[str, float]]:
    """Interference of ``b`` at each step as it slides ``travel`` along ``axis`` into place (from out to in)."""
    b3d = _b3d()
    unit = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}[axis.lower()]
    rows = []
    for i in range(steps, -1, -1):
        s = travel * i / steps
        moved = b3d.Pos(unit[0] * s, unit[1] * s, unit[2] * s) * b
        rows.append({"offset_mm": s, "interference_mm3": interference(a, moved)})
    return rows


def _assembly_frame(source: Path, defines):
    """A build123d program whose build() takes print_orient gets it False unless the caller set it:
    parts are compared in the assembly frame, not oriented for a print bed."""
    import inspect
    defines = dict(defines or {})
    if Path(source).suffix.lower() == ".py" and "print_orient" not in defines:
        try:
            from agentcad.engines.build123d_worker import _execute
            build = _execute(str(Path(source).resolve())).get("build")
            if callable(build) and "print_orient" in inspect.signature(build).parameters:
                defines["print_orient"] = "false"
        except Exception as e:  # a source that will not import fails later, with its own message
            print(f"agentcad fit: could not inspect {source} for print_orient ({e})", file=sys.stderr)
    return defines


def fit(a_source: Path, b_source: Path, *, a_defines=None, b_defines=None,
        offset=(0, 0, 0), spin_deg=0.0, spin_axis="z", windows: Optional[Dict[str, Sequence[float]]] = None,
        sweep_axis: Optional[str] = None, sweep_travel: float = 10.0,
        out_dir: Optional[Path] = None) -> Dict[str, Any]:
    from agentcad.probe import load_shape

    a_defines, b_defines = _assembly_frame(a_source, a_defines), _assembly_frame(b_source, b_defines)
    a = load_shape(Path(a_source), a_defines)
    b = pose(load_shape(Path(b_source), b_defines), offset, spin_deg, spin_axis)
    result: Dict[str, Any] = {
        "a": str(a_source), "b": str(b_source),
        "pose": {"offset": list(offset), "spin_deg": spin_deg, "spin_axis": spin_axis},
        "interference_mm3": interference(a, b),
        "clearance_mm": clearance(a, b),
    }
    if windows:
        try:
            result["windows"] = window_clearances(a, b, windows)
        except ImportError as e:
            result["windows_error"] = f"scipy unavailable: {e}"
    if sweep_axis:
        result["insertion"] = insertion_sweep(a, b, sweep_axis, sweep_travel)
    if out_dir is not None:
        result["renders"] = _render_pair(a, b, Path(out_dir))
    return result


def _render_pair(a, b, out_dir: Path) -> Dict[str, str]:
    """Assembled and exploded views of the pair through PyVista (best effort)."""
    try:
        import numpy as np
        import pyvista as pv
    except ImportError as e:
        print(f"agentcad fit: renders skipped (pyvista unavailable: {e})", file=sys.stderr)
        return {}
    b3d = _b3d()
    out_dir.mkdir(parents=True, exist_ok=True)
    pv.OFF_SCREEN = True

    def mesh_of(shape):
        bb = shape.bounding_box()
        tol = max(math.sqrt(bb.size.X ** 2 + bb.size.Y ** 2 + bb.size.Z ** 2) / 1000.0, 1e-4)
        verts, tris = shape.tessellate(tolerance=tol, angular_tolerance=0.1)
        V = np.array([[v.X, v.Y, v.Z] for v in verts]); F = np.array(tris)
        return pv.PolyData(V, np.hstack([np.full((len(F), 1), 3), F]).ravel())

    renders = {}
    bb = (a + b).bounding_box() if True else a.bounding_box()
    explode = max(bb.size.X, bb.size.Y, bb.size.Z) * 0.6
    for name, shift in (("assembled", 0.0), ("exploded", explode)):
        plotter = pv.Plotter(off_screen=True, window_size=[900, 900])
        plotter.set_background("white")
        plotter.add_mesh(mesh_of(a), color="#cfd8e3", smooth_shading=True, specular=0.15)
        plotter.add_mesh(mesh_of(b3d.Pos(0, 0, shift) * b), color="#e94560", smooth_shading=True, specular=0.15, opacity=0.85)
        plotter.camera_position = "iso"
        plotter.reset_camera()
        path = out_dir / f"fit_{name}.png"
        plotter.screenshot(str(path)); plotter.close()
        renders[name] = str(path)
    return renders


def load_mates(project_dir: Path) -> Dict[str, Any]:
    """The [mates] table of a project's agentcad.toml: name -> {window: [x0,y0,z0,x1,y1,z1], nominal_mm}."""
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore
        except ImportError:
            return {}
    path = Path(project_dir) / "agentcad.toml"
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return dict(data.get("mates") or {})


def write_json(data: Dict[str, Any], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, default=float))
    return path
