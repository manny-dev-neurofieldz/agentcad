# Engines: The CAD Kernels Behind One Contract

**Type**: Capability Policy (engines)
**Scope**: Any agent or person choosing an engine, configuring one, writing a source for one, or adding one
**Status**: ACTIVE
**Commands**: agentcad info

## Purpose

agentcad drives several CAD kernels through one contract: OpenSCAD for `.scad` sources, and build123d and VoxelCAD for Python sources. The session, the probes, the viewer and the print path talk only to the contract, so a part moves between them without changing how it is iterated, measured or shown. This policy says what an engine does and reports, how a project configures one, what a Python source must provide, what each registered engine is good for and how it measures, and what a new engine must satisfy.

## CEP Navigation Guide

**1 Engines and the Contract**
- What does every engine do, and what does it report?
- How is an engine chosen for a command?
- How are the installed engines and their versions listed?

**1.1 Settings**
- Where are an engine's settings written, and what happens to a key it does not know?
- Which settings does every engine accept?

**1.2 Measured Metadata**
- Which measurements can an engine report, and what does a missing one mean?
- How does an engine that measures nothing on render still feed the tray?

**2 Python Sources: the Program Contract**
- What must a Python source define?
- How do `-D` overrides reach the program, and with which types?
- What happens when a source defines no build function?

**3 build123d**
- What is build123d for, and which settings tune it?
- What does it measure?

**4 OpenSCAD**
- Which OpenSCAD binary and libraries does the engine use?
- What does it measure, and from what?

**5 VoxelCAD**
- What is VoxelCAD for, and how is its grid sized?
- Which surface pipeline does it render and export with?
- What does it measure, and what can it not?

**6 Camera Presets**
- Which views can be rendered, and which are rendered by default?

**7 Adding an Engine**
- What must a new engine implement, and what checks it?

**8 Integration with Other Policies**
- Which policies use the engines?

**9 Anti-Patterns**
- Which uses of an engine mislead?

**10 Evolution and Feedback**
- How does this policy change?

=== CEP_NAV_BOUNDARY ===

## 1 Engines and the Contract

An engine renders a source to one PNG per camera view, exports it to the geometry formats it supports, checks a source's syntax, and reports what it measured about the result. It also says whether its backend is installed and working, and the backend's version. A command picks the engine from its `-e`/`--engine` flag where it has one, else from `[project] engine` in the nearest `agentcad.toml`, else OpenSCAD.

`agentcad info` lists every registered engine with its status (available with its version, or not found), its source extension and its export formats, then the camera presets. It reads no project: an OpenSCAD binary named only in a project's `[engine.openscad]` table is not the one it checks (section 4).

### 1.1 Settings

An engine's settings are the `[engine.<name>]` table of the project's `agentcad.toml`; only the table of the engine in use is read. A key the engine does not know is reported on stderr with the list it does know, never silently dropped, so a misspelt setting is visible.

Two settings belong to every engine because they parameterise the report, not the kernel: `expected_solids`, how many bodies a single-part source should make (default 1), and `short_edge_mm`, the length below which an edge counts as short (default 0.25). A finding the tray raises names whether its limit came from the project's setting or from the default.

### 1.2 Measured Metadata

The keys an engine may report are fixed so that the tray and every later check read the same names: the bounding box (`bbox_min`, `bbox_size`), `volume`, `area`, `center_of_mass`, `counts` (solids, faces, edges, vertices), `is_valid`, `face_census` (planes, cylinders, cones, spheres, tori, BSplines, others), `short_edges` and `min_edge_mm`, `twisted_faces`, the voxel keys (`grid_resolution`, `voxel_size`, `grid_target`, `occupied_voxels`, `surface`), `kind` and `runtime_s`. Every key is optional: an engine that cannot measure a quantity leaves it out and readers print it as unavailable, and a measurement that failed is reported as `<key>_error` with the reason.

A session needs geometry from every iteration. When a render carries no volume and the engine exports STL, the session exports a mesh and measures it, so an OpenSCAD iteration still reports its box, volume and solid count; a lone `agentcad render` does not (`agentcad-render-export`).

## 2 Python Sources: the Program Contract

A Python source should define `build(**params)` returning the part, with a default value for every parameter: the defaults are the design, and each parameter is a knob a user may turn. `-D name=value` overrides arrive as strings and are converted to the type of the parameter's default (true or false, an integer, a number or a string; a parameter with no scalar default takes a Python literal). A value that cannot be read as that type is an error, and so is a name the function does not take, unless it accepts `**kwargs`.

A source without `build()` must leave its product in a module-level name: `part` (or `result`, or `model`) for build123d, `model` for VoxelCAD; any overrides are then ignored and a warning says so. As a last resort the build123d engine takes the largest shape the module left behind and names it in a warning, which can pick an intermediate over the product in a multi-body script: name the product instead.

## 3 build123d

