---
name: review
description: Use before calling a design done, and whenever asked to review someone else's design. Prepares a frozen review packet as the author, or works through a review as the reviewer: build and probe first, the author's conclusions last, a rubric scored with evidence, one revision.
---

Review a design for the findings its author could not make, or prepare one so a reviewer can.

## Policy Engagement Protocol

Run `agentcad policy navigate` for each policy below and read the sections whose questions match the role at hand:

1. `design-review` - the packet, the order of work, the rubric and the one revision.
2. `design-practice` - the practices the rubric scores against.
3. `build123d` - the construction the rubric's technique and parametrization scores look at.
4. `compare`, `probe-inspect` and `probe-construction` - the reviewer's instruments.

## Questions to Extract from Policy Reading

1. **Packet** - What does an author hand over, and how is it frozen?
2. **Order** - What does a reviewer do before reading the author's conclusions?
3. **Rubric** - On what is a design scored, and what counts as evidence?
4. **Findings** - How are findings ranked and grouped?
5. **Revision** - How is the one revision chosen, and what must it carry?
6. **Record** - What does a review produce, and what does a reviewer not touch?

## Workflow

As the author:

1. Freeze the revision: `agentcad session tag PROJECT NAME`.
2. Assemble the packet the review policy names and hand over the tag, not the live project.

As the reviewer:

1. Build the program and probe it before reading anything the author concluded: `agentcad compare` against the original, `agentcad probe rays` for widths, `agentcad probe knobs` for dead or dangerous parameters, `agentcad probe fillet` for an operation that fails.
2. Read the author's spec against the build, re-run the author's own instruments, and read the author's critique last.
3. Score the rubric with evidence, rank the findings, build and measure the one revision, and record what the critique missed.

The `design-reviewer` agent shipped with agentcad runs the reviewer's side.

## Critical Meta-Pattern

Policy as API: the rubric lives in the installed review policy; this skill holds who does what, in which order.
