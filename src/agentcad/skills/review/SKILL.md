---
name: review
description: Use before calling a design done, and whenever asked to review someone else's design. Prepares a frozen review packet as the author, or works through a review as the reviewer: build and probe first, the author's conclusions last, a rubric scored with evidence, one revision.
---

Review a design so the author learns what they could not see: as the author, a frozen packet; as the reviewer, numbers first and the author's conclusions last.

## Policy Engagement Protocol

Run `agentcad policy navigate NAME` for each policy below. Read its Reaching for It first, then the sections whose questions match the step at hand, and run the recipe closest to the task before your own commands:

1. `design-review` - the packet, the order of work, the rubric and the one revision.
2. `design-practice` - the practices the rubric scores against.
3. `build123d` - the construction the rubric's technique and parametrization scores look at.
4. `compare` - judging a replication.
5. `probe-inspect` - rays and knobs.
6. `probe-construction` - fillets and draft.

## Questions to Extract from Policy Reading

1. **Packet** - What does an author hand over, and how is it frozen?
2. **Order** - What does a reviewer do before reading the author's conclusions?
3. **Rubric** - On what is a design scored, and what counts as evidence?
4. **Findings** - How are findings ranked and grouped?
5. **Revision** - How is the one revision chosen, and what must it carry?
6. **Record** - What does a review produce, and what does a reviewer not touch?
7. **Reaching** - When does each policy say to reach for its commands, and when for another?
8. **Recipes** - Which of its recipes is closest to this task, and what did its output show when run?
9. **Constraints** - Which constraints does it say to probe for this task, and with which command?

## Workflow

As the author:

1. `agentcad session tag PROJECT NAME`.
2. Which items does the review policy list for the packet, and are they all in the tag?

As the reviewer:

1. `agentcad render TAG_SOURCE --report`, then `agentcad probe knobs TAG_SOURCE --knob NAME=DELTA`, `agentcad probe rays TAG_SOURCE --line ...` and, against an original, `agentcad compare`: what do the numbers say before any claim is read?
2. What does the author's spec claim, and do the author's own instruments, run again, agree?
3. How does each rubric line score, with which number, and which single revision retires the most findings? Build it and measure it.

The `design-reviewer` agent shipped with agentcad runs the reviewer's side.

## Critical Meta-Pattern

Policy as API: the packet, the order and the rubric live in the installed policies; this skill holds whose turn it is.
