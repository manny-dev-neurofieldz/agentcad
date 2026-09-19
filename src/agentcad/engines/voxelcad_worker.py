"""Subprocess worker for the VoxelCAD engine.

Usage: python -m agentcad.engines.voxelcad_worker JOB_JSON

The engine writes a job file, runs this module with a timeout
(``agentcad.engines.subprocess_worker``), and reads the result file the job
names. Everything that allocates a voxel grid happens here, so an oversize
grid or an out-of-memory kill is reported as an error in the parent and
never takes the CLI down.

The job is a dict with:
    mode:         "render" | "export"
    source_path:  file to execute
    defines:      {name: str} overrides
    result_path:  where to write the result JSON
    resolution:   {voxel_size: float|None, grid: int, warn_voxels: int}
                  voxel_size None means "size the grid from the model's extent
                  so its longest side spans `grid` voxels"
    render:       {output_dir, stem, image_size, views: [{name, eye, up,
                  orthographic, distance}], color, background}
    export:       {output_path, fmt}

The result is a dict with errors, warnings, images {view: path},
output_path, facet_count and metadata (measured facts about the model).

Resolution. VoxelCAD primitives take their voxel size from
``voxelcad.environment.voxel_size`` at construction, and a model's grid
limits are known before any volume is rendered. So the grid target is
applied in two passes: the source is executed once at a coarse probe size
to read the extent, the voxel size is derived from it, and the source is
executed again at that size. A boolean's rendered grid can differ from its
pre-render grid, so one corrective rebuild follows when the rendered grid
overshoots the target by more than a quarter. An explicit voxel size skips
all of that.
"""

import json
import math
import os
import struct
import sys
import time
import traceback
from typing import Any, Dict, List, Optional

_PROBE_VOXEL = 1.0          # coarse first pass: only the grid limits are read
_PROBE_MIN_CELLS = 4        # below this many cells the probe is re-run finer


def _last_line(exc: BaseException) -> str:
    return traceback.format_exception_only(type(exc), exc)[-1].strip()


# --- source execution and harvest ---------------------------------------------

def _execute(source_path: str) -> Dict[str, Any]:
    with open(source_path) as f:
        code = f.read()
    namespace: Dict[str, Any] = {"__file__": source_path, "__name__": "__agentcad_source__"}
    exec(compile(code, source_path, "exec"), namespace)
    return namespace


def _harvest(namespace: Dict[str, Any], defines: Dict[str, str], warnings: List[str], *, report: bool):
    """The model a source produced: build(**params) first, else the module-level ``model``.

    ``report`` controls whether the ignored-overrides warning is emitted, so a
    two-pass execution warns once.
    """
    from agentcad.params import coerce_defines

    build = namespace.get("build")
    if callable(build):
        params = coerce_defines(defines, build)
        model = build(**params)
        if model is None:
            raise TypeError("build() returned None, not a VoxelCAD model")
        return model
    if defines and report:
        warnings.append(f"Overrides {sorted(defines)} ignored: source defines no build(**params)")
    model = namespace.get("model")
    if model is None:
        raise ValueError(
            "Script must define build(**params) returning the model, or assign it to a "
            "variable named 'model'. Example: model = Sphere(r=5) & Cube(size=8, center=True)"
        )
    return model


def _extent(model) -> List[float]:
    g = model.grid
    return [float(g.xlim[1] - g.xlim[0]), float(g.ylim[1] - g.ylim[0]), float(g.zlim[1] - g.zlim[0])]


def _build_at_resolution(job: Dict[str, Any], out: Dict[str, Any]):
    """Execute the source at the resolved voxel size; returns (model, resolved_voxel_size)."""
    import voxelcad.environment as ENV

    spec = job.get("resolution") or {}
    explicit = spec.get("voxel_size")
    grid_target = int(spec.get("grid") or 256)
    defines = job.get("defines") or {}
    source = job["source_path"]

    if explicit:
        ENV.voxel_size = float(explicit)
        model = _harvest(_execute(source), defines, out["warnings"], report=True)
        model.render_volume()
        return model, float(explicit)

    # Pass 1: a coarse probe to read the model's extent. Refine once if the
    # model is small enough that the probe grid degenerates.
    probe = _PROBE_VOXEL
    for _ in range(3):
        ENV.voxel_size = probe
        probe_model = _harvest(_execute(source), defines, out["warnings"], report=True)
        # Primitives pad their grid by one voxel per side; at the probe size
        # that padding is a large fraction of a small part, so remove it
        # before deriving the cell size from the geometry's own extent.
        longest = max(_extent(probe_model)) - 2.0 * probe
        if longest / probe >= _PROBE_MIN_CELLS:
            break
        probe /= 100.0
    if longest <= 0:
        raise ValueError("model has zero extent; cannot size a grid from it")
    voxel = longest / grid_target
    # Pass 2: the real build at the derived size.
    ENV.voxel_size = voxel
    model = _harvest(_execute(source), defines, out["warnings"], report=False)
    model.render_volume()
    # A boolean's grid before rendering reports one operand's extent while the
    # rendered volume lands on the operands' union grid, so only the rendered
    # grid is trustworthy. When it overshoots the target by more than a
    # quarter, rebuild once at the size the rendered extent implies; the
    # overshoot costs one extra volume at most twice the intended size.
    longest_cells = max(int(v) for v in model.grid.res_vector)
    if longest_cells > 1.25 * grid_target:
        actual = max(_extent(model)) - 2.0 * voxel
        voxel = actual / grid_target
        ENV.voxel_size = voxel
        model = _harvest(_execute(source), defines, out["warnings"], report=False)
        model.render_volume()
        out["warnings"].append("grid sized twice: the boolean's rendered extent differed from its probe extent")
    return model, voxel


