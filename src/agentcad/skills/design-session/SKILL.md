---
name: design-session
description: Use when designing, revising or replicating a part with agentcad, from before the first line of source to the finalize. Walks the session loop and reads the rules for each step from the installed agentcad policies.
---

Design a part through an agentcad session, taking the rules for each step from the installed policies rather than from memory.

## Policy Engagement Protocol

Run `agentcad policy list`. For each policy below, run `agentcad policy navigate NAME` and read the sections whose questions match the step at hand with `agentcad policy read NAME --section N`:

1. `design-practice` - the posture, the spec, the predictions and the evidence.
2. `session` - the loop, the tray and the render gate.
3. `engines` - the program contract and the engine's settings.
4. `build123d` - construction practice, when the engine is build123d.
5. `projects` - where the project lives and what its file states.

## Questions to Extract from Policy Reading

1. **Spec** - What must the spec reconcile, and what is decided before any dimension?
2. **Predictions** - What is written down before the first build, and which prediction catches what the aggregate numbers miss?
3. **Program** - What must a source define, and which of its values are knobs?
4. **Each iteration** - What is read after every iterate, and what counts as evidence?
5. **Warnings** - What does each tray warning mean, and what does it ask for?
6. **Freezing** - When is a revision tagged, and why?
7. **Finishing** - What does finalize write and check?

## Workflow

1. Orient: `agentcad info` for the engines available here; `agentcad status PROJECT`, or `agentcad new-project NAME` for a new part.
2. Write the spec and the predictions before the first build.
3. `agentcad session start PROJECT`.
4. For each attempt: `agentcad session iterate PROJECT SOURCE`; open every render and say what it shows (the render-gate skill); read the tray; record what was learned with `agentcad session note PROJECT TEXT`.
5. Measure what the renders and the tray cannot settle, with the probe the inspection policies name for the question.
6. Before a review, freeze the revision: `agentcad session tag PROJECT NAME`.
7. `agentcad session finalize PROJECT`, then look at the viewer it wrote.

## Critical Meta-Pattern

Policy as API: this skill holds the order of the work and the questions to ask; the answers live in the policies of the installed agentcad and change with the tool.
