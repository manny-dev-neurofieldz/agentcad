# Recovering Curves: Arcs, Chains and Drawn Intent

**Type**: Capability Policy (recover)
**Scope**: Any agent or person rebuilding a part whose source is gone: from a STEP file, a mesh-converted body or a design dump
**Status**: ACTIVE
**Commands**: agentcad probe section, agentcad probe sketches

## Purpose

A part to be rebuilt keeps its construction in the curves of its sections. In a body made of exact edges the arcs and lines can be read directly; in a mesh-converted body they survive only as hundreds of short edges whose vertices lie on them. The recover commands read those curves back as what a designer would have drawn (lines, arcs, which arc is tangent to which) and label every number with where it came from. The sketches of a design dump say what was drawn, which the finished solid does not; `probe sketches` reads them and says which drawn dimensions the part still carries. This policy says how to use these commands to recover a construction without inventing one.

## CEP Navigation Guide

**1 What Recovery Is For**
- When is recovering curves the right step, and when is a comparison enough?
- What does a recovered number carry with it?

**2 Reading Section Loops**
- What does `probe section` list, and for which planes?
- What limits does it apply, and how are they reported?

**2.1 The Frame**
- Which two coordinates are kept for each section plane?
- What do cw and ccw mean?

**2.2 Exact and Polylined Loops**
- How does a loop of exact edges differ from a polylined one?
- What does the record of a circular edge carry?

**3 Lines and Arcs from a Loop**
- How is a run of short edges turned into an arc?
- Which tolerances apply, and what does each one bound?
- What does each field of an arc mean?
- What happens to an edge that is neither a line nor an arc?

**3.1 Judging a Joint**
- What do tangent, kinked, not tangent, corner and skipped mean?
- Why is the centre distance alone not enough to call a joint tangent?
- What does scatter in the vertices do to the verdicts?

**3.2 Where the Reading Goes Wrong**
- Which inputs are read wrongly, and how can that be seen?

**4 A Loop as a Chain**
- What does the chain literal contain, and in which frame?
- Where do the literal and the listing go?

**4.1 Slivers**
- How are segments shorter than a stated length handled?

**4.2 Edges that Are Neither**
- What is done with an edge that is neither a line nor an arc?

**4.3 From the Literal to a Face**
- How is a literal turned into a face?

**5 Design Dumps**
- What is a design dump, and what does `probe sketches` print from it?
- Which part of the output needs no CAD backend?

**5.1 The Dump Format**
- Which fields does the reader use, and in which units?
- What happens to a field or a curve type it does not know?

**5.2 DRAWN and APPLIED**
- What does each label claim?
- How is a dimension matched against a part, and with what tolerance?
- Which sketches cannot be matched, and what does the output say then?

**6 Integration with Other Policies**
- Which policies govern what follows a recovery?

**7 Anti-Patterns**
- Which readings of these reports are wrong?

**8 Evolution and Feedback**
- How does this policy change?

=== CEP_NAV_BOUNDARY ===

## 1 What Recovery Is For

Recover curves when the source of a part is gone or was never code: a STEP file from a vendor or a converter, an STL turned into a solid, a part whose sketch history is lost. The aim is the construction (which lines and arcs, what radii, which are tangent) so that a new program is parametric and not a copy of the facets. `agentcad compare` says whether a rebuild matches the original; recovery says what to build.

Every number says where it came from. An exact edge keeps the numbers it has (`source` is `edge`, `rms` is 0). A fitted arc carries `rms` and `max` (the distances of its vertices from the fitted circle) and `n`, the count of vertices. An arc fitted to ten vertices with an `rms` close to the tolerance is a hypothesis, not a measurement; read those fields before building on a radius.

## 2 Reading Section Loops

`agentcad probe section SOURCE` cuts a STEP file or a build123d program at each plane named by `--planes` and lists the closed loops of exact edges, longest first, numbered from 1. A plane is `x=`, `y=` or `z=` followed by a number or `mid`, the middle of the bounding box on that axis; the default is `z=mid`. `-D VAR=VAL` (long form `--define`, repeatable) overrides a parameter of a program. `--max-loops N` keeps at most N loops per plane and prints the cap with its value. `--show N` lists at most N loops per plane, and at most N segments and N joints under each loop; a cut-off is printed, never silent. `-o FILE` (long form `--output`) writes the whole record as JSON, which `agentcad compare` also reads.

### 2.1 The Frame

Coordinates and directions are in the section plane's own 2D frame, the one the overlays draw: a section on `x=` keeps (y, z), on `y=` keeps (x, z) and on `z=` keeps (x, y). The record names the two axes. In that frame `ccw` turns left. Loops are read counter-clockwise whatever order the kernel listed the edges in, so `cw` and `ccw` mean the same on every part. An arc is `convex` when it bulges out of the loop's own inside (`ccw`) and concave when it bulges in (`cw`); for a hole, the inside of the loop is the hole.

