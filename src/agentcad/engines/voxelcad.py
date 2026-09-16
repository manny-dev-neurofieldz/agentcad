"""VoxelCAD engine backend.

Executes Python VoxelCAD code, renders via PyVista offscreen, and exports
STL via the SDF + Butterworth smoothed mesh pipeline.

Source contract (shared with every Python-based engine):
    * ``def build(**params)`` returning the model - parameter overrides
      (``-D name=value``) are coerced to the types of the defaults and
      passed in; or
    * a module-level ``model`` - no overrides possible; any given are
      reported as ignored.
"""

import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agentcad.camera import MULTI_VIEW_DEFAULT
from agentcad.engine import (
    CADEngine, Defines, RenderResult, ExportResult, ValidationResult,
)
from agentcad.params import coerce_defines

_DEFAULTS: Dict[str, Any] = {
    "voxel_size": 0.2,
    "color": "steelblue",
    "background": "white",
}


class VoxelCADEngine(CADEngine):
    """VoxelCAD rendering engine with PyVista offscreen and smoothed mesh export."""

    known_settings = ("voxel_size", "color", "background")
    FILE_EXTENSION = ".py"
    EXPORT_FORMATS = ("stl",)

    def __init__(self, settings=None, **overrides):
        super().__init__(settings, **overrides)
        self._voxel_size = self.setting("voxel_size", _DEFAULTS["voxel_size"])
        self._color = self.setting("color", _DEFAULTS["color"])
        self._background = self.setting("background", _DEFAULTS["background"])

    @property
    def name(self) -> str:
        return "VoxelCAD"

    @property
    def syntax_language(self) -> str:
        return "python"

    def available(self) -> bool:
        try:
            import voxelcad  # noqa: F401
            return True
        except ImportError:
            return False

    def version(self) -> Optional[str]:
        try:
            import voxelcad
            return voxelcad.__version__
        except (ImportError, AttributeError):
            return None

    # --- contract -----------------------------------------------------------

    def render(
        self,
        source_path: Path,
        output_dir: Path,
        views: Optional[List[str]] = None,
        image_size: int = 1024,
        defines: Defines = None,
    ) -> RenderResult:
        source_path = Path(source_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if views is None:
            views = MULTI_VIEW_DEFAULT

        images: Dict[str, Path] = {}
        errors: List[str] = []
        warnings: List[str] = []
        t0 = time.monotonic()

        model = self._execute_source(source_path, defines, errors, warnings)
        if model is None:
            return RenderResult(
                images={}, success=False, errors=errors, warnings=warnings,
                render_time_ms=(time.monotonic() - t0) * 1000,
            )

        metadata = self._measure(model)

        try:
            import pyvista as pv
            pv.OFF_SCREEN = True

            mesh = model.render_surface_mesh()
            center, radius = _bounding_sphere(mesh.bounds)

            for view_name in views:
                preset = self.get_preset(view_name)
                out_file = output_dir / f"{source_path.stem}_{view_name}.png"

                plotter = pv.Plotter(off_screen=True, window_size=[image_size, image_size])
                plotter.set_background(self._background)
                plotter.add_mesh(mesh, color=self._color, smooth_shading=True)
                plotter.camera_position = [preset.eye_position(center, radius), center, preset.up]
                if preset.orthographic:
                    plotter.enable_parallel_projection()
                plotter.reset_camera()
                plotter.screenshot(str(out_file))
                plotter.close()

                if out_file.exists() and out_file.stat().st_size > 0:
                    images[view_name] = out_file
                else:
                    errors.append(f"{view_name}: screenshot produced no file")
        except Exception as e:
            # Deliberately broad: PyVista/VTK raise many types for a missing
            # GL context; none is recoverable here and the message is what matters.
            errors.append(f"PyVista render error: {type(e).__name__}: {e}")

        return RenderResult(
            images=images,
            success=len(images) > 0 and len(errors) == 0,
            errors=errors,
            warnings=warnings,
            render_time_ms=(time.monotonic() - t0) * 1000,
            metadata=metadata,
        )

    def export(
        self,
        source_path: Path,
        output_path: Path,
        fmt: str = "stl",
        defines: Defines = None,
    ) -> ExportResult:
        fmt = fmt.lower()
        if fmt not in self.supported_export_formats:
            return self._unsupported_format(fmt)

        source_path = Path(source_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        errors: List[str] = []
        warnings: List[str] = []
        t0 = time.monotonic()

        model = self._execute_source(source_path, defines, errors, warnings)
        if model is None:
            return ExportResult(format=fmt, success=False, errors=errors)

        try:
            model.export(str(output_path))
        except Exception as e:
            # Deliberately broad: user geometry can fail anywhere in the
            # export pipeline; the caller gets the message, not a crash.
            return ExportResult(
                format=fmt, success=False,
                errors=[f"STL export error: {type(e).__name__}: {e}"],
                render_time_ms=(time.monotonic() - t0) * 1000,
            )

        elapsed_ms = (time.monotonic() - t0) * 1000

        # Count facets from file size (binary STL: 84 bytes header + 50 bytes/facet)
        facets = 0
        produced = output_path.exists() and output_path.stat().st_size > 0
        if produced:
            size = output_path.stat().st_size
            if size > 84:
                facets = (size - 84) // 50

        return ExportResult(
            output_path=output_path if produced else None,
            format=fmt,
            success=produced,
            errors=[] if produced else ["VoxelCAD produced no STL file"],
            facet_count=facets,
            render_time_ms=elapsed_ms,
            metadata=self._measure(model),
        )

    def validate_syntax(self, code: str) -> ValidationResult:
        errors: List[str] = []
        try:
            compile(code, "<voxelcad>", "exec")
        except SyntaxError as e:
            errors.append(f"Line {e.lineno}: {e.msg}")
        return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=[])

    # --- helpers ------------------------------------------------------------

    def _execute_source(self, source_path: Path, defines: Defines, errors: List[str], warnings: List[str]):
        """Run a VoxelCAD script and return its model, or None with errors filled.

        A ``build(**params)`` function takes precedence and receives coerced
        overrides; otherwise the module-level ``model`` is harvested.
        """
        code = source_path.read_text()
        namespace: Dict[str, Any] = {"__file__": str(source_path), "__name__": "__agentcad_source__"}

        try:
            exec(code, namespace)
        except Exception as e:
            # Deliberately broad: this runs user code, which may raise anything.
            errors.append(f"Execution error: {type(e).__name__}: {e}")
            return None

        build = namespace.get("build")
        if callable(build):
            try:
                params = coerce_defines(defines, build)
            except ValueError as e:
                errors.append(f"Parameter override rejected: {e}")
                return None
            try:
                model = build(**params)
            except Exception as e:
                # Deliberately broad: user code again.
                errors.append(f"build() raised {type(e).__name__}: {e}")
                return None
        else:
            if defines:
                warnings.append(
                    f"Overrides {sorted(defines)} ignored: source defines no build(**params)"
                )
            model = namespace.get("model")

        if model is None:
            errors.append(
                "Script must define build(**params) returning the model, or assign it "
                "to a variable named 'model'. Example: model = Sphere(r=5) & Cube(size=8, center=True)"
            )
            return None

        # Ensure rendered
        if not hasattr(model, "voxel_data") or model.voxel_data is None:
            try:
                model.render_volume()
            except Exception as e:
                # Deliberately broad: geometry evaluation of user models.
                errors.append(f"render_volume() failed: {type(e).__name__}: {e}")
                return None

        return model

    @staticmethod
    def _measure(model) -> Dict[str, Any]:
        """Measured facts about a rendered VoxelCAD model (best effort, never raises)."""
        metadata: Dict[str, Any] = {}
        grid = getattr(model, "grid", None)
        if grid is None:
            return metadata
        try:
            metadata["grid_resolution"] = [int(v) for v in grid.res_vector]
            metadata["voxel_size"] = [float(v) for v in grid.voxel_size_vector]
            metadata["bbox"] = [list(map(float, grid.xlim)), list(map(float, grid.ylim)), list(map(float, grid.zlim))]
        except (AttributeError, TypeError, ValueError) as e:
            print(f"agentcad warning: VoxelCAD metadata incomplete: {e}", file=sys.stderr)
        return metadata


def _bounding_sphere(bounds) -> Tuple[Tuple[float, float, float], float]:
    """Centre and radius of the sphere around a PyVista bounds tuple."""
    xmin, xmax, ymin, ymax, zmin, zmax = bounds
    center = ((xmin + xmax) / 2, (ymin + ymax) / 2, (zmin + zmax) / 2)
    radius = 0.5 * ((xmax - xmin) ** 2 + (ymax - ymin) ** 2 + (zmax - zmin) ** 2) ** 0.5
    return center, max(radius, 1e-9)
