---
name: start
description: Use when arriving at agentcad with a goal and no map of its commands, or when a task changes kind (from designing to fitting, from a finished part to a printer). Routes the goal to the skill and the policies that serve it.
---

Find the route for a goal before running any command: the skill that walks it, the policies behind it, the first command.

## Policy Engagement Protocol

Run `agentcad policy navigate NAME` for each policy below. Read its Reaching for It first, then the sections whose questions match the step at hand, and run the recipe closest to the task before your own commands:

1. `start` - agentcad by goal: each goal's skill, policies, first command and route.
2. `engines` - which engine a new part needs.
3. `policies` - how every policy is found and read.

## Questions to Extract from Policy Reading

1. **Goal** - Which of the goals the map lists is this task, and which skill walks it?
2. **First command** - What is the first command for that goal, and what does its route look like?
3. **Engine** - For a new part, which engine does the part need?
4. **Reaching** - When does each policy say to reach for its commands, and when for another?
5. **Recipes** - Which of its recipes is closest to this task, and what did its output show when run?
6. **Constraints** - Which constraints does it say to probe for this task, and with which command?

## Workflow

1. `agentcad policy navigate start`: which goal is this task?
2. `agentcad policy read start --section N`, N the section whose question names the goal: which skill, policies and first command does it name?
3. Use that skill: design-session (then render-gate), reverse-engineer, fit-check, review or print-prep. For making the know-how available in a harness: `agentcad plugin export --target T -o DIR`.
4. When the task changes kind, which goal is it now? Come back here.

## Critical Meta-Pattern

Policy as API: the map lives in the start policy of the installed agentcad; this skill only asks for it at the moment a goal arrives.
