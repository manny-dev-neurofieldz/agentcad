---
name: reverse-engineer
description: Use when replicating an existing part from its STEP, mesh or design record, or revising a part whose source is lost. Recovers the part's intent with agentcad's probes, builds it forward in a session and judges it feature by feature against the original.
---

Recover an existing part's intent and build it forward, judged feature by feature against the original.

## Policy Engagement Protocol

Run `agentcad policy navigate NAME` for each policy below. Read its Reaching for It first, then the sections whose questions match the step at hand, and run the recipe closest to the task before your own commands:

1. `reverse-engineering` - the order of work and how each kind of evidence is read.
2. `probe-recover` - section loops, arcs, chains and design dumps.
3. `probe-inspect` - the inventory, rays and knobs.
4. `compare` - judging the rebuild against the original.
5. `design-practice` - what a replication is faithful to.

## Questions to Extract from Policy Reading

1. **Before starting** - What must be decided before the original is read?
2. **Records** - Where does a design's own record survive, and what does each kind keep?
3. **Census** - What does a face census say about how the part was made?
4. **Curves** - How are section loops read for parameters, and which fits lie?
5. **Building** - How do hypotheses and recovered curves become a program?
6. **Judging** - How is a rebuild judged, and against which numbers?
7. **Editing** - How is a solid with no source edited safely?
8. **Reaching** - When does each policy say to reach for its commands, and when for another?
9. **Recipes** - Which of its recipes is closest to this task, and what did its output show when run?
10. **Constraints** - Which constraints does it say to probe for this task, and with which command?

## Workflow

1. May the original's source be read for this work, and is the rebuild faithful to the outline or to the intent?
2. `agentcad probe inventory ORIGINAL`: what does the census say about how the part was made?
3. `agentcad probe sketches DUMP --against ORIGINAL`, when a design record exists: which drawn numbers does the part still carry?
4. `agentcad probe section ORIGINAL --planes ... --arcs`, and `--chain N` for a loop to build from: which fits are good, and which loops hold two features?
5. Which parameters do the hypotheses predict? Build them forward in a session (the design-session skill) and assert them.
6. `agentcad compare ORIGINAL CANDIDATE --planes ... --window NAME=... -o DIR`: the gate first, then the windows, then the deviation.

## Critical Meta-Pattern

Policy as API: the method and the readings live in the installed policies; this skill holds the order of a replication.
