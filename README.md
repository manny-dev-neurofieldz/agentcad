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
     +------------+ +------------+ +------------+
     |  OpenSCAD  | |  VoxelCAD  | | build123d  |
     |   Engine   | |   Engine   | |   Engine   |
     +------------+ +------------+ +------------+
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
- `[engine.openscad] binary` (or `AGENTCAD_OPENSCAD`) names the executable when the first
  `openscad` on PATH is not the one to use; a binary that will not run reports the engine as
  unavailable in `agentcad info` rather than failing mid-render

### VoxelCAD
- Python-native voxel-based solid modeling
- Cython streaming kernels for fast geometry evaluation
- Smoothed STL export through the fused streaming pipeline (packed bits,
  Butterworth low-pass, marching cubes, straight to STL with no intermediate
  volumes); `[engine.voxelcad] surface_method`, `lowpass_cutoff`,
  `lowpass_order`, `mc_stride` and `only_largest_component` tune it for the
  renders and the export alike, and the metadata's `surface` block records
  which pipeline ran with its triangle count and time
- Source contract: `def build(**params)` returning the model (overrides are
  coerced to the types of the defaults), or a module-level `model`
- The grid is sized from the model: by default the longest side spans
  `grid` voxels (256), so a 10 mm part and a 100 mm part build at the same
  cell count; an explicit `voxel_size` overrides that, and a grid past
  `warn_voxels` (64M) is reported before it is built
- Every build runs in a subprocess with a configurable timeout, so an
  oversize grid or an out-of-memory kill is an error result, not a stuck CLI
- Measured facts (grid resolution, voxel size, bounding box, occupied cells,
  volume, solid count by connectivity) travel back in `RenderResult.metadata`
  / `ExportResult.metadata`
- Install the backend with `pip install -e ".[voxelcad]"` (from the VoxelCAD
  repository; it is not on PyPI)

### build123d
- B-rep modelling (OCCT) with STEP, STL, 3MF and SVG export
- Same Python source contract as VoxelCAD: `def build(**params)` or a module-level
  `part`; a script that names its product differently is harvested by size with
  a warning naming the variable chosen
- Every kernel call runs in a subprocess with a configurable timeout, so a hung
  operation is reported instead of waited on; renders are shaded tessellations
  with true B-rep edges; STEP/STL/3MF/SVG export work without PyVista
- Measured facts (volume, area, bounding box, face and edge counts, validity)
  travel back in `RenderResult.metadata` / `ExportResult.metadata`
- Install the backend with `pip install -e ".[build123d]"`

## Examples and the gallery

`examples/` holds one project per design across the three engines: a
gyroid electrode support plug (VoxelCAD), a pegboard J-hook, a printed M6
thread pair and a peg-and-plate assembly with part subprojects (build123d), and a
BOSL2 L-bracket and a hex pocket tray (OpenSCAD). Each is a plain agentcad
project (`agentcad.toml`, `source/`, a README saying what it exercises).

```bash
python examples/build_examples.py          # every example through a session, from scratch
agentcad gallery build -o site --projects "examples/*"
agentcad gallery check site                # every link and thumbnail resolves
```

The `gallery` workflow does exactly that on every pull request from a
clean checkout, attaches the built site to the run, and on `main` deploys
it as this repository's GitHub Page. An example that stops building fails
the check: the gallery is a test of the tool on every engine.

## Probe and compare

```bash
agentcad probe section part.py --planes y=3.2 z=mid -o loops.json   # closed loops of exact edges per plane
agentcad probe inventory part.step --planes z=mid                    # bbox, volume, census, cylinder AXES, loops
agentcad compare original.step candidate.py --planes y=3.2 -o cmp/   # loop-count gate, deviation both ways, overlays
```

`loops.json` (loops of typed edges per plane) and `points.json` (sampled
surface points) are the two exchange formats; every probe writes them and
`compare` reads them. A cap an instrument applies is printed with its
value. A cylindrical face reports its axis, never its centroid. Meshes are
compared in the sampled compartment only, and the output says so.

## Fit and mates

```bash
agentcad fit bar.py chute.py --mates-from job/ --record project/   # interference, clearance, windows, renders
```

A `[mates]` table in `agentcad.toml`, `job.toml` or `part.toml` declares each
mate's window (`[x0, y0, z0, x1, y1, z1]`), its `parts = [a, b]` (or a
`counterpart` in a part's own toml) and a `nominal_mm`. Windows are sampled on
both surfaces with a lattice, so a window in the middle of a flat face still
reads the gap; a mate is checked only on its own pair. The result is recorded
in the project's print manifest keyed by the two parts' defines.

## Reading sliced files

A design is not finished when it is exported: the slicer decides where supports go, which settings
apply and how each layer is printed, and Prusa printers receive that as binary G-code (`.bgcode`).
The `gcode` commands read it, in pure Python, with no slicer installed:

```bash
agentcad gcode info part.bgcode           # header, block table, printer and print metadata, thumbnails
agentcad gcode decode part.bgcode -o part.gcode   # plain G-code (a plain .gcode passes through)
agentcad gcode thumbnails part.bgcode -o thumbs/
agentcad gcode summary part.bgcode [--json]       # layers, filament, extrusion by object and feature, supports
```

`gcode summary` models the sliced file by layer (`;LAYER_CHANGE`/`;Z:`/`;HEIGHT:`), object (`M486` labels)
and feature type (`;TYPE:`), in absolute or relative extrusion with G92 resets, arcs and firmware retraction.
Its filament total is computed the way the slicer reports it (net extrusion without a final retraction that
is never primed again) and is printed beside the total the file states, so the two can be compared. A file
without feature comments still gives layers by Z and totals, and says the features are unknown; feature
types the model does not recognise are counted, never dropped.

