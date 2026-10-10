# Fit and Mates: Testing a Mate with Both Bodies

**Type**: Capability Policy (assembly verification)
**Scope**: Any agent or person checking that two parts mate
**Status**: ACTIVE
**Commands**: agentcad fit

## Purpose

A mate stated in one part's program is a hypothesis; only a check with both bodies tests it. Every single-part instrument can pass while two parts meet line to line, bind on the way in, or miss each other by a millimetre. `agentcad fit` loads two exact shapes, poses the second against the first, and measures overlap, clearance, the gap inside each declared window, and where the surfaces touch. This policy says how to declare a mate, how the pair is posed and measured, how to read the verdicts, and what is recorded.

## CEP Navigation Guide

**1 Declaring Mates**
- Where is a mate declared, and what does each part state about its side?
- What do the datums fix, and what is left free when one is missing?

**1.1 The Assembly's Declaration**
- What does an assembly state about a mate that its parts do not?
- How does a mate name the two parts it joins?

**2 Posing the Pair**
- How is the second body placed when both parts declare datums?
- How is it placed when they do not?

**3 What Fit Measures**
- What do interference and clearance report, and what can neither show?
- What is a window, and how is it measured?
- What does the contacts report answer that a window does not?
- What do the sampling options change?

**3.1 The Insertion Sweep**
- How is a part that binds on the way in found?

**4 Verdicts**
- When does a window fail, and when is it unmeasured?
- What does the overall verdict say, and when does the command exit non-zero?

**5 The Views**
- Which images does fit write, and how is overlapping material marked?

**6 Records**
- What does a fit record carry, and where is it written?
- What does session finalize do with declared mates?

**7 Integration with Other Policies**
- Which policies govern the parts before and after a fit?

**8 Anti-Patterns**
- Which readings of a fit are wrong?

**9 Evolution and Feedback**
- How does this policy change?

=== CEP_NAV_BOUNDARY ===

## 1 Declaring Mates

A mate is declared under `[mates.NAME]` in an `agentcad.toml`, `job.toml` or `part.toml`. Each part declares its own side of the mate beside its source, in its own frame:

- `counterpart`: the other part's name;
- `axis`: a `point` and a `direction`, the axis the parts share (a bore and its pin, a slot's centre line);
- `key_line`: a `point` and a `direction` that fix the rotation about the axis;
- `rim_plane`: a `point` and a `normal`, the face the parts seat against;
- `window`, `nominal_mm`, `tol_mm`: a box `[x0, y0, z0, x1, y1, z1]` in this part's frame where the clearance is measured, the intended clearance, and the tolerance on it;
- `insertion` (the direction the part travels to assemble) and `dimensions` (named sizes, each with the `datum` it counts from) are read and kept for programs that use them; fit does not read them.

Vectors are three numbers. Directions and normals are normalised on load; a zero vector, a malformed entry, or a `rim_plane` or `key_line` without an `axis` is an error that names the mate and the key. An entry with only a window and a nominal stays valid.

Without a `key_line` on both sides the rotation about the axis is free; without a `rim_plane` on both sides the position along the axis is set by the axis points. Fit makes a fixed choice in each case and says so in its pose notes.

### 1.1 The Assembly's Declaration

An assembly (a project with part subprojects, or a print job) names the pair with `parts = [a, b]` and states the window, nominal and tolerance for it, the window in the frame of the first part. Its parts state their own datums. In a project that is not an assembly, `counterpart` alone names the pair, the project being the other part.

## 2 Posing the Pair

`agentcad fit A B` keeps part A where it is and places part B:

- `--mate NAME` poses B from the datums both parts declare for NAME: B's axis onto A's axis, B's key line onto A's about it, B's rim plane onto A's along it. Each side is the nearest `[mates.NAME]` at or above that part's source; `--a-mates` and `--b-mates` name the file or folder instead, which is needed when one source builds both parts. A side with no declaration, or one without an `axis`, is an error that says what to declare, or to pose with `--map`. Given more than once, the first mate poses B and each further one is compared with it. The window and nominal are A's side's, or else those of the nearest declaration above it (an assembly's).
- `--map axis=x|y|z spin=DEG offset=X,Y,Z` turns B about the named axis and then moves it: the pose for a pair with no declared datums.
- `--offset X,Y,Z` with `--spin DEG` and `--spin-axis` is the same turn-then-move; `--mate` and `--map` each replace them.
- With none of these, B stays as modelled, which is right when both parts are modelled in one assembly frame.

A build123d program whose `build()` takes `print_orient` is built with it false unless a define sets it, so parts meet in the assembly frame rather than in a print pose. `--a-define` and `--b-define` set each part's parameters.

## 3 What Fit Measures

