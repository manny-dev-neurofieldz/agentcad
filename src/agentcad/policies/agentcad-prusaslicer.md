# PrusaSlicer Target: A Project File from a Complete Configuration

**Type**: Capability Policy (print readiness)
**Scope**: Any agent or person staging a part for PrusaSlicer, or reading what PrusaSlicer wrote
**Status**: ACTIVE
**Commands**: none

## Purpose

PrusaSlicer slices from a complete configuration, and a part staged for it should arrive as a project that already carries the settings the designer stated, the pose the part prints in, and nothing the designer did not mean. The `prusaslicer` output target (`agentcad-targets`) writes that project as a 3MF from a base configuration the user supplies, layers the print intent and the native settings over it, and refuses what it cannot write truthfully. This policy says where the base configuration comes from, how the layers combine, what the project holds, what is never written, and how the bed is checked.

## CEP Navigation Guide

**1 The Base Configuration**
- What is the base configuration, and why does agentcad not ship one?
- Which files can supply it, and how is it passed to the target?
- What makes the target refuse a configuration?

**1.1 The Default**
- How is a default base configuration set, and where must it not be kept?

**2 The Settings a Project Carries**
- In what order are the settings layered?

**2.1 The Mapping**
- Which neutral intent keys have a PrusaSlicer setting, and in what form is each written?
- Which keys are reported as not mapped, and why?

**2.2 Overrides and Refusals**
- What happens when a native setting disagrees with the intent?
- When is a key refused by name?
- What does a range in a native table do?

**2.3 What Is Never Written**
- Which settings never reach a project?

**3 The Project File**
- What does the 3MF hold, and in what order?
- How is a part's place stored?
- What is written for an object, and what is not built?

**4 The Bed**
- What is checked before a file is written, and against which bed?

**5 Reading**
- What does the target read, and which command checks a project?

**6 Integration with Other Policies**
- Which policies govern the pieces around this target?

**7 Anti-Patterns**
- Which uses of this target mislead?

**8 Evolution and Feedback**
- How does this policy change?

=== CEP_NAV_BOUNDARY ===

## 1 The Base Configuration

A PrusaSlicer project is only as right as the configuration under it: the printer's bed and start G-code, the filament's temperatures, the print profile's hundreds of values. agentcad does not ship one, because any copy would be somebody's printer. The user supplies the configuration the project starts from, and every setting the project carries is that configuration, changed only where the intent or a native table says so.

It is read from any one of these, told apart by the file's first bytes and not its name:

- an exported `.ini` (PrusaSlicer, File, Export, Export Config): `key = value` lines;
- a project 3MF saved from PrusaSlicer, or one this target wrote: its `Metadata/Slic3r_PE.config`;
- a sliced `.gcode` (the configuration block at its end) or `.bgcode` (its slicer metadata).

`agentcad stage PROJECT --target prusaslicer --base-config PATH` names it. A config bundle (a file of many `[section]` presets) is refused: it is not one configuration. So is a fragment: a configuration that lacks any of the settings every exported configuration carries (the printer technology, the bed and its height, the nozzle, the G-code flavor, the start and end G-code, the layer height, perimeters, infill density, the support switch, the filament and bed temperatures, the filament diameter) would be completed by PrusaSlicer with its own defaults, an empty start G-code among them, and nothing would say so. A configuration for resin printing is refused too: this target writes projects for filament printers.

### 1.1 The Default

When `--base-config` is not given, the target reads `base_config` under `[prusaslicer]` in `targets.toml` in the agentcad user config folder (`$XDG_CONFIG_HOME/agentcad`, else `~/.config/agentcad`); a relative path there is relative to that folder.

```
[prusaslicer]
base_config = "profiles/my_printer.ini"
```

The file names a path and holds no setting. The base configuration itself stays out of every project, public file and repository: an exported configuration can hold print-host credentials and local paths. With neither the flag nor the default, or with a file that cannot be read, `agentcad stage` prints one line that says how to supply one and exits with status 2.

## 2 The Settings a Project Carries

Three layers, each changing only what the one below it has:

1. the base configuration;
2. the neutral `[print]` intent, mapped (section 2.1);
3. the native settings, `[slice]` when PrusaSlicer is the project's default target and `[slice.prusaslicer]` over it (`agentcad-print-intent`).

### 2.1 The Mapping

| Intent key | PrusaSlicer setting | Written as |
|---|---|---|
| `layer_height` | `layer_height` | millimetres, over 0 |
| `walls` | `perimeters` | a whole number, 0 or more |
| `infill_percent` | `fill_density` | a percentage between 0 and 100, `25%` |
| `supports` | `support_material`, and with true also `support_material_auto` | `1` or `0`; the auto switch is set to `1` so that supports are generated where the model needs them, not only where an enforcer is painted |

A value that is not usable (a layer height of 0, a fractional number of walls, `supports = "yes"`) is refused naming the key. These are the only keys with a setting of their own; everything else stated in `[print]` is listed by `agentcad stage` as not mapped, with its reason:

- `material`: the filament profile in the base configuration carries the material. When the stated material differs from the base configuration's `filament_type`, `stage` says so; the project still carries the base configuration's filament, so supply a base configuration made for that filament.
- `print_orientation`: orientation is the placement's job (the print pose in `[qc]` and the build item transforms), not a setting.
- `printer_profile` and `filament_profile`: they name profiles; the base configuration is the printer and the filament.
- `target` and `notes`: the first names the output target, the second is prose.
- any other key: this target has no setting for it, and none is guessed.

