# Printers: What Each Machine Can Make

**Type**: Capability Policy (print readiness)
**Scope**: Any agent or person choosing the printer a part is judged against, or adding one
**Status**: ACTIVE
**Commands**: agentcad printers

## Purpose

A design rule means nothing without the machine it is for: a wall that prints on a resin printer fails on a 0.4 mm FDM nozzle, and a part that fits one bed overhangs another. agentcad keeps a registry of printers, each naming its process, its build volume and, for FDM, its nozzle, with the process defaults QC applies when nothing closer to the part sets a limit. This policy says what the registry holds, how a printer is added, and how to read the defaults.

## CEP Navigation Guide

**1 The Registry**
- Which printers are known without any configuration?
- Where else do printers come from, and which source wins?
- How is the registry listed?

**2 Process Defaults**
- Which limits does each process set by default?
- How are the defaults named in a finding?

**3 Adding a Printer**
- What does a printer table hold?
- What happens to a table that cannot be read?

**4 Printers from a Sliced File**
- Which settings of a sliced file describe its printer?

**5 Integration with Other Policies**
- Which policy uses the registry?

**6 Anti-Patterns**
- Which uses of the registry mislead?

**7 Evolution and Feedback**
- How does this policy change?

=== CEP_NAV_BOUNDARY ===

## 1 The Registry

Two printers are built in: `mk4`, the Original Prusa MK4 (FDM, 0.4 mm nozzle, 250 x 210 x 220 mm), and `form3`, the Formlabs Form 3 (resin, 145 x 145 x 185 mm).

More come from `printers.toml` in the agentcad user config folder (`$XDG_CONFIG_HOME/agentcad`, else `~/.config/agentcad`) and from a project's `[printers.<name>]` tables in its `agentcad.toml`. The built-ins come first, then the user file, then the project; a later source replaces an earlier printer of the same name, so a project can describe its own MK4 without touching anyone else's. Every printer records where it was defined.

`agentcad printers` lists the registry as seen from the current folder's project: name, label, process, nozzle, build volume and source. `--json` adds each printer's process defaults.

## 2 Process Defaults

- FDM: a minimum wall of two extrusion lines and a minimum feature of one, a line being 1.125 times the nozzle (0.45 mm for a 0.4 mm nozzle, so walls of 0.9 mm); overhangs to 45 degrees; bridges to 10 mm.
- Resin: a minimum wall of 0.4 mm and a minimum feature of 0.3 mm.

A finding names these as `process default (fdm, 0.4 mm nozzle)` or `process default (resin)`. They are starting points, not the machine's limits: a project that knows better sets its own in `[qc] limits` (`agentcad-qc`, section 2).

## 3 Adding a Printer

A table holds `label`, `process` (`fdm` or `resin`), `build_volume = [x, y, z]` in mm and, for FDM, `nozzle_mm`:

```
[printers.xl]
label = "Large FDM printer"
process = "fdm"
build_volume = [360, 360, 360]
nozzle_mm = 0.6
```

A table with an unknown process or a malformed build volume is reported on stderr, naming the table and the key, and skipped; the rest of the registry still loads.

## 4 Printers from a Sliced File

A slicer's printer configuration describes a printer too: the bed from `bed_shape` (its corner points), the height from `max_print_height`, the nozzle from `nozzle_diameter`. A sliced file carries all three in its embedded configuration, so the printer a file was sliced for can be compared with the one the part was judged against.

## 5 Integration with Other Policies

- `agentcad-qc`: judges a part against a printer from this registry.
- `agentcad-policies`: how this policy is found and read.

## 6 Anti-Patterns

- **The default printer by accident**: a project judged against the MK4 because nothing named its printer; set `[qc] printer`.
- **Defaults read as the machine's limits**: process defaults are generic; a material or nozzle that does better or worse belongs in the project's limits.
- **Editing a built-in in place**: replace it by name in the user file or the project, where the change is visible.

## 7 Evolution and Feedback

This policy ships with agentcad and changes with the command it governs; a change to the registry, its sources or its defaults updates this policy in the same pull request.
