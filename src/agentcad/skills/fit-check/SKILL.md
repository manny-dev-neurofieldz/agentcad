---
name: fit-check
description: Use before printing a mating pair, after any change to a mate's parameters, and whenever a slot, key, bore or seat is sized to another part. Declares the mate from both parts' sources and measures it with both bodies posed, instead of trusting either part alone.
---

Test a mate with both parts present: declared from their sources, posed from their datums, measured where it matters.

## Policy Engagement Protocol

Run `agentcad policy navigate` for each policy below and read the sections whose questions match the step at hand:

1. `fit` - declaring mates, posing the pair, what fit measures, verdicts and records.
2. `design-practice` - stating a mate and choosing a clearance.
3. `render-export` - variant plates for a clearance the material decides.

## Questions to Extract from Policy Reading

1. **Declaring** - Where is a mate declared, and from whose source does each relation come?
2. **Posing** - How are the two parts posed, and what does the pose leave undetermined?
3. **Measuring** - What does fit measure, and what does each number say and not say?
4. **Windows** - How is a window placed so it speaks for one mate?
5. **Verdicts** - When does a fit pass or fail?
6. **Records** - Where is a fit recorded, and when does finalize run one?
7. **Material** - How is a clearance found when the process takes its own share?

## Workflow

1. Read the mating feature's relation in the other part's source and declare the mate in both parts.
2. `agentcad fit A B --mate NAME -o DIR`, with an insertion sweep for anything that slides in.
3. Read the windows, the contacts and the sweep, then look at the views (the render-gate skill).
4. Fix the relation, not the number; fit again.
5. Record it: `agentcad fit A B --mate NAME --record`, or let finalize fit every declared mate.
6. Where the material decides the clearance, export a variant plate and print it.

## Critical Meta-Pattern

Policy as API: what fit measures and how to read it lives in the installed policies; this skill holds the order of the check.