### 2.2 Overrides and Refusals

A native value over a mapped one wins, and the disagreement is reported naming the key and both values; the same value spelled differently (`true`, `1` and `"1"`) is one statement, not a conflict.

A mapped or native key that the base configuration does not carry is refused by name, with the nearest keys the base does carry: a mistyped key would otherwise be written as a setting nothing reads, and the project would silently not say what the designer wrote. A key that holds a credential, an address or a program to run is refused as well (section 2.3). A value that spans lines is refused: a configuration value is one line.

A native entry that states a range or a reason but no value (`temperature = { min = 270, max = 285 }`) is a check for `agentcad gcode check`, not a setting. It is not written, and the target says so.

### 2.3 What Is Never Written

`post_process` is always written empty: it names a program that runs on the machine that slices. The print-host family (`printhost_*` and `print_host`: credentials, addresses, certificates) is never written; the target lists the names it left out of the base configuration, never the values. A native table that names one of these keys is refused.

## 3 The Project File

`<job>.3mf` holds, in this order and with fixed timestamps (the same job writes the same bytes):

- the package skeleton;
- `3D/3dmodel.model`: a core 3MF, one object per part and one build item per copy, each item's `transform` the 12 numbers of the part's model-to-bed placement in the row-vector convention of `agentcad-targets`, translation last; the version metadata marks it a PrusaSlicer project, so the placement stays the instance's transformation;
- `Metadata/Slic3r_PE.config`: the complete configuration, `; key = value` lines in key order;
- `Metadata/Slic3r_PE_model.config`: for each object its name, its instance count, its own settings and one volume over all its triangles.

`<job>.placement.json` is written beside it, as the generic target writes it (`agentcad.placement/2`, target `prusaslicer`). Copies after the first sit along the bed's x, each a part's width as posed plus a 5 mm gap.

A job may state settings for one part alone. They are written as the object's own settings, only for the keys PrusaSlicer lets one object override: `layer_height`, `perimeters`, `top_solid_layers`, `bottom_solid_layers`, `fill_density`, `fill_pattern`, `support_material`, `support_material_auto`, `support_material_buildplate_only`, `support_material_threshold`, `support_material_style` and `support_material_contact_distance`. Any other key is refused, since PrusaSlicer would not read it as an object's. A project's tables do not state them yet; a job built in code does.

Not built: support blockers and enforcers. A job has no way to state the region of one, so none is written; supports are controlled by the settings above.

## 4 The Bed

Before any file is written, every instance of every part is posed with its full placement and checked against the bed of the configuration that will slice it: `bed_shape` (its outline) and `max_print_height`. A part below the bed, higher than the printer prints, or reaching outside the outline is refused with the part, how far it reaches and the printer's name, and nothing is written. A rectangular bed is tested by its extent, any other outline by the corners of the part's footprint. A part exactly at an edge is on the bed.

`agentcad stage` places each part on the bed of the project's QC printer (`agentcad-qc`), not of the configuration, so the two should describe one printer; when they differ, the bed check is the one that sees it. A plate of many copies can run past the bed: the refusal names the first copies that do and counts the rest.

## 5 Reading

The target reads the settings a sliced `.bgcode`, a plain `.gcode` or a project 3MF carries, as one set of key and value pairs. `agentcad gcode check` accepts a project 3MF as it accepts a sliced file and compares the configuration in it with the `[slice]` intent (`agentcad-gcode`); a 3MF written by another tool has no such configuration, and the command says so. A printer is described from any file that carries a configuration: its bed from `bed_shape`, its height from `max_print_height`, its nozzle from `nozzle_diameter`, as `agentcad-printers` reads a sliced file.

## 6 Integration with Other Policies

- `agentcad-targets`: the contract this target implements, the placement and the generic target.
- `agentcad-print-intent`: `[print]`, `[slice.<target>]`, the conflict report and `agentcad stage`.
- `agentcad-gcode`: checking a sliced file against the native settings, and comparing slices.
- `agentcad-printers`: the printer a configuration describes.
- `agentcad-qc`: the print pose and the printer a part is judged against before it is staged.
- `agentcad-policies`: how this policy is found and read.

## 7 Anti-Patterns

- **A fragment as the base**: a few settings are not a printer; PrusaSlicer fills the rest with defaults. Supply an exported configuration.
- **The base configuration in a project**: it can carry credentials and local paths, and projects are shared. Keep it in the user config folder or pass it on the command line.
- **Reading a project's settings as the print**: the project says what PrusaSlicer was told. Only the sliced file says what it did; check that with `agentcad gcode check` on the `.gcode` or `.bgcode`.
- **Expecting `material` to change temperatures**: it changes nothing. Supply a base configuration made for the filament.
- **The same setting in both tables without meaning it**: a native value silently over the intent is a setting written twice; the conflict report is where it shows.
- **A typo kept alive**: a native key the base configuration lacks is refused on purpose; correct the name rather than adding the key to the base.

## 8 Evolution and Feedback

This policy ships with agentcad and changes with the target; a change to the mapping, the layering, the project file or the bed check updates this policy in the same pull request.
