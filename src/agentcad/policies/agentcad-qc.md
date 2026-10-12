# QC: Design Rules Judged Before a Print

**Type**: Capability Policy (print readiness)
**Scope**: Any agent or person checking that a part can be printed before it is staged
**Status**: ACTIVE
**Commands**: agentcad qc

## Purpose

Every print problem found after a print was a number that could have been read before it: a wall thinner than the nozzle can lay, a part taller than the printer. QC judges a part against the design rules of the printer it is meant for, before staging, and says in each finding what was measured, the limit, who set the limit, and the usual fix. This policy says how QC is configured, what it measures today, how its findings are read, and what its gate does at finalize.

## CEP Navigation Guide

**1 What QC Judges**
- Which rules does QC measure, and how is each measured?
- Against which printer is a part judged?

**1.1 Bridges and Floors**
- When is a ceiling a bridge, and how is its span measured?
- How is a floor too thin across the layers found?

**2 Limits and Their Layers**
- Where does each limit come from, and in what order do the sources apply?
- How is a rule's severity changed or a rule turned off?

**2.1 Feature Annotations**
- How does a program declare its features, and what does a feature change about a finding?
- How does a program accept a finding, or loosen a limit, and where is that shown?
- How does a program stay runnable without agentcad?
- Which engines read a Python program's annotations, and what is different about a voxel part?

**2.2 Annotations from OpenSCAD**
- How does an OpenSCAD file declare a feature, a suppression or a pose?
- What must an annotation string avoid, and how exact are the numbers in it?
- Why does a finding from an OpenSCAD declaration name the file and no line?
- What happens when a declaration is printed again, or cannot be read?

**3 The Print Pose**
- How is the pose a part prints in declared, by the project or by the program?
- How does the build-volume rule use the pose and the bed?

**4 Reading a Report**
- What does a finding carry?
- What does a rule that is not measured mean?
- When is a wall read off a voxel mesh, and when is it left unmeasured?
- When does the command exit non-zero?

**4.1 Fixes by Sensitivity**
- Which knob moves a failing finding, in which direction and by how much?
- What does a knob that moves nothing, or only one way, look like?
- How many rebuilds does it cost, and how is that bounded?
- For which engines does it work?

**5 The Gate at Finalize**
- When does QC run at finalize, and when does it hold a part back?
- What does a held part look like, and how does it continue?

**6 Integration with Other Policies**
- Which policies govern the printers, the session and the engines around QC?

**7 Anti-Patterns**
- Which readings of a QC report are wrong?

**8 Evolution and Feedback**
- How does this policy change?

=== CEP_NAV_BOUNDARY ===

## 1 What QC Judges

`agentcad qc PROJECT` judges the project's latest iteration. It measures the mesh of that iteration: the export finalize wrote, or, before a finalize, one exported for QC alone.

Measured today, on the mesh in its print pose:

