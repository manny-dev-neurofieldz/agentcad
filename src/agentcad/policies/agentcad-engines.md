# Engines: The CAD Kernels Behind One Contract

**Type**: Capability Policy (engines)
**Scope**: Any agent or person choosing an engine, configuring one, writing a source for one, or adding one
**Status**: ACTIVE
**Commands**: agentcad info

## Purpose

agentcad drives several CAD kernels through one contract: OpenSCAD for `.scad` sources, and build123d and VoxelCAD for Python sources. The session, the probes, the viewer and the print path talk only to the contract, so a part moves between them without changing how it is iterated, measured or shown. This policy says what an engine does and reports, how a project configures one, what a Python source must provide, what each registered engine is good for and how it measures, and what a new engine must satisfy.

## Reaching for It

Choose the engine by what the part must be. Each row is what an engine gives you; the last column is where another engine is the better choice.

| The part needs | Reach for | Not when |
|---|---|---|
| exact faces, fillets and chamfers; measurement, mates, STEP in or out, reverse engineering | build123d | the shape is a lattice or a field: use VoxelCAD |
| a parametric family, a library of OpenSCAD modules (BOSL2), plain CSG that renders in a fraction of a second | OpenSCAD | it must be measured face by face, mated or exported as STEP: use build123d |
| lattices, gyroids, implicit shapes, booleans of anything with an inside | VoxelCAD | it needs exact edges or STEP, or walls thinner than about two voxels |

`agentcad info` says which of them are installed here. Section 8 compares them in full and says how a part moves from one to another; section 9 has a recipe for each.

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
- Which keys give QC a program's declarations, and the resolution and frame of a mesh, and which engine supplies each?

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

**8 Choosing an Engine**
- What does each engine do well, and what can it not do?

**8.1 Moving a Part Between Engines**
- How does a part built in one engine continue in another?

**9 Recipes**
- What does a first render and export look like in each engine?

**10 Constraints to Probe**
- Which limits of an engine are found by a command before they cost an iteration?

**11 Integration with Other Policies**
- Which policies use the engines?

**12 Anti-Patterns**
- Which uses of an engine mislead?

**13 Evolution and Feedback**
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

Three more keys are for QC and not for the tray (`agentcad-qc`); the iteration keeps them with the rest:

