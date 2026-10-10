# Policy ledger

Where the guidance in agentcad's policies came from. Before the policies existed, the know-how lived in working notes and scripts kept outside the package: three workflow skills, the index of a toolbox of probe scripts, two method pages and a set of design critiques from a knowledge base, and the definition of a reviewer agent. Each point of those sources is listed below with the policy section that now carries it, or with the reason it was not carried.

Policies are named without the `agentcad-` prefix, with a section number where one applies: `design-practice 3` is `agentcad policy read design-practice --section 3`. Points are paraphrased, with the parts they were learned on described rather than named.

Reasons a point was not carried:

- **local practice**: a step that belongs to one lab's own workflow (its knowledge base, notes, archives, experiments or file conventions). It stays in a local skill and is not part of the tool's guidance.
- **replaced by a command**: a script whose job an agentcad command now does; the command's policy carries the guidance.
- **part history**: the numbers, events or revisions of one particular part.
- **version detail**: a defect of one release of a library.
- **kernel detail**: a call or file-format detail used outside agentcad, with no agentcad command behind it.
- **agent runtime**: how an agent runs its own work, not how the tool is used.

## S1: Design workflow skill (build123d)

| Point | Now in |
|---|---|
| Not for editing a STEP that has no source | `reverse-engineering 7` |
| Not for OpenSCAD or BOSL2 work | not carried: local practice (the OpenSCAD engine itself is `engines 4`) |
| Not for repairing a mesh-only object | not carried: mesh repair is not an agentcad capability (`engines 5` covers modelling on a grid) |
| Consult the knowledge-base index and its recurring findings first | not carried: local practice; the recurring findings are carried (see S7) |
| Consult the lab's learnings index | not carried: local practice |
| Look at every render before reporting it | `session 2.2`, `render-export 1.1` |
| Watch long computations with progress logs and time limits | not carried: agent runtime; engine time limits are `engines 3` and `engines 5` |
| Pin a drill's predictions in its experiment register | not carried: local practice; pinning itself is `design-practice 3` |
| Archaeology: read the design dump's sketches, label hypotheses by origin, assume no symmetry the sketch does not draw | `reverse-engineering 2`, `probe-recover 5.2` |
| Where the lab's design archive lives | not carried: local practice |
| Spec by reconciliation; a probe reading explained away is still a reading | `design-practice 2` |
| State the direction of every mate before any dimension | `design-practice 2` |
| Pin volume band, envelope, solid count, load-bearing dimension, iterations; pins never move | `design-practice 3` |
| Build through a session; `build(**params)`; knobs are what a user turns, radii and levels derived | `session 1`, `engines 2`, `build123d 1` |
| Count the knobs and hunt the dead ones | `build123d 1`, `probe-inspect 5` |
| Look, measure and count on every iteration | `design-practice 4`, `session 2` |
| A render cannot see a tangency, a small gap or an internal throat | `session 2.2`, `build123d 3` |
| Probe what matters: overlays, ray runs, cavity scans, short-edge census, deviation as the secondary number | `design-practice 4`, `compare 5`, `probe-inspect 2` |
| A tight deviation is not evidence of function | `compare 4`, `design-practice 4` |
| Review before done: rubric, one revision | `design-review 3`, `design-review 4` |
| Hand the review round to a reviewer agent | not carried: agent runtime (the rubric is `design-review`) |
| Feed the knowledge base after each drill | not carried: local practice |
| Script: section overlay of original and candidate | replaced by a command: `compare 3` |
| Script: ray runs with circle fits | replaced by a command: `probe-inspect 2` |
| Script: cavity scan along an axis | replaced by a command: `probe-inspect 2.1` |
| Script: sampled deviation both ways, with where the worst 5% lies | replaced by a command: `compare 4` |
| Script: plane-section radial histograms of a mesh | replaced by a command: `probe-inspect 4.2` |
| Script: section of a STEP as loops of exact edges | replaced by a command: `probe-recover 2` |
| Script: arc fit of a polylined loop | replaced by a command: `probe-recover 3` |
| Script: one loop as a chained literal | replaced by a command: `probe-recover 4` |
| Script: zoomed per-window overlays with p95 and max | replaced by a command: `compare 3` |
| Script: spec numbers from a STEP; compare loop counts with the original | replaced by a command: `probe-inspect 3`, `compare 2` |
| The kernel import may need the worker's bootstrap in one container | not carried: agent runtime |
| A fillet tangent to a crown propagates; make plan rounds as a rounded prism intersected | `build123d 2.1` |
| Fillet a revolved body's profile, then revolve; every axisymmetric feature goes in the profile | `build123d 2.2` |
| A tilted cylinder meets a plane in an ellipse of semi-major r / cos(tilt) | `build123d 2.3` |
| A line builder inside a helper does not feed the sketch; faces sharing only an edge extrude apart | `build123d 2.3` |
| One elliptical-arc constructor crashes with positional arguments in one release | not carried: version detail |
| Aggregate pins hide compensating errors | `design-practice 3` |
| An unlabelled rounded section with two symmetry axes is a stadium | `build123d 4` |
| Lofts: match the sections' edge structures; thicken by offsetting each section in 2D | `build123d 2.4` |
| A first exercise missed its mass target on exactly that reading | not carried: part history |
| Read your spec against your build | `design-practice 2`, `build123d 4` |
| Reverse engineering: loops of exact edges, shared centres, repeated radii, polylines as arcs, no fit across two curves, hypotheses asserted against data | `reverse-engineering 3`, `reverse-engineering 4`, `reverse-engineering 5` |
| A census dominated by planes means a mesh-converted body; fit on each edge's own vertices; split the work by body | `reverse-engineering 3`, `reverse-engineering 4`, `reverse-engineering 5` |
| Bodies ending on the same cylinder fuse invalid or leave a sliver the mesher refuses; overlap and cut once through the union | `build123d 2.5` |
| Read validity and the tessellation every iteration | `build123d 3` |

