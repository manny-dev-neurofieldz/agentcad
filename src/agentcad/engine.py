"""Abstract CAD engine interface.

Every backend (OpenSCAD, VoxelCAD, build123d, ...) implements ``CADEngine``.
The CLI, the design session and the viewer only ever talk to this contract,
so a new backend is usable everywhere the moment it satisfies it. The
contract test in ``tests/test_engine_contract.py`` drives every registered
engine through the same calls the CLI makes; an engine that is registered
but skips part of the contract fails there rather than in a user's session.
"""

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from agentcad.camera import CameraPreset, STANDARD_PRESETS, MULTI_VIEW_DEFAULT

Defines = Optional[Mapping[str, str]]

#: Measured-metadata keys an engine may report in ``RenderResult.metadata`` /
#: ``ExportResult.metadata``. Every key is optional: an engine that cannot
#: measure something omits the key (a reader prints "n/a"), and a measurement
#: that failed is reported as ``<key>_error`` with the reason. Engines may add
#: keys of their own, but the report layer (``agentcad.report``) reads only
#: these, so a number an engine wants on the tray goes under one of them.
#:
#:   bbox_min, bbox_size   [x, y, z] in model units
#:   volume, area          model units cubed / squared
#:   center_of_mass        [x, y, z]
#:   counts                {solids, faces, edges, vertices}; solids is the
#:                         connectivity gate (a part in three pieces renders whole)
#:   is_valid              kernel validity (B-rep engines)
#:   face_census           {plane, cylinder, cone, sphere, torus, bspline, other: n}
#:   short_edges           edges shorter than the ``short_edge_mm`` setting
#:   min_edge_mm           the shortest edge
#:   expected_solids       the ``expected_solids`` setting the engine ran with
#:   twisted_faces         free-form faces whose normal turns sharply along a
#:                         ruling (a twisted loft), with ``twisted_faces_detail``
#:   grid_resolution, voxel_size, grid_target, occupied_voxels   (voxel engines)
#:   kind                  "3d" | "2d" | "1d"
#:   runtime_s             seconds the engine spent building and measuring
METADATA_KEYS = frozenset({
    "bbox_min", "bbox_size", "bbox", "volume", "area", "center_of_mass", "counts",
    "is_valid", "face_census", "short_edges", "min_edge_mm", "expected_solids",
    "twisted_faces", "twisted_faces_detail",
    "grid_resolution", "voxel_size", "grid_target", "occupied_voxels",
    "kind", "runtime_s", "facet_count",
    # engine identity lines
    "build123d_version", "openscad_version", "voxelcad_version",
})

#: Settings every engine accepts in its ``[engine.<name>]`` table regardless
#: of backend: they parameterise the report, not the kernel.
#:   expected_solids   how many bodies a single-part source should produce (default 1)
#:   short_edge_mm     an edge below this length is counted in ``short_edges`` (default 0.25)
UNIVERSAL_SETTINGS: Tuple[str, ...] = ("expected_solids", "short_edge_mm")
UNIVERSAL_DEFAULTS: Dict[str, Any] = {"expected_solids": 1, "short_edge_mm": 0.25}


@dataclass
class RenderResult:
    """Result of a render operation."""
    images: Dict[str, Path]  # view_name -> image_path
    success: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    render_time_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)  # measured facts (engine-specific keys)


@dataclass
class ExportResult:
    """Result of an export operation (STL, STEP, 3MF, ...)."""
    output_path: Optional[Path] = None
    format: str = "stl"
    success: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    facet_count: int = 0  # mesh formats only; 0 when unknown or not a mesh
    render_time_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def stl_path(self) -> Optional[Path]:
        """Compatibility alias for callers written against the STL-only API."""
        return self.output_path


