"""build123d engine backend.

B-rep modelling through build123d (OCCT). The source contract is the one
every Python-source engine shares (see ``agentcad.params``): ``build(**params)``
returning a build123d object, or a module-level ``part`` (``result`` and
``model`` are accepted too). All kernel work runs in a subprocess
(``build123d_worker``) with a timeout, so a hung kernel call is reported as a
timeout rather than waited on. Rendering needs PyVista; STEP, STL, 3MF and SVG
export do not.

Settings (``[engine.build123d]``):
    tolerance          tessellation tolerance in model units (default: bbox diagonal / 2000)
    angular_tolerance  tessellation angular tolerance in radians (default 0.1)
    timeout            seconds allowed for a render (default 120)
    export_timeout     seconds allowed for an export (default 300)
    color, background, edge_color   render colours
    shading            "smooth" (default) interpolates vertex normals so a curved
                       face reads as curved; "flat" shades each triangle on its
                       own normal, which shows the tessellation on lofted or
                       twisted faces
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

_WORKER_MODULE = "agentcad.engines.build123d_worker"
_VALIDATE_TIMEOUT = 30

_DEFAULTS: Dict[str, Any] = {
    "tolerance": None,
    "angular_tolerance": 0.1,
    "timeout": 120,
    "export_timeout": 300,
    "color": "#cfd8e3",
    "background": "white",
    "edge_color": "black",
    "shading": "smooth",
}


class Build123dEngine(CADEngine):
    """B-rep modelling via build123d, rendered through PyVista offscreen."""

    known_settings = tuple(_DEFAULTS)
    FILE_EXTENSION = ".py"
    EXPORT_FORMATS = ("stl", "step", "3mf", "svg")

    def __init__(self, settings=None, **overrides):
        super().__init__(settings, **overrides)
        self._timeout = float(self.setting("timeout", _DEFAULTS["timeout"]))
        self._export_timeout = float(self.setting("export_timeout", _DEFAULTS["export_timeout"]))

    @property
    def name(self) -> str:
        return "build123d"

    @property
    def syntax_language(self) -> str:
        return "python"

    def available(self) -> bool:
        return importlib.util.find_spec("build123d") is not None

    def version(self) -> Optional[str]:
        try:
            return importlib.metadata.version("build123d")
        except importlib.metadata.PackageNotFoundError:
            return None

    # --- worker plumbing --------------------------------------------------------

    def _job_base(self, mode: str, defines: Defines) -> Dict[str, Any]:
        return {
            "mode": mode,
            "defines": dict(defines or {}),
            "tolerance": self.setting("tolerance", _DEFAULTS["tolerance"]),
            "angular_tolerance": self.setting("angular_tolerance", _DEFAULTS["angular_tolerance"]),
            "short_edge_mm": self.setting("short_edge_mm"),
            "expected_solids": self.setting("expected_solids"),
        }

    def _run_worker(self, job: Dict[str, Any], timeout: float, cwd: Optional[Path] = None) -> Dict[str, Any]:
        """Run the worker on ``job``; always returns a result dict (errors filled on failure)."""
        return run_worker(_WORKER_MODULE, job, timeout, label="build123d", cwd=cwd)

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
            "edge_color": self.setting("edge_color", _DEFAULTS["edge_color"]),
            "shading": str(self.setting("shading", _DEFAULTS["shading"])).lower(),
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

    def _view_spec(self, name: str) -> Dict[str, Any]:
        preset = self.get_preset(name)
        return {
            "name": preset.name,
            "eye": list(preset.eye),
            "up": list(preset.up),
            "orthographic": preset.orthographic,
            "distance": preset.distance,
        }

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
            compile(code, "<build123d>", "exec")
        except SyntaxError as e:
            errors.append(f"Line {e.lineno}: {e.msg}")
            return ValidationResult(valid=False, errors=errors, warnings=[])
        job = self._job_base("validate", None)
        job["code"] = code
        res = self._run_worker(job, _VALIDATE_TIMEOUT)
        errors.extend(res.get("errors", []))
        return ValidationResult(valid=not errors, errors=errors, warnings=list(res.get("warnings", [])))