## S2: Assembly fit skill

| Point | Now in |
|---|---|
| Use it when a feature is sized to another part | `design-practice 6`, `fit 1` |
| Parts from different tools share no assembly, so nothing else checks the mate | `design-practice 6`; a mesh counterpart is not yet accepted by `fit` (captured as an idea) |
| Run it before a pair is printed and after any mate parameter changes | `design-practice 6`; finalize fits declared mates, `session 4` |
| Copy the mate's relation from the other part's source, not from a description of it | `design-practice 6`, `fit 1` |
| Pose from datums; check the map is a rotation | `fit 1`, `fit 2` |
| Measure penetration both ways, clearance per window, an insertion sweep, renders and sections | `fit 3`, `fit 3.1`, `fit 5` |
| Read where the parts touch, not only the minima | `fit 3` |
| A window holding two mates reports the nearer; one window per face pair | `fit 3` |
| Fix the relation, not the number; record the fit in both parts | `design-practice 5`, `fit 6` |
| File the run's images and numbers with the part | not carried: local practice (the library's file conventions) |
| A derivation datum mismatch passes every render, volume and loop count | `design-practice 6` |
| Clean the tessellation and fall back to the kernel's classifier for a closed-surface test | not carried: kernel detail, now inside `fit` |
| Distances are exact only to the tessellation; sample finely enough for the smallest gap | `fit 3` (a minimum that halving the step changes was not resolved) |
| Sweep from fully outside to seated | `fit 3.1` |
| As-printed is not nominal; bracket the clearance | `design-practice 6`, `render-export 2.1` |
| Script: the whole fit measurement | replaced by a command: `fit` |

## S3: STEP edit without source skill

| Point | Now in |
|---|---|
| Edit the parametric source when it is available | `reverse-engineering 7` |
| A large reshaping is redesign, not an edit | `reverse-engineering 7` (a small edit) |
| A mesh-only input needs another workflow | `reverse-engineering 7` (a STEP remains) |
| Toolchain installation and per-session check; off-screen rendering | not carried: agent runtime |
| Inventory the solid first; face-type counts identify features | `reverse-engineering 7` step 1, `probe-inspect 3` |
| Match against an independent reference before cutting; derive the mapping from centres | `reverse-engineering 7` step 2 |
| Parsing one CAD tool's sketch export (line endings, units, offsets) | not carried: kernel detail |
| No reference: show the candidates and get the edit confirmed | `reverse-engineering 7` step 2 |
| Guards that refuse to cut; a tripped guard is a finding | `reverse-engineering 7` step 3 |
| Defeature a feature's complete face set; an addition is a fuse or cut with a tool solid | `reverse-engineering 7` step 4 |
| Verify: validity, face-count delta, volume delta and its sign, rays, a render that outranks the rest | `reverse-engineering 7` step 5 |
| Record the fork, with the caveat to recreate a canonical variant parametrically | `reverse-engineering 7` step 6 |
| Bounding boxes of untessellated splines bound control points; integrated volume is exact | `reverse-engineering 7` |
| A feature is not its most visible face | `reverse-engineering 7` |
| One mesh writer's API spelling | not carried: kernel detail |
| Exclude notebooks and environments when searching CAD trees | not carried: agent runtime |
| Defeaturing can fail politely; fall back to a cut with a tool solid | `reverse-engineering 7` step 4 |
| Reference scripts for the steps | not carried: kernel detail (no agentcad editing command yet; captured as an idea) |
| Where derived files go in the lab's library | not carried: local practice |
| Report measured numbers as facts and label the rest as estimates | `design-practice 4` |

