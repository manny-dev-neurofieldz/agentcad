---
name: print-prep
description: Use when a finished part is headed for a printer: checking it against the printer's rules, stating how it should print, staging it for an output target, reading the sliced file before it prints, and fetching files or status from a printer host.
---

Take a finished part to the plate: checked against its process, its print intent stated once, staged for a target, and the sliced file read before anything prints.

## Policy Engagement Protocol

Run `agentcad policy navigate` for each policy below and read the sections whose questions match the step at hand:

1. `qc` and `printers` - the design rules and the printer they judge against.
2. `print-intent` - where intent is written, how native settings layer over it, what staging writes.
3. `targets` - the output targets and what each can do.
4. `gcode` - reading, checking and comparing a sliced file.
5. `printer-hosts` - reading files and status from a printer, read-only.
6. `design-practice` - arguing the print orientation.

## Questions to Extract from Policy Reading

1. **Rules** - What is checked before staging, against which printer and pose?
2. **Intent** - Where is the print intent stated, and what reaches the manifest?
3. **Native settings** - How do a target's own settings combine with the intent, and how is a disagreement shown?
4. **Staging** - What does staging write, and for which targets?
5. **Reading** - What is read in a sliced file before it prints, and what proves each reading?
6. **Hosts** - What may be read from a printer, and what is never done to one?

## Workflow

1. `agentcad printers`, then `agentcad qc PROJECT` in the print pose; settle every error before staging.
2. State the intent in the project's `[print]` table, with a target's native settings under `[slice.TARGET]`, and argue the orientation in writing.
3. `agentcad session finalize PROJECT`, then `agentcad targets` and `agentcad stage PROJECT --target NAME`.
4. Once sliced: `agentcad gcode summary FILE`, `agentcad gcode supports FILE`, `agentcad gcode check FILE --project PROJECT`, and `agentcad gcode view FILE` to look; `agentcad gcode compare A B` against an earlier slice.
5. At the printer: `agentcad printer status` and `agentcad printer files`; `agentcad printer get NAME` to read back what it holds. Starting, stopping, uploading and deleting are never done from here.

## Critical Meta-Pattern

Policy as API: the rules, the targets and the hosts live in the installed policies and grow as targets and hosts are added; this skill holds the order and the questions.
