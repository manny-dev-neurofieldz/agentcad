# QC: Design Rules Judged Before a Print

**Type**: Capability Policy (print readiness)
**Scope**: Any agent or person checking that a part can be printed before it is staged
**Status**: ACTIVE
**Commands**: agentcad qc

## Purpose

Every print problem found after a print was a number that could have been read before it: a wall thinner than the nozzle can lay, a part taller than the printer. QC judges a part against the design rules of the printer it is meant for, before staging, and says in each finding what was measured, the limit, who set the limit, and the usual fix. This policy says how QC is configured, what it measures today, how its findings are read, and what its gate does at finalize.

## CEP Navigation Guide

**1 What QC Judges**
- Which rules does QC measure today, and which only list a limit?
- Against which printer is a part judged?

**2 Limits and Their Layers**
- Where does each limit come from, and in what order do the sources apply?
- How is a rule's severity changed or a rule turned off?

**3 The Print Pose**
- How is the pose a part prints in declared?
- How does the build-volume rule use the pose and the bed?

**4 Reading a Report**
- What does a finding carry?
- What does a rule that is not measured mean?
- When does the command exit non-zero?

**5 The Gate at Finalize**
- When does QC run at finalize, and when does it hold a part back?
- What does a held part look like, and how does it continue?

**6 Integration with Other Policies**
- Which policies govern the printers and the session around QC?

**7 Anti-Patterns**
- Which readings of a QC report are wrong?

**8 Evolution and Feedback**
- How does this policy change?

=== CEP_NAV_BOUNDARY ===

## 1 What QC Judges

`agentcad qc PROJECT` judges the project's latest iteration. It measures the mesh of that iteration: the export finalize wrote, or, before a finalize, one exported for QC alone.

Measured today: `build_volume`, the part's extent in its print pose against the printer's build volume. The process rules of the printer (minimum wall and feature, maximum overhang and bridge) have limits, and the report lists them with their layers, but they are not measured yet: wall, overhang and bridge measurement comes with feature annotations in a later capability.

A part is judged against `--printer NAME` when given, else the project's `[qc] printer`, else the printer whose label equals the project's `[print] printer_profile`, else the Original Prusa MK4. `agentcad printers` lists the printers known (`agentcad-printers`).

## 2 Limits and Their Layers

A limit comes from the first of these that sets it, from the most specific:

1. a feature's annotation in the design source (not yet available);
2. the project's `[qc] limits` table, e.g. `limits = { min_wall_mm = 1.6 }`;
3. the printer's process defaults (`agentcad-printers`, section 2).

Every finding names the layer that set its limit (`project [qc]`, `process default (fdm, 0.4 mm nozzle)`, or, for the build volume, the printer and where it was defined), so a reader knows which number to argue with.

`[qc] severity` sets a rule's severity: `error`, `warning` or `off`, e.g. `severity = { build_volume = "warning" }`. A rule turned off is listed as not measured, with that reason.

## 3 The Print Pose

`[qc] pose` declares how the part sits on the bed: `up` is the part's direction that points up (default `[0, 0, 1]`, the part as modelled), and `spin_deg` turns it about the vertical after that. For example `pose = { up = [1, 0, 0] }` lays a part on its side, its x axis up.

The build-volume rule takes the part's extent in that pose. A part taller than the build height is an error, since no turn on the bed helps. A footprint that fits the bed as posed passes. A footprint that fits only when turned about the vertical is a warning that names the turn, trying a quarter turn first and then the smallest turn that fits. A footprint that fits at no turn is an error.

## 4 Reading a Report

A finding carries the rule, the severity (`error`, `warning` or `ok`), what was measured and what was intended, why the rule matters, the layer that set the limit, and the usual fix; its sentence says all of it. `--json` prints the printer, the pose, every limit with its layer, the findings, and the rules not measured with the reason for each.

A rule that is not measured has no finding: QC never fails a part on a number it did not take, and a part with no mesh to read is reported as not measured, not as passing.

The command exits 1 when a finding is an error or the project is not found, and 2 when its session, its pose or its printer cannot be read.

## 5 The Gate at Finalize

QC runs at `agentcad session finalize` only in a project that declares a `[qc]` table; a project without one finalizes as before. Its findings are shown on the newest variant of the viewer and printed.

With `[qc] gate = true`, an error holds the part back: finalize still writes the viewer, with a banner at the top saying why, but writes no print manifest, does not mark the session finalized, and exits 1. Fix the part and iterate again; no reopen is needed. A warning never holds a part back. `finalize --all` finalizes every part it can and exits 1 when any part was held back or could not be finalized, naming them.

## 6 Integration with Other Policies

- `agentcad-printers`: the printers, their build volumes and process defaults.
- `agentcad-session`: finalize, the viewer, and the tray's own findings.
- `agentcad-policies`: how this policy is found and read.

## 7 Anti-Patterns

- **A clean report read as a printable part**: rules that are not measured are listed for a reason; a part QC passed can still have a wall too thin to print.
- **Arguing with the wrong limit**: the finding names the layer that set it; change that layer, not a different one.
- **Turning a rule off to pass a gate**: `off` is listed in every report; fix the part, or set the limit in `[qc] limits` with the reason in a comment.
- **A pose in prose**: a pose written in notes is not the pose QC judged; declare it in `[qc] pose`.

## 8 Evolution and Feedback

This policy ships with agentcad and changes with the command it governs; a change to QC's rules, limits, pose or gate updates this policy in the same pull request.