# --- measurement --------------------------------------------------------------

def _measure(model, voxel: float, spec: Dict[str, Any]) -> Dict[str, Any]:
    """Measured facts about a rendered model. Every item is best effort with an
    error sibling, so one failed measurement never hides the others."""
    import numpy as np

    md: Dict[str, Any] = {}
    grid = getattr(model, "grid", None)
    if grid is None:
        md["grid_error"] = "model has no grid"
        return md
    try:
        res = [int(v) for v in grid.res_vector]
        vsv = [float(v) for v in grid.voxel_size_vector]
        md["grid_resolution"] = res
        md["voxel_size"] = vsv
        md["grid_target"] = int(spec.get("grid") or 256)
        md["bbox_min"] = [float(grid.xlim[0]), float(grid.ylim[0]), float(grid.zlim[0])]
        md["bbox_size"] = _extent(model)
        md["bbox"] = [list(map(float, grid.xlim)), list(map(float, grid.ylim)), list(map(float, grid.zlim))]
    except (AttributeError, TypeError, ValueError) as e:
        md["grid_error"] = _last_line(e)
        return md

    try:
        total = int(np.prod(res))
        bits = np.unpackbits(model.voxel_data)[:total]
        occupied = int(bits.sum())
        md["occupied_voxels"] = occupied
        md["volume"] = occupied * float(np.prod(vsv))
    except (AttributeError, TypeError, ValueError) as e:
        md["volume_error"] = _last_line(e)
        return md

    try:
        from scipy import ndimage
        # Packed bits are stored Fortran-ordered so Z-slices are contiguous.
        vol = bits.reshape(tuple(res), order="F")
        _, count = ndimage.label(vol)
        md["counts"] = {"solids": int(count)}
    except ImportError as e:
        md["counts_error"] = f"scipy unavailable for connectivity: {e}"
    except (TypeError, ValueError) as e:
        md["counts_error"] = _last_line(e)
    return md


# --- render -------------------------------------------------------------------

def _render(model, job: Dict[str, Any], out: Dict[str, Any]) -> None:
    import pyvista as pv
    pv.OFF_SCREEN = True

    spec = job["render"]
    output_dir = spec["output_dir"]
    os.makedirs(output_dir, exist_ok=True)
    size = int(spec.get("image_size", 1024))

    mesh = model.render_surface_mesh()
    xmin, xmax, ymin, ymax, zmin, zmax = mesh.bounds
    center = ((xmin + xmax) / 2, (ymin + ymax) / 2, (zmin + zmax) / 2)
    radius = max(0.5 * math.sqrt((xmax - xmin) ** 2 + (ymax - ymin) ** 2 + (zmax - zmin) ** 2), 1e-9)

    for view in spec["views"]:
        name = view["name"]
        path = os.path.join(output_dir, f"{spec['stem']}_{name}.png")
        plotter = pv.Plotter(off_screen=True, window_size=[size, size])
        plotter.set_background(spec.get("background", "white"))
        plotter.add_mesh(mesh, color=spec.get("color", "steelblue"), smooth_shading=True)
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
        return (size - 84) // 50
    with open(path, "rb") as f:
        return sum(1 for line in f if b"facet normal" in line)


def _export(model, job: Dict[str, Any], out: Dict[str, Any]) -> None:
    spec = job["export"]
    path = spec["output_path"]
    fmt = spec["fmt"]
    if fmt != "stl":
        raise ValueError(f"unsupported format {fmt!r}")
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    model.export(path)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        out["output_path"] = path
        out["facet_count"] = _stl_facets(path)
    else:
        out["errors"].append("VoxelCAD produced no STL file")


# --- entry --------------------------------------------------------------------

def run(job: Dict[str, Any], out: Dict[str, Any]) -> None:
    mode = job["mode"]
    t0 = time.monotonic()
    model, voxel = _build_at_resolution(job, out)

    spec = job.get("resolution") or {}
    try:
        cells = int(math.prod(int(v) for v in model.grid.res_vector))
    except (AttributeError, TypeError, ValueError):
        cells = 0
    warn_at = int(spec.get("warn_voxels") or 0)
    if warn_at and cells > warn_at:
        out["warnings"].append(
            f"grid of {cells:,} voxels exceeds warn_voxels={warn_at:,} at voxel_size {voxel:.4g}; "
            "raise voxel_size or lower grid to build faster"
        )

    out["metadata"] = _measure(model, voxel, spec)
    out["metadata"]["runtime_s"] = round(time.monotonic() - t0, 3)
    if mode == "render":
        _render(model, job, out)
    elif mode == "export":
        _export(model, job, out)
    else:
        raise ValueError(f"unknown mode {mode!r}")


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: voxelcad_worker JOB_JSON", file=sys.stderr)
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
