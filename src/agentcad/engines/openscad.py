"""OpenSCAD engine backend.

Wraps the OpenSCAD CLI for rendering .scad files to PNG and exporting
meshes. Supports BOSL2, the Manifold backend, and native EGL headless
rendering.
"""

import functools
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agentcad.camera import CameraPreset, MULTI_VIEW_DEFAULT
from agentcad.engine import (
    CADEngine, Defines, RenderResult, ExportResult, ValidationResult,
)

# Default BOSL2 library path (container convention)
_DEFAULT_OPENSCADPATH = "/opt/openscad-libraries"

# agentcad format name -> OpenSCAD --export-format value
_EXPORT_FORMAT_FLAGS: Dict[str, str] = {
    "stl": "binstl",
    "3mf": "3mf",
    "off": "off",
    "amf": "amf",
}

_DEFAULTS: Dict[str, Any] = {
    "fa": 1.0,
    "fs": 0.5,
    "backend": "Manifold",
    "colorscheme": "Cornfield",
    "library_path": _DEFAULT_OPENSCADPATH,
}


@functools.lru_cache(maxsize=None)
def _backend_flag_supported(binary: str) -> bool:
    """Whether the installed OpenSCAD lists ``--backend`` in its help.

    Older releases (e.g. 2024.03) lack the flag and dump usage instead of
    rendering. Probed once per binary path; failures to probe are reported
    and treated as "unsupported" so the flag is dropped rather than guessed.
    """
    try:
        proc = subprocess.run([binary, "--help"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"agentcad warning: OpenSCAD --help probe failed (dropping --backend): {e}", file=sys.stderr)
        return False
    return "--backend" in (proc.stdout + proc.stderr)


class OpenSCADEngine(CADEngine):
    """OpenSCAD rendering engine with BOSL2 and Manifold support."""

    known_settings = ("fa", "fs", "backend", "colorscheme", "library_path")
    FILE_EXTENSION = ".scad"
    EXPORT_FORMATS = tuple(_EXPORT_FORMAT_FLAGS)

    def __init__(self, settings=None, **overrides):
        """Initialize from a settings table (dict or OpenSCADConfig) plus overrides."""
        super().__init__(settings, **overrides)
        self._binary = shutil.which("openscad") or "openscad"
        self._library_path = os.environ.get(
            "OPENSCADPATH", self.setting("library_path", _DEFAULTS["library_path"])
        )
        backend = self.setting("backend", _DEFAULTS["backend"])
        self._backend = backend if backend and _backend_flag_supported(self._binary) else ""
        self._color_scheme = self.setting("colorscheme", _DEFAULTS["colorscheme"])
        self._fa = self.setting("fa", _DEFAULTS["fa"])
        self._fs = self.setting("fs", _DEFAULTS["fs"])

    @property
    def name(self) -> str:
        return "OpenSCAD"

    @property
    def syntax_language(self) -> str:
        return "openscad"

    def available(self) -> bool:
        try:
            result = subprocess.run(
                [self._binary, "--version"],
                capture_output=True, text=True, timeout=10,
            )
            return result.returncode == 0 or "OpenSCAD version" in result.stderr
        except (OSError, subprocess.TimeoutExpired):
            return False

    def version(self) -> Optional[str]:
        try:
            result = subprocess.run(
                [self._binary, "--version"],
                capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        # Version may be on stdout or stderr
        output = result.stdout.strip() or result.stderr.strip()
        match = re.search(r"OpenSCAD version (\S+)", output)
        return match.group(1) if match else (output or None)

    # --- command construction (public so tests can assert on argv) ---------

    def _common_args(self, defines: Defines) -> List[str]:
        args: List[str] = []
        if self._backend:
            args += ["--backend", self._backend]
        args += ["--render", "-D", f"$fa={self._fa}", "-D", f"$fs={self._fs}"]
        for k, v in (defines or {}).items():
            args += ["-D", f"{k}={v}"]
        return args

    def render_args(
        self,
        source_path: Path,
        out_file: Path,
        preset: CameraPreset,
        image_size: int = 1024,
        defines: Defines = None,
    ) -> List[str]:
        """Argument list (without the binary) for rendering one view."""
        args = self._common_args(defines)
        args += [
            "-o", str(out_file),
            f"--camera={preset.camera_string}",
            f"--imgsize={image_size},{image_size}",
            "--viewall", "--autocenter",
            f"--colorscheme={self._color_scheme}",
        ]
        if preset.orthographic:
            args.append("--projection=ortho")
        args.append(str(source_path))
        return args

    def export_args(
        self,
        source_path: Path,
        output_path: Path,
        fmt: str = "stl",
        defines: Defines = None,
    ) -> List[str]:
        """Argument list (without the binary) for exporting one file."""
        args = self._common_args(defines)
        args += ["--export-format", _EXPORT_FORMAT_FLAGS[fmt], "-o", str(output_path), str(source_path)]
        return args

    def _build_env(self) -> dict:
        """Environment with OPENSCADPATH set."""
        env = os.environ.copy()
        if self._library_path:
            env["OPENSCADPATH"] = self._library_path
        return env

    def _run(self, args: List[str], timeout: int = 120) -> subprocess.CompletedProcess:
        """Run OpenSCAD with configured environment."""
        return subprocess.run(
            [self._binary] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=self._build_env(),
        )

    @staticmethod
    def _classify_stderr(stderr: str, errors: List[str], warnings: List[str]) -> None:
        """Sort OpenSCAD's stderr lines into errors and warnings."""
        for line in (stderr or "").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            # Informational lines
            if "NoError" in stripped or stripped.startswith("Facets:"):
                continue
            if stripped.startswith("ERROR"):
                # Shader errors are a headless-GL artefact, not a model error
                if "shader" in stripped.lower():
                    warnings.append(stripped)
                else:
                    errors.append(stripped)
            elif "WARNING" in stripped:
                warnings.append(stripped)

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
        metadata: Dict[str, Any] = {}
        t0 = time.monotonic()

        for view_name in views:
            preset = self.get_preset(view_name)
            out_file = output_dir / f"{source_path.stem}_{view_name}.png"
            args = self.render_args(source_path, out_file, preset, image_size, defines)

            try:
                result = self._run(args)
            except subprocess.TimeoutExpired:
                errors.append(f"{view_name}: render timed out")
                continue

            self._classify_stderr(result.stderr, errors, warnings)
            match = re.search(r"Facets:\s+(\d+)", result.stderr or "")
            if match:
                metadata["facet_count"] = int(match.group(1))

            if out_file.exists() and out_file.stat().st_size > 0:
                images[view_name] = out_file
            elif result.returncode != 0:
                errors.append(f"{view_name}: render failed (exit {result.returncode})")

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

        t0 = time.monotonic()
        try:
            result = self._run(self.export_args(source_path, output_path, fmt, defines), timeout=300)
        except subprocess.TimeoutExpired:
            return ExportResult(format=fmt, success=False, errors=[f"{fmt} export timed out"])

        elapsed_ms = (time.monotonic() - t0) * 1000
        if result.returncode != 0:
            return ExportResult(
                format=fmt,
                success=False,
                errors=[result.stderr.strip() or f"OpenSCAD exited {result.returncode}"],
                render_time_ms=elapsed_ms,
            )

        facets = 0
        match = re.search(r"Facets:\s+(\d+)", result.stderr or "")
        if match:
            facets = int(match.group(1))

        produced = output_path.exists() and output_path.stat().st_size > 0
        return ExportResult(
            output_path=output_path if produced else None,
            format=fmt,
            success=produced,
            errors=[] if produced else [f"OpenSCAD produced no {fmt} file"],
            facet_count=facets,
            render_time_ms=elapsed_ms,
            metadata={"facet_count": facets} if facets else {},
        )

    def validate_syntax(self, code: str) -> ValidationResult:
        errors: List[str] = []
        warnings: List[str] = []

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=self.file_extension, delete=False
        ) as f:
            f.write(code)
            tmp_path = f.name

        try:
            # Export the CSG tree to the null device: parses and evaluates the
            # source without rendering. The explicit format is required because
            # the null device has no suffix for OpenSCAD to infer one from.
            args = ["--backend", self._backend] if self._backend else []
            args += ["--export-format", "csg", "-o", os.devnull, tmp_path]
            result = self._run(args, timeout=30)
            self._classify_stderr(result.stderr, errors, warnings)
            if result.returncode != 0 and not errors:
                tail = (result.stderr or "").strip().splitlines()
                errors.append(tail[-1] if tail else f"OpenSCAD exited {result.returncode}")
        except subprocess.TimeoutExpired:
            errors.append("Syntax check timed out")
        finally:
            os.unlink(tmp_path)

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )
