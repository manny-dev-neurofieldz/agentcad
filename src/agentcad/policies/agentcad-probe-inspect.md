# Inspection Probes: Rays, Knobs and the Census

**Type**: Capability Policy (inspection probes)
**Scope**: Any agent or person measuring what a part is made of: walls, voids, parameters, face types
**Status**: ACTIVE
**Commands**: agentcad probe rays, agentcad probe knobs, agentcad probe inventory

## Purpose

A render shows a silhouette; it does not show how thick a wall is, how deep a bore goes, whether a gap is where it should be, which parameters of a program move the part at all, or whether a count of faces can be believed. The inspection probes measure those things. They read an exact source (a build123d program or a STEP file) exactly and a mesh to its tessellation, and every output says which it did. This policy says which probe answers which question, how to read the numbers, and what each one cannot tell.

## CEP Navigation Guide

**1 Choosing the Probe**
- Which question does each inspection probe answer?
- When is a render, a count or a section the wrong tool?

**1.1 Exact and Sampled Sources**
- What does a program or STEP source give that a mesh does not?
- How does an output say which one it read?

**2 Rays: Material and Void Along Lines**
- What does a ray report, and for which sources?

**2.1 Lines and Fans**
- How is a line given, and how is a fan?
- How are fan angles counted?
- How far is a line followed, and where is that recorded?

**2.2 Reading the Intervals**
- What do entry, exit and length mean?
- What do clipped and enclosed say?
- How is a wall thickness read from a ray?

**2.3 What a Ray Cannot Tell**
- How far may a mesh and an exact source differ?
- What does a line that touches a surface, or lies in one, report?
- What does a warning about a mesh that is not closed mean?

**3 Inventory and the Census**
- What does inventory report, and for which sources?

**3.1 When the Census Cannot See Analytic Types**
- When do inventory and the iteration tray say the representation hides analytic types?
- What follows from that warning?

**4 Meshes in probe section**
- What changes when probe section is given an STL?
- Where are the flags that apply to every source documented?

**4.1 Loops from Triangles**
- How does a mesh loop differ from an exact one?
- How is a plane that passes through vertices, or lies in a face, read?

**4.2 Radial and Axial Extents**
- What are the radial and axial extents of a loop?
- How are the axis and its centre chosen, and when must they be named?

**5 Knobs: Which Parameters Matter**
- What does a knob sweep run, and how many builds does it cost?
- How is the base moved, and how is a delta given?

**5.1 Reading the Verdicts**
- What do live, saturated, dead, partial and refused mean?
- What does a dead verdict not prove?

**6 Integration with Other Policies**
- Which policies govern what surrounds these probes?

**7 Anti-Patterns**
- Which readings of these probes mislead?

**8 Evolution and Feedback**
- How does this policy change?

=== CEP_NAV_BOUNDARY ===

## 1 Choosing the Probe

- A wall, a floor, a bore, a gap or a rib along a direction: `agentcad probe rays`. It returns lengths, which a render cannot.
- Whether a parameter is worth tuning, and which ones the part ignores: `agentcad probe knobs`.
- What the whole part is made of (bounding box, volume, area, solid and face counts, face types, cylinder axes, loops on planes): `agentcad probe inventory`.
- The outline of the part on a plane: `agentcad probe section`, governed by the recover policy; section 4 covers an STL source.

A render is evidence of silhouette, orientation and gross error only. A number that a feature must meet (a wall of at least so much) is read from a ray or an inventory, never from a picture.

### 1.1 Exact and Sampled Sources

A build123d program or a STEP file is a boundary representation: every crossing of a line with a face is found exactly, and the numbers are the part's. An STL is a soup of triangles with no exact surface: the numbers are the tessellation's, to the tessellation's tolerance, and a polygon that approximates a circle is slightly smaller than the circle.

Every output names its kind. The rays record carries `kind` (`brep` or `mesh`) and `method`, and the text header repeats them; an inventory is always exact and refuses a mesh.

## 2 Rays: Material and Void Along Lines

`agentcad probe rays SOURCE` follows lines through a solid and reports, per line, the intervals of material and of void. SOURCE is a build123d program, a STEP file or an STL file. `-D VAR=VAL` (`--define`, repeatable) overrides a parameter of a program, as everywhere; it is ignored for a mesh, and the output says so. `--show N` caps the intervals printed per line (default 12; the cap is printed when it applies and the JSON keeps all), and `-o FILE` (`--output`) writes the record (schema `agentcad.probe.rays/1`) as JSON.

Rays need a solid. A face, a wire or an empty shape has no inside, and the command says so.

### 2.1 Lines and Fans

`--line X,Y,Z:DX,DY,DZ[:LEN]` (repeatable) is a line from the start point X,Y,Z along the direction DX,DY,DZ, which need not be a unit vector. A start whose first number is negative is written with an equals sign, `--line=-30,0,0:1,0,0`, because a bare argument that begins with a minus sign is read as an option.

