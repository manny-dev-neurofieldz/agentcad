"""Subprocess worker for the build123d engine.

Usage: python -m agentcad.engines.build123d_worker JOB_JSON

The engine writes a job file, runs this module with a timeout, and reads the
result file the job names. Everything that touches the OCCT kernel happens
here, so a hung kernel call is a timeout in the parent and never a stuck CLI.

The job is a dict with:
    mode:         "render" | "export" | "validate"
    source_path:  file to execute (render/export) or None
    code:         source text (validate)
    defines:      {name: str} overrides
    result_path:  where to write the result JSON
    tolerance, angular_tolerance: tessellation controls (tolerance may be None
                  for "relative to the bounding-box diagonal")
    render:       {output_dir, stem, image_size, views: [{name, eye, up,
                  orthographic, distance}], color, background, edge_color}
    export:       {output_path, fmt}

The result is a dict with errors, warnings, images {view: path},
output_path, facet_count and metadata (measured facts about the shape).
"""

import ast
import json
import math
import os
import struct
import sys
import time
import traceback
from typing import Any, Dict, List, Optional


def _last_line(exc: BaseException) -> str:
    return traceback.format_exception_only(type(exc), exc)[-1].strip()


def _bootstrap():
    """Import build123d with the libexpat load-order shim applied first.

    Also registers a no-op ``ocp_vscode`` when the real one is absent: sources
    written for the interactive viewer call ``show(...)``, which has no meaning
    in a headless worker and must not be the reason a render fails.
    """
    import pyexpat  # noqa: F401  (must precede build123d on some containers)
    import build123d as b3d
    try:
        import ocp_vscode  # noqa: F401
    except ImportError:
        import types

        stub = types.ModuleType("ocp_vscode")
        stub.__doc__ = "agentcad headless stand-in: every viewer call is a no-op"

        def _noop(*args, **kwargs):
            return None

        def _getattr(name):
            return _noop

        stub.__getattr__ = _getattr  # type: ignore[attr-defined]
        for fn in ("show", "show_object", "show_all", "show_clear", "set_defaults", "set_port", "reset_show"):
            setattr(stub, fn, _noop)
        sys.modules["ocp_vscode"] = stub
    return b3d


# --- harvesting ---------------------------------------------------------------

def _unwrap(b3d, obj):
    """Builder context -> its product; list of shapes -> Compound; Shape -> itself."""
    if isinstance(obj, b3d.Builder):
        for attr in ("part", "sketch", "line"):
            value = getattr(obj, attr, None)
            if value is not None:
                return value
        return None
    if isinstance(obj, b3d.Shape):
        return obj
    if isinstance(obj, (list, tuple)) and obj and all(isinstance(o, b3d.Shape) for o in obj):
        return b3d.Compound(children=list(obj))
    return None


HARVEST_NAMES = ("part", "result", "model")


def _harvest(b3d, namespace: Dict[str, Any], defines: Dict[str, str], warnings: List[str]):
    """The shape a source produced: build(**params) first, else a named module-level object."""
    from agentcad.params import coerce_defines

    build = namespace.get("build")
    if callable(build):
        params = coerce_defines(defines, build)
        produced = build(**params)
        shape = _unwrap(b3d, produced)
        if shape is None:
            raise TypeError(f"build() returned {type(produced).__name__}, not a build123d shape or builder")
        return shape
    if defines:
        warnings.append(f"Overrides {sorted(defines)} ignored: source defines no build(**params)")
    for name in HARVEST_NAMES:
        if name in namespace:
            shape = _unwrap(b3d, namespace[name])
            if shape is None:
                raise TypeError(f"'{name}' is {type(namespace[name]).__name__}, not a build123d shape or builder")
            return shape
    # Last resort: the biggest, most solid thing the module left behind. Named
    # in a warning because a size heuristic can pick an intermediate over the
    # intended product in a multi-body script.
    best = None
    for name, value in namespace.items():
        if name.startswith("_"):
            continue
        shape = _unwrap(b3d, value)
        if shape is None:
            continue
        score = _rank(shape)
        if best is None or score > best[0]:
            best = (score, name, shape)
    if best is None:
        raise LookupError(
            "Source must define build(**params) returning the shape, or assign it to "
            "'part' (or 'result'/'model'); no build123d shape was found"
        )
    warnings.append(
        f"No build() or part/result/model: harvested '{best[1]}' as the largest shape "
        f"(name the product explicitly to silence this)"
    )
    return best[2]


def _rank(shape):
    """Bigger, more solid things win when no product name is given."""
    try:
        if shape.solids():
            return (3, float(shape.volume))
        if shape.faces():
            return (2, float(shape.area))
        if shape.edges():
            return (1, sum(e.length for e in shape.edges()))
    except Exception:  # unrankable geometry simply ranks last
        pass
    return (0, 0.0)


def _execute(source_path: str) -> Dict[str, Any]:
    code = open(source_path).read()
    namespace: Dict[str, Any] = {"__name__": "__agentcad_source__", "__file__": os.path.abspath(source_path)}
    cwd = os.getcwd()
    os.chdir(os.path.dirname(os.path.abspath(source_path)) or ".")
    try:
        exec(compile(code, source_path, "exec"), namespace)
    finally:
        os.chdir(cwd)
    return namespace


