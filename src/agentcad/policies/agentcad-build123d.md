# build123d Practice: Programs That Keep Their Promises

**Type**: Practice Policy (construction)
**Scope**: Any agent or person writing or revising a build123d program for agentcad
**Status**: ACTIVE
**Commands**: none

## Purpose

A build123d program can build, report a valid solid and render plausibly while doing something other than what was asked: a fillet that never built, a vent that stops short of the wall, two bodies that only touch. The kernel does not know the intent, so the program has to carry it: knobs that mean something, values derived from the knobs instead of written twice, and a check after every feature. This policy collects the construction practice that keeps a build123d part honest, and the pitfalls that have each cost real time.

## CEP Navigation Guide

**1 The Program**
- Which values should be parameters, and which derived?
- How are dead knobs and silent couplings found?
- What should a program assert?

**2 Construction Practice**
- Which construction pitfalls have cost time, and how is each avoided?

**2.1 Fillets and Rounds**
- How are fillets and rounds made so they build and stay where they belong?

**2.2 Revolved and Axisymmetric Bodies**
- Where do the features of a revolved body go?

**2.3 Sketches, Lines and Chains**
- What goes wrong with sketches, lines and chains?

**2.4 Lofts**
- How are lofts made, thickened and checked?

**2.5 Bodies That Meet**
- How should bodies that meet be joined?

**3 After Every Feature**
- What is read after each feature, and why is a valid solid not enough?

**4 Reading Drawings**
- How is an unlabelled rounded section read?

**5 Integration with Other Policies**
- Which policies hold the engine, the probes and the review this practice relies on?

**6 Anti-Patterns**
- Which habits make a program lie?

**7 Evolution and Feedback**
- How does this policy change?

=== CEP_NAV_BOUNDARY ===

## 1 The Program

Write the part as `build(**params)` (`agentcad-engines`, section 2). The parameters are the knobs a user turns: widths, thicknesses, clearances, counts. Radii, levels and positions that follow from them are computed inside, never offered as knobs of their own: a value that encodes "ten from the end" or "tangent to the end face" becomes wrong the moment its neighbour moves.

A number two features must agree on is written once and the other derived from it; the program then asserts the derived value. Written twice, it is a coupling nobody enforces: one copy moves, the part still builds valid, and a vent becomes a blind pocket or an outline loses its tangency. To check, perturb the first value and watch the second feature keep doing its job.

Count the knobs and look for dead ones: `agentcad probe knobs` perturbs each and names those that move nothing measurable. A dead knob is a derived value posing as a parameter, or a feature that has stopped depending on what it should.

Cutters overshoot the faces they cut; a cut or a join that ends exactly on a face leaves coplanar faces the kernel resolves unpredictably. A height or a length that exists only to make an operation work (an intersect prism, a cutting box) is derived from what it must clear, not chosen. Assert what must stay true (one solid, a wall above its minimum, a feature present) so that a parameter value that breaks the geometry fails loudly instead of returning a valid-looking part.

## 2 Construction Practice

### 2.1 Fillets and Rounds

A fillet on an edge tangent to a curved crown propagates around it. Make a round in plan as a rounded-rectangle prism intersected with the body, rather than a fillet on vertical edges. Size a radius beside its neighbours, and when a fillet refuses, find the artifact it runs into before shrinking it (`agentcad-probe-construction`). Never wrap a fillet or chamfer in a bare `try`/`except`: the failure ships silently on every revision while the part still reads valid.

### 2.2 Revolved and Axisymmetric Bodies

Fillet the profile, then revolve it. Every axisymmetric feature goes in the profile: a sphere or a cut added outside it after the revolve can swallow the profile's narrowest feature (a throat, a seat) without any warning, and the knobs that sized that feature go dead.

### 2.3 Sketches, Lines and Chains

A line builder made inside a helper function does not feed the sketch that called it; make the face from its edges explicitly. Faces that share only an edge extrude to separate solids; overlap them in area. A 2D chain must share its endpoints exactly between consecutive segments, or the face gets an open wire: emit each joint once and reuse it, and draw an arc through three points with the middle one on the arc, on the long side for a sweep over 180 degrees. A raw section result from the kernel is wrapped in a compound before its edges are read.

A tilted cylinder meets a plane in an ellipse with semi-major radius r / cos(tilt); derive it rather than measuring it off a render. Know a plane's normal rather than working around it.

### 2.4 Lofts

Match the sections' edge structures (a stadium to a stadium, not a stadium to an ellipse) or the loft twists. Thicken a lofted sleeve by offsetting each section in 2D and lofting the offsets; a 3D offset of the lofted face may fail in the kernel. Render a loft with flat shading before calling it smooth: smooth shading hides a twist that flat shading shows (`agentcad-engines`, section 3), and the tray reports twisted faces.

### 2.5 Bodies That Meet

Bodies that end on the same cylinder or face fuse into an invalid solid, or leave a sliver so thin that the mesher refuses it: the render comes back empty while the volume and the solid count look fine. Overlap the bodies, and cut the shared feature once through the union. A fillet that would exist only over part of an edge is refused by the kernel; build it as a body (a revolved quarter-round, a prism along a chord) clipped to where it belongs.

## 3 After Every Feature

A feature is a change, and the change is what to check: after each one, read the solid count (one is the only passing value for a single part), validity, the volume change, the face census change (a chamfer that built adds its faces; zero new cone faces where two were due means it never built), and the extent. "It built" answers a different question from "did what I asked happen". A render cannot settle connectivity: a tangent touch and a 0.6 mm gap look the same at render size, and a part that renders whole can be three solids. A patch that joins two bodies needs its margin measured as well: the solid count says joined, not by how much, and a neck a few hundredths of a millimetre thick passes it.

The tray reads these for every session iteration (`agentcad-session`, section 2.1); read its warnings for short edges, twisted faces and a census that hides analytic faces, and look at the render itself: an empty render beside a sound volume is the sliver of section 2.5.

## 4 Reading Drawings

An unlabelled rounded section with two symmetry axes is a stadium of circle arcs, not an ellipse; drawings label ellipses. Read the drawing's numbers into the spec, then read the spec against the build: the build can contradict numbers the spec already holds.

## 5 Integration with Other Policies

- `agentcad-engines`: the program contract and the build123d engine's settings.
- `agentcad-session`: the loop and the tray that read every feature.
- `agentcad-probe-construction` and `agentcad-probe-inspect`: the probes for fillets, draft, rays and knobs.
- `agentcad-design-practice`: the posture these practices serve.
- `agentcad-design-review`: what a reviewer looks for in a program.
- `agentcad-policies`: how this policy is found and read.

## 6 Anti-Patterns

- **A derived value posing as a knob**: it goes wrong silently when its neighbour moves.
- **A number written twice**: two copies drift; derive one and assert it.
- **Valid as a verdict**: `is_valid` True on a broken part is the defect to look for, not a reassurance.
- **A swallowed failure**: an operation in a bare `except` never built and nobody knows.
- **Features bolted onto a revolve**: put them in the profile.

## 7 Evolution and Feedback

This policy changes as builds teach new pitfalls; a pitfall is added here when it has cost time on a real part and its cause is understood.