### 2.2 Exact and Polylined Loops

A loop of exact edges lists lines and circular edges. A circular edge carries `center`, `radius`, `sweep_deg` and `via`, a point a quarter of the way along it: the end points cannot say which way a semicircle or a full circle is traversed, and neither can the circle's axis. A mesh-converted body, or any body whose curves were sampled, gives hundreds of short `line` edges instead, and the arcs are only in the vertices. A loop of lines alone with a dozen or more edges also reports `fit`, one circle through all its vertices; that is a first look, not a recovery.

## 3 Lines and Arcs from a Loop

`--arcs` reads every loop as lines and arcs. It prints, under each listed loop, the segments and a verdict for each joint, and adds the full record to the `-o` file under `arcs`.

The edges are chained head to tail first. A vertex that turns more than 30 degrees is a corner and never a sample of an arc. Between corners a run grows while one line or one circle holds every vertex within `--fit-tol` (default 0.005 mm); the circle is a least-squares fit of the vertices. Fewer than four vertices are never called an arc, because three points always lie on a circle, and neither are vertices joined by edges of very different lengths (the longest more than five times the median): a mesher samples an arc evenly, so a long edge among short ones is a straight side. A run grown this way swallows the first vertices of the next arc, since at a tangent joint a vertex cannot yet tell which arc it is on; so each boundary is then moved to the position where the two segments around it fit best. Edges that are already lines or circular arcs pass through with their own numbers.

Each segment is a line (`p0`, `p1`, `length`) or an arc: `center`, `radius`, `sweep_deg`, `direction` (`cw` or `ccw`), `convex`, `p0` and `p1` (equal for a full circle), `length`. All carry `rms`, `max`, `n` and `source`. `--tangent-tol` (default 0.01 mm) bounds how far the centre distance of two arcs may be from the tangent one; `--fit-tol` bounds how far a vertex may lie from its line or arc. They answer different questions: the first is a design test, the second a property of the data.

An edge that is neither a line nor a circular arc (an ellipse from an oblique cut, a spline) is not recovered. It is listed as REPORTED with its type, end points and length, it breaks the chain there, and the two joints next to it are skipped. It is never turned into a line.

The reading was checked on 3,060 generated loops (random convex polygons with filleted corners, lobed stars, sides of one edge or of up to 40 collinear edges, regular and irregular sampling, 0.25 to 5 degrees per vertex, vertex scatter 0 to 3e-5 mm): every one came back with the right number of arcs and lines, every radius within a few thousandths of a millimetre (plus 500 times the scatter), and every joint `tangent`.

### 3.1 Judging a Joint

Each pair of neighbouring segments gets a verdict from the fitted primitives alone, never from the vertex a fit happened to end at (one vertex of a 1 degree step on a 4 mm arc is 0.07 mm).

- Two arcs are tangent when their centres are |r1 - r2| apart if they turn the same way, and r1 + r2 apart if they turn opposite ways. `gap` is how far the centres are from that distance.
- An arc and a line are tangent when the line is r from the centre; `gap` is the difference.
- `kink_deg` is the angle at which the two curves cross, from the radii and the centre distance (none if they do not cross).

`not tangent`: the gap is more than `--tangent-tol`. `kinked`: the gap passes but the curves cross at more than one degree. `tangent`: neither. `corner`: two lines meet; `kink_deg` is the turn. `skipped`: a neighbour is not a line or an arc.

The centre distance is second order in the crossing angle. Circles of radius 4 and 6.1 that cross at 1.6 degrees have centres a thousandth of a millimetre from the tangent distance, so the stated test calls them tangent at any sensible tolerance; `kinked` exists for them. Test a construction hypothesis (lobes tangent to valleys, a slot tangent to its sides) with both numbers, `gap` for the centres and `kink_deg` for the directions. Do not tighten `--tangent-tol` to catch a kink: the gap shrinks with the square of the angle, and a tolerance low enough to see 1.6 degrees is at the noise floor of the fit.

On generated loops whose joints are all truly tangent (1,256 joints at each level of vertex scatter), no joint was flagged `not tangent` at any scatter up to 1e-3 mm (the largest gap was 0.0076 mm against the default 0.01), and none read `kinked` up to 3e-5 mm. At 1e-4 mm 3 joints read `kinked`, at 3e-4 mm 54 (4 per cent) and at 1e-3 mm 283 (22 per cent); at 1e-3 mm 3 of 120 loops also came back with the wrong count of arcs and lines. A few `kinked` joints in noisy data are expected; every joint `kinked` means the fit tolerance or the data needs a look.

