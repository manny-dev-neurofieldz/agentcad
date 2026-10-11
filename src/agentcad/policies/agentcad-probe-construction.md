# Construction Probes: Why a Fillet Fails, and Whether a Part Releases

**Type**: Capability Policy (inspection)
**Scope**: Any agent or person whose fillet or chamfer will not build, or whose part must leave a mold or a die
**Status**: ACTIVE
**Commands**: agentcad probe fillet, agentcad probe draft

## Purpose

Two construction questions recur and cannot be answered from the finished part. A fillet that fails was asked of edges that existed at the moment of the call, often next to a tiny step left by an earlier operation, and later operations may remove those edges before anyone looks. A part meant to leave a mold, a die or a support needs every side face leaning the right way, and a render does not show a degree. `agentcad probe fillet` stops a program at the call that fails and reports the edges as they were; `agentcad probe draft` measures the draft of every face against a pull direction. This policy says what each reports and how to act on it.

## CEP Navigation Guide

**1 Why a Fillet Fails**
- How is a program stopped at one fillet or chamfer call?
- What does the probe report about the selected edges and the part they belong to?

**1.1 Acting on the Result**
- What does a short step beside the chain mean, and what is the fix?
- Why is shrinking the radius until it builds the wrong fix?

**2 Draft Against a Pull Direction**
- How is draft measured on each face, and with what sign?
- Which faces are not judged, and why?
- How is a minimum draft enforced?

**3 Integration with Other Policies**
- Which policies cover the construction these probes diagnose?

**4 Anti-Patterns**
- Which ways of handling a failing fillet or a draft check mislead?

**5 Evolution and Feedback**
- How does this policy change?

=== CEP_NAV_BOUNDARY ===

## 1 Why a Fillet Fails

`agentcad probe fillet PROGRAM` runs a build123d program (any other source is refused, by name, since only a program can be stopped at a call) until its call of build123d's `fillet` function number `--index` (counting from 0; default the first), or of `chamfer` with `--at chamfer`, and stops there, leaving the program unmodified. A shape's own fillet method is not intercepted, and a program with fewer such calls is an error that says how many it saw. `-D`/`--define VAR=VAL` overrides the program's parameters.

At that call the probe reports:

- the live part the selected edges belong to: volume, solid count, face and edge counts, validity;
- each selected edge: type, length and midpoint, marked SHORT when shorter than `--short` (default 0.2 mm);
- every short edge of the live part that touches the selection: the steps a fillet runs into;
- for each size in `--radii` (default 1.0, 0.6, 0.4, 0.25), whether the whole selection takes it, and the largest size each edge takes alone;
- whether the live part is watertight.

`-o`/`--output` writes the record as JSON. Select edges from the part (`part.edges()`, or a face's edges); edges built apart from the part carry no parent, and the probe says so.

### 1.1 Acting on the Result

A fillet that fails is pointing at an artifact. The usual one is a step or a line under a fifth of a millimetre left beside the chain by an earlier operation: a boolean that stopped just short, two levels that differ by a rounding. Find it in the steps list, remove what made it, and size the radius beside its neighbours. Shrinking the radius until the call succeeds keeps the artifact and changes the design to fit it. Test a fillet at the step where it is applied, on the live part: the finished part may no longer have the edges the call selected.

## 2 Draft Against a Pull Direction

`agentcad probe draft SOURCE` takes a STEP file or a build123d program and measures, at a grid of `--samples` by `--samples` points on every face (default 7), the angle between the face and the pull direction: the arcsine of the outward normal's component along the unit pull. A positive draft releases, zero is a wall that drags, and a negative one is an undercut that locks; the sign rule is the same for a pocket and a boss. A curved face reports its range. `--pull x,y,z` sets the direction (default `0,0,1`). A face within one degree of perpendicular to the pull everywhere (a floor, a top, a parting face) is listed as perpendicular and given no draft: the probe says what it cannot judge instead of folding it into a number.

`--min-draft DEG` judges the side faces: those whose smallest draft is under it are listed as UNDERCUT, no draft or too little, worst first (up to `--show` lines, default 12; without `--min-draft` nothing is listed, and `--show` is named on stderr as ignored), and the command exits 1 when there is any. `-o`/`--output` writes the record as JSON, and `-D`/`--define` overrides a program's parameters (named as ignored for a STEP file). An STL is refused by name: draft is read on exact faces.

## 3 Integration with Other Policies

- `agentcad-build123d`: the construction practice that keeps fillets building.
- `agentcad-probe-inspect`: rays, knobs and the inventory, for the rest of a part's inspection.
- `agentcad-qc`: design rules judged against a printer before staging.
- `agentcad-policies`: how this policy is found and read.

## 4 Anti-Patterns

- **Probing the finished part for a fillet that failed earlier**: later cuts removed the edges; stop at the call.
- **A bare except around a fillet**: the failure ships silently on every revision while the part still reads valid; let it fail and probe it.
- **A draft check with no pull direction thought through**: the answer depends on the direction; state it from how the part leaves its mold or support.

## 5 Evolution and Feedback

This policy ships with agentcad and changes with these probes; a change to either updates this policy in the same pull request.
