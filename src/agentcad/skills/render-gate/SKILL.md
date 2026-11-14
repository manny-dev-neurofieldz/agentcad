---
name: render-gate
description: Use whenever agentcad has produced an image or a page (an iteration's renders, agentcad render, fit and compare views, a toolpath page, a viewer) and before acting on it or sending it to anyone. Looks first, then measures what looking cannot settle.
---

Look at what agentcad produced before acting on it, then measure what looking cannot settle.

## Policy Engagement Protocol

Run `agentcad policy navigate NAME` for each policy below. Read its Reaching for It first, then the sections whose questions match the step at hand, and run the recipe closest to the task before your own commands:

1. `session` - the render gate and the tray.
2. `design-practice` - what a render is evidence of, and which instruments count for the rest.
3. `viewer` - what the page check sees and does not see.
4. `probe-inspect` - the probes for what an image cannot show.

## Questions to Extract from Policy Reading

1. **Looking** - What must be done with an image before anyone acts on it?
2. **Limits** - What can a render not show, and which measurement shows it instead?
3. **Pages** - What does the page check catch, and what does it miss?
4. **Reaching** - When does each policy say to reach for its commands, and when for another?
5. **Recipes** - Which of its recipes is closest to this task, and what did its output show when run?
6. **Constraints** - Which constraints does it say to probe for this task, and with which command?

## Workflow

1. Open each image: what does it show, in words, and does that match what was intended?
2. What can this image not show for this part, by the session policy's list? Read that from the tray, or run the probe: `agentcad probe rays SOURCE --line ...` for a width, `agentcad render SOURCE --report` for the solid count.
3. For a page: `agentcad check PAGE`, then open it and look; what does it show that the check could not?
4. What was looked at and what was measured? Say both before acting on the result or sending it on.

## Critical Meta-Pattern

Policy as API: the gate's rules live in the installed policies; this skill only makes sure they are read at the moment an image appears.
