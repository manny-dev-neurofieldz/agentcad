# Design Practice: Posture, Pins and Evidence

**Type**: Practice Policy (design)
**Scope**: Any agent or person designing a part with agentcad, from first sketch to a part ready to print
**Status**: ACTIVE
**Commands**: none

## Purpose

agentcad measures everything an iteration produces, but the measurements answer only the questions asked of them. A design goes wrong in the questions: a function stated in the wrong words, a prediction never written down, a number trusted because it passed, a mate assumed instead of tested. This policy states the posture a design is approached with, the order of work that makes each iteration evidence, and the habits that keep a part's numbers true statements about it.

## Reaching for It

- Before the first line of a new part: sections 1 to 3 (what the part is faithful to, the spec reconciled, the pins written down).
- After every iteration, before the next edit: section 4, and the probe each practice names in section 9.
- A number that two features share, a face that may already have a job, a feature that may not have built: section 5.
- A part that mates with another, or a fit that depends on the material: section 6, then `agentcad fit` (`agentcad-fit`).
- How the commands themselves run: the command policies (`agentcad policy list`); this policy says what to ask of them.

## CEP Navigation Guide

**1 Posture**
- When is a design estimated, and when is it engineered?
- What is a design faithful to?

**2 The Spec by Reconciliation**
- How is a spec written so its numbers agree with each other?
- What is decided before any dimension?

**3 Pins Before Contact**
- What is predicted before the first build, and why written down?
- Which pin catches what the aggregate pins miss?

**4 Every Iteration**
- What is read after every iteration, and which instruments count as evidence?

**5 Couplings, Faces and Deltas**
- How is a number kept from drifting between two features?
- What is checked before a feature is added to a face?
- How is a feature known to have done what was asked?

**6 Mates and Clearances**
- How is a mate stated and tested?
- How is a clearance chosen for a real material?

**7 Orientation and Process**
- How is a print orientation decided?

**8 Recipes**
- How is a feature's delta asserted, and a load-bearing dimension pinned, as commands?

**9 Constraints to Probe**
- Which command answers each practice, so that it is checked instead of trusted?

**10 Integration with Other Policies**
- Which policies carry out each step?

**11 Anti-Patterns**
- Which habits let a design pass while being wrong?

**12 Evolution and Feedback**
- How does this policy change?

=== CEP_NAV_BOUNDARY ===

## 1 Posture

In the conceptual stage, be a designer: estimate, parameterize, render, iterate, and let the form settle before chasing tenths of a millimetre. Measured tolerances and calipers come once the big picture holds; engineering a shape that will change is wasted precision.

Derive, do not copy. A feature's dimensions follow from the part's own dimensions and from the parts it meets, as relations in the program; a curve or a number lifted from a file carries that file's mistakes. Before matching anything, say what the design is faithful to: a file's outline, or the intent the outline approximates. Matching a hand-edited original to a fraction of a percent reproduces its defects; re-deriving it as relations shows them. Improve on a source where it is wrong instead of copying a defect because the file has it.

## 2 The Spec by Reconciliation

Write the spec's numbers from the drawing, the probe of the object or the stated intent, then reconcile them before building: the volume from its components, the counts from the topology, the envelope from the extremes. When two readings disagree, resolve it before the first build; a probe reading explained away is still a reading.

State the direction of every mate before any dimension: which way the stem, the shaft, the wire or the key goes, and what moves against what. A function written in the vocabulary of shapes ("a slot", "a boss") names shapes, not a joint. Then read the spec against the build, every revision: a build can contradict numbers its own spec already records.

## 3 Pins Before Contact

Before the first build, write down the predictions: the volume as a band, the envelope, the solid count (one, unless the part is an assembly), the iterations it should take, and the load-bearing dimension (the beam width, the wall, the cap thickness). Pins are not moved after the fact; a correction is a new, dated entry, so the record shows what was predicted and what was learned.

Pair every aggregate pin (volume, envelope, solid count) with a pin on the load-bearing dimension. Aggregates pass on compensating errors: a hub a quarter too full and beams nearly half too thin can sum to the right volume, and a volume pin within a few percent passes a part that will break.

## 4 Every Iteration

Read every iteration before editing again: the renders (open each and say what it shows), the tray's numbers and warnings, and the solid count (`agentcad-session`, section 2). A render is evidence of silhouette, orientation and gross error; it cannot show connectivity, a wall's thickness or whether a feature is the requested size.

The evidence for those is the section and the probe: section overlays against the original at mid-thickness, rays for widths, scans along a cavity's axis for throats and seats, the census of short edges for skins and slivers (`agentcad-compare`, `agentcad-probe-inspect`). A tight overall deviation is not evidence of function. A number no instrument measured is an estimate, and is labelled as one wherever it is reported.

## 5 Couplings, Faces and Deltas

A number written twice is a coupling nobody enforces. When two features must agree (a hole and the edge that wraps it, a vent and the wall it must cross), define the quantity once, derive the other, and assert the derived value; then perturb the first and watch the second keep doing its job.

A face with a job takes no second job silently. Before adding a feature, read what every face it touches already does: a tab fused onto the face that was the cable exit has taken that face's job without anyone deciding so.

A feature is a delta; assert the delta. After each feature, check that the volume, the face census, the solid count and the extent changed as the feature should change them. A feature that did not build leaves a valid part; only the delta shows it is missing.

## 6 Mates and Clearances

A mate stated in one program is a hypothesis. Take the relation, and the datum it counts from, from the other part's source rather than from a description of it, then test the mate with both bodies posed from their datums (`agentcad-fit`): penetration both ways, the clearance in each mate's window, and an insertion sweep. Every single-part instrument passes a key slot whose reach was derived from the wrong radius; only the fit check sees it.

As-printed is not nominal: a material and a process take their own share of a clearance. Where a fit depends on it, print the mating feature at several clearances side by side (`agentcad-render-export`, section 2.1) and keep the one that fits.

## 7 Orientation and Process

Argue the print orientation in writing: what touches the bed, how large the first layer is, how the material warps, where supports land and what they will scar, which way the layers run through a part that bends. An orientation asserted ("plate down") is not one argued; a reviewer will ask for the argument, and the printer will test it. State it as intent (`agentcad-print-intent`) and check it against the process (`agentcad-qc`).

## 8 Recipes

A feature is a delta: lengthen the hook's peg by 4 mm and check that the part changed by exactly a cylinder of the peg's diameter, 4 mm long, and nothing else.

```console
# recipe: examples
$ agentcad session start examples/j_hook
Session started
$ agentcad session iterate examples/j_hook examples/j_hook/source/j_hook.py
Iteration v1 recorded
counts     solids 1, faces 10
$ agentcad session iterate examples/j_hook examples/j_hook/source/j_hook.py -D peg_len=10
Report v2 vs v1:
volume     1518 (+120.8, +8.64%)
bbox       [35.6, 6.2, 37.5] (+0, +0, +4)
counts     solids 1 (+0), faces 10 (+0)
```

The prediction, written before the iterate: pi x 3.1^2 x 4 = 120.8 mm^3, +4 mm in z, the same faces, one solid. The report says exactly that, so the peg grew and nothing else moved. A delta that differs from its prediction is the finding, even when the part is valid.

Pin the load-bearing dimension, not only the aggregates: the peg's diameter measured across the part, at its nominal and at a clearance variant.

```console
# recipe: examples
$ agentcad probe rays examples/j_hook/source/j_hook.py --line 0,-10,3:0,1,0 --length 20
material 6.2000 in 1 run(s)
$ agentcad probe rays examples/j_hook/source/j_hook.py --line 0,-10,3:0,1,0 --length 20 -D peg_d=6.4
material 6.4000 in 1 run(s)
```

The ray crosses the peg 3 mm above its base and finds one run of material exactly the diameter asked for. Next: the same probe on the mating hole, or the fit check with both bodies (`agentcad-fit`).

## 9 Constraints to Probe

Each practice of this policy, with the command that checks it:

- One solid for a single part (sections 3, 4): `agentcad session iterate` prints the solid count every iteration and warns when it is not the expected one.
- A feature did what was asked (section 5): `agentcad session iterate` prints the change since the last iteration in volume, box, faces and census; compare it with the prediction.
- A knob is live and not a derived value posing as one (section 5): `agentcad probe knobs SOURCE --knob NAME=DELTA` perturbs it both ways and says whether the part changes.
- A wall, a width or a seat is the size asked for (sections 3, 4): `agentcad probe rays SOURCE --line ...` measures the material along a line.
- A replica is faithful where it matters (section 1): `agentcad compare ORIGINAL CANDIDATE --planes ...`, with the loop counts as the gate.
- A mate is right with both bodies (section 6): `agentcad fit A B --mate NAME`.
- A clearance holds in the real material (section 6): `agentcad export SOURCE --variants KNOB=v1,v2,...` writes one file per value, to print side by side.
- An orientation survives the process (section 7): `agentcad qc PROJECT` judges the part posed as stated.

## 10 Integration with Other Policies

- `agentcad-start`: where this practice sits among the goals.
- `agentcad-session`: the loop every iteration runs in.
- `agentcad-build123d`: the construction practice for build123d programs.
- `agentcad-compare`, `agentcad-probe-inspect`, `agentcad-probe-recover`: the instruments that make an iteration evidence.
- `agentcad-fit`: testing a mate with both bodies.
- `agentcad-design-review`: a peer's look before a design is called done.
- `agentcad-print-intent` and `agentcad-qc`: stating and checking how the part prints.
- `agentcad-policies`: how this policy is found and read.

## 11 Anti-Patterns

- **Engineering too early**: tolerancing a form that will change.
- **Copying a defect for fidelity**: matching a file's mistakes because the file has them.
- **Aggregate pins alone**: a volume and an envelope that pass on compensating errors.
- **The render as the verdict**: connectivity, walls and sizes are measured, not seen.
- **A mate never tested with both bodies**: a relation derived from the wrong datum passes every single-part check.

## 12 Evolution and Feedback

This policy changes as designs and reviews teach; a practice is added here when it has held across more than one part.