`--json` prints a record with schema `agentcad.gcode.summary/1`: `layers`, `top_z`, `filament_used`
(`filament_mm`, `volume_cm3`, `mass_g` when the density is known), `filament_used_stated_mm` (from the
file's metadata), `features_known`, `unknown_features`, `objects` (id to name), `by_object` (filament,
per-feature amounts, `support_share`), `by_feature`, `support` (`share`, first and last layer and Z) and
`brim_area_mm2`.

`gcode check` compares the slicer settings the file carries with what the project intended, declared as a
`[slice]` table in `agentcad.toml` (or any TOML file, such as a print job's `job.toml`), keyed by the
slicer's own setting names:

```toml
[slice]
layer_height = 0.2
temperature = { min = 270, max = 285, why = "layer bond in ASA-CF" }
support_material_buildplate_only = { value = 1, why = "supports must not grow inside the bores" }
```

```bash
agentcad gcode check part.bgcode --project my_part/      # or --intent job.toml; --json for the findings
```

Each finding is a sentence: the setting, the value in the file, the value asked for, why it matters, and
the usual fix. A differing value is an error (exit status 1); a value outside a range, or a setting the file
does not carry, is a warning. With no `[slice]` table the command prints the file's key settings and says
there is nothing to check against. Print-host credentials in a slicer configuration are never printed. The
table also travels in the session's print manifest (`slice_intent`).

`gcode supports` says where supports touch the part, found from the toolpaths themselves: support extrusion
under the part's own extrusion within a Z window of the slicer's contact distance plus two layer heights (the
feature labels alone miss organic supports, which end in tips with no interface layer). Contacts are grouped
into bands, each with its object, height range, area and bed position:

```bash
agentcad gcode supports plate.bgcode                                   # bands in the bed frame
agentcad gcode supports plate.bgcode --placement plate.placement.json  # also in each STL's frame, and
                                                                       # outside / inside a cavity
```

A placement sidecar (schema `agentcad.placement/1`) records, per slicer label, the STL and its offset on the
bed. With it, each band is located in its object's own frame and checked against the mesh: on an outer surface,
or walled in on every side (a bore or pocket), which is an error (exit status 1): such supports are hard to
remove and foul the fit.

`gcode view` writes a standalone page of the toolpaths, offline (three.js inlined): lines coloured by
feature with a toggle per feature and a layer-range slider. Toolpaths are embedded within a budget
(`--budget-mb`, default 8, counted as embedded base64; the inlined three.js adds about 0.6 MB); over it,
every Nth layer is kept, first and last always, and the page says so.

With `--placement` (and `--stl-root` when the STLs are elsewhere) the placed parts are drawn translucent
under the paths, and support contacts as dots: green on an outer surface, red walled in a cavity.

```bash
agentcad gcode view plate.bgcode -o plate.toolpaths.html --placement plate.placement.json
```

`--artifact DIR` writes the same page as `DIR/index.html` without its document shell, plus an empty
`files.json` (everything is inline), for an artifact host that supplies the shell.

`session finalize` writes a toolpath page beside every `.bgcode` or `.gcode` file in the project's exports
folder (`<name>.toolpaths.html`, within `[output] viewer_embed_mb`) and lists them in the print manifest
under `sliced`; a file it cannot read is warned about and skipped.

Every block's CRC32 is checked; a damaged or truncated file fails with an error that names the block and
its byte offset (`--no-verify` skips the checks and says so). Supported: the format's version 1, all four
compression codes (none, deflate, heatshrink 11/4 and 12/4) and all three G-code encodings (none, MeatPack,
MeatPack keeping comments). The reader is written from the published format specification of Prusa's
libbgcode and the descriptions of heatshrink and MeatPack; it does not contain libbgcode code.

## Program-side helpers (build123d)

```python
from agentcad.helpers import soften
part, report = soften(part, fillet_r=1.0, chamfer_c=0.4, exclude=[[x0, y0, z0, x1, y1, z1]])
print("\n".join(agentcad.report.render_lines(report)))
```

`soften` fillets the concave joints and chamfers the convex edges of a
build123d part, trying the size then half of it and bisecting the selection
so one edge that refuses costs only itself. Every refused edge is listed
with its length, midpoint and the error; edges a neighbour's feature made
unfindable are counted as lost, never dropped, so applied + refused + lost
equals the candidates. `exclude` keeps a coin path or a thread sharp.

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
grid = 256            # voxels along the longest side (default)
# voxel_size = 0.05   # or an explicit cell size, which overrides grid
timeout = 120
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

## Adding a Command

A command module in `src/agentcad/commands/` adds commands without editing `cli.py`. The module defines `register(subparsers, groups)`: `subparsers` is the top-level subparsers action, and `groups` maps a command group's name (`probe`, `gcode`, `gallery`, `session`, and any group a module adds) to that group's subparsers action, so a module can also add a subcommand under an existing group. Every argument carries help text; `tests/test_cli_tree.py` walks the whole tree (`agentcad.cli.build_parser()`) and fails on a command without a handler or an argument without help. A module that fails to import is reported on stderr and skipped, and the other commands keep working.

## Testing

```bash
pip install -e ".[dev]"
pytest                          # summary; add --tb=short for failures
pytest --cov=agentcad           # with coverage (workers included; see pyproject)
```

Engine tests skip when a backend is not installed, so the suite is green on a
machine with only one engine and still exercises every engine that is present.
CI installs all three engines, runs the suite with coverage and fails under
the floor set in `.github/workflows/tests.yml`.

## License

MIT
