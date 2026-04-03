# AgentCAD

Extensible agentic feedback loop for parametric 3D CAD design. Write CAD code, render, analyze visually, iterate — all driven by an AI agent.

AgentCAD abstracts the design feedback loop so it works with any CLI or API-scriptable CAD engine. The agent generates parametric code, renders it to multi-view PNG images, analyzes the visual output, identifies errors, and corrects the design autonomously.

## Quick Start

```bash
pip install -e .

# Check available engines
agentcad info

# Render a .scad file to multi-view PNGs
agentcad render design.scad -v iso front top right

# Export to STL
agentcad export design.scad -o output.stl
```

## Engines

### OpenSCAD (implemented)
- Renders `.scad` files via the OpenSCAD CLI
- Supports BOSL2 library for high-level parametric modeling
- Manifold backend for fast CSG operations
- Native EGL headless rendering (no display server needed)
- Multi-view rendering with configurable camera presets

### VoxelCAD (planned)
- Python-native voxel-based solid modeling
- Cython streaming kernels for fast geometry evaluation
- Smoothed mesh export via SDF + Butterworth pipeline

## Camera Presets

| Preset | View | Purpose |
|--------|------|---------|
| `iso` | Isometric (55, 45) | Default — shows three faces |
| `front` | Front orthographic | Dimensional inspection |
| `top` | Top-down orthographic | Plan view |
| `right` | Right orthographic | Side profile |
| `back` | Rear orthographic | Back features |

## Python API

```python
from agentcad.engines import get_engine
from pathlib import Path

engine = get_engine("openscad")
result = engine.render(Path("design.scad"), Path("output/"), views=["iso", "front"])
for view, path in result.images.items():
    print(f"{view}: {path}")

stl = engine.export_stl(Path("design.scad"), Path("output/design.stl"))
print(f"Exported {stl.facet_count} facets")
```

## Adding a New Engine

Implement the `CADEngine` abstract interface:

```python
from agentcad.engine import CADEngine, RenderResult, ExportResult, ValidationResult

class MyEngine(CADEngine):
    @property
    def name(self) -> str: return "MyCAD"

    @property
    def file_extension(self) -> str: return ".mycad"

    def render(self, source_path, output_dir, views=None, image_size=1024) -> RenderResult: ...
    def export_stl(self, source_path, output_path) -> ExportResult: ...
    def validate_syntax(self, code) -> ValidationResult: ...
```

Register in `engines/__init__.py` and the engine is available via `get_engine("mycad")`.

## License

MIT
