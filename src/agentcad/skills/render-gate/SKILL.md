---
name: render-gate
description: Use whenever agentcad has produced an image or a page (an iteration's renders, agentcad render, fit and compare views, a toolpath page, a viewer) and before acting on it or sending it to anyone. Looks first, then measures what looking cannot settle.
---

Look at what agentcad drew before acting on it, and measure what a picture cannot show.

## Policy Engagement Protocol

Run `agentcad policy navigate` for each policy below and read the sections whose questions are about renders, pages and evidence:

1. `session` - the render gate and the tray.
2. `design-practice` - what counts as evidence.
3. `viewer` - what a page check sees and what it misses.

## Questions to Extract from Policy Reading

1. **The gate** - What must be done with an image before it is reported or acted on?
2. **Limits** - What can a render show, and what can it not?
3. **Instruments** - Which measurement answers each question a render cannot?
4. **Pages** - What does the page check catch, and what still needs a look?

## Workflow

1. Open each image. Say in words what it shows, and compare that with what was intended.
2. Name what the image cannot show for this part (connectivity, a wall's thickness, a size), and read the measurement that can: the tray's solid count and numbers, or the probe the inspection policies name.
3. For a page, run `agentcad check` on it, then open it and look; a clean check is not a look.
4. Only then act on the result or send it on, saying what was looked at and what was measured.

## Critical Meta-Pattern

Policy as API: the gate's rules live in the installed policies; this skill only makes sure they are read at the moment an image appears.