### 3.2 Where the Reading Goes Wrong

- A polygon with turns under 30 degrees whose vertices lie on a circle (a 36-sided prism) is read as a circle. Vertices on a circle cannot be told from a sampled circle; `n` and the sweep per vertex are what a person judges it by.
- An arc sampled with fewer than four vertices, or with turns over 30 degrees, comes back as lines and corners.
- A straight side of only a few edges between two arcs of similar radius, sampled every 5 degrees with some scatter, can come back as a short shallow arc of four vertices: the data admit both readings (1 loop in 6,000 generated ones). An arc with `n` of 4 and a radius several times its neighbours' is the sign, and the joints on either side read `kinked`.
- Coarse tessellation: the vertices lie on the arc but the edges lie inside it by length squared over eight radii. The fit uses vertices, so the radius is right; `--fit-tol` does not bound the edges.
- Vertex scatter above about 1e-3 mm: raise `--fit-tol` to a few times the scatter, and read `rms`.
- An edge that is neither a line nor an arc makes the orientation of the loop approximate, because it is taken as the chord between its ends.
- Time grows with the number of edges: a loop of 54,000 edges takes about three seconds.

## 4 A Loop as a Chain

`--chain N` prints loop N of the listing (1 is the longest) as a Python literal on stdout, and the listing on stderr, so `agentcad probe section part.step --planes y=3.2 --chain 2 > outline.py` writes a fragment a program can paste. With several planes the loop N of each is printed, named for its plane. The literal is a list in the section plane's 2D frame, counter-clockwise, to four decimals:

```
LOOP = [
    ("arc", (5.0000, 0.0000), 3.0000, (5.0000, -3.0000), (5.0000, 3.0000), "ccw"),
    ("line", (5.0000, 3.0000), (-5.0000, 3.0000)),
    ("arc", (-5.0000, 0.0000), 3.0000, (-5.0000, 3.0000), (-5.0000, -3.0000), "ccw"),
    ("line", (-5.0000, -3.0000), (5.0000, -3.0000)),
]
```

Arcs are `("arc", center, radius, p0, p1, direction)`; `p0` equal to `p1` is a full circle. Each segment ends on the same numbers the next one begins with, and the last ends where the first begins. The header comments name the plane to build on (`Plane.XZ` for a section on `y=`) and say how many slivers were merged. A polylined loop comes out as a handful of tuples, because the arcs are recovered as in section 3; `--fit-tol` and `--tangent-tol` apply here too.

### 4.1 Slivers

`--min-len MM` (default 0.02) sets the length below which a line or arc is a sliver. A sliver is removed and the joint moves to where its two neighbours meet, so a micro-chamfer becomes the sharp corner it replaced; next to an unsupported edge the other neighbour runs on to cover it. Each merge is listed on stderr, and the count is in the header. Lower the value to keep more of the original edges.

### 4.2 Edges that Are Neither

An edge that is neither a line nor an arc is left out as a visible gap with a `REPORTED` comment, the header says `INCOMPLETE`, stderr says it was not turned into a line, and the exit status is 1. A wire built from the list is open exactly where the edge was. Model that edge by hand (a spline through points read from the section) or choose another plane.

### 4.3 From the Literal to a Face

This function builds the face from a literal; its arcs go through their end points and the middle of their sweep, so they join their neighbours exactly.

```python
import math
from build123d import Edge, Face, Location, Plane, Wire


def chain_face(chain, plane=Plane.XY):
    """A Face from a chain literal; the 2D points are in the plane's own frame."""
    edges = []
    for seg in chain:
        if seg[0] == "line":
            edges.append(Edge.make_line(seg[1], seg[2]))
            continue
        _, (cx, cy), r, p0, p1, direction = seg
        if p0 == p1:
            edges.append(Edge.make_circle(r).moved(Location((cx, cy, 0))))
            continue
        a0, a1 = math.atan2(p0[1] - cy, p0[0] - cx), math.atan2(p1[1] - cy, p1[0] - cx)
        sweep = (a1 - a0) % (2 * math.pi) if direction == "ccw" else -((a0 - a1) % (2 * math.pi))
        mid = a0 + sweep / 2
        edges.append(Edge.make_three_point_arc(p0, (cx + r * math.cos(mid), cy + r * math.sin(mid)), p1))
    return Face(Wire(edges)).moved(Location(plane))
```

The face lies in the plane through the origin. Move it to the section's coordinate by offsetting the plane: `Plane.XY.offset(z)` and `Plane.YZ.offset(x)`, but `Plane.XZ.offset(-y)`, because the normal of the XZ plane points toward -y.

## 5 Design Dumps

