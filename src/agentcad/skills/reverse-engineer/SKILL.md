---
name: reverse-engineer
description: Use when replicating an existing part from its STEP, mesh or design record, or revising a part whose source is lost. Recovers the part's intent with agentcad's probes, builds it forward in a session and judges it feature by feature against the original.
---

Recover what an existing part's designer decided, build from those decisions, and prove the rebuild against the original.

## Policy Engagement Protocol

Run `agentcad policy navigate` for each policy below and read the sections whose questions match the step at hand:

1. `reverse-engineering` - the order of work and how each kind of evidence is read.
2. `probe-recover` - section loops, arcs, chains and design dumps.
3. `probe-inspect` - the inventory, rays and knobs.
4. `compare` - the gate, the windows and the deviation.
5. `design-practice` - what the replication is faithful to.

## Questions to Extract from Policy Reading

1. **Before starting** - What must be decided before the original is read?
2. **Records** - Where does a design's own record survive, and what does each kind keep?
3. **Census** - What does a face census say about how the part was made?
4. **Curves** - How are section loops read for parameters, and which fits lie?
5. **Building** - How do hypotheses and recovered curves become a program?
6. **Judging** - How is a rebuild judged, and against which numbers?
7. **Editing** - How is a solid with no source edited safely?

## Workflow

1. Decide whether the original's source may be read and what the rebuild is faithful to.
2. Inventory: `agentcad probe inventory ORIGINAL`.
3. Archaeology, when a design record exists: `agentcad probe sketches DUMP --against ORIGINAL`.
4. Sections: `agentcad probe section ORIGINAL --planes ...`, with `--arcs` for polylined loops and `--chain N` for a loop to build from.
5. Build forward in a session (the design-session skill), asserting the parameters the hypotheses predict.
6. Judge: `agentcad compare ORIGINAL CANDIDATE --planes ... --window NAME=... -o DIR`, gate first, then the windows, then the deviation.

## Critical Meta-Pattern

Policy as API: the methods live in the installed policies; this skill holds their order and the questions that find them.
