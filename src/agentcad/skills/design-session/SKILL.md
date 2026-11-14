---
name: design-session
description: Use when designing, revising or replicating a part with agentcad, from before the first line of source to the finalize. Walks the session loop and reads the rules for each step from the installed agentcad policies.
---

Design a part through an agentcad session, taking the rules for each step from the installed policies rather than from memory.

## Policy Engagement Protocol

Run `agentcad policy navigate NAME` for each policy below. Read its Reaching for It first, then the sections whose questions match the step at hand, and run the recipe closest to the task before your own commands:

1. `start` - where this goal sits, and the engine choice it points to.
2. `design-practice` - the posture, the spec, the predictions and the evidence.
3. `session` - the loop, the tray and the render gate.
4. `engines` - which engine the part needs, the program contract and the settings.
5. `build123d` - construction practice, when the engine is build123d.
6. `projects` - where the project lives and what its file states.

## Questions to Extract from Policy Reading

1. **Engine** - Which engine does this part need, and what can that engine not do?
2. **Spec** - What must the spec reconcile, and what is decided before any dimension?
3. **Predictions** - What is written down before the first build, and which prediction catches what the aggregate numbers miss?
4. **Program** - What must a source define, and which of its values are knobs?
5. **Each iteration** - What is read after every iterate, and what counts as evidence?
6. **Warnings** - What does each tray warning mean, and what does it ask for?
7. **Finishing** - What does finalize write, and what is checked before calling the part done?
8. **Reaching** - When does each policy say to reach for its commands, and when for another?
9. **Recipes** - Which of its recipes is closest to this task, and what did its output show when run?
10. **Constraints** - Which constraints does it say to probe for this task, and with which command?

## Workflow

1. `agentcad info` and `agentcad policy navigate engines`: which engine does the part need, and is it installed here?
2. `agentcad new-project NAME -e ENGINE`, or `agentcad status PROJECT` for one that exists.
3. Which spec numbers and predictions does design-practice say to write down before the first build?
4. `agentcad session start PROJECT`.
5. `agentcad session iterate PROJECT SOURCE` for each attempt; what do the render gate and the tray say about it (the render-gate skill)?
6. Which probe does design-practice name for what the renders and the tray cannot settle? Run it: `agentcad probe rays`, `agentcad probe knobs` or `agentcad probe section`.
7. `agentcad session note PROJECT TEXT`: what was learned, and what changes next?
8. `agentcad session tag PROJECT NAME` before a review.
9. `agentcad session finalize PROJECT`, then `agentcad qc PROJECT` for a part that will be printed.

## Critical Meta-Pattern

Policy as API: this skill holds the order of the work and the questions to ask; the answers live in the policies of the installed agentcad and change with the tool.