`--fan X,Y,Z:AX,AY,AZ:STEP[:FROM[:TO]]` (repeatable) is a set of lines that leave the point X,Y,Z on the axis along AX,AY,AZ, square to it, every STEP degrees. This is the reading for a bore, a boss or a turned part: from the axis outward, the radial wall in every direction. `--fan 5,0,0:0,0,1:45` gives eight lines, every 45 degrees about the Z axis through x=5, y=0, at the height of the point. `FROM` and `TO` limit the sweep (`TO` is included); the default is a full turn, which does not repeat its first line.

Angles follow the right-hand rule about the axis direction. 0 degrees is the world axis most nearly square to the fan axis (X, then Y, then Z when equally square): for an axis along Z, 0 degrees is +X and 90 degrees is +Y. Lines are labelled L1, L2, ... and F1@0, F1@45, ... (the fan's number and its angle).

A line is followed from its start, never behind it. Without a length it is followed through the part's bounding box, so a line begun far outside the part reports from where it enters; a line that misses the box reports no intervals and says so. `:LEN` on a line, or `--length L` for all lines without one, follows the line that far from its start instead. The range used is recorded on each line as `range` and `range_from` (`bounding box` or `length`).

### 2.2 Reading the Intervals

Each interval has a `kind` (`material` or `void`), an `entry` and an `exit` (distances along the line from its start, in the units of the part), their difference `length`, and the entry and exit points. Intervals tile the range with no gaps, alternating by kind. A line also carries totals: `material`, `void` and `enclosed_void`.

- `clipped_start` and `clipped_end` mark an interval that the end of the range cut short, not the part: a lower bound, never a thickness. A fan line begins on the axis, so its first interval is clipped when the axis lies inside a bore.
- `enclosed` on a void says material lies on both sides of it: a bore crossed, a gap in a wall, an internal cavity. A void that touches the start or the end of the range is open.
- A wall thickness is the `length` of a material interval that is not clipped, measured along a line square to the wall. An oblique line gives a longer interval, so aim the line along the wall's normal; a fan about a bore's axis is square to the bore wall everywhere.
- A depth is the length of the interval between two surfaces; a bore's diameter along a diameter line is its enclosed void.

### 2.3 What a Ray Cannot Tell

- A mesh differs from the exact part by its tessellation. A crossing on a curved wall can sit as far from the true surface as the tessellation's sagitta, and a line at a shallow angle to a surface moves the crossing by the sagitta divided by the sine of that angle. Compare mesh intervals with a tolerance of a few sagittas, not to the last digit, and expect a line that skims a curved wall to differ in kind.
- A line that only touches a surface (a tangent to a bore) does not open a gap. A line that lies in a face of the part is on its boundary and counts as material, for an exact source and for a mesh alike.
- A mesh that is not closed, or whose triangles are not consistently wound, has no inside along a line that crosses the fault. That line's record carries a warning, and its intervals are read from the crossing parity; repair or re-export the mesh before trusting intervals there. A mesh wound inward is read correctly.

## 3 Inventory and the Census

`agentcad probe inventory SOURCE` measures a build123d program or a STEP file exactly: bounding box, volume, area, validity, the solid, face, edge and vertex counts, the face census by surface type, every cylindrical and conical face with its axis (origin and direction, never a centroid) and radius, and with `--planes` (x=, y= or z= followed by a number or `mid`) the closed loops where each named plane cuts the part. `--max-loops N` keeps at most N loops per plane, and the cap is printed with its value when it applies. `--show N` caps the printed face list. `-o FILE` (`--output`) writes the record as JSON, and `-D VAR=VAL` (`--define`) overrides a program's parameter.

### 3.1 When the Census Cannot See Analytic Types

A body converted to splines (a STEP written from a spline export, a mesh-to-solid result, many swept or lofted bodies) describes every surface as a BSpline. The census then counts no cylinders, cones, spheres or tori, and the cylinder list is empty, which looks like a finding and is the representation talking.

When 90 percent or more of the counted faces are BSpline, `probe inventory` prints a warning and records it in `census_notes` (for a compound it checks the whole shape, then each solid), and the iteration tray prints the same sentence in its warnings. Read the zero as unknown, not as none. To learn whether the part has a round feature, measure it: a fan of rays about the suspected axis (a bore shows as a constant radius in every direction), or the section loops on a plane across it.

## 4 Meshes in probe section

`agentcad probe section SOURCE` accepts an STL as well as a program or a STEP file; the file's suffix decides. The planes (`--planes`), the cap on loops (`--max-loops`), the number of lines printed (`--show`) and the JSON output (`-o`) behave as for an exact source and are described in `agentcad-probe-recover`, which governs the command. This section covers what an STL changes. `-D` is ignored for a mesh and the command says so.

### 4.1 Loops from Triangles

Each triangle is cut by the plane and the cut segments are joined into loops. A loop record has the keys of an exact loop (`edges`, `closed`, `n_edges`, `length`, `fit`, `total_on_plane`), and every edge is a `line`. Collinear segments are merged, so a flat face gives one edge however many triangles it is made of; a polylined circle stays a run of short edges, and `fit` reads a run of at least 12 as a circle with its radius and residual. `closed` is false for a chain that does not return to its start: a hole in the mesh.

The JSON carries `kind` `mesh` and a note, and the text says it too: the loops are the tessellation's section, not the part's exact edges, so lengths and radii are compared to a tolerance. A plane that passes exactly through vertices reads as moved a hair toward lower coordinates, so a face lying in it belongs to the part above it. At the lowest coordinate of the mesh nothing is below, so the plane reads as moved a hair up: a part standing on z=0 and cut at z=0 gives the outline of its bottom face, as the exact kernel does.

### 4.2 Radial and Axial Extents

Every mesh loop, and each plane over all its loops (including any a cap dropped), carries `extents`: the radial extent (the nearest and the farthest distance of the loop from an axis) and the axial extent (its lowest and highest position along that axis). These are the numbers a turned part or a profile is checked by.

`--axis x|y|z` names the axis the extents are measured about; the default is the normal of each plane, so a section at z=mid gives radii about the Z axis and an axial extent that is the plane's own coordinate. To read a profile through the axis, cut with a plane that contains it and name the axis: for a part turned about Z, `--planes y=0 --axis z` gives the distance from the axis to the wall as the radial extent and the height as the axial extent.

`--axis-center A,B` names where the axis passes, as the two coordinates across it in x, y, z order (for the Z axis, x then y). The default is the middle of the mesh's bounding box, which for a polygonal body of revolution is within a sagitta of the true axis; name the centre for a part whose axis lies elsewhere.

## 5 Knobs: Which Parameters Matter

`agentcad probe knobs SOURCE --knob NAME=DELTA` runs a build123d program that defines `build(**params)` at its base values and, for each knob, at the base plus DELTA and minus DELTA: two builds per knob and one for the base, never more, and the count is printed. `--knob` is repeatable, and a delta may be a percentage of the base, `--knob width=10%`. `-D VAR=VAL` (`--define`, repeatable) moves the base before the sweep, for a part that is worth tuning around a value other than its default. `-o FILE` (`--output`) writes the record (schema `agentcad.probe.knobs/1`).

Each run is measured four ways: volume, area, bounding-box size and solid count, and each side reports its change against the base. A knob is a number: an integer's delta must be a whole number, and a boolean or a string is refused with a message. A run that does not build is recorded with its error, not hidden; a base that does not build stops the sweep.

### 5.1 Reading the Verdicts

- `live`: both sides change the part.
- `saturated`: one side changes the part and the other does nothing, so the knob is at a limit in that direction (a clamp, a minimum, a branch not taken). The record names the side that does nothing.
- `dead`: neither side changes anything the four measures can see. The parameter may be unused, shadowed, or overwritten before it is read.
- `partial`: one side does not build (a negative size, a fillet larger than its edge) and the error says why; `refused` means neither side builds.

A dead verdict names the measures, not a certainty. A knob that only moves a feature of equal volume along a wall, or only a label, reads as dead, and a delta that stays inside a clamp or below a feature's resolution reads as no change. Sweep again with a larger delta, and read the program, before removing a knob.

## 6 Integration with Other Policies

- `agentcad-session`: the tray after each iteration carries the census warning of section 3.1.
- `agentcad-probe-recover`: section loops of an exact source, fits and comparison; it governs `agentcad probe section` for every source, and section 4 here adds what an STL changes.
- `agentcad-policies`: how this and every other policy is found and read.

## 7 Anti-Patterns

- **Reading a clipped interval as a thickness**: an interval cut short by the range is a lower bound, whatever its length.
- **Trusting a zero from a spline census**: no cylinders counted is not no cylinders present when the census says it cannot see them.
- **Measuring a wall on a slant**: only a line along the wall's normal gives its thickness; aim it, or use a fan.
- **Comparing a mesh to the nominal to the last digit**: the tessellation is a stated approximation; the tolerance belongs to the comparison.
- **Judging a wall by its render**: a picture shows no thickness; ask a ray.
- **Reading mesh loops as exact edges**: a polylined circle has the tessellation's perimeter; read the fitted radius or the extents.
- **Calling a knob dead from one small delta**: a delta inside a clamp reads as no change; sweep a larger one.
- **Reading a saturated side as a broken knob**: it is at a limit, and the limit is the design's.

## 8 Evolution and Feedback

This policy ships with agentcad and changes with the commands it governs; a change to an inspection command's behaviour updates this policy in the same pull request.
