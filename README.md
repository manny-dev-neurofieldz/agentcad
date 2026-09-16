# AgentCAD

Extensible agentic feedback loop for parametric 3D CAD design. Write CAD code, render, analyze visually, iterate - all driven by an AI agent.

AgentCAD abstracts the design feedback loop so it works with any CLI or API-scriptable CAD engine. The agent generates parametric code, renders it to multi-view PNG images, analyzes the visual output, identifies errors, and corrects the design autonomously.

## Architecture

```
╭──────────────────────────────────────────────────────────╮
│                    AI Agent (Claude)                     │
│                                                          │
│  ╭──────────╮    ╭──────────╮    ╭────────────────────╮  │
│  │  Write   │───▶│  Render  │───▶│  Analyze images    │  │
│  │ CAD code │    │  via CLI │    │  (multimodal)      │  │
│  ╰──────────╯    ╰──────────╯    ╰─────────┬──────────╯  │
│       ▲                                    │             │
│       └──────────── Feedback Loop ─────────╯             │
╰──────────────────────────┬───────────────────────────────╯
                           │
                   ╭───────┴───────╮
                   │   CADEngine   │ ◀── Abstract interface
                   ╰───────┬───────╯
            ┌──────────────┼──────────────┐
            ▼              ▼              ▼
     ┌────────────┐ ┌────────────┐ ┌────────────┐
     │  OpenSCAD  │ │  VoxelCAD  │ │   Future   │
     │   Engine   │ │   Engine   │ │    ...     │
     └────────────┘ └────────────┘ └────────────┘
```

## Quick Start

```bash
pip install -e .

# Check registered engines, their versions and export formats
agentcad info

# Render a source file to multi-view PNGs (engine from agentcad.toml, or -e)
agentcad render design.scad -v iso front top right
agentcad render model.py -e voxelcad -D size=25

# Export (STL by default; other formats per engine)
agentcad export design.scad -o output.stl
agentcad export design.scad --format 3mf
```

## Engines

Every engine implements the same `CADEngine` contract, so `render`, `export`,
`session` and the viewer behave the same way whichever one a project uses.
`agentcad info` lists what is registered, whether its backend is installed,
and which export formats it supports.

### OpenSCAD
- Renders `.scad` files via the OpenSCAD CLI
- Supports BOSL2 library for high-level parametric modeling
- Manifold backend for fast CSG operations (dropped automatically when the binary lacks it)
- Native EGL headless rendering (no display server needed)
- Exports STL, 3MF, OFF, AMF; `-D name=value` overrides go straight to OpenSCAD

### VoxelCAD
- Python-native voxel-based solid modeling
- Cython streaming kernels for fast geometry evaluation
- Smoothed STL export via SDF + Butterworth pipeline
- Source contract: `def build(**params)` returning the model (overrides are
  coerced to the types of the defaults), or a module-level `model`

### build123d (planned)
- B-rep modelling with STEP/STL/3MF/SVG export; same Python source contract as VoxelCAD

## Configuration

Each project folder carries an `agentcad.toml`. Engine tuning lives in a
`[engine.<name>]` table; only the project's engine reads its table, and keys
the engine does not know are reported on stderr rather than silently ignored.

```toml
[project]
engine = "openscad"

[engine.openscad]
fa = 1.0
fs = 0.5

[engine.voxelcad]
voxel_size = 0.2
```

## Camera Presets

Presets are engine-neutral viewing directions (eye, target, up, projection);
each engine derives its own camera from them, so the same preset gives the
same view on every engine.

| Preset | View | Purpose |
|--------|------|---------|
| `iso` | Front-right-top perspective | Default - shows three faces |
| `front` | Front orthographic | Dimensional inspection |
| `top` | Top-down orthographic | Plan view |
| `right` | Right orthographic | Side profile |
| `back` | Rear orthographic | Back features |

## Python API

```python
from agentcad.engines import get_engine
from pathlib import Path

engine = get_engine("openscad", settings={"fa": 2.0})
result = engine.render(Path("design.scad"), Path("output/"), views=["iso", "front"],
                       defines={"width": "40"})
for view, path in result.images.items():
    print(f"{view}: {path}")
print(result.metadata)  # engine-specific measured facts, e.g. facet_count

mesh = engine.export(Path("design.scad"), Path("output/design.3mf"), fmt="3mf")
if not mesh.success:
    print(mesh.errors)    # an unsupported format is an error result, not an exception
```

## Adding a New Engine

Implement the `CADEngine` abstract interface:

```python
from agentcad.engine import CADEngine, RenderResult, ExportResult, ValidationResult

class MyEngine(CADEngine):
    known_settings = ("tolerance",)     # keys accepted from [engine.mycad]
    FILE_EXTENSION = ".mycad"
    EXPORT_FORMATS = ("stl", "step")

    @property
    def name(self) -> str: return "MyCAD"

    def available(self) -> bool: ...
    def version(self) -> str | None: ...
    def render(self, source_path, output_dir, views=None, image_size=1024, defines=None) -> RenderResult: ...
    def export(self, source_path, output_path, fmt="stl", defines=None) -> ExportResult: ...
    def validate_syntax(self, code) -> ValidationResult: ...
```

Register it in `engines/__init__.py`. The contract test suite is parametrized
over the registry, so `pytest` exercises the new engine the same way the CLI
does with no test changes; `export` must return `self._unsupported_format(fmt)`
for formats outside `EXPORT_FORMATS`.

## Testing

```bash
pip install -e ".[dev]"
pytest              # summary; add --tb=short for failures
```

Engine tests skip when a backend is not installed, so the suite is green on a
machine with only one engine and still exercises every engine that is present.

## License

MIT