# --- measurement --------------------------------------------------------------

def _kind(shape) -> str:
    if shape.solids():
        return "3d"
    if shape.faces():
        return "2d"
    return "1d"


def _measure(b3d, shape) -> Dict[str, Any]:
    """Measured facts; each item is best-effort and reports its own failure."""
    m: Dict[str, Any] = {"build123d_version": getattr(b3d, "__version__", None), "kind": _kind(shape)}
    try:
        bb = shape.bounding_box()
        m["bbox_min"] = [bb.min.X, bb.min.Y, bb.min.Z]
        m["bbox_size"] = [bb.size.X, bb.size.Y, bb.size.Z]
    except Exception as e:  # kernel call on user geometry: anything can come back
        m["bbox_error"] = _last_line(e)
    for name in ("volume", "area"):
        try:
            m[name] = float(getattr(shape, name))
        except Exception as e:
            m[f"{name}_error"] = _last_line(e)
    try:
        c = shape.center(b3d.CenterOf.MASS) if m["kind"] != "1d" else shape.center()
        m["center_of_mass"] = [c.X, c.Y, c.Z]
    except Exception as e:
        m["center_error"] = _last_line(e)
    try:
        m["counts"] = {
            "solids": len(shape.solids()), "faces": len(shape.faces()),
            "edges": len(shape.edges()), "vertices": len(shape.vertices()),
        }
    except Exception as e:
        m["counts_error"] = _last_line(e)
    try:
        v = shape.is_valid
        m["is_valid"] = bool(v() if callable(v) else v)
    except Exception as e:
        m["is_valid_error"] = _last_line(e)
    return m


def _diag(shape) -> float:
    bb = shape.bounding_box()
    return max(1e-6, math.sqrt(bb.size.X ** 2 + bb.size.Y ** 2 + bb.size.Z ** 2))


def _tolerances(job: Dict[str, Any], shape):
    tol = job.get("tolerance")
    if tol is None:
        # Relative default: a 300 mm part tessellates at 0.3 mm. Fine enough
        # for renders and printable meshes; a heavily filleted part at 1/2000
        # produced a 134 MB STL, which is why this is 1/1000.
        tol = _diag(shape) / 1000.0
    ang = job.get("angular_tolerance") or 0.1
    return float(tol), float(ang)


# --- render -------------------------------------------------------------------

def _edge_polylines(b3d, shape, seg_len: float):
    import numpy as np
    import pyvista as pv

    lines = []
    for e in shape.edges():
        try:
            if e.geom_type == b3d.GeomType.LINE:
                pts = [e.position_at(0), e.position_at(1)]
            else:
                n = max(8, int(e.length / seg_len) + 1)
                pts = [e.position_at(t) for t in np.linspace(0, 1, n)]
            arr = np.array([[p.X, p.Y, p.Z] for p in pts])
            if len(arr) >= 2:
                lines.append(pv.lines_from_points(arr))
        except Exception:  # one bad edge must not lose the picture
            continue
    return pv.merge(lines) if lines else None


def _render(b3d, shape, job: Dict[str, Any], out: Dict[str, Any]) -> None:
    try:
        import numpy as np
        import pyvista as pv
    except ImportError as e:
        out["errors"].append(f"pyvista unavailable for rendering: {_last_line(e)}")
        return
    pv.OFF_SCREEN = True

    spec = job["render"]
    output_dir = spec["output_dir"]
    os.makedirs(output_dir, exist_ok=True)
    size = int(spec.get("image_size", 1024))
    tol, ang = _tolerances(job, shape)
    kind = _kind(shape)

    mesh = None
    if kind in ("3d", "2d"):
        verts, tris = shape.tessellate(tolerance=tol, angular_tolerance=ang)
        if tris:
            V = np.array([[v.X, v.Y, v.Z] for v in verts])
            F = np.array(tris)
            faces = np.hstack([np.full((len(F), 1), 3), F]).ravel()
            mesh = pv.PolyData(V, faces)
    edges = _edge_polylines(b3d, shape, _diag(shape) / 200.0)

    bb = shape.bounding_box()
    center = (bb.center().X, bb.center().Y, bb.center().Z)
    radius = max(_diag(shape) / 2.0, 1e-6)

    for view in spec["views"]:
        name = view["name"]
        path = os.path.join(output_dir, f"{spec['stem']}_{name}.png")
        plotter = pv.Plotter(off_screen=True, window_size=[size, size])
        plotter.set_background(spec.get("background", "white"))
        if mesh is not None:
            # Smooth shading interpolates vertex normals (PyVista splits them at
            # sharp edges, so corners stay crisp). Flat shading paints each
            # triangle with its own normal, which on a lofted or twisted face
            # shows the tessellation as a crumpled surface even though the
            # B-rep is smooth.
            smooth = spec.get("shading", "smooth") != "flat"
            plotter.add_mesh(mesh, color=spec.get("color", "#cfd8e3"), smooth_shading=smooth, specular=0.15)
        if edges is not None:
            plotter.add_mesh(edges, color=spec.get("edge_color", "black"), line_width=2)
        d = view.get("distance") or 0.0
        d = d if d > 0 else radius * 2.5
        eye = view["eye"]
        position = (center[0] + eye[0] * d, center[1] + eye[1] * d, center[2] + eye[2] * d)
        plotter.camera_position = [position, center, tuple(view["up"])]
        if view.get("orthographic"):
            plotter.enable_parallel_projection()
        plotter.reset_camera()
        plotter.screenshot(path)
        plotter.close()
        if os.path.exists(path) and os.path.getsize(path) > 0:
            out["images"][name] = path
        else:
            out["errors"].append(f"{name}: screenshot produced no file")


