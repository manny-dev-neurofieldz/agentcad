"""OpenSCAD engine backend.

Wraps the OpenSCAD CLI for rendering .scad files to PNG and STL.
Supports BOSL2, Manifold backend, and native EGL headless rendering.
"""

import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import List, Optional

from agentcad.camera import CameraPreset, STANDARD_PRESETS, MULTI_VIEW_DEFAULT
from agentcad.engine import (
    CADEngine, RenderResult, ExportResult, ValidationResult,
)

# Default BOSL2 library path (container convention)
_DEFAULT_OPENSCADPATH = "/opt/openscad-libraries"


class OpenSCADEngine(CADEngine):
    """OpenSCAD rendering engine with BOSL2 and Manifold support."""

    def __init__(
        self,
        binary_path: Optional[str] = None,
        library_path: Optional[str] = None,
        backend: str = "Manifold",
        color_scheme: str = "Tomorrow Night",
    ):
        self._binary = binary_path or shutil.which("openscad") or "openscad"
        self._library_path = library_path or os.environ.get(
            "OPENSCADPATH", _DEFAULT_OPENSCADPATH
        )
        self._backend = backend
        self._color_scheme = color_scheme

    @property
    def name(self) -> str:
        return "OpenSCAD"

    @property
    def file_extension(self) -> str:
        return ".scad"

    def available(self) -> bool:
        try:
            result = subprocess.run(
                [self._binary, "--version"],
                capture_output=True, text=True, timeout=10,
            )
            return result.returncode == 0 or "OpenSCAD version" in result.stderr
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def version(self) -> Optional[str]:
        try:
            result = subprocess.run(
                [self._binary, "--version"],
                capture_output=True, text=True, timeout=10,
            )
            # Version may be on stdout or stderr
            output = result.stdout.strip() or result.stderr.strip()
            match = re.search(r"OpenSCAD version (\S+)", output)
            return match.group(1) if match else output
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

    def _build_env(self) -> dict:
        """Build environment with OPENSCADPATH set."""
        env = os.environ.copy()
        if self._library_path:
            env["OPENSCADPATH"] = self._library_path
        return env

    def _run(self, args: List[str], timeout: int = 120) -> subprocess.CompletedProcess:
        """Run OpenSCAD with configured environment."""
        cmd = [self._binary] + args
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=self._build_env(),
        )

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

        for view_name in views:
            preset = self.get_preset(view_name)
            out_file = output_dir / f"{source_path.stem}_{view_name}.png"

            args = [
                "--backend", self._backend,
                "-o", str(out_file),
                f"--camera={preset.camera_string}",
                f"--imgsize={image_size},{image_size}",
                "--viewall", "--autocenter",
                f"--colorscheme={self._color_scheme}",
                str(source_path),
            ]

            try:
                result = self._run(args)
                # Capture warnings from stderr
                if result.stderr:
                    for line in result.stderr.splitlines():
                        if "ERROR" in line or "error" in line.lower():
                            if "shader" not in line.lower():
                                errors.append(line.strip())
                            else:
                                warnings.append(line.strip())
                        elif "WARNING" in line:
                            warnings.append(line.strip())

                if out_file.exists() and out_file.stat().st_size > 0:
                    images[view_name] = out_file
                elif result.returncode != 0:
                    errors.append(f"{view_name}: render failed (exit {result.returncode})")
            except subprocess.TimeoutExpired:
                errors.append(f"{view_name}: render timed out")

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

        t0 = time.monotonic()
        args = [
            "--backend", self._backend,
            "--render",
            "-o", str(output_path),
            str(source_path),
        ]

        try:
            result = self._run(args, timeout=300)
        except subprocess.TimeoutExpired:
            return ExportResult(success=False, errors=["STL export timed out"])

        elapsed_ms = (time.monotonic() - t0) * 1000

        if result.returncode != 0:
            return ExportResult(
                success=False,
                errors=[result.stderr.strip()],
                render_time_ms=elapsed_ms,
            )

        # Parse facet count from stderr
        facets = 0
        match = re.search(r"Facets:\s+(\d+)", result.stderr)
        if match:
            facets = int(match.group(1))

        return ExportResult(
            stl_path=output_path,
            success=output_path.exists() and output_path.stat().st_size > 0,
            facet_count=facets,
            render_time_ms=elapsed_ms,
        )

    def validate_syntax(self, code: str) -> ValidationResult:
        errors = []
        warnings = []

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".scad", delete=False
        ) as f:
            f.write(code)
            tmp_path = f.name

        try:
            # Render to /dev/null — syntax errors show in stderr
            result = self._run([
                "--backend", self._backend,
                "-o", "/dev/null",
                tmp_path,
            ], timeout=30)

            for line in (result.stderr or "").splitlines():
                line = line.strip()
                if not line:
                    continue
                if "ERROR" in line and "shader" not in line.lower():
                    errors.append(line)
                elif "WARNING" in line:
                    warnings.append(line)
        except subprocess.TimeoutExpired:
            errors.append("Syntax check timed out")
        finally:
            os.unlink(tmp_path)

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )
