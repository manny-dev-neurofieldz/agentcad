"""VoxelCAD engine backend.

Voxel modelling through the VoxelCAD package: the source builds a model on a
voxel grid, PyVista renders its smoothed surface offscreen, and export writes
STL through the SDF + Butterworth pipeline. The source contract is the one
every Python-source engine shares (see ``agentcad.params``): ``build(**params)``
returning the model, or a module-level ``model``. All grid work runs in a
subprocess (``voxelcad_worker``) with a timeout, so an oversize grid or an
out-of-memory kill is reported as an error rather than taking the CLI down.

Settings (``[engine.voxelcad]``):
    grid            voxels along the model's longest side when voxel_size is
                    not given (default 256): the grid is sized from the
                    model's extent, so a 10 mm part and a 100 mm part both
                    build at the same cell count
    voxel_size      explicit voxel edge in model units; overrides grid
    warn_voxels     warn when the grid exceeds this many cells (default 64M)
    timeout         seconds allowed for a render (default 120)
    export_timeout  seconds allowed for an export (default 300)
    color, background   render colours

Measured metadata: grid_resolution, voxel_size, grid_target, bbox_min,
bbox_size, occupied_voxels, volume (occupied cells times the cell volume),
counts.solids (connected components on the grid), runtime_s. Area, validity
and a face census have no meaning on a voxel grid and are not reported.
"""

import importlib.metadata
import importlib.util
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from agentcad.camera import MULTI_VIEW_DEFAULT
from agentcad.engine import (
    CADEngine, Defines, RenderResult, ExportResult, ValidationResult,
)
from agentcad.engines.subprocess_worker import run_worker

_WORKER_MODULE = "agentcad.engines.voxelcad_worker"

_DEFAULTS: Dict[str, Any] = {
    "grid": 256,
    "voxel_size": None,
    "warn_voxels": 64_000_000,
    "timeout": 120,
    "export_timeout": 300,
    "color": "steelblue",
    "background": "white",
}


class VoxelCADEngine(CADEngine):
    """VoxelCAD rendering engine, worker-hosted, with PyVista offscreen renders and smoothed STL export."""

    known_settings = tuple(_DEFAULTS)
    FILE_EXTENSION = ".py"
    EXPORT_FORMATS = ("stl",)

    def __init__(self, settings=None, **overrides):
        super().__init__(settings, **overrides)
        self._timeout = float(self.setting("timeout", _DEFAULTS["timeout"]))
        self._export_timeout = float(self.setting("export_timeout", _DEFAULTS["export_timeout"]))

    @property
    def name(self) -> str:
        return "VoxelCAD"

    @property
    def syntax_language(self) -> str:
        return "python"

    def available(self) -> bool:
        return importlib.util.find_spec("voxelcad") is not None

    def version(self) -> Optional[str]:
        try:
            return importlib.metadata.version("voxelcad")
        except importlib.metadata.PackageNotFoundError:
            try:
                import voxelcad
                return getattr(voxelcad, "__version__", None)
            except ImportError:
                return None

    # --- worker plumbing --------------------------------------------------------

    def _job_base(self, mode: str, defines: Defines) -> Dict[str, Any]:
        voxel = self.setting("voxel_size", _DEFAULTS["voxel_size"])
        return {
            "mode": mode,
            "defines": dict(defines or {}),
            "resolution": {
                "voxel_size": float(voxel) if voxel else None,
                "grid": int(self.setting("grid", _DEFAULTS["grid"])),
                "warn_voxels": int(self.setting("warn_voxels", _DEFAULTS["warn_voxels"])),
            },
        }

    def _run_worker(self, job: Dict[str, Any], timeout: float, cwd: Optional[Path] = None) -> Dict[str, Any]:
        return run_worker(_WORKER_MODULE, job, timeout, label="voxelcad", cwd=cwd)

    def _view_spec(self, name: str) -> Dict[str, Any]:
        preset = self.get_preset(name)
        return {
            "name": preset.name,
            "eye": list(preset.eye),
            "up": list(preset.up),
            "orthographic": preset.orthographic,
            "distance": preset.distance,
        }

    # --- contract ---------------------------------------------------------------

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

        t0 = time.monotonic()
        job = self._job_base("render", defines)
        job["source_path"] = str(source_path)
        job["render"] = {
            "output_dir": str(output_dir),
            "stem": source_path.stem,
            "image_size": int(image_size),
            "views": [self._view_spec(name) for name in views],
            "color": self.setting("color", _DEFAULTS["color"]),
            "background": self.setting("background", _DEFAULTS["background"]),
        }
        res = self._run_worker(job, self._timeout, cwd=source_path.parent)
        images = {name: Path(p) for name, p in res.get("images", {}).items()}
        errors = list(res.get("errors", []))
        return RenderResult(
            images=images,
            success=len(images) > 0 and not errors,
            errors=errors,
            warnings=list(res.get("warnings", [])),
            render_time_ms=(time.monotonic() - t0) * 1000,
            metadata=dict(res.get("metadata", {})),
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

        t0 = time.monotonic()
        job = self._job_base("export", defines)
        job["source_path"] = str(source_path)
        job["export"] = {"output_path": str(output_path), "fmt": fmt}
        res = self._run_worker(job, self._export_timeout, cwd=source_path.parent)
        errors = list(res.get("errors", []))
        produced = res.get("output_path")
        return ExportResult(
            output_path=Path(produced) if produced else None,
            format=fmt,
            success=bool(produced) and not errors,
            errors=errors,
            warnings=list(res.get("warnings", [])),
            facet_count=int(res.get("facet_count") or 0),
            render_time_ms=(time.monotonic() - t0) * 1000,
            metadata=dict(res.get("metadata", {})),
        )

    def validate_syntax(self, code: str) -> ValidationResult:
        errors: List[str] = []
        try:
            compile(code, "<voxelcad>", "exec")
        except SyntaxError as e:
            errors.append(f"Line {e.lineno}: {e.msg}")
        return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=[])