## S4: Probe toolbox index

| Point | Now in |
|---|---|
| Section curves of a STEP as loops with type, centre, radius, sweep | replaced by a command: `probe-recover 2` |
| Arc fit of a polylined loop with a tangency check | replaced by a command: `probe-recover 3` |
| A loop as a chained literal with shared endpoints, slivers merged | replaced by a command: `probe-recover 4` |
| Per-window overlays with p95 and max, any plane, program or STEP | replaced by a command: `compare 3` |
| Loft smoothness: flat versus smooth shading, normal turns | `engines 3`, `build123d 2.4`; twisted faces in the tray, `session 2.1` |
| A design dump's sketches in mm with construction flags | replaced by a command: `probe-recover 5` |
| Spec numbers from a STEP; a loop cap named as the instrument's; a census that reveals a converted body | replaced by a command: `probe-inspect 3`; the cap lesson is `compare 2` and `reverse-engineering 3` |
| A gear-pair fit judged against the original pair's own residual | `reverse-engineering 6` |
| The mixed-source fit measurement | replaced by a command: `fit` |
| Other drill scripts (full-part overlay, ray runs, sampled deviation) | replaced by a command: `compare`, `probe-inspect 2` |
| Organise tools by the question asked: recover, compare, inspect, present | the command groups and their policies: `probe-recover`, `compare`, `probe-inspect`, `viewer` |
| Label tools by the representation they consume: exact, sampled, intent | `probe-inspect 1.1`, `compare 1`, `probe-recover 5` |
| Use cases are checklists, not folders | not carried here: workflow skills that ask these policies |
| One exchange format for loops, shared by every tool | `probe-recover 2` (loop records) |
| Run a compare by default at finalize | not carried: finalize runs declared fits (`session 4`); there is no declared original to compare with |
| The order the tools would pay off as commands | not carried: part history (all four are commands now) |
| The dated promotion notes | not carried: part history |

## S5: Method, recovering curve intent from a STEP

| Point | Now in |
|---|---|
| Precondition: reading the original's source must be allowed | `reverse-engineering 1` |
| Section at mid-thickness; loops by endpoint connectivity; print each edge | `reverse-engineering 3`, `probe-recover 2` |
| Read the loops for shared centres, repeated radii, recurring centres | `reverse-engineering 3` |
| Polylined loops are arcs: curvature runs, circle fits, tangency | `reverse-engineering 4`, `probe-recover 3` |
| Never fit across two curves | `reverse-engineering 4`, `probe-recover 3.2` |
| Build forward from hypotheses and chained literals; assert predicted radii | `reverse-engineering 5`, `probe-recover 4` |
| Verify per feature with windows, then sampled deviation; acceptance at the export's own discretisation | `reverse-engineering 6`, `compare 5` |
| Two segment lengths in a polyline go with two radii | `reverse-engineering 4` |
| Tiny lines between paired fillets are modelling residue | `reverse-engineering 5` |
| One rebuild once the curves are exact | `reverse-engineering 6` |
| Wrap a raw section result before reading its edges | `build123d 2.3` |
| A chain's endpoints must be shared exactly; arcs through three points | `build123d 2.3`, `probe-recover 4.3` |
| Sweeps over 180 degrees need the middle point on the long way | `build123d 2.3` |
| The part's later revision and its numbers | not carried: part history |
| Promote these steps to commands | done: `probe-recover`, `compare` |
| Archaeology: sketches keep the drawn skeleton; body edits appear only in sections | `reverse-engineering 2` |
| Base-feature chains hide geometry in a sibling design | `reverse-engineering 2` |
| A capped loop inventory truncates toothed parts; compare counts of your own build | `compare 2`, `reverse-engineering 3`, `reverse-engineering 6` |
| A fit is judged against the original pair's own residual | `reverse-engineering 6` |
| A STEP can carry a mesh-converted body beside exact geometry; split the work by body | `reverse-engineering 3`, `reverse-engineering 5` |
| Drawn reference circles over mesh polygons are the intent | `reverse-engineering 5` |
| Fit an edge's circle to its own vertices; a centre on an axis means tangency; a run across a corner lies | `reverse-engineering 4` |
| Rib ends were radial flat cuts, not rounds | not carried: part history |
| Bodies drawn on the same radius fuse invalid or leave a sliver; overlap and cut once | `build123d 2.5` |
| A fillet over part of an edge is refused; build it as a clipped body | `build123d 2.5` |

## S6: Method, reading a sliced file before it prints