@dataclass
class ValidationResult:
    """Result of syntax validation."""
    valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class CADEngine(ABC):
    """Abstract interface for a scriptable CAD engine.

    Subclasses implement rendering, export and syntax validation for one
    CAD tool. Construction takes the engine's settings table (the
    ``[engine.<name>]`` section of ``agentcad.toml``) plus keyword overrides;
    ``known_settings`` names the keys an engine understands, and anything
    else is reported on stderr rather than silently dropped.
    """

    #: Setting keys this engine understands (subclasses override).
    known_settings: Tuple[str, ...] = ()
    #: Source file extension including the dot; class-level so the registry
    #: can answer "which extension is which engine" without instantiating.
    FILE_EXTENSION: str = ""
    #: Lower-case export formats this engine can produce.
    EXPORT_FORMATS: Tuple[str, ...] = ("stl",)

    def __init__(self, settings: Optional[Any] = None, **overrides):
        if not self.FILE_EXTENSION:
            raise TypeError(f"{type(self).__name__} must set FILE_EXTENSION")
        self._settings: Dict[str, Any] = self._merge_settings(settings, overrides)

    def _merge_settings(self, settings: Optional[Any], overrides: Mapping[str, Any]) -> Dict[str, Any]:
        """Merge a settings table (mapping or dataclass) with keyword overrides.

        Unknown keys are kept out of the result and announced on stderr so a
        misspelled option in a config file is visible instead of inert.
        """
        merged: Dict[str, Any] = {}
        if settings is None:
            source: Mapping[str, Any] = {}
        elif is_dataclass(settings) and not isinstance(settings, type):
            source = vars(settings)
        elif isinstance(settings, Mapping):
            source = settings
        else:
            raise TypeError(
                f"{self.name}: settings must be a mapping or dataclass, got {type(settings).__name__}"
            )
        for key, value in list(source.items()) + list(overrides.items()):
            if key in self.known_settings or key in UNIVERSAL_SETTINGS:
                merged[key] = value
            else:
                print(
                    f"agentcad warning: {self.name}: ignoring unknown setting '{key}' "
                    f"(known: {', '.join(self.known_settings) or 'none'})",
                    file=sys.stderr,
                )
        return merged

    def setting(self, key: str, default: Any = None) -> Any:
        """Read a merged setting with a default (universal settings carry their own)."""
        if key in self._settings:
            return self._settings[key]
        if key in UNIVERSAL_DEFAULTS and default is None:
            return UNIVERSAL_DEFAULTS[key]
        return default

    # --- identity -----------------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable engine name (e.g., 'OpenSCAD', 'VoxelCAD')."""

    @property
    def file_extension(self) -> str:
        """Source file extension including the dot (from FILE_EXTENSION)."""
        return self.FILE_EXTENSION

    @property
    def syntax_language(self) -> str:
        """Highlighting language for the viewer's source block."""
        return "plaintext"

    @property
    def supported_export_formats(self) -> Tuple[str, ...]:
        """Lower-case export format names this engine can produce."""
        return self.EXPORT_FORMATS

    def available(self) -> bool:
        """Whether this engine's backend is installed and working."""
        return False

    def version(self) -> Optional[str]:
        """Backend version string, or None when it cannot be determined."""
        return None

    # --- operations ---------------------------------------------------------

    @abstractmethod
    def render(
        self,
        source_path: Path,
        output_dir: Path,
        views: Optional[List[str]] = None,
        image_size: int = 1024,
        defines: Defines = None,
    ) -> RenderResult:
        """Render a source file to one PNG per view.

        Args:
            source_path: Path to the CAD source file.
            output_dir: Directory for output images.
            views: Camera preset names. Defaults to MULTI_VIEW_DEFAULT.
            image_size: Image width and height in pixels.
            defines: Parameter overrides (``-D name=value``) as strings; each
                engine coerces them to what its sources expect.
        """

    @abstractmethod
    def export(
        self,
        source_path: Path,
        output_path: Path,
        fmt: str = "stl",
        defines: Defines = None,
    ) -> ExportResult:
        """Export a source file to a geometry file.

        Implementations must return an error ``ExportResult`` (not raise) for
        a format outside ``supported_export_formats``; ``_unsupported_format``
        builds that result.
        """

    def export_stl(
        self,
        source_path: Path,
        output_path: Path,
        defines: Defines = None,
    ) -> ExportResult:
        """Compatibility wrapper: ``export`` with ``fmt="stl"``."""
        return self.export(source_path, output_path, fmt="stl", defines=defines)

    @abstractmethod
    def validate_syntax(self, code: str) -> ValidationResult:
        """Check source code for syntax errors without rendering."""

    # --- helpers for implementations ---------------------------------------

    def _unsupported_format(self, fmt: str) -> ExportResult:
        return ExportResult(
            format=fmt,
            success=False,
            errors=[
                f"{self.name} cannot export '{fmt}'; "
                f"supported: {', '.join(self.supported_export_formats)}"
            ],
        )

    def get_preset(self, name: str) -> CameraPreset:
        """Look up a camera preset by name."""
        if name not in STANDARD_PRESETS:
            raise ValueError(
                f"Unknown preset '{name}'. "
                f"Available: {list(STANDARD_PRESETS.keys())}"
            )
        return STANDARD_PRESETS[name]

    @staticmethod
    def default_views() -> List[str]:
        return list(MULTI_VIEW_DEFAULT)
