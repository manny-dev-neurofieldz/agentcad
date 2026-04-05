"""VoxelCAD engine backend.

Executes Python VoxelCAD code, renders via PyVista offscreen,
and exports STL via the SDF + Butterworth smoothed mesh pipeline.
"""

import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Optional

from agentcad.camera import CameraPreset, STANDARD_PRESETS, MULTI_VIEW_DEFAULT
from agentcad.engine import (
    CADEngine, RenderResult, ExportResult, ValidationResult,
)

# PyVista camera position mapping from AgentCAD presets
_PYVISTA_POSITIONS = {
    "iso": "iso",
    "front": "yz",
    "top": "xy",
    "right": "xz",
    "back": "-yz",
}


class VoxelCADEngine(CADEngine):
    """VoxelCAD rendering engine with PyVista offscreen and smoothed mesh export."""

    def __init__(self, config=None, **overrides):
        self._voxel_size = overrides.get("voxel_size", 0.2)
        self._color = overrides.get("color", "steelblue")
        self._background = overrides.get("background", "white")

    @property
    def name(self) -> str:
        return "VoxelCAD"

    @property
    def file_extension(self) -> str:
        return ".py"

    def available(self) -> bool:
        try:
            import voxelcad
            return True
        except ImportError:
            return False

    def version(self) -> Optional[str]:
        try:
            import voxelcad
            return voxelcad.__version__
        except (ImportError, AttributeError):
            return None

    def render(
        self,
        source_path: Path,
        output_dir: Path,
        views: Optional[List[str]] = None,
        image_size: int = 1024,
    ) -> RenderResult:
        source_path = Path(source_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if views is None:
            views = MULTI_VIEW_DEFAULT

        images = {}
        errors = []
        warnings = []
        t0 = time.monotonic()

        # Execute the Python source to get the model
        model = self._execute_source(source_path, errors)
        if model is None:
            return RenderResult(
                images={}, success=False, errors=errors,
                render_time_ms=(time.monotonic() - t0) * 1000,
            )

        # Render surface mesh once, screenshot from multiple angles
        try:
            import pyvista as pv
            pv.OFF_SCREEN = True

            mesh = model.render_surface_mesh()

            for view_name in views:
                out_file = output_dir / f"{source_path.stem}_{view_name}.png"
                cam_pos = _PYVISTA_POSITIONS.get(view_name, "iso")

                plotter = pv.Plotter(off_screen=True, window_size=[image_size, image_size])
                plotter.set_background(self._background)
                plotter.add_mesh(mesh, color=self._color, smooth_shading=True)
                plotter.camera_position = cam_pos
                plotter.screenshot(str(out_file))
                plotter.close()

                if out_file.exists() and out_file.stat().st_size > 0:
                    images[view_name] = out_file

        except Exception as e:
            errors.append(f"PyVista render error: {e}")

        elapsed_ms = (time.monotonic() - t0) * 1000
        return RenderResult(
            images=images,
            success=len(images) > 0 and len(errors) == 0,
            errors=errors,
            warnings=warnings,
            render_time_ms=elapsed_ms,
        )

    def export_stl(
        self,
        source_path: Path,
        output_path: Path,
    ) -> ExportResult:
        source_path = Path(source_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        errors = []
        t0 = time.monotonic()

        model = self._execute_source(source_path, errors)
        if model is None:
            return ExportResult(success=False, errors=errors)

        try:
            model.export(str(output_path))
        except Exception as e:
            return ExportResult(
                success=False, errors=[f"STL export error: {e}"],
                render_time_ms=(time.monotonic() - t0) * 1000,
            )

        elapsed_ms = (time.monotonic() - t0) * 1000

        # Count facets from file size (binary STL: 84 bytes header + 50 bytes/facet)
        facets = 0
        if output_path.exists():
            size = output_path.stat().st_size
            if size > 84:
                facets = (size - 84) // 50

        return ExportResult(
            stl_path=output_path,
            success=output_path.exists() and output_path.stat().st_size > 0,
            facet_count=facets,
            render_time_ms=elapsed_ms,
        )

    def validate_syntax(self, code: str) -> ValidationResult:
        errors = []
        warnings = []
        try:
            compile(code, "<voxelcad>", "exec")
        except SyntaxError as e:
            errors.append(f"Line {e.lineno}: {e.msg}")
        return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)

    def _execute_source(self, source_path: Path, errors: list):
        """Execute a VoxelCAD Python script and return the model object.

        The script must assign its final model to a variable named `model`.
        """
        code = source_path.read_text()
        namespace = {"__file__": str(source_path)}

        try:
            exec(code, namespace)
        except Exception as e:
            errors.append(f"Execution error: {e}")
            return None

        model = namespace.get("model")
        if model is None:
            errors.append(
                "Script must assign final geometry to a variable named 'model'. "
                "Example: model = Sphere(r=5) & Cube(size=8, center=True)"
            )
            return None

        # Ensure rendered
        if not hasattr(model, "voxel_data") or model.voxel_data is None:
            try:
                model.render_volume()
            except Exception as e:
                errors.append(f"render_volume() failed: {e}")
                return None

        return model