- `qc_annotations`: the features, suppressions and print pose a program declared, as records that each carry the `file` and `line` it was declared at. build123d and VoxelCAD supply them from the program's `agentcad.annotate` calls, one build's worth (VoxelCAD executes a source more than once to size its grid, and keeps the last pass's). OpenSCAD supplies them from the `echo("AGENTCAD_QC", ...)` lines in its output, each distinct line once, with a line of None because an echo carries none. An engine whose program declares nothing leaves the key out.
- `resolution_mm`: the finest feature the part's mesh can show, in model units. VoxelCAD sets it to its largest voxel edge times the marching-cubes stride of the pipeline that ran. A B-rep or CSG engine, whose mesh is exact to its tessellation, leaves it unset; QC reads a missing value as an exact mesh.
- `mesh_offset`: where the origin of the exported mesh lies in the frame the program builds in. VoxelCAD writes a mesh from the corner of its grid, so it reports that corner (the same point as `bbox_min`); an engine that writes the mesh where the program built it leaves the key out.

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

A `.scad` file declares its features for QC with `echo("AGENTCAD_QC", ...)` statements (`agentcad-qc`, section 2.2). Each render view and each export is a separate OpenSCAD process that prints them again, so the engine reads the distinct lines of all of them and reports the records as `qc_annotations` on the render and on the export alike. A declaration it cannot read, or that the checks refuse, fails that render or export with the line in the message; every other echo line is ignored.

## 5 VoxelCAD

VoxelCAD models on a voxel grid: implicit shapes, lattices and gyroids, booleans of anything with an inside, and parts whose geometry is easier to state as a field than as faces. Every build runs in a worker process with a time limit, so an oversized grid or a process killed for memory is reported as an error.

The grid is sized from the model: `grid` voxels along its longest side (default 256), so a small and a large part build at the same cell count, unless `voxel_size` sets the cell edge directly; `warn_voxels` warns above a cell count (default 64 million). The surface used for renders and for the exported STL is the same: `surface_method` `auto` (the default; the fused streaming pipeline when its compiled kernels are present), `fast_smooth` or `cdt`; the staircase of the voxels is removed by a low-pass filter of `lowpass_cutoff` cycles per voxel (default 0.25; raise it towards 0.35 on a coarse grid whose thin walls are only a few voxels thick) and `lowpass_order` (default 4), then contoured with marching cubes at `mc_stride` (default 2, which loses nothing under the default cutoff). `only_largest_component` keeps the largest connected piece. Also `timeout`, `export_timeout`, `color` and `background`. Exports: STL.

It reports the grid (resolution, voxel size, target), the surface pipeline that ran, the box, the occupied voxels, the volume (occupied cells times the cell volume) and the solid count (connected components on the grid). Area, validity and a face census have no meaning on a grid and are not reported.

For QC it also reports `resolution_mm` (the voxel edge times the marching-cubes stride of the pipeline that ran, so `voxel_size = 0.1` at the default `mc_stride = 2` is 0.2 mm), `mesh_offset` (its mesh starts at the corner of the grid, not where the program built the part) and the program's `qc_annotations`. The worker executes a source twice or three times when the grid is sized from the model, and the annotation registry is cleared before each pass, so the declarations reported are the last pass's, one of each. A wall thinner than about the resolution does not survive the contouring, so QC reads a width off the mesh only where the resolution is at most half the limit (`agentcad-qc`, section 4); pick `voxel_size` and `mc_stride` for the walls the part must be checked for.

## 6 Camera Presets

Renders are named views: `iso`, `front`, `top`, `right`, `back`, `left` and `bottom`, all but `iso` orthographic. A lone render takes `iso`, `front`, `top` and `right` unless told otherwise; a session renders the project's `[output] default_views` (`agentcad-projects`).

## 7 Adding an Engine

An engine subclasses the engine base class, declares its source extension, its export formats and the settings it knows, and implements render, export and syntax validation; an unsupported export format returns an error naming the supported ones rather than raising. An engine may also say which names `-D` can set in a source, read without running it (`parameters`, None when it cannot tell), so `render` and `export` refuse a misspelt name before anything runs; the Python engines read `build()`'s signature and OpenSCAD the variables a file assigns at top level. It registers under a short lower-case name. The engine contract test drives every registered engine through the same calls the commands make, so a registered engine that skips part of the contract fails there rather than in a session. Measurements go under the fixed keys of section 1.2, or the tray cannot read them.

## 8 Choosing an Engine

| | build123d | OpenSCAD | VoxelCAD |
|---|---|---|---|
| Kernel | B-rep (OpenCASCADE): exact faces and edges | CSG on meshes (Manifold) | voxel grid, contoured to a mesh |
| Source | Python, `build(**params)` | `.scad` | Python, `build(**params)` |
| Good at | fillets, chamfers, lofts, sweeps; STEP; parts that are measured, mated or rebuilt from an original | parametric families; OpenSCAD libraries such as BOSL2; fast plain CSG | lattices, gyroids, implicit shapes, booleans of fields |
| Exports | STL, STEP, 3MF, SVG | STL, 3MF, OFF, AMF | STL |
| Measures | box, volume, area, counts, validity, face census, short edges, twisted faces | facet count on render; box, volume and solids from its STL in a session | grid, volume by cells, solids by connected components, resolution |
| Cannot | lattices at any useful density | report faces or a census; write STEP | exact edges, a face census, STEP; walls under about its resolution |
| QC declarations | `agentcad.annotate` calls | `echo("AGENTCAD_QC", ...)` lines | `agentcad.annotate` calls |

When two engines could build a part, prefer the one that can also check it: a part that will be mated or measured belongs in build123d even when OpenSCAD would draw it faster, because only a B-rep carries the faces the fit and the probes read (`agentcad-fit`, `agentcad-probe-inspect`).

### 8.1 Moving a Part Between Engines

A part moves as geometry or as intent.

- **As geometry**: export it and load the file in the receiving program. build123d writes STEP and every engine writes STL; a build123d program reads either (`import_step`, `import_stl`), and an OpenSCAD file reads an STL with `import()`. A mesh brought into build123d is a solid of triangles: it can be cut and combined but has no faces to fillet or measure as faces. VoxelCAD reads no mesh.
- **As intent**: write the part again in the receiving engine from its dimensions and relations, not from its mesh. This is the only way into VoxelCAD, and the better way into build123d for a part that will be revised, since its parameters then stay knobs.

A move is checked like a reverse-engineered part: `agentcad compare ORIGINAL CANDIDATE --planes ...` with the loop counts as the gate (`agentcad-compare`).

## 9 Recipes

build123d: render a knob change, then export STEP, which only this engine writes.

```console
# recipe: examples
$ agentcad render examples/j_hook/source/j_hook.py -D reach=40 --views iso -o renders_j
counts: {'solids': 1
is_valid: True
Rendered 1 view(s)
$ agentcad export examples/j_hook/source/j_hook.py -f step -o j_hook.step
Exported: ...j_hook.step (step
```

The report carries the full B-rep set; `bbox_size` grows by the 10 mm the knob added. Next: look at the render (`agentcad-render-export`), then iterate in a session.

OpenSCAD: a render reports only its facets; the export is where the geometry is.

```console
# recipe: examples
$ agentcad render examples/hex_tray/source/hex_tray.scad -D cols=2 --views top -o renders_hex
facet_count:
Rendered 1 view(s)
$ agentcad export examples/hex_tray/source/hex_tray.scad -o hex_tray.stl
Exported: ...hex_tray.stl (stl
```

VoxelCAD: the report names the grid and the resolution the mesh can show; it exports STL and refuses STEP by name.

```console
# recipe: examples
$ agentcad render examples/gyroid_support_plug/source/gyroid_support_plug.py --views iso -o renders_plug
grid_resolution:
counts: {'solids': 1}
resolution_mm:
$ agentcad export examples/gyroid_support_plug/source/gyroid_support_plug.py -f step -o plug.step
# exit 2
--format step: VoxelCAD exports stl
```

`resolution_mm` is the thinnest wall the mesh can show; a wall the part needs thinner than twice it needs a finer `voxel_size` (section 5). Next: export STL, or iterate in a session.

## 10 Constraints to Probe

- An engine is usable only where its backend is installed and runs: `agentcad info` says available or not found for each, with its version.
- A format is written only by the engines that list it: `agentcad info` lists each engine's exports, and `agentcad export SOURCE -f FORMAT` refuses another with the engine's list.
- A `-D` name must be a parameter of the source: `agentcad render SOURCE -D name=value` refuses a misspelt name before anything runs and lists the names the source takes.
- A source must match its engine's language: `agentcad render SOURCE -e ENGINE` refuses a `.py` source for OpenSCAD, naming the extension the engine reads.
- A VoxelCAD wall survives only above about its resolution: `agentcad render SOURCE` reports `resolution_mm`, and `agentcad qc PROJECT` lists the width rules it could not measure at that resolution (`agentcad-qc`).

## 11 Integration with Other Policies

- `agentcad-projects`: the project file that names the engine and holds its settings.
- `agentcad-session`: the loop that renders and measures each iteration.
- `agentcad-render-export`: rendering or exporting a source outside a session.
- `agentcad-build123d`: building well in the B-rep engine.
- `agentcad-qc`: how the declarations, the resolution and the frame an engine reports are used.
- `agentcad-start`: the map by goal, whose first design step points here.
- `agentcad-fit`, `agentcad-probe-inspect`, `agentcad-compare`: what a B-rep lets a part be checked with, and how a move between engines is checked.
- `agentcad-policies`: how this policy is found and read.

## 12 Anti-Patterns

- **Leaving the product unnamed**: a program without `build()` or a named product gets the largest shape it left behind, which may be an intermediate.
- **Trusting `info` for a project's binary**: `info` checks the environment's OpenSCAD, not the one a project names.
- **A mesh measurement read as B-rep**: VoxelCAD's volume is a count of cells, and OpenSCAD's numbers come from its exported mesh; neither has a face census.
- **A voxel part's QC read as exact**: its mesh is coarser than a CAD kernel's by `resolution_mm`; a rule QC lists as not measured needs a finer grid, not a different reading.
- **Smooth shading as evidence of a smooth surface**: render with `flat` shading before calling a loft smooth.

## 13 Evolution and Feedback

This policy ships with agentcad and changes with the engines; a new engine, setting or measured key updates this policy in the same pull request.