| Point | Now in |
|---|---|
| A design is not finished when it is exported; the slicer decides | `gcode 1` |
| Summary first: layers and top height against the part, filament against the file's own statement | `gcode 3` |
| Where supports touch: contact bands, tested by height against the intended overhang | `gcode 5`, `gcode 5.1` |
| Settings against an intent table; no table, no verdict | `gcode 4`, `print-intent 2` |
| Look at the toolpath page in a browser | `gcode 6`, `viewer 2` |
| One job's observed numbers | not carried: part history |
| Bands are in the bed frame; naming the feature needs the placement | `gcode 5`, `gcode 9` |
| A clean check without an intent table is not a pass | `gcode 4` |
| One job note left unconfirmed | not carried: part history |
| Proposal: an intent table keyed by the slicer's own settings for every job | `print-intent 1`, `print-intent 2` |

## S7: Design critiques (index, recurring findings, four rounds)

| Point | Now in |
|---|---|
| Consult before submitting a design or repeating a construction | `design-review 1`, `build123d` |
| The rubric: function, constructive-technique choice, parametrization sanity, printability | `design-review 3` |
| A number written twice is a coupling nobody enforces | `design-practice 5`, `build123d 1` |
| A face with a job takes no second job silently | `design-practice 5` |
| Aggregate pins hide compensating errors | `design-practice 3` |
| The section and the probe are the evidence, not the render | `design-practice 4`, `design-review 2` |
| Read the spec against the build | `design-practice 2` |
| The direction of every mate comes before any dimension | `design-practice 2` |
| Derived values posing as parameters, and dead knobs | `build123d 1` |
| Cuts added outside a revolved profile swallow its narrowest feature | `build123d 2.2` |
| A connectivity patch needs its margin measured | `build123d 3` |
| A geometry operation in a bare except ships its failure | `build123d 2.1`, `build123d 3`, `probe-construction 4` |
| Freeze the target before the review | `design-review 1` |
| Re-run the author's own instrument against the author's claims | `design-review 2` |
| Round 1 (a flexure pawl): beams far thinner than the spec, which the build ignored | `design-practice 2`, `design-practice 3` |
| Round 1: the working direction of the part lost | `design-practice 2` |
| Round 1: a root patch with almost no margin | `build123d 3` |
| Round 1: wrong hub shape; volume passed on compensating errors | `design-practice 3` |
| Round 1: skins found by the short-edge census; polygonised arcs; beams below the process's bead | `session 2.1`, `reverse-engineering 4`, `design-practice 7` |
| Round 2 (a ball-socket guide): a feature's function read from shape vocabulary | `design-practice 2` |
| Round 2: a sphere added after a revolve erased a throat; its knobs went dead | `build123d 2.2`, `build123d 1` |
| Round 2: a cap thickness never computed, under the process minimum | `design-practice 2`, `qc 1` |
| Round 2: a circle where a tilted crossing makes an ellipse; a wedge that traps resin | `build123d 2.3`, `design-practice 7` |
| Round 2: knob count, couplings, absolute levels hiding thicknesses | `build123d 1` |
| Round 3 (a bearing bracket): derived values posing as parameters | `build123d 1` |
| Round 3: a magic intersect height that clips a feature | `build123d 1` |
| Round 3: a construction valid only in a parameter range | `build123d 1` (assert what must stay true) |
| Round 3: no validation, three solids reported valid | `build123d 1`, `build123d 3` |
| Round 3: coplanar cutters, a leftover identity, a plane normal dodged | `build123d 1`, `build123d 2.3` |
| Round 3: the reference solution was itself wrong twice | `design-review 4` (never copy the reference) |
| Round 4 (a camera housing): two silent-valid couplings, one leaving a blind pocket | `design-practice 5`, `build123d 1` |
| Round 4: one face given two jobs | `design-practice 5` |
| Round 4: print orientation asserted, not argued | `design-practice 7` |
| Round 4: sub-0.05 mm edges to re-check after changes | `session 2.1` |
| Round 4: the packet reused an earlier revision's overlays | `design-review 1` |
| Each round's applied revision and what its self-critique missed | not carried: part history (the general findings above are carried) |

## S8: Reviewer agent definition

| Point | Now in |
|---|---|
| A one-shot peer review: findings the author could not make | `design-review` purpose, `design-review 1` |
| Build and probe before reading the author; self-critique last | `design-review 2` |
| Probes: sections, rays, cavity scans, short-edge census, parameter perturbation | `design-review 2` |
| Required reading for the reviewer agent | not carried: agent runtime |
| Every finding cites a program line or a measured number | `design-review 3` |
| One revision, built before it is recommended | `design-review 4` |
| Three bins; never copy the reference | `design-review 4` |
| Silent-valid is the failure to hunt | `design-review 2` |
| The record: scores with evidence, one revision, up to five findings, what was missed | `design-review 4`, `design-review 5` |
| The reviewer's own reflection | not carried: agent runtime |
| The reviewer edits nothing | `design-review 5` |
