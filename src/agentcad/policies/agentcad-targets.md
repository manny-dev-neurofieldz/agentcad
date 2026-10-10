# Output Targets: What a Part Becomes on Its Way to a Machine

**Type**: Capability Policy (print readiness)
**Scope**: Any agent or person staging a part for a slicer, a printer host or another machine, or adding a target
**Status**: ACTIVE
**Commands**: agentcad targets

## Purpose

A finished part reaches a machine through a tool: a slicer project, a plate file, a host's queue. Each tool wants its own format and settings, and the lab already has more than one. agentcad keeps a registry of output targets, each declaring what it can do, so that every target is used the same way and the next one needs no new command. This policy says what a target is, what the registry reports, how the generic target writes a plate, and how a placement is stated so that no tool reads it turned the wrong way.

## CEP Navigation Guide

**1 Targets and Capabilities**
- What is an output target, and what can one declare?
- What happens when a target is asked for something it does not declare?

**2 The Registry**
- How are the registered targets and their capabilities listed?

**3 The Generic Target**
- What does the generic target write and read?

**3.1 Placement**
- How is a part's place on the plate stated, and in which convention?
- How does a plate file store the same placement?

**4 Adding a Target**
- What does a new target implement, and what checks it?

**5 Integration with Other Policies**
- Which policies use the targets?

**6 Anti-Patterns**
- Which uses of targets and placements mislead?

**7 Evolution and Feedback**
- How does this policy change?

=== CEP_NAV_BOUNDARY ===

## 1 Targets and Capabilities

An output target turns finished parts (their meshes, their placement on the plate, the print intent) into what one tool takes, and reads back what that tool produced. A target declares some of these capabilities:

- `write_job`: write a project or package for a job;
- `slice`: slice headless;
- `read_output`: read the target's outputs and the settings they carry;
- `map_intent`: map neutral print intent to the target's native settings;
- `printer_config`: describe a printer from the target's printer configuration.

A capability a target does not declare raises an error that names the target and the capabilities it has; it is never a silent no-op, so a command can ask the registry what a target can do instead of trying and guessing.

## 2 The Registry

`agentcad targets` lists every registered target with its version (when the tool reports one), whether it is available here, and its capabilities; `--json` prints the same as data.

## 3 The Generic Target

`generic` writes and reads without any slicer installed. Its job writes two files: a core 3MF plate (one object per part, one build item per copy, copies after the first laid out along x with a 5 mm gap) that any slicer opens, and a placement sidecar. It writes no slicer settings. It reads the settings a sliced file carries, plain or binary G-code, through the same reader `agentcad gcode check` uses. The plate is written deterministically: the same job writes the same bytes.

### 3.1 Placement

A placement sidecar has the schema `agentcad.placement/2`. Each instance names its part, its copy number, its mesh file and that file's SHA-256, the target, and `transform`: a row-major 4x4 acting on column vectors (`p_bed = T p_model`), translation in the last column. The sidecar states this convention in its `convention` field.

A 3MF build item stores the same placement as 12 numbers in the row-vector convention (`p_bed = p_model M`, `M` the transpose of `T`'s 3x3 part, then the translation last). The two differ by a transpose, which is the easiest mistake to make and the hardest to see on a symmetric part; the target is tested with an asymmetric turn and offset, which a transposed matrix fails.

## 4 Adding a Target

A target subclasses the target base class, sets its name and the capabilities it declares, implements exactly those, and registers under a short lower-case name. The target contract test runs over every registered target: each declared capability must work on a small fixture, and each undeclared one must raise the error that names the target. A target that cannot work here (its tool is not installed) still registers and reports itself as not available.

## 5 Integration with Other Policies

- `agentcad-gcode`: reading what a slicer produced from a target's job.
- `agentcad-qc`: judging a part before it is staged.
- `agentcad-policies`: how this policy is found and read.

## 6 Anti-Patterns

- **A transform without its convention**: a 4x4 or 12 numbers with no stated convention will be read transposed by someone; state it, as the sidecar does.
- **Testing placement on a symmetric part**: a square turned the wrong way looks right; test with an asymmetric part and an asymmetric turn.
- **A capability claimed by trying**: ask the registry what a target declares; do not call and catch.

## 7 Evolution and Feedback

This policy ships with agentcad and changes with the targets; a new target, capability or placement field updates this policy in the same pull request.