`agentcad probe sketches DUMP` reads a design dump, a JSON record of a parametric-CAD design, and prints its sketches in millimetres with a flag on every construction curve (`C`), then its parameters and its timeline. The dump is read with the standard library alone, so it needs no CAD backend. `--sketch NAME` keeps the sketches whose name contains NAME, ignoring case, and says how many of the dump's sketches it shows. `-o FILE` (long form `--output`) writes the record, every dimension with its labels, as JSON.

### 5.1 The Dump Format

The reader uses these fields; every other key is ignored, and a curve of any other type is listed with its keys as not read, never dropped.

```
{
  "designName": "name",                  string
  "designType": "...",                   string, optional
  "parameters": [                        optional
    {"name": "width", "expression": "40 mm", "role": "user", "comment": "...", "value_internal_cm": 4.0}
  ],
  "timeline": [                          optional, in order
    {"index": 0, "name": "Extrude1", "entityType": "ExtrudeFeature", "isSuppressed": false, "operation": "..."}
  ],
  "sketches": [                          required
    {
      "name": "Sketch1",
      "origin": [x, y, z],               centimetres, in model space
      "xDirection": [x, y, z],           unit vectors, in model space
      "yDirection": [x, y, z],
      "profileCount": 2,                 optional
      "curves": [
        {"type": "SketchLine",   "isConstruction": false, "start": [x, y, 0], "end": [x, y, 0]},
        {"type": "SketchArc",    "isConstruction": false, "center": [x, y, 0], "radius": r, "start": [x, y, 0], "end": [x, y, 0]},
        {"type": "SketchCircle", "isConstruction": true,  "center": [x, y, 0], "radius": r}
      ]
    }
  ]
}
```

Geometry (`origin`, curve points, `radius`) is in centimetres and is printed in millimetres. Curve points are in the sketch's own frame; an arc runs counter-clockwise from `start` to `end`. A parameter is kept as the dump states it: its `expression` is the authority, and `value_internal_cm` is centimetres whatever unit the design displays. A timeline entry is printed with its index, name, type, operation and whether it is suppressed.

### 5.2 DRAWN and APPLIED

Every number read from the dump is DRAWN: the radius of each circle and arc, the sweep of each arc, the length of each line, and each parameter. A line's angle and every position are printed without a label, because they follow from drawn endpoints.

`--against PART` (a STEP file or a build123d program) adds APPLIED. The part is cut on each sketch's plane, which must lie along an axis (`x=`, `y=` or `z=`); a dimension is APPLIED when that section carries it: a circular edge of that radius, an arc of that radius and sweep, or a line of that length, within `--tol` (default 0.01 mm; a sweep within the angle `--tol` subtends at the arc's radius). The section is read as in section 3, so a mesh-converted part is matched through its fitted arcs. The label names the loop that carries it. Construction curves are never matched, and parameters are DRAWN only.

A dimension compared and not found is printed `absent from the section`: it was drawn and the part does not have it. A later feature may have changed it, or the curve may only ever have been construction; the timeline says which features follow the sketch. A sketch whose plane is not along an axis, or that has no usable origin and directions, is not compared; the output says why and its dimensions stay DRAWN only. Without the build123d backend `--against` says so on stderr and leaves every dimension DRAWN only.

## 6 Integration with Other Policies

- `agentcad-session`: a program built from a chain is iterated, read and noted like any other. The measured solid count and face census say whether the rebuild closed and which faces it has.
- `agentcad-policies`: how this and every other policy is found and read.

## 7 Anti-Patterns

- **A radius without its evidence**: building on a fitted number without reading `rms`, `max` and `n`.
- **Reading tangency from the verdict word alone**: `tangent` with a gap near the tolerance is a joint to measure again; `kinked` is a joint to look at, not an error.
- **Straightening what was reported**: editing a REPORTED edge into a line to make the chain close. The face then has a shape the part never had.
- **Tightening `--tangent-tol` to catch a kink**: the gap shrinks with the square of the angle; read `kink_deg`.
- **Copying a defect because the file has it**: a sliver, or a joint that was drawn near-tangent by eye. Recovery shows what the file contains; what to build is a decision.
- **Reading DRAWN as true of the part**: the dump says what was drawn. Only APPLIED says the part still carries it.
- **Reading APPLIED as proof of intent**: a drawn length that equals an unrelated edge's length is APPLIED too; the loop named in the label says where.
- **Recovering a part that is a polygon**: a faceted body with many small turns is read as a circle. Check `n` and the sweep per vertex.

## 8 Evolution and Feedback

This policy ships with agentcad and changes with the commands it governs; a change to the behaviour of `probe section` or `probe sketches` updates this policy in the same pull request.
