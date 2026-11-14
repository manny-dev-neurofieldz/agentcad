---
name: print-prep
description: Use when a finished part is headed for a printer: checking it against the printer's rules, stating how it should print, staging it for an output target, reading the sliced file before it prints, and fetching files or status from a printer host.
---

Take a finished part to a printer: judged, stated, staged, read back.

## Policy Engagement Protocol

Run `agentcad policy navigate NAME` for each policy below. Read its Reaching for It first, then the sections whose questions match the step at hand, and run the recipe closest to the task before your own commands:

1. `qc` - the design rules and how a verdict is read.
2. `printers` - the printers those rules come from.
3. `print-intent` - where intent is written and what staging writes.
4. `targets` - the output targets and what each can do.
5. `prusaslicer` - staging and slicing for PrusaSlicer.
6. `gcode` - reading, checking and comparing a sliced file.
7. `printer-hosts` - reading files and status from a printer, read-only.
8. `design-practice` - arguing the print orientation.

## Questions to Extract from Policy Reading

1. **Rules** - What is checked before staging, against which printer and pose?
2. **Intent** - Where is the print intent stated, and what reaches the manifest?
3. **Native settings** - How do a target's own settings combine with the intent, and how is a disagreement shown?
4. **Staging** - What does staging write, and what is refused before it writes?
5. **Reading** - What is read in a sliced file before it prints, and what proves each reading?
6. **Hosts** - What may be read from a printer, and what is never done to one?
7. **Reaching** - When does each policy say to reach for its commands, and when for another?
8. **Recipes** - Which of its recipes is closest to this task, and what did its output show when run?
9. **Constraints** - Which constraints does it say to probe for this task, and with which command?

## Workflow

1. `agentcad printers`, then `agentcad qc PROJECT`: which warnings and errors stand, and which does the part need settled?
2. What does the part's `[print]` table state, and is the orientation argued in writing as design-practice asks?
3. `agentcad session finalize PROJECT`, `agentcad targets`, then `agentcad stage PROJECT --target NAME`.
4. Once sliced: `agentcad gcode summary FILE`, `agentcad gcode supports FILE` and `agentcad gcode check FILE --project PROJECT`; does the file say what the intent asked?
5. `agentcad gcode view FILE`: what do the toolpaths show (the render-gate skill)?
6. At the printer, read only: `agentcad printer status`, `agentcad printer files`, `agentcad printer get NAME`.

## Critical Meta-Pattern

Policy as API: the rules, the intent and the readings live in the installed policies; this skill holds the order from a finished part to a print.
