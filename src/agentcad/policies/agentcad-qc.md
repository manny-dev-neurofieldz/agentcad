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

**3 The Print Pose**
- How is the pose a part prints in declared, by the project or by the program?
- How does the build-volume rule use the pose and the bed?

**4 Reading a Report**
- What does a finding carry?
- What does a rule that is not measured mean?
- When does the command exit non-zero?

**5 The Gate at Finalize**
- When does QC run at finalize, and when does it hold a part back?
- What does a held part look like, and how does it continue?

**6 Integration with Other Policies**
- Which policies govern the printers and the session around QC?

**7 Anti-Patterns**
- Which readings of a QC report are wrong?

**8 Evolution and Feedback**
- How does this policy change?

=== CEP_NAV_BOUNDARY ===

## 1 What QC Judges

`agentcad qc PROJECT` judges the project's latest iteration. It measures the mesh of that iteration: the export finalize wrote, or, before a finalize, one exported for QC alone.

Measured today, on the mesh in its print pose:

- `build_volume`: the part's extent against the printer's build volume (section 3).
- `min_feature` and `min_wall`: the in-layer width of the material, the width the printer lays down. The part is cut at layer pitch (the project's `[print] layer_height`, coarser for a tall part, at most 400 sections, and the report says which); from points along every section edge a ray runs inward to the far boundary of the section, so the width is exact on the mesh. A corner is never read from inside itself: a hit closer than the limit along the boundary is two edges meeting, not the far side of a wall. Each thin region is then checked through the part, along the inward normal of the faces it lies on: thin there too, it is a wall; thick behind, it is a layer cutting a sloped edge (a layer sliver), counted in the report and not judged.
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

A build123d program can declare its features with `agentcad.annotate`, so that QC judges each one by its own job:

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
    feature("flexure", box=(10, -2, 0, 20, 2, 4), kind="wall", min_wall_mm=0.5, why="the beam is the spring")
    suppress("max_overhang", box=(0, 0, 20, 30, 10, 22), why="the lid's underside; supports are planned")
    return part
```

A box is six numbers, `(x0, y0, z0, x1, y1, z1)`, in the part's own frame. A finding inside a feature's box belongs to that feature (the smallest box when several hold it): it names the feature and the file and line that declared it, takes the feature's own limits (`min_wall_mm`, `min_feature_mm`, `max_overhang_deg`, `max_bridge_mm`), and may be an error. The line is in the file the iteration was read from, not in the copy the session keeps, so it can be opened and edited.

`suppress(rule, why=..., box=...)` accepts a rule's findings, in the box or anywhere: they leave the findings and are listed in the report with the reason and the line. The reason is required; a suppression without one stops the build. A feature limit looser than the layer below it is listed the same way, with the feature's `why`; one loosened without a reason is also a warning. Each call is recorded per build, so a program built twice declares its features once. The build123d engine collects the annotations; the program runs unchanged where agentcad is not installed, through the fallback above.

## 3 The Print Pose

`[qc] pose` declares how the part sits on the bed: `up` is the part's direction that points up (default `[0, 0, 1]`, the part as modelled), and `spin_deg` turns it about the vertical after that. For example `pose = { up = [1, 0, 0] }` lays a part on its side, its x axis up.

A program can state its own pose instead, with `print_pose(up=..., spin_deg=...)` or the whole rotation as `print_pose(matrix=...)` (three rows; a reflection is refused). It takes the place of `[qc] pose`, and the report says which pose was used and where it came from.

The build-volume rule takes the part's extent in that pose. A part taller than the build height is an error, since no turn on the bed helps. A footprint that fits the bed as posed passes. A footprint that fits only when turned about the vertical is a warning that names the turn, trying a quarter turn first and then the smallest turn that fits. A footprint that fits at no turn is an error.

## 4 Reading a Report

A finding carries the rule, the severity (`error`, `warning` or `ok`), what was measured and what was intended, why the rule matters, the layer that set the limit, where on the part (in the part's own frame), and the usual fix; its sentence says all of it. A wall finding gives its narrowest in-layer width, the layers it runs over, and the material through the part at its thinnest. `--json` prints the printer, the pose and where it came from, every limit with its layer, what each measurement sampled (section pitch and spacing, layer slivers counted, the floor grid, every bridge with its verdict), the findings, the features the program declared, what was suppressed and which limits were loosened (each with its reason and line), and the rules not measured with the reason for each.

A rule that is not measured has no finding: QC never fails a part on a number it did not take, and a part with no mesh to read is reported as not measured, not as passing.

The command exits 1 when a finding is an error or the project is not found, and 2 when its session, its pose or its printer cannot be read.

## 5 The Gate at Finalize

QC runs at `agentcad session finalize` only in a project that declares a `[qc]` table; a project without one finalizes as before. Its findings are shown on the newest variant of the viewer and printed.

With `[qc] gate = true`, an error holds the part back: finalize still writes the viewer, with a banner at the top saying why, but writes no print manifest, does not mark the session finalized, and exits 1. Fix the part and iterate again; no reopen is needed. A warning never holds a part back. `finalize --all` finalizes every part it can and exits 1 when any part was held back or could not be finalized, naming them.

## 6 Integration with Other Policies

- `agentcad-printers`: the printers, their build volumes and process defaults.
- `agentcad-session`: finalize, the viewer, and the tray's own findings.
- `agentcad-policies`: how this policy is found and read.

## 7 Anti-Patterns

- **A clean report read as a printable part**: rules that are not measured are listed for a reason; a part QC passed can still have a wall too thin to print.
- **Arguing with the wrong limit**: the finding names the layer that set it; change that layer, not a different one.
- **Turning a rule off to pass a gate**: `off` is listed in every report; fix the part, or set the limit in `[qc] limits` with the reason in a comment.
- **A pose in prose**: a pose written in notes is not the pose QC judged; declare it in `[qc] pose` or with `print_pose`.
- **A box around the whole part**: a feature that claims every finding turns every warning into an error of that feature and says nothing about which feature is thin; box the feature itself.
- **Suppressing to pass**: every suppression and loosened limit is listed with its reason; a reason a reviewer would not accept is a finding left unfixed.

## 8 Evolution and Feedback

This policy ships with agentcad and changes with the command it governs; a change to QC's rules, limits, pose or gate updates this policy in the same pull request.
