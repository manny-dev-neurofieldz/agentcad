# Viewer and Gallery: Where a Design Is Seen

**Type**: Capability Policy (presentation)
**Scope**: Any agent or person regenerating, checking or publishing a project's viewer, or building a gallery of projects
**Status**: ACTIVE
**Commands**: agentcad viewer, agentcad check, agentcad gallery build, agentcad gallery check

## Purpose

A finalized session leaves a viewer: one HTML page per project that shows every iteration's renders, mesh, source, parameters, notes, findings and print settings, so a reviewer sees the design history without running anything. The gallery gathers many projects' viewers behind one page of cards. This policy says what the viewer shows and how it is rebuilt from the files on disk, how a frozen tag or an artifact host gets its own page, what the page check can and cannot see, and how a gallery is built and verified.

## CEP Navigation Guide

**1 The Project Viewer**
- What does a project's viewer show?
- How is the viewer rebuilt from the files on disk?

**1.1 Tags and Artifact Hosts**
- How is the viewer of a frozen tag rebuilt?
- How is a page written for a host that supplies its own document shell?

**2 Checking a Page**
- What does the page check catch, and what can it not see?
- What does the check need installed?

**3 The Gallery**
- What does a gallery card show, and which projects get one?
- When are viewers copied under the gallery, and when only linked?

**3.1 Checking a Gallery**
- What makes a built gallery broken?

**4 Integration with Other Policies**
- Which policies produce what the viewer shows?

**5 Anti-Patterns**
- Which ways of presenting a design mislead?

**6 Evolution and Feedback**
- How does this policy change?

=== CEP_NAV_BOUNDARY ===

## 1 The Project Viewer

`index.html` in the project folder shows one variant per iteration, latest first. Each variant has its findings above its tabs (or a line saying the tray had no warnings), then tabs: Renders, 3D View (the iteration's exported STL; meshes are embedded in the page up to the project's `[output] viewer_embed_mb` and linked beside it beyond), Source, Parameters (the iteration, and its overrides on a page written by finalize), Notes and Print Settings (the print manifest, with the parts, their quantities and any recorded fits). An assembly's latest variant shows each part's latest mesh with its own toggle. When the quality gate held the part back at finalize, a banner at the top of the page says so; a page rebuilt with `agentcad viewer` does not carry it, because a rebuild does not run the gate (run `agentcad qc` to see the findings).

`agentcad session finalize` writes the viewer. `agentcad viewer PROJECT` rebuilds it from the files on disk alone: the versioned sources (`source/NAME_vN` with the engine's extension), renders (`renders/NAME_vN_VIEW.png`), exports (`exports/NAME_vN.FORMAT`), the print manifest (`exports/*.print.json`) and, when present, the session record (`_work/session.json`) for notes and findings, re-judged against the current settings. The project's engine decides which source extension is read. A folder without any versioned file is an error (exit 1). Rebuild after editing notes or settings, or when a page was lost; the page goes into the folder that was scanned.

### 1.1 Tags and Artifact Hosts

`--tag NAME` rebuilds the page of a frozen tag, `tags/NAME/index.html`, from that tag's own copies; a name with no tag is an error. `--artifact DIR` writes the page as a fragment without a document shell, plus the files it references and a `files.json` map, for a host that supplies the shell and serves the files; `--title` names it (default: the project's name).

## 2 Checking a Page

`agentcad check HTML` opens the page in a headless Chromium (through Playwright), waits until the network is idle or `-t`/`--timeout` milliseconds have passed (default 10000) and then two seconds more, and reports every console error and page error. It exits 1 when there is any. It needs Playwright and a Chromium build for the machine's architecture; without them it cannot run.

The check sees script errors and nothing else. A page that loads clean can still show the wrong part, an empty 3D view, a missing findings block or a broken image. Open the page and look at it before calling it right; a clean check is a precondition, not a review.

## 3 The Gallery

`agentcad gallery build` writes a static page of cards, one per project: the latest iso render as the thumbnail, the engine, the description, the iteration count, the last iteration's volume and solid count, the project's tags and, for a part, the assembly it belongs to. Each card links to the project's viewer. The projects are the folders that `--projects` globs match (each with an `agentcad.toml`), or else the direct subfolders of `--designs-dir` (default: the designs directory); none found is an error. `-o`/`--output` names the gallery folder (default `site`) and `--title` the page title.

By default each viewer page and its renders are copied under the gallery, so the folder is self-contained and can be served as a static site. `--max-mb` is the budget for copied files (default 200): a project that would exceed it is listed but not copied, on the card and on stderr. `--no-copy` links every viewer in place by relative paths instead, which works only while the gallery and the projects keep their places relative to each other. The gallery never modifies a project; it reads what sessions produced.

### 3.1 Checking a Gallery

`agentcad gallery check DIR` verifies a built gallery: every link and thumbnail on its page resolves, no reference is an absolute path, and every image in each copied viewer resolves. It prints the problems and exits 1 when there are any. Run it before publishing a gallery anywhere.

## 4 Integration with Other Policies

- `agentcad-session`: the iterations, findings and finalize that the viewer shows.
- `agentcad-qc`: the gate whose banner the viewer carries.
- `agentcad-fit` and `agentcad-print-intent`: the fits and print settings in the Print Settings tab.
- `agentcad-projects`: the designs directory and the `[output]` settings the viewer reads.
- `agentcad-policies`: how this policy is found and read.

## 5 Anti-Patterns

- **A clean check called a review**: the check sees script errors, not whether the page shows the part.
- **Publishing a gallery unchecked**: a link that resolves on the machine that built it may not resolve where it is served; `gallery check` first.
- **Editing the page by hand**: the next finalize or rebuild overwrites it; change the notes, the settings or the files it is built from.

## 6 Evolution and Feedback

This policy ships with agentcad and changes with the viewer, the page check and the gallery; a change to what the viewer shows updates this policy in the same pull request.
