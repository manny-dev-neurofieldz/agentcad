# Viewer and Gallery: Where a Design Is Seen

**Type**: Capability Policy (presentation)
**Scope**: Any agent or person regenerating, checking or publishing a project's viewer, or building a gallery of projects
**Status**: ACTIVE
**Commands**: agentcad viewer, agentcad check, agentcad gallery build, agentcad gallery check

## Purpose

A finalized session leaves a viewer: one HTML page per project that shows every iteration's renders, mesh, source, parameters, notes, findings and print settings, so a reviewer sees the design history without running anything. The gallery gathers many projects' viewers behind one page of cards. This policy says what the viewer shows and how it is rebuilt from the files on disk, how a frozen tag or an artifact host gets its own page, what the page check can and cannot see, and how a gallery is built and verified.

## Reaching for It

- Showing a design's whole history to someone who will not run anything: the project's viewer, written by `agentcad session finalize`.
- A page lost, or notes and settings changed since the finalize: `agentcad viewer PROJECT` rebuilds it from the files on disk.
- A frozen revision for a reviewer: `agentcad viewer PROJECT --tag NAME`.
- Many projects behind one page, to publish as a static site: `agentcad gallery build`, then `agentcad gallery check`.
- Whether a page's scripts run: `agentcad check`; whether it shows the right part: open it and look (section 2).

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

**4 Recipes**
- How is a viewer rebuilt and a gallery built and checked, as commands?

**5 Constraints to Probe**
- What does a page or a gallery need before it is shown to anyone?

**6 Integration with Other Policies**
- Which policies produce what the viewer shows?

**7 Anti-Patterns**
- Which ways of presenting a design mislead?

**8 Evolution and Feedback**
- How does this policy change?

=== CEP_NAV_BOUNDARY ===

## 1 The Project Viewer

`index.html` in the project folder shows one variant per iteration, latest first. Each variant has its findings above its tabs (or a line saying the tray had no warnings), then tabs: Renders, 3D View (the iteration's exported STL; meshes are embedded in the page up to the project's `[output] viewer_embed_mb` and linked beside it beyond), Source, Parameters (the iteration, and its overrides on a page written by finalize), Notes and Print Settings (the print manifest, with the parts, their quantities and any recorded fits). An assembly's latest variant shows each part's latest mesh with its own toggle. When the quality gate held the part back at finalize, a banner at the top of the page says so. The session record keeps the banner, so a page rebuilt with `agentcad viewer` carries it too, until a finalize the gate does not hold clears it. A rebuild does not run the gate itself (`agentcad qc` does).

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

## 4 Recipes

From a finished session to a checked gallery of it:

```console
# recipe: examples
$ agentcad session start examples/hex_tray
Session started
$ agentcad session iterate examples/hex_tray examples/hex_tray/source/hex_tray.scad
Iteration v1 recorded
$ agentcad session finalize examples/hex_tray
HTML viewer: ...examples/hex_tray/index.html
$ agentcad viewer examples/hex_tray
Regenerated: examples/hex_tray/index.html
$ agentcad gallery build -o site --projects examples/hex_tray --title "trays"
Gallery: site/index.html (1 project(s))
$ agentcad gallery check site
Gallery check: clean
```

`viewer` rebuilt the page from the files alone, which is how a page with edited notes or settings is refreshed. A clean gallery check means every link and image resolves, not that the page shows the right part: open `site/index.html` and a viewer from it and look before publishing (section 2). Next: serve `site/` as static files.

A page the files cannot make is refused, with what was looked for:

```console
# recipe: examples
$ agentcad viewer examples/j_hook
# exit 1
No versioned files found in examples/j_hook
$ agentcad viewer examples/hex_tray --tag review-1
# exit 1
no tag 'review-1'
```

Next: finalize a session first (`agentcad-session`), or tag the revision before asking for its page.

## 5 Constraints to Probe

- A viewer is built only from versioned files: `agentcad viewer PROJECT` refuses a folder without them and names the patterns it looked for.
- A page can load clean and still show the wrong part: `agentcad check HTML` reports script errors only (and needs Playwright with a Chromium); opening the page is the rest of the check.
- A gallery is portable only if every reference resolves where it is served: `agentcad gallery check DIR` lists each broken link, thumbnail and absolute path.
- A large project may not be copied under the gallery: `agentcad gallery build` names on stderr each project it only listed because of `--max-mb`.

## 6 Integration with Other Policies

- `agentcad-session`: the iterations, findings and finalize that the viewer shows.
- `agentcad-qc`: the gate whose banner the viewer carries.
- `agentcad-fit` and `agentcad-print-intent`: the fits and print settings in the Print Settings tab.
- `agentcad-projects`: the designs directory and the `[output]` settings the viewer reads.
- `agentcad-policies`: how this policy is found and read.

## 7 Anti-Patterns

- **A clean check called a review**: the check sees script errors, not whether the page shows the part.
- **Publishing a gallery unchecked**: a link that resolves on the machine that built it may not resolve where it is served; `gallery check` first.
- **Editing the page by hand**: the next finalize or rebuild overwrites it; change the notes, the settings or the files it is built from.

## 8 Evolution and Feedback

This policy ships with agentcad and changes with the viewer, the page check and the gallery; a change to what the viewer shows updates this policy in the same pull request.