`interference_mm3` is the volume both bodies occupy; zero is the only passing value for parts that must not overlap, and a boolean that fails is reported, never read as zero. `clearance_mm` is the smallest distance between the bodies; a line-to-line mate reads 0 here while every single-part instrument passes. Neither says where.

A window is a box where one gap matters: a key tip, a flange, a hole wall. Per window, fit reports the smallest distance between the two surfaces inside the box, measured both ways over a lattice of points covering each surface (`min_mm`, with `p05_mm` the fifth percentile). A window in which one part has no surface says so; it is never read as clear. Windows come from `--window NAME=x0,y0,z0,x1,y1,z1`, from `--mates-from PROJECT` and from `--mate`; when the parts are chosen with `part` defines, `--mates-from` keeps only that pair's entries.

Contacts answer where the parts meet, which a window answers only for the box it names. The points of A's surface lattice within `--contact-mm` (default 0.05; a negative value skips the report) of B's surface, measured to B's tessellated surface rather than to its sample points, are joined into regions; each region gives its centroid, its box and its closest distance.

`--step MM` sets the spacing of the surface lattice for windows and contacts (default: part A's bounding-box diagonal / 100). A finer step resolves smaller features and costs time.

### 3.1 The Insertion Sweep

`--sweep x|y|z` with `--travel MM` and `--sweep-steps N` reports the interference with B moved along the positive axis by the travel and then back to its pose in N steps (default 10), so a part that binds on the way in is seen even when it fits once seated.

## 4 Verdicts

A window with a `nominal_mm` gets a verdict: `fail` when its smallest clearance is below the nominal by more than the tolerance (`tol_mm`, default 0.05 mm), `unmeasured` when the window could not be read, and `pass` otherwise. An unmeasured window is never a pass. The verdict guards against too tight a mate: a clearance far above the nominal passes.

The overall verdict of a fit is `fail` (overlap beyond `--allow`, or a failing window), `unmeasured` (the overlap or a declared window could not be measured), `pass` (every declared nominal met) or `measured` (numbers recorded, no nominal declared to judge them by). The command exits 1 when a window fails or the interference exceeds `--allow` (mm^3, default 0), and 2 when the pose or the parts cannot be read.

## 5 The Views

With `-o DIR`, fit writes `fit.json` and its views: `fit_assembled.png` and `fit_exploded.png`; `fit_cutaway.png`, both parts cut open along the plane through the mate's axis and key line; and `fit_section_1.png` and `fit_section_2.png`, the two planes that contain the axis, part A grey and part B blue. Overlapping material is filled in one flat red in the cutaway and both sections. The frame is A's side of the mate when the pose came from datums; otherwise it is B's bounding-box centre with z as the axis.

A view shows where to look; the numbers in section 4 decide. Look at every view before acting on it.

## 6 Records

`--record` writes a fit record into the fit table of print manifests (`exports/NAME.print.json`): with no project named, into each part's own project (under `--mate`, the folder where the part declares its side; otherwise the project holding its source); with projects named, into those. A record carries when it was measured, the mate, both sources and their defines, a snapshot of each source (its SHA-256, and every `build()` parameter's value with the defines applied), the pose, the numbers, the window verdicts and the overall verdict. A later fit of the same mate, parts and defines replaces it. A project without a manifest is reported, not created: finalize it first.

`agentcad session finalize` fits every mate the project declares and records it. The pair comes from `parts = [a, b]`, or from `counterpart` in a project that is not an assembly. Each name is a part subproject's latest iteration, or a value of the project source's `part` parameter. Both parts' own declarations pose the pair when both state datums; otherwise the pair is fitted as modelled and the pose notes say so. The record goes to both parts' manifests and to the project's. A mate that cannot be fitted is reported with the reason and does not stop the finalize; a failing fit is printed and does not change finalize's exit status.

Fit reads build123d programs and STEP files as exact shapes; any other part is refused with the reason.

## 7 Integration with Other Policies

- `agentcad-session`: finalize runs the declared mates; the print manifest carries the fit table.
- `agentcad-policies`: how this policy is found and read.

## 8 Anti-Patterns

- **A render as the fit**: an assembled view looks the same at 0.0 mm and at 0.6 mm; read the clearance, the windows and the contacts.
- **An empty window read as clear**: a window where one part has no surface measures nothing; move the box.
- **A free spin read as a pose**: with no key line on both sides, the rotation is a choice fit made, not a fact about the parts.
- **A number written twice**: a window or nominal typed into a toml by hand drifts from the program that places the parts; generate it from the same parameters, or derive the datums from the parts.
- **A pass read as a good fit**: the verdict guards against tight; a loose mate passes. Compare the clearance with the nominal.

## 9 Evolution and Feedback

This policy ships with agentcad and changes with the command it governs; a change to fit's behaviour, to the `[mates]` contract or to the fit record updates this policy in the same pull request.
