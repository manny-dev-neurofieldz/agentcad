# Projects: Where a Design Lives and How It Is Configured

**Type**: Capability Policy (projects and configuration)
**Scope**: Any agent or person creating, finding or configuring an agentcad project
**Status**: ACTIVE
**Commands**: agentcad new-project, agentcad projects, agentcad status, agentcad open, agentcad config-init, agentcad config-show

## Purpose

Every agentcad command works on a project: a folder whose `agentcad.toml` names the engine, the views, the print intent, the checks and the mates of one part or one assembly. This policy says what a project folder holds, how a command finds one, where a session writes, how a project is created or an existing folder made into one, how to see what a command will use, and which policy governs each table of the file.

## CEP Navigation Guide

**1 What a Project Is**
- What makes a folder a project, and what does it hold?
- How does a command find the project it is given?

**1.1 Where Outputs Go**
- Where does a session write its renders, exports and record?
- What must a project kept outside the designs directory state?

**1.2 Part Subprojects**
- How does an assembly declare its parts, and how many of each it uses?

**2 Creating a Project**
- How is a new project created, and what does it start with?
- How is an existing folder made a project?

**3 Inspecting Projects**
- How are the projects listed?
- How is one project's state read, or its path printed?
- How is the configuration a command will use shown?

**4 The agentcad.toml Tables**
- Which tables does the file hold, and which policy governs each?
- Which values does the template state that the designer has not chosen?

**5 Integration with Other Policies**
- Which policies govern the work done inside a project?

**6 Anti-Patterns**
- Which ways of placing or configuring a project mislead?

**7 Evolution and Feedback**
- How does this policy change?

=== CEP_NAV_BOUNDARY ===

## 1 What a Project Is

A project is a folder with an `agentcad.toml` file; agentcad recognizes a project by that file and nothing else. The folder holds `source/` (the engine's source files), `renders/` (images), `exports/` (meshes and other geometry, and the print manifest), and once a session has run, `_work/` (the session record and every iteration's files) and `index.html` (the viewer).

A command given a PROJECT takes a name or a path. A name is looked up in the designs directory, which the installed package's output defaults fix; a project's own settings cannot move it, because the lookup happens before any project is read. When no folder of that name is there, the argument is tried as a path. The session commands, `viewer`, `qc` and `stage` also find a part subproject by its own folder name under any project in the designs directory. `status` takes a name or a path; `open` takes a name only.

### 1.1 Where Outputs Go

A session writes into the folder that `[output] base_dir` and `sub_dir` name, joined with the project folder's name. A relative `base_dir` is relative to the `agentcad.toml` it is written in, so `base_dir = ".."` with `sub_dir = "."` names the project folder itself, wherever it is; projects made by `new-project` and `config-init` are written that way. A project without an `[output]` table (written by hand, or by an older template) uses the package defaults, and its sessions write to the folder of its name in the designs directory rather than to the folder it is in. Give such a project those two lines before its first session.

The same table sets `image_size` (pixels per side of a session's renders, default 1024), `default_views` (the camera presets a session renders) and `viewer_embed_mb` (each variant's meshes are embedded in the viewer up to this size and linked beside the page beyond it, default 8).

### 1.2 Part Subprojects

An assembly lists its parts in `[project] parts`: globs, relative to its folder, of part subprojects, each a folder with its own `agentcad.toml` (for example `parts = ["parts/*"]`). The parent then iterates and finalizes every part with `--all`, its viewer shows each part's latest mesh with a toggle, and `projects` lists the parts under it. A part's `[project] quantity` (default 1) says how many the assembly uses: the viewer labels the part's toggle with it, the print manifest lists it, and `stage` stages that many copies unless told otherwise.

## 2 Creating a Project

`agentcad new-project NAME` creates the folder `NAME` in the designs directory with `source/`, `renders/` and `exports/`, and writes `agentcad.toml` from the template unless the folder already has one. `-e`/`--engine` names the engine the file declares (default `openscad`; `agentcad info` lists the registered engines), `-d`/`--description` its description, and `-b`/`--base-dir` another base directory: the project is then created in that directory's `mechanical_designs` folder, and its sessions write there.

`agentcad config-init` writes the template into the current directory, which makes that folder a project wherever it is. `-n`/`--name` sets the project name (default: the folder's name) and `-d`/`--description` the description. An existing `agentcad.toml` is kept, and the command exits 1, unless `-f`/`--force` is given. The file it writes declares the `openscad` engine; change `[project] engine` for another.

## 3 Inspecting Projects

`agentcad projects` lists the projects that are direct subfolders of the designs directory, with engine and description, each followed by the part subprojects it declares. A project kept anywhere else is not listed.

`agentcad status PROJECT` prints the project's resolved configuration and counts its files: sources, PNG renders, STL exports and JSON manifests, and whether a viewer page exists. The state of its session is `agentcad session status` (`agentcad-session`).

`agentcad open NAME` prints the path NAME has in the designs directory, for a shell to change into; it does not check that the folder exists.

`agentcad config-show` prints the configuration found from the current directory upward, from the nearest `agentcad.toml` in this folder or a parent. The print lines it shows are typed fields that hold defaults where the file states nothing; what the project actually states is its `[print]` table (`agentcad-print-intent`).

## 4 The agentcad.toml Tables

| Table | Holds | Governed by |
|---|---|---|
| `[agentcad]` | `version`, the configuration format's version | this policy |
| `[project]` | `name`, `engine`, `description`, `parts`, `quantity` | this policy |
| `[output]` | `base_dir`, `sub_dir`, `image_size`, `default_views`, `viewer_embed_mb` | this policy, section 1.1 |
| `[engine.<name>]` | one engine's settings; only the project engine's table is used | `agentcad-engines` |
| `[print]` | the neutral print intent | `agentcad-print-intent` |
| `[slice]`, `[slice.<target>]` | a target's native slicer settings | `agentcad-print-intent`, `agentcad-gcode` |
| `[qc]`, `[printers.<name>]` | the design-rule checks and the printers they judge against | `agentcad-qc`, `agentcad-printers` |
| `[mates.<name>]` | a mate, its datums and its windows | `agentcad-fit` |

The template states a `[print]` table with a material, a layer height, an infill, a supports flag and a printer. Once in the file those values are the project's stated intent and reach the print manifest, whether or not anyone chose them: set them to what the part needs, or delete the lines that are not decided yet.

## 5 Integration with Other Policies

- `agentcad-session`: the design loop that runs inside a project.
- `agentcad-engines`: the engine a project names and its `[engine.<name>]` settings.
- `agentcad-print-intent`, `agentcad-qc`, `agentcad-fit`: the tables that state how the part prints, what it is checked against and how it mates.
- `agentcad-viewer`: the page a project's sessions produce, and the gallery of projects.
- `agentcad-policies`: how this policy is found and read.

## 6 Anti-Patterns

- **A project outside the designs directory without `[output]`**: its sessions write to another folder; the two lines of section 1.1 keep them in the project.
- **Template values left as intent**: a `[print]` table nobody edited states a material and a layer height nobody chose.
- **Looking up an unlisted project by name**: `projects` and `open` see only the designs directory; pass a path.

## 7 Evolution and Feedback

This policy ships with agentcad and changes with the project commands and the configuration file; a new table or key updates this policy in the same pull request.
