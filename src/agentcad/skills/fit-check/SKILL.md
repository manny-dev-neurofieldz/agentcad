---
name: fit-check
description: Use before printing a mating pair, after any change to a mate's parameters, and whenever a slot, key, bore or seat is sized to another part. Declares the mate from both parts' sources and measures it with both bodies posed, instead of trusting either part alone.
---

Test a mate with both parts present: declared from their sources, posed from their datums, measured where it matters.

## Policy Engagement Protocol

Run `agentcad policy navigate NAME` for each policy below. Read its Reaching for It first, then the sections whose questions match the step at hand, and run the recipe closest to the task before your own commands:

1. `fit` - declaring mates, posing the pair, what fit measures, verdicts and records.
2. `design-practice` - stating a mate and choosing a clearance.
3. `render-export` - variant plates for a clearance the material decides.
4. `records` - what a fit record must hold so a later change shows it is owed again.

## Questions to Extract from Policy Reading

1. **Declaring** - Where is a mate declared, and from whose source does each relation come?
2. **Posing** - How are the two parts posed, and what does the pose leave undetermined?
3. **Measuring** - What does fit measure, and what does each number say and not say?
4. **Windows** - How is a window placed so it speaks for one mate?
5. **Verdicts** - When does a fit pass or fail, and what does a window's pass not guard against?
6. **Material** - How is a clearance found when the process takes its own share?
7. **Reaching** - When does each policy say to reach for its commands, and when for another?
8. **Recipes** - Which of its recipes is closest to this task, and what did its output show when run?
9. **Constraints** - Which constraints does it say to probe for this task, and with which command?

## Workflow

1. Where does the other part's source state the relation this mate depends on, and is the mate declared in both parts?
2. `agentcad fit A B --mate NAME -o DIR`. Does the mate slide in, and if it does, along which axis does fit say to sweep (`--sweep AXIS`)?
3. What do the interference, the windows, the contacts, the sweep and the pose notes say, and what do the views show (the render-gate skill)?
4. Which part's relation is wrong? Change that, not the number, and run `agentcad fit` again.
5. `agentcad fit A B --mate NAME --record`, or `agentcad session finalize PROJECT` for a project that declares the mate; in a library, `agentcad records check LIBRARY`.
6. Does the material decide the clearance? `agentcad export SOURCE --variants KNOB=v1,v2,...`; what does render-export say to print and compare?

## Critical Meta-Pattern

Policy as API: what fit measures and how to read it lives in the installed policies; this skill holds the order of the check.
