"""Abstract CAD engine interface.

All CAD backends (OpenSCAD, VoxelCAD, etc.) implement this interface,
enabling the agentic feedback loop to work with any scriptable CAD tool.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from agentcad.camera import CameraPreset, STANDARD_PRESETS, MULTI_VIEW_DEFAULT


@dataclass
class RenderResult:
    """Result of a render operation."""
    images: Dict[str, Path]  # view_name -> image_path
    success: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    render_time_ms: float = 0.0


@dataclass
class ExportResult:
    """Result of an STL export operation."""
    stl_path: Optional[Path] = None
    success: bool = True
    errors: List[str] = field(default_factory=list)
    facet_count: int = 0
    render_time_ms: float = 0.0


@dataclass
class ValidationResult:
    """Result of syntax validation."""
    valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class CADEngine(ABC):
    """Abstract interface for a scriptable CAD engine.

    Subclasses implement rendering, STL export, and syntax validation
    for a specific CAD tool (OpenSCAD, VoxelCAD, etc.).
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable engine name (e.g., 'OpenSCAD', 'VoxelCAD')."""

    @property
    @abstractmethod
    def file_extension(self) -> str:
        """Source file extension (e.g., '.scad', '.py')."""

    @abstractmethod
    def render(
        self,
        source_path: Path,
        output_dir: Path,
        views: Optional[List[str]] = None,
        image_size: int = 1024,
    ) -> RenderResult:
        """Render source file to PNG images.

        Args:
            source_path: Path to CAD source file.
            output_dir: Directory for output images.
            views: List of view preset names. Defaults to MULTI_VIEW_DEFAULT.
            image_size: Image width and height in pixels.

        Returns:
            RenderResult with paths to rendered images.
        """

    @abstractmethod
    def export_stl(
        self,
        source_path: Path,
        output_path: Path,
    ) -> ExportResult:
        """Export source file to STL mesh.

        Args:
            source_path: Path to CAD source file.
            output_path: Path for output STL file.

        Returns:
            ExportResult with path and metadata.
        """

    @abstractmethod
    def validate_syntax(self, code: str) -> ValidationResult:
        """Check source code for syntax errors without rendering.

        Args:
            code: CAD source code as string.

        Returns:
            ValidationResult with any errors found.
        """

    def get_preset(self, name: str) -> CameraPreset:
        """Look up a camera preset by name."""
        if name not in STANDARD_PRESETS:
            raise ValueError(
                f"Unknown preset '{name}'. "
                f"Available: {list(STANDARD_PRESETS.keys())}"
            )
        return STANDARD_PRESETS[name]

    def available(self) -> bool:
        """Check whether this engine's backend is installed and working."""
        return False
