# Print Intent: Stating a Print Once, Staging It Anywhere

**Type**: Capability Policy (print readiness)
**Scope**: Any agent or person stating how a part should print, or staging it for an output target
**Status**: ACTIVE
**Commands**: agentcad stage

## Purpose

How a part should print is decided once, by the designer, and should not be rewritten for every slicer. agentcad keeps the intent in neutral terms in the project, carries it into the print manifest, and lets each output target turn it into its own settings, with the target's native overrides beside it and every disagreement between the two reported. This policy says where intent is written, how native settings layer over it, and what `agentcad stage` does with both.

## CEP Navigation Guide

**1 Neutral Intent**
- Where is print intent written, and which keys does it hold?
- Where does it go when a session is finalized?

**2 Native Settings**
- Where are a target's own settings written?
- Which settings does a bare slice table belong to?
- What happens when a native setting disagrees with the intent?

**3 Staging**
- What does stage write, and from what?
- How is a part posed and placed on the bed?

**4 Integration with Other Policies**
- Which policies govern the targets and the checks around staging?

**5 Anti-Patterns**
- Which ways of stating intent defeat it?

**6 Evolution and Feedback**
- How does this policy change?

=== CEP_NAV_BOUNDARY ===

## 1 Neutral Intent

The project's `[print]` table states the intent in neutral terms: `material`, `layer_height`, `walls`, `infill_percent`, `supports`, `print_orientation`, `printer_profile`, `filament_profile`, and `target` (the output target the project is staged for). At `agentcad session finalize` the table goes into the print manifest verbatim as `print_intent`, and the keys it states also fill the manifest's own fields of the same names; a field it does not state keeps its default, which is never read as intent.

## 2 Native Settings

A target's own settings are written in `[slice.<target>]`, keyed by that tool's own names. A bare `[slice]` table holds the settings of the project's default target: the `[print] target`, else `prusaslicer`; `agentcad gcode check` reads it as before. A table under `[slice]` is a target's only when its keys are not a setting's own (`value`, `min`, `max`, `why`), so `temperature = { min = 270, max = 285 }` stays a setting.

A target's settings are the intent as the target maps it, then its native tables. Where a native value differs from the mapped one, the native value wins, and the disagreement is reported naming the key and both values: two statements of one setting are a coupling nobody enforces, and the report is where it shows.

## 3 Staging

`agentcad stage PROJECT --target NAME` writes a finalized project's parts for one output target (`agentcad-targets`): each part's export of its latest iteration (a project with part subprojects stages every part), posed by its `[qc] pose` (else the project's), placed with its lowest point on the bed and centred on the bed of the project's QC printer, parts of an assembly in a row along y with a 10 mm gap. `--copies N` sets the copies of each part (default: each part's `[project] quantity`); `-o` the folder (default: `exports/stage_<target>`). It prints the files written and every conflict between intent and native settings. A target that does not write jobs is refused with its capabilities, and a part without an export of its latest iteration is refused with "finalize it first".

## 4 Integration with Other Policies

- `agentcad-targets`: the targets, their capabilities and the placement sidecar.
- `agentcad-qc`: the printer, the pose and the checks to run before staging.
- `agentcad-gcode`: checking a sliced file against the native settings.
- `agentcad-policies`: how this policy is found and read.

## 5 Anti-Patterns

- **Intent in prose**: a print plan in notes cannot be checked or staged; state it in `[print]`.
- **The same setting in both tables without meaning it**: a native value that silently overrides the intent is a setting written twice; the conflict report exists to show it.
- **Staging an unfinalized part**: the export of the latest iteration is what is staged; finalize first.

## 6 Evolution and Feedback

This policy ships with agentcad and changes with the intent tables and the stage command; a change to either updates this policy in the same pull request.