- `build_volume`: the part's extent against the printer's build volume (section 3).
- `min_feature` and `min_wall`: the in-layer width of the material, the width the printer lays down. The part is cut at layer pitch (the project's `[print] layer_height`, coarser for a tall part, at most 400 sections, and the report says which); from points along every section edge a ray runs inward to the far boundary of the section, so the width is exact on the mesh. A corner is never read from inside itself: a hit closer than the limit along the boundary is two edges meeting, not the far side of a wall. Each thin region is then checked through the part, along the inward normal of the faces it lies on: thin there too, it is a wall; thick behind, it is a layer cutting a sloped edge (a layer sliver), counted in the report and not judged. On the mesh of a voxel engine a width is read only where the mesh can show it (section 4).
- `max_overhang`: faces turned down further than the limit from vertical, the face on the bed (within one layer of the lowest point) and the ceilings of bridges excepted, grouped into regions that share a vertex, each with its area and worst angle.
- `max_bridge` and the floors (section 1.1).

A wall or floor finding that no feature annotation claims (section 2.1) is unattributed and never more than a warning, whatever its severity setting: QC cannot tell a defect from a feature it does not know.

A part is judged against `--printer NAME` when given, else the project's `[qc] printer`, else the printer whose label equals the project's `[print] printer_profile`, else the Original Prusa MK4. `agentcad printers` lists the printers known (`agentcad-printers`).

### 1.1 Bridges and Floors

A ceiling is a set of faces within 5 degrees of facing straight down, above the first layer, joined where they share a vertex. Along each principal axis of its footprint (from the footprint's exact second moments), material within reach beyond both ends means the ceiling is held there; the reach is 2 mm or a fifth of the ceiling's extent, whichever is larger, so a fillet between a ceiling and its support still finds the support. A ceiling held along an axis is a bridge, and its span is its extent along that axis, the shorter one when it is held along both (a roof held all round). A bridge longer than `max_bridge_mm` is a `max_bridge` finding, unless the project's `[print]` table states `supports = true`, in which case the report lists it as supported. A ceiling held at one end or none is a cantilever or a floating roof, and stays an overhang. Every bridge is listed in the report with its span, width and verdict.

A floor is found across the layers, which the in-layer width cannot do: each layer of a thin horizontal plate is wide. Vertical lines on a grid over the part (spaced at the wall limit, or the part's width over 120 when that is larger) give the material along z; a run shorter than the wall limit is thin there. A thin run whose grid neighbours have no thin run at that height is the rim of a thin area (a chamfer or a fillet), and is left out. Each thin area is judged by its median thickness, as a wall is, and reports its thinnest run and its area.

## 2 Limits and Their Layers

A limit comes from the first of these that sets it, from the most specific:

1. a feature's annotation in the design's program (section 2.1);
2. the project's `[qc] limits` table, e.g. `limits = { min_wall_mm = 1.6 }`;
3. the printer's process defaults (`agentcad-printers`, section 2).

Every finding names the layer that set its limit (`project [qc]`, `process default (fdm, 0.4 mm nozzle)`, or, for the build volume, the printer and where it was defined), so a reader knows which number to argue with.

`[qc] severity` sets a rule's severity: `error`, `warning` or `off`, e.g. `severity = { build_volume = "warning" }`. A rule turned off is listed as not measured, with that reason.

### 2.1 Feature Annotations

A Python program, for the build123d or the VoxelCAD engine, can declare its features with `agentcad.annotate`, so that QC judges each one by its own job (an OpenSCAD file does the same with echo statements, section 2.2):

```
try:
    from agentcad.annotate import feature, suppress, print_pose
except ImportError:                       # without agentcad the annotations do nothing
    def feature(*args, **kwargs):
        pass
    suppress = print_pose = feature

def build(wall=1.2):
    ...
    feature("socket wall", box=(-6, -6, 0, 6, 6, 12), kind="wall")
    feature("flexure", box=(10, -2, 0, 20, 2, 4), kind="wall", min_wall_mm=0.5, why="the beam is the spring",
            knobs=("wall=0.1", "beam_len=10%"))
    suppress("max_overhang", box=(0, 0, 20, 30, 10, 22), why="the lid's underside; supports are planned")
    return part
```

A box is six numbers, `(x0, y0, z0, x1, y1, z1)`, in the part's own frame. A finding inside a feature's box belongs to that feature (the smallest box when several hold it): it names the feature and the file and line that declared it, takes the feature's own limits (`min_wall_mm`, `min_feature_mm`, `max_overhang_deg`, `max_bridge_mm`), and may be an error. The line is in the file the iteration was read from, not in the copy the session keeps, so it can be opened and edited.

`suppress(rule, why=..., box=...)` accepts a rule's findings, in the box or anywhere: they leave the findings and are listed in the report with the reason and the line. The reason is required; a suppression without one stops the build. A feature limit looser than the layer below it is listed the same way, with the feature's `why`; one loosened without a reason is also a warning. Each call is recorded per build, so a program built twice declares its features once. The build123d and VoxelCAD engines collect the annotations; the program runs unchanged where agentcad is not installed, through the fallback above.

The VoxelCAD engine executes a program more than once to size its grid, and the program's `feature` calls run each time; the engine keeps those of the pass that built the model, so a feature is declared once whatever the grid setting. A voxel mesh is written from the corner of its grid, not where the program built the part: QC puts it back before it sets the boxes against it (the report's `resolution` block lists the offset it applied). A place on such a mesh is good to about the mesh's resolution (section 4), so QC matches a box within that distance, and a box around a feature of a voxel part should reach a resolution beyond the feature.

### 2.2 Annotations from OpenSCAD

OpenSCAD cannot import `agentcad.annotate`, so a file declares the same things with `echo` statements. The first value is the marker `"AGENTCAD_QC"`, the second the kind of declaration (`"feature"`, `"suppress"` or `"pose"`), and the rest are named arguments, which are the Python call's keyword arguments one to one:

```
echo("AGENTCAD_QC", "feature", name="socket wall", box=[-6, -6, 0, 6, 6, 12], kind="wall",
     min_wall_mm=0.5, why="the beam is the spring", knobs=["wall=0.2"]);
echo("AGENTCAD_QC", "suppress", rule="max_overhang", why="planned supports", box=[0, 0, 20, 30, 10, 22]);
echo("AGENTCAD_QC", "pose", up=[0, -1, 0], spin_deg=0);
```

`pose` takes `up` and `spin_deg`, or `matrix` (three rows of three numbers); `feature` takes `name`, `box`, `kind`, `why`, `knobs` and the limits `min_wall_mm`, `min_feature_mm`, `max_overhang_deg` and `max_bridge_mm`; `suppress` takes `rule`, `why` and `box`. An argument given as `undef` counts as not passed. The same checks apply as in Python: a feature needs a name and a box, a suppression needs its reason, a feature is declared once, the pose is stated once. Boxes are in the part's own frame, as in Python. The statement counts only where OpenSCAD evaluates it: an echo in a module that is never instantiated declares nothing. `agentcad qc --fixes` turns a Python program's knobs and does not apply here.

Two things to know when writing one:

- **No double quotes inside an annotation string.** OpenSCAD 2021.01 prints a string without escaping what is inside it, and newer releases escape it differently, so the engine tells the end of a string by the quote that is followed by a comma, a closing bracket or the end of the line. A quote inside a string can look like such an end. Keep the strings plain: no double quotes, no backslashes, one line.
- **Coordinates carry six significant digits.** OpenSCAD prints a number with six significant digits, so a box is exact to 0.01 mm up to 9999.99 mm, and a coordinate such as `123456789` is read back as `123457000`. Write the numbers a box needs, not computed ones with a long tail.

An echo carries no line number, so a finding from an OpenSCAD declaration names the file alone (`part.scad`), where a Python declaration names `file:line`. The path is the one you edit, not the copy a session keeps.

OpenSCAD runs once for each view rendered and once for an export, and each run prints the declarations again. The engine reads each distinct line once, in the order it first appeared, so the same declaration printed by every view, or by a module evaluated twice, is one declaration; two different lines that declare the same feature are an error, as in Python. A declaration the engine cannot read (a misspelt argument, an unknown kind, a missing box, a value that is not a string, number, vector, true, false or undef) or that the checks refuse fails that render or export, with the offending line in the message, as an invalid annotation call fails a Python build. Other echo lines are ignored.

## 3 The Print Pose

`[qc] pose` declares how the part sits on the bed: `up` is the part's direction that points up (default `[0, 0, 1]`, the part as modelled), and `spin_deg` turns it about the vertical after that. For example `pose = { up = [1, 0, 0] }` lays a part on its side, its x axis up.

A program can state its own pose instead, with `print_pose(up=..., spin_deg=...)` or the whole rotation as `print_pose(matrix=...)` (three rows; a reflection is refused). It takes the place of `[qc] pose`, and the report says which pose was used and where it came from.

The build-volume rule takes the part's extent in that pose. A part taller than the build height is an error, since no turn on the bed helps. A footprint that fits the bed as posed passes. A footprint that fits only when turned about the vertical is a warning that names the turn, trying a quarter turn first and then the smallest turn that fits. A footprint that fits at no turn is an error.

## 4 Reading a Report

A finding carries the rule, the severity (`error`, `warning` or `ok`), what was measured and what was intended, why the rule matters, the layer that set the limit, where on the part (in the part's own frame), and the usual fix; its sentence says all of it. A wall finding gives its narrowest in-layer width, the layers it runs over, and the material through the part at its thinnest. `--json` prints the printer, the pose and where it came from, every limit with its layer, what each measurement sampled (section pitch and spacing, layer slivers counted, the floor grid, every bridge with its verdict), the findings, the features the program declared, what was suppressed and which limits were loosened (each with its reason and line), and the rules not measured with the reason for each.

A rule that is not measured has no finding: QC never fails a part on a number it did not take, and a part with no mesh to read is reported as not measured, not as passing.

A mesh from a voxel engine cannot show everything. The engine reports `resolution_mm`, the finest feature its mesh can show: the voxel edge times the marching-cubes stride of the pipeline that ran (a 0.1 mm voxel at stride 2 resolves 0.2 mm). QC reads a width off such a mesh only where the mesh resolves at most half the smallest limit in force for the rule, the layered limit and any feature's own: against the MK4's 0.45 mm feature limit that is 0.225 mm, and against its 0.9 mm wall limit 0.45 mm. A rule the mesh is too coarse for is listed as not measured, with the resolution, the voxel size and stride, and the limit, for example "the mesh resolves 0.40 mm (voxel 0.2 mm x stride 2); a 0.45 mm limit needs 0.225 mm or finer", and its thin regions are not judged against it. When only the wall rule can be read, a thin region is judged against the wall limit alone; when neither can, walls and floors are not measured at all. The walls and floors that are read carry the resolution as their uncertainty, where the mesh of a CAD kernel is exact, and the printed sentence says so. Overhangs, bridges and the build volume do not depend on it. To measure a wall the report calls unmeasured, make the mesh finer: a smaller `voxel_size`, or `mc_stride = 1`, at the cost of a grid that grows with the cube of the voxel count. Before a finalize, `agentcad qc` exports the mesh again and judges it by that export's resolution; after one, by the resolution recorded with the iteration, and an iteration recorded before its engine reported a resolution has none, so iterate again to get it.

The command exits 1 when a finding is an error or the project is not found, and 2 when its session, its pose or its printer cannot be read.

### 4.1 Fixes by Sensitivity

A feature can name the build parameters that move it: `knobs=("wall", "r=0.2", "h=10%")`, each a name with an amount or a percentage of its value (a bare name moves by 10%). `agentcad qc PROJECT --fixes` takes every error a feature claims and, for each knob that feature names, rebuilds the program at the knob's value plus and minus its amount and measures the same rule again at the same place: the width of the wall, the thickness of the floor, the worst angle of the overhang, the span of the bridge. The finding's fix then says what each knob did, with the measured value, the change and whether it passes. A knob is `live` (both directions move it), `saturated` (only one does), `dead` (it moves nothing there: a knob the feature does not depend on), `partial` or `refused` (a value that does not build). A knob can surprise: a larger outer diameter can thin a wall when the bore grows with it, and the measurement says so. When a change leaves nothing thin near the place, the fix reads, on the new build, the line the measure read across the place (a wall's inward normal in its layer, the vertical through a floor). Material on that line near the place, at least the limit across, means the finding is cleared, and the fix says how much material is there; material there still under the limit is neither, and the fix says to look; no material means the material is gone, and the fix calls that a failure, not a fix. An overhang or a bridge has no such line, so its fix still names both readings: look at the part. A bore that breaks through a wall can leave thin lips near the place. So the line across the place is read on every build that still has something thin near it: no material on it within the limit of the place means the wall is gone, and the fix says so with the lips' width beside it ("lips of 0.141 mm remain near it") rather than reporting the lips as a thinner wall.

The sweep rebuilds the program with build123d, so it works for a build123d project only: for a project on another engine, a VoxelCAD program included though it is a `.py` file too, the command says which engine the project uses and runs nothing, and the report is printed as usual. The program must define `build(**params)`; a knob with no default to start from takes its value from the iteration's defines. Every rebuild runs the program, so the sweep is bounded: `--max-runs N` (default 16, the base build included) caps the rebuilds, and a knob the budget did not reach is listed as not tried. Given without `--fixes`, `--max-runs` bounds nothing, and the command says it was ignored. The sweep runs only on errors a feature claims and only when asked; finalize does not run it. The JSON report carries every knob's record under `sensitivity`.

## 5 The Gate at Finalize

QC runs at `agentcad session finalize` only in a project that declares a `[qc]` table; a project without one finalizes as before. Its findings are shown on the newest variant of the viewer and printed.

With `[qc] gate = true`, an error holds the part back: finalize still writes the viewer, with a banner at the top saying why (kept in the session record, so a rebuilt viewer shows it too, until a finalize that is not held), but writes no print manifest, does not mark the session finalized, and exits 1. Fix the part and iterate again; no reopen is needed. A warning never holds a part back. `finalize --all` finalizes every part it can and exits 1 when any part was held back or could not be finalized, naming them.

## 6 Integration with Other Policies

- `agentcad-printers`: the printers, their build volumes and process defaults.
- `agentcad-session`: finalize, the viewer, and the tray's own findings.
- `agentcad-engines`: the metadata an engine gives QC: the declarations of a program, and the resolution and frame of a voxel mesh.
- `agentcad-policies`: how this policy is found and read.

## 7 Anti-Patterns

- **A clean report read as a printable part**: rules that are not measured are listed for a reason; a part QC passed can still have a wall too thin to print.
- **Arguing with the wrong limit**: the finding names the layer that set it; change that layer, not a different one.
- **Turning a rule off to pass a gate**: `off` is listed in every report; fix the part, or set the limit in `[qc] limits` with the reason in a comment.
- **A pose in prose**: a pose written in notes is not the pose QC judged; declare it in `[qc] pose` or with `print_pose`.
- **A box around the whole part**: a feature that claims every finding turns every warning into an error of that feature and says nothing about which feature is thin; box the feature itself.
- **Suppressing to pass**: every suppression and loosened limit is listed with its reason; a reason a reviewer would not accept is a finding left unfixed.
- **A voxel part read as exact**: a wall measured on a voxel mesh is good to about the mesh's resolution, which its uncertainty states; a wall the report lists as not measured was not found thick, it was not looked at.
- **A quote in an OpenSCAD annotation string**: OpenSCAD prints strings without escaping them, so a quote can end the string early; the declaration then fails with its line in the message, or reads shorter than written.

## 8 Evolution and Feedback

This policy ships with agentcad and changes with the command it governs; a change to QC's rules, limits, pose or gate updates this policy in the same pull request.