# --- export -------------------------------------------------------------------

def _stl_facets(path: str) -> int:
    with open(path, "rb") as f:
        head = f.read(84)
    size = os.path.getsize(path)
    if len(head) == 84 and not head.startswith(b"solid"):
        return struct.unpack_from("<I", head, 80)[0]
    if size > 84 and head.startswith(b"solid") and (size - 84) % 50 == 0:
        # a binary file whose header happens to start with "solid"
        return (size - 84) // 50
    with open(path, "rb") as f:
        return sum(1 for line in f if b"facet normal" in line)


def _export(b3d, shape, job: Dict[str, Any], out: Dict[str, Any]) -> None:
    spec = job["export"]
    path = spec["output_path"]
    fmt = spec["fmt"]
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tol, ang = _tolerances(job, shape)

    if fmt == "stl":
        b3d.export_stl(shape, path, tolerance=tol, angular_tolerance=ang)
        out["facet_count"] = _stl_facets(path)
    elif fmt == "step":
        b3d.export_step(shape, path)
    elif fmt == "3mf":
        mesher = b3d.Mesher()
        mesher.add_shape(shape, linear_deflection=tol, angular_deflection=ang)
        mesher.write(path)
        _, tris = shape.tessellate(tolerance=tol, angular_tolerance=ang)
        out["facet_count"] = len(tris)
    elif fmt == "svg":
        kind = _kind(shape)
        origin = (-100, -100, 70) if kind == "3d" else (0, 0, 100)
        visible, hidden = shape.project_to_viewport(origin)
        allshapes = list(visible) + list(hidden)
        if not allshapes:
            raise ValueError("nothing to project for SVG")
        maxdim = max(b3d.Compound(children=allshapes).bounding_box().size)
        exporter = b3d.ExportSVG(scale=120.0 / max(maxdim, 1e-6))
        exporter.add_layer("Visible")
        exporter.add_layer("Hidden", line_color=(120, 120, 120), line_type=b3d.LineType.ISO_DOT)
        exporter.add_shape(visible, layer="Visible")
        if hidden:
            exporter.add_shape(hidden, layer="Hidden")
        exporter.write(path)
    else:
        raise ValueError(f"unsupported format {fmt!r}")

    if os.path.exists(path) and os.path.getsize(path) > 0:
        out["output_path"] = path
    else:
        out["errors"].append(f"{fmt} export produced no file")


# --- validate -----------------------------------------------------------------

def _validate(job: Dict[str, Any], out: Dict[str, Any]) -> None:
    """compile() plus an import-only dry run: every import statement is executed, nothing else."""
    code = job["code"]
    try:
        tree = compile(code, "<build123d>", "exec", ast.PyCF_ONLY_AST)
    except SyntaxError as e:
        out["errors"].append(f"Line {e.lineno}: {e.msg}")
        return
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    module = ast.Module(body=imports, type_ignores=[])
    ast.fix_missing_locations(module)
    try:
        _bootstrap()
        exec(compile(module, "<build123d imports>", "exec"), {"__name__": "__agentcad_validate__"})
    except Exception as e:  # any import failure is the finding
        out["errors"].append(_last_line(e))


# --- entry --------------------------------------------------------------------

def run(job: Dict[str, Any], out: Dict[str, Any]) -> None:
    mode = job["mode"]
    if mode == "validate":
        _validate(job, out)
        return
    t0 = time.monotonic()
    b3d = _bootstrap()
    namespace = _execute(job["source_path"])
    shape = _harvest(b3d, namespace, job.get("defines") or {}, out["warnings"])
    out["metadata"] = _measure(b3d, shape)
    out["metadata"]["runtime_s"] = round(time.monotonic() - t0, 3)
    if mode == "render":
        _render(b3d, shape, job, out)
    elif mode == "export":
        _export(b3d, shape, job, out)
    else:
        raise ValueError(f"unknown mode {mode!r}")


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: build123d_worker JOB_JSON", file=sys.stderr)
        return 2
    with open(argv[0]) as f:
        job = json.load(f)
    out: Dict[str, Any] = {"errors": [], "warnings": [], "images": {}, "output_path": None,
                           "facet_count": 0, "metadata": {}}
    try:
        run(job, out)
    except Exception as e:  # the worker's whole job is to turn any failure into a result record
        out["errors"].append(_last_line(e))
        out["traceback"] = traceback.format_exc()
    with open(job["result_path"], "w") as f:
        json.dump(out, f, indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
