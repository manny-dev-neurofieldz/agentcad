# Design Sessions: the Iterate, Look, Record Loop

**Type**: Capability Policy (design loop)
**Scope**: Any agent or person designing a part with agentcad
**Status**: ACTIVE
**Commands**: agentcad session start, agentcad session iterate, agentcad session reopen, agentcad session tag, agentcad session note, agentcad session finalize, agentcad session status

## Purpose

A design session is agentcad's unit of design work: a numbered sequence of iterations of one part, each rendered and measured, with notes, frozen tags for review, and a final set of exports, a print manifest and a viewer. This policy says how to run one so that every iteration is looked at and measured before the next, and so that what was decided can be found again.

## CEP Navigation Guide

**1 The Session Loop**
- What is a session, and when is one better than a plain render?
- What is the order of work inside a session?

**1.1 Starting a Session**
- What does start create, and what do its defines do?
- What happens to an earlier session when one is started again?

**1.2 Iterating**
- What does one iteration produce?
- How do per-iteration defines differ from session defines?
- What does iterating a project with part subprojects do?

**2 Reading Each Iteration**
- What must be read after every iterate, before the next one?

**2.1 The Tray**
- What does the measured report contain?
- Which warnings does it raise, and what does each mean?

**2.2 The Render Gate**
- What must happen to a render before anyone acts on it or sends it?
- What can a render not show?

**3 Recording and Freezing**
- How are findings recorded against an iteration?
- When is a tag the right tool, and what does it freeze?
- How is a finished session continued?

**4 Finalizing**
- What does finalize write, and what does it reuse?
- What is the print manifest?

**5 Session Status**
- How is a session's state inspected?

**6 Integration with Other Policies**
- Which policies govern what happens after a session?

**7 Anti-Patterns**
- What mistakes does the loop exist to prevent?

**8 Evolution and Feedback**
- How does this policy change?

=== CEP_NAV_BOUNDARY ===

## 1 The Session Loop

A session holds one part's design history in its project folder: every iteration's source copy, renders, measured metadata and notes, under `_work/`. Use a session whenever a part takes more than one attempt, which is almost always; `agentcad render` is for a single look at a source.

The order of work is fixed: start, then for each attempt iterate, read the renders and the tray, note what was learned; tag a revision before handing it to a reviewer; finalize when the design is accepted.

### 1.1 Starting a Session

`agentcad session start PROJECT` begins iteration 1 of a new session for the project (a folder under the designs directory, or a path). `-D VAR=VAL` (repeatable) sets parameter overrides applied to every iteration; `--engine` overrides the project's default engine; `--max-iter` caps the iterations.

Starting again over an unfinalized session requires `--force`. The earlier session record and the iteration files it names are moved to `_work/archive_<timestamp>/`, not deleted; `--no-archive` (with `--force`) discards them instead.

### 1.2 Iterating

`agentcad session iterate PROJECT SOURCE` renders the source at the project's views, measures the result and records iteration N: a copy of the source, the render images, the metadata and the tray report.

`-D VAR=VAL` on an iterate overrides a parameter for that iteration only, on top of the session's defines; the defines are recorded with the iteration and shown in the viewer.

`--all` also iterates every part subproject the project declares (`[project] parts` globs), with the same source.

## 2 Reading Each Iteration

After every iterate, before the next: read the tray and look at every render. An iteration that is not read is a measurement thrown away, and the next edit is then a guess.

### 2.1 The Tray

The tray is the measured report printed by iterate (and by `agentcad render --report`). Its lines give the change since the previous iteration: volume and area, bounding box, solid and face counts, the face census by surface type, edge statistics, validity, and run time.

Its warnings each name a defect a render does not show:

- the solid count differs from the expected count (one, unless the engine's `expected_solids` setting says otherwise): parts that should be one body are touching or apart;
- short edges, with the shortest length: slivers that break fillets and slicers;
- the kernel reports the shape invalid;
- twisted faces: a free-form face whose normal turns sharply along a ruling (a twisted loft);
- a measurement that failed, named by its key;
- the source changed but nothing measurable did: the edit did not land.

Each warning is also a finding: the rule that judged it, the limit and the layer that set it (an engine default, or the project's setting), and the usual fix. The session record keeps measurements and judgments apart; whenever a session loads, its judgments are recomputed from the stored measurements against the current settings, so changing `expected_solids` re-judges every iteration without rendering again. The viewer shows each iteration's findings above its tabs, or says that the tray had no warnings.

### 2.2 The Render Gate

Look at every render before acting on the iteration or sending an image to anyone: open the image, describe what it shows, and compare that with what was intended. A metric that passed is not a render that was looked at.

A render cannot show connectivity (a tangent touch and a small gap look the same), wall thickness, or whether a feature is the requested size. Read the tray's solid count and measured values for those; a render is evidence of silhouette, orientation and gross error only.

## 3 Recording and Freezing

`agentcad session note PROJECT TEXT` attaches a note to the current iteration: what was learned, what the next iteration will change, what a number means.

`agentcad session tag PROJECT NAME [--note TEXT]` copies the latest iteration's source, renders, exports and metadata into `tags/NAME/`, read-only, and refuses to overwrite an existing tag. Tag a revision before a review so the reviewer scores a frozen copy while work continues.

`agentcad session reopen PROJECT` clears a finalized session's finished state; iteration numbering continues from where it stopped.

## 4 Finalizing

`agentcad session finalize PROJECT` writes the session's results: an export per iteration (an existing export newer than its source is reused; `--export-all` re-exports every one), the print manifest `exports/NAME.print.json`, and the HTML viewer `index.html`. `--all` also finalizes every declared part subproject.

The print manifest carries what a print job needs: the parts, the print settings, any `[slice]` intent declared in the project, recorded fit results, and the sliced files found among the exports.

Finalize also fits every mate the project declares between two parts it can name, and records each fit in both parts' manifests and the project's; a mate that cannot be fitted is reported and does not stop the finalize (`agentcad-fit`, section 6).

## 5 Session Status

`agentcad session status PROJECT` prints the session's state: the engine, the iteration count against the maximum, each iteration's status with its notes, and where the session was finalized if it was. Per-iteration defines are in the session record and the viewer's Parameters tab; tags are folders under `tags/`.

## 6 Integration with Other Policies

- `agentcad-gcode`: reading the sliced file a finalized part was printed from.
- `agentcad-fit`: declaring mates and testing them with both bodies; finalize runs the declared ones.
- `agentcad-policies`: how this and every other policy is found and read.

## 7 Anti-Patterns

- **Iterating blind**: editing again before reading the tray and the renders of the last iteration.
- **Trusting the render for connectivity**: a part that renders whole can be three solids; the tray's count is the gate.
- **Reviewing a moving target**: handing a reviewer the live project instead of a tag.
- **Restarting to hide history**: `start --force --no-archive` discards the record that explains the design; archive instead.

## 8 Evolution and Feedback

This policy ships with agentcad and changes with the commands it governs; a change to a session command's behaviour updates this policy in the same pull request.
