# Render and Export: A Single Look and a Single File

**Type**: Capability Policy (rendering and export)
**Scope**: Any agent or person rendering or exporting a source outside a design session
**Status**: ACTIVE
**Commands**: agentcad render, agentcad export

## Purpose

Most design work runs in a session, which keeps every iteration and compares each with the last. Sometimes one look or one file is all that is needed: a quick render of a source someone sent, an STL of a finished program, a plate of test pieces that differ in one dimension. `agentcad render` and `agentcad export` do that on any source, with the engine its project names. This policy says what each produces, where, how a variant plate is made, and when a session is the better tool.

## CEP Navigation Guide

**1 Rendering a Source**
- What does a render produce, and where?
- Which views and size does it use, and which engine?
- What does the report show?

**1.1 When a Session Is the Better Tool**
- What does a lone render not give that an iteration does?

**2 Exporting a Source**
- Which formats can be written, and where does the file go?

**2.1 Variant Plates**
- How is one file written per value of a parameter?
- What is a variant plate for?

**3 Integration with Other Policies**
- Which policies govern what a render shows and what an export becomes?

**4 Anti-Patterns**
- Which uses of a lone render or export mislead?

**5 Evolution and Feedback**
- How does this policy change?

=== CEP_NAV_BOUNDARY ===

## 1 Rendering a Source

`agentcad render SOURCE` renders the source to one PNG per view in `output/` beside the source, or in the folder `-o`/`--output-dir` names, and prints each image's path and what the engine measured. The engine is `-e`/`--engine`, else the one named by the nearest `agentcad.toml` from the source's folder upward (whose `[engine.<name>]` settings it also takes), else OpenSCAD. `-v`/`--views` picks camera presets (default `iso`, `front`, `top`, `right`), `-s`/`--size` the image size in pixels (default 1024), and `-D`/`--define VAR=VAL` (repeatable) overrides a parameter. Before anything runs, exit 2 refuses a `-D` without `=`, a `-D` name the source does not have (where the engine can read the names without running the source: the parameters of a Python source's `build()`, the variables an OpenSCAD file assigns at top level; a file that includes another, or a `build()` that takes any keyword, is passed on), and an `--engine` that reads another kind of file than the source; each message names the flag. A render fails, with exit 1, when the source is missing, the engine is not available, or the engine reports the render failed.

`--report` prints the measured report instead of the raw metadata: the tray an iteration prints, with values but no changes (there is no previous iteration), and its warnings on stderr.

### 1.1 When a Session Is the Better Tool

A lone render keeps no history: nothing compares it with the previous attempt, so the tray's change lines are absent and a source edit that changed nothing measurable goes unnoticed. It also takes neither the project's `[output] default_views` nor its `image_size`. For an OpenSCAD source the render measures only the facet count, because OpenSCAD's geometry is measured from an exported mesh, which an iteration makes and a lone render does not. Use `render` for one look; use a session (`agentcad-session`) for anything that will be iterated.

Every render is still subject to the render gate: open the images and say what they show before acting on them or sending them on.

## 2 Exporting a Source

`agentcad export SOURCE` writes the source as STL, or as the format `-f`/`--format` names; `agentcad info` lists the formats each engine writes, and a format the engine cannot write is refused before anything runs, naming `--format` and that list (exit 2). The file goes beside the source with the format's extension, or to `-o`/`--output`. The engine is chosen as for a render (`-e`/`--engine`), and `-D`/`--define VAR=VAL` overrides parameters. It prints the path, the format, the facet count where it applies and the time, and exits 1 on failure.

### 2.1 Variant Plates

`--variants KNOB=v1,v2,...` writes one file per value of one parameter, each with the value in its name: `part_clearance-0p2.stl` for `clearance=0.2` (a dot becomes `p`), on top of any `-D` overrides. Each line printed gives the value, and the file's volume where the engine measured one. A malformed specification exits 2, as does a knob the source has no parameter for (named as for `-D`, section 1); a value that fails to export makes the command exit 1 after the others are written.

A variant plate is how a material's real clearance is found: print the same mating feature at several clearances side by side and keep the one that fits. As-printed is not nominal, and a single print at the nominal clearance says nothing about the margin either way.

## 3 Integration with Other Policies

- `agentcad-engines`: the engines, their formats and their settings.
- `agentcad-session`: iterating a design, the tray and the render gate.
- `agentcad-print-intent`: what an exported part needs before it is staged for a printer.
- `agentcad-policies`: how this policy is found and read.

## 4 Anti-Patterns

- **Iterating with lone renders**: each look is unrelated to the last; nothing tells you the edit did not land.
- **A render reported unseen**: a render that was not looked at is not evidence.
- **One clearance printed and called the fit**: print a variant plate when the fit depends on the material.

## 5 Evolution and Feedback

This policy ships with agentcad and changes with the render and export commands; a change to either updates this policy in the same pull request.
