"""Print-ready manifest for STL exports.

Generates a machine-readable JSON file alongside each STL with suggested
print settings for PrusaSlicer. The human reviews and adjusts before slicing.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class PrintManifest:
    """Suggested print settings for a design export."""

    # Part identity
    part_name: str = ""
    project_name: str = ""
    stl_filename: str = ""

    # Material
    material: str = "PLA"
    material_notes: str = ""

    # Print settings
    layer_height: float = 0.2
    infill_percent: int = 20
    infill_pattern: str = "grid"
    supports: bool = False
    support_notes: str = ""

    # Orientation
    print_orientation: str = ""
    orientation_notes: str = ""

    # Mechanical
    wall_count: int = 3
    top_bottom_layers: int = 4

    # PrusaSlicer profile
    printer_profile: str = "Original Prusa MK4"
    filament_profile: str = ""
    print_profile: str = "0.20mm QUALITY"

    # Agent metadata
    agent_notes: List[str] = field(default_factory=list)
    design_iterations: int = 0
    created: str = ""
    engine: str = ""

    # Custom overrides
    custom: Dict[str, Any] = field(default_factory=dict)

    def save(self, path: Path) -> Path:
        """Write manifest as JSON alongside the STL."""
        path = Path(path)
        if not self.created:
            self.created = datetime.now().isoformat()
        path.write_text(json.dumps(asdict(self), indent=2))
        return path

    @classmethod
    def load(cls, path: Path) -> "PrintManifest":
        """Load manifest from JSON file."""
        data = json.loads(Path(path).read_text())
        return cls(**{k: v for k, v in data.items()
                      if k in cls.__dataclass_fields__})