build123d is a B-rep kernel (OpenCASCADE): exact faces and edges, fillets and chamfers, STEP in and out. It is the engine for a part that will be measured, mated, reverse-engineered or exported as STEP. Every build runs in a separate worker process with a time limit, so a kernel call that hangs is reported as a timeout.

Settings: `tolerance` (tessellation tolerance in model units; default the bounding-box diagonal divided by 2000), `angular_tolerance` (radians, default 0.1), `timeout` (seconds per render, default 120), `export_timeout` (seconds per export, default 300), `color`, `background`, `edge_color`, and `shading`: `smooth` (the default) shades a curved face as curved, `flat` shades each triangle on its own normal and so shows the tessellation, which is how a twisted or wrinkled loft is told apart from a smooth one. Exports: STL, STEP, 3MF and SVG. Rendering needs PyVista; export does not.

It reports the full set of B-rep measurements: box, volume, area, counts, validity, the face census, short edges and twisted faces. Its practice is `agentcad-build123d`.

## 4 OpenSCAD

OpenSCAD builds constructive solid geometry from a `.scad` program. The engine runs the binary named by `[engine.openscad] binary`, else by the `AGENTCAD_OPENSCAD` environment variable, else the first `openscad` on PATH; a binary that will not run reports the engine as not available, so a broken install reads as absent rather than failing mid-render. Where a machine has two installs and PATH finds the broken one, name the working one; set the environment variable when `info` should agree with the project.

Settings: `fa` and `fs` (fragment angle and size, defaults 1.0 and 0.5), `backend` (default `Manifold`; dropped when the binary does not offer a backend option), `colorscheme`, `library_path` (where included libraries are found; the `OPENSCADPATH` environment variable wins when set) and `binary`. `-D` overrides are passed to OpenSCAD's own command line unchanged. Exports: STL, 3MF, OFF and AMF.

OpenSCAD exposes no geometry through its command line: a render reports only the facet count, and the box, volume and solid count come from measuring an exported STL (section 1.2).

## 5 VoxelCAD

VoxelCAD models on a voxel grid: implicit shapes, lattices and gyroids, booleans of anything with an inside, and parts whose geometry is easier to state as a field than as faces. Every build runs in a worker process with a time limit, so an oversized grid or a process killed for memory is reported as an error.

The grid is sized from the model: `grid` voxels along its longest side (default 256), so a small and a large part build at the same cell count, unless `voxel_size` sets the cell edge directly; `warn_voxels` warns above a cell count (default 64 million). The surface used for renders and for the exported STL is the same: `surface_method` `auto` (the default; the fused streaming pipeline when its compiled kernels are present), `fast_smooth` or `cdt`; the staircase of the voxels is removed by a low-pass filter of `lowpass_cutoff` cycles per voxel (default 0.25; raise it towards 0.35 on a coarse grid whose thin walls are only a few voxels thick) and `lowpass_order` (default 4), then contoured with marching cubes at `mc_stride` (default 2, which loses nothing under the default cutoff). `only_largest_component` keeps the largest connected piece. Also `timeout`, `export_timeout`, `color` and `background`. Exports: STL.

It reports the grid (resolution, voxel size, target), the surface pipeline that ran, the box, the occupied voxels, the volume (occupied cells times the cell volume) and the solid count (connected components on the grid). Area, validity and a face census have no meaning on a grid and are not reported.

## 6 Camera Presets

Renders are named views: `iso`, `front`, `top`, `right`, `back`, `left` and `bottom`, all but `iso` orthographic. A lone render takes `iso`, `front`, `top` and `right` unless told otherwise; a session renders the project's `[output] default_views` (`agentcad-projects`).

## 7 Adding an Engine

An engine subclasses the engine base class, declares its source extension, its export formats and the settings it knows, and implements render, export and syntax validation; an unsupported export format returns an error naming the supported ones rather than raising. It registers under a short lower-case name. The engine contract test drives every registered engine through the same calls the commands make, so a registered engine that skips part of the contract fails there rather than in a session. Measurements go under the fixed keys of section 1.2, or the tray cannot read them.

## 8 Integration with Other Policies

- `agentcad-projects`: the project file that names the engine and holds its settings.
- `agentcad-session`: the loop that renders and measures each iteration.
- `agentcad-render-export`: rendering or exporting a source outside a session.
- `agentcad-build123d`: building well in the B-rep engine.
- `agentcad-policies`: how this policy is found and read.

## 9 Anti-Patterns

- **Leaving the product unnamed**: a program without `build()` or a named product gets the largest shape it left behind, which may be an intermediate.
- **Trusting `info` for a project's binary**: `info` checks the environment's OpenSCAD, not the one a project names.
- **A mesh measurement read as B-rep**: VoxelCAD's volume is a count of cells, and OpenSCAD's numbers come from its exported mesh; neither has a face census.
- **Smooth shading as evidence of a smooth surface**: render with `flat` shading before calling a loft smooth.

## 10 Evolution and Feedback

This policy ships with agentcad and changes with the engines; a new engine, setting or measured key updates this policy in the same pull request.
