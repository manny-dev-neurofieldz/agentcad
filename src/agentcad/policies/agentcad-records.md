# Records: Part, Job and Fit Records Others Can Rely On

**Type**: Capability Policy (records)
**Scope**: Any agent or person who writes or reads part, job or fit records, or derives owed work from them
**Status**: ACTIVE
**Commands**: agentcad records check, agentcad duties

## Purpose

A part library keeps its history in record files: what each part is and how it fits its neighbours, what each print job sent to which printer, and how each print came out. Most of a record is prose, written for the next person. A few fields are structured, so that a tool can rely on them without reading the prose: the day a job was staged and the day it printed, the verdict on a print, when a fit was measured, against which part, with what result and on which sources. Owed work follows from those fields alone: a fit to re-run because a source it measured has changed, a print whose planned day has passed, a print nobody has judged yet. This policy says which fields are structured, what each must hold, how prose and structure live side by side, and what `agentcad records check` reports.

## CEP Navigation Guide

**1 Record Files and Libraries**
- Which files are records, and what does a library hold?
- Which folders are not read, and what does a catalog add?

**2 Part Records**
- Which fields of a part record are structured, and what must each hold?

**2.1 Fit Records**
- What does a fit record state, and where can it live?
- What is a snapshot, and why record one?
- Why should a fit be recorded on both parts?

**3 Job Records**
- Which fields of a job record are structured, and what must each hold?

**3.1 Verdicts**
- Which verdicts can a print have, and what does each require?
- Where does a sentence about the print go?

**4 The Check**
- What does the check read, and what does it report?
- Which problems are errors and which are warnings, and what do the exit codes mean?

**5 Owed Work**
- Which work do the records say is owed, and from which fields?
- What makes two runs agree on the same duty?

**6 Writing Structured Fields from Prose**
- How is a structured field filled in from an older record without inventing anything?

**7 Integration with Other Policies**
- Which policies write or read these records?

**8 Anti-Patterns**
- Which ways of writing records defeat the tools that read them?

**9 Evolution and Feedback**
- How does this policy change?

=== CEP_NAV_BOUNDARY ===

## 1 Record Files and Libraries

Four kinds of file are records:

- `part.toml`, one in each part's folder: what the part is, how it is made, what it mates with, and its fit records.
- `job.toml`, one in each print job's folder: what was sent to which printer, when, and how it came out.
- `exports/<project>.print.json`, the print manifest a project's finalize writes: among other things, the fit records `agentcad fit` and finalize leave there.
- `catalog.toml`, optionally, at the top of a library: a list of parts (`[[part]]` tables with a `slug`) that may have no folder yet.

A library is any folder that holds such files, at any depth. Folders whose names begin with `_` or `.` are not read: they hold templates, tools and caches, and a template with empty fields is not a record. The parts a library knows are the slugs of its part records and the slugs its catalog lists; a reference to any other name is reported (section 4).

## 2 Part Records

The structured fields of a `part.toml`:

- `[identity] slug`: the part's stable name, required, the same as its folder's name. Two records with one slug are an error.
- `[status] state`: one of `candidate` (known to exist, its files not yet in the library), `draft`, `print-tested`, `validated`, `superseded`, when present.
- `[relations] mates_with` and `supersedes`: lists of part slugs; `superseded_by`: a part slug or empty. Each should name a part the library knows.
- `[fit.<mate>]`: the part's fit records (section 2.1).

Everything else in a part record is prose and free: the description, the design intent, the provenance, the variants, how it is made (`[fabrication]`). The days a part was staged and printed are not written in the part record: they are in the job records that name it, once.

### 2.1 Fit Records

A fit record says that two parts were fitted, when, and with what result. In a part record it is a table named for the mate:

```
[fit.clip]
recorded = 2026-01-04T10:00:00        # when the fit was measured: a TOML date-time, or "2026-01-04T10:00"
counterpart = "clip"                  # the other part's slug
verdict = "pass"                      # pass | fail | unmeasured | measured
verdict_note = "The tab seats with 0.1 mm a side."
snapshots = [
    { path = "source/bracket.py", sha256 = "<64 hex digits>" },
    { path = "../clip/source/clip.scad", sha256 = "<64 hex digits>" },
]
```

`recorded`, `counterpart` and `verdict` are required. The verdict uses the words `agentcad fit` writes: `pass` (every window at or above its nominal clearance, no overlap), `fail`, `unmeasured` (something could not be measured), `measured` (numbers without windows to judge them by). A sentence about the fit goes in `verdict_note`, or any other key: the verdict itself is one word, so a tool can read it.

A snapshot names a file the fit measured, relative to the record's folder, and its SHA-256 at the time. Snapshots are optional, but a fit without them cannot tell anyone whether it still holds: with them, a changed source shows as a changed digest, and the fit is owed again. `agentcad fit` and finalize write fit records into the print manifests of both projects, with a snapshot of each source and the program's parameter values; the check reads those too.

A fit is one event between two parts. Record it on both: the check warns when the other part's record has no fit naming this part, because whoever reads only that part would not know the fit exists.

## 3 Job Records

The structured fields of a `job.toml`:

- `[job] date`: the day the job was staged (its files ready for the slicer or printer), required.
- `[job] planned`: the day the print is planned for, when there is one.
- `[[item]]`: one table per part the job prints, at least one. `part` names the part's slug (required); `quantity`, when present, is a whole number of at least 1; `stl`, when present, names a file in the job's folder; `verdict` (section 3.1) may judge one item apart from the rest, as when a job prints two variants and one fits.
- `[outcome] date_printed`: the day it printed, or empty while it has not.
- `[outcome] verdict`: the verdict on the print (section 3.1).

Dates are TOML dates or ISO strings (`2026-03-06`); a date and time is accepted where a date is asked for.

### 3.1 Verdicts

A job's verdict, and an item's, is one of:

- `success`: printed and judged good.
- `partial`: printed; some of it is good, some is not (say which in the prose, or judge the items one by one).
- `failed`: printed and not usable.
- `pending`: printed, not judged yet.
- `cancelled`: will not print.

The first four say a print happened, so they need `[outcome] date_printed`; `cancelled` with a print date is a contradiction. A printed job with no verdict (or an empty one, as a template leaves it) reads as not judged yet, like `pending`. When the items carry their own verdicts, the job's sums them up: `pending` while any item is, `success` or `failed` when all items agree, otherwise `partial`. A sentence about the print goes in `[outcome] result` or any other key; the verdict is one word.

## 4 The Check

`agentcad records check <path> [--json]` reads every record under a folder (a library or a project), or one record file, and checks the structured fields above. It prints what it read (parts, jobs, how many printed and how many of those have no verdict, fit records, parts only the catalog lists), then each problem with its file and key:

- **Errors**: a required field missing; a value of the wrong type; a word outside its enumeration; a date that does not read as a date; a verdict that contradicts the print date; two records with one slug; a snapshot without a well-formed digest; a record that is not readable at all.
- **Warnings**: a reference to a part the library does not know; a fit recorded on one side only; a snapshot or `stl` file that is not where the record says; a slug that differs from its folder's name; a job printed before the day it was staged; a job verdict that differs from what its items' verdicts sum to.

The exit code is 0 with no errors (warnings allowed), 1 with errors, 2 when the path does not exist or holds no records. `--json` prints the whole reading (schema `agentcad.records/1`): every part, job and fit as read, each snapshot's file named from the checked folder, and every problem. Tools that derive owed work read that, not the files.

One record file checked alone is checked for its own fields only: the parts and fits it refers to are in other files, so references are checked when its library is. The check never edits a record.

## 5 Owed Work

`agentcad duties <path> [--as-of DATE] [--json]` reads the same records and lists the work they say is owed, from the structured fields alone:

- **Record a verdict**: a job that printed (`[outcome] date_printed`) and has no verdict, or a pending one. A job without a verdict of its own whose items all carry verdicts is judged by their sum (section 3.1).
- **Print by the plan**: a job whose `[job] planned` day is before the day asked about (`--as-of`, default today), that has not printed and is not cancelled.
- **Re-run a fit**: a fit whose sources have changed since it was recorded (a snapshot's SHA-256 differs from the file's now, or the file is gone), or one that recorded no snapshots and so cannot say whether it still holds. A fit recorded on both parts, the same two parts at the same time, is one duty.

Each duty says what is owed, why, and the record files and keys it was read from. Each has a stable key (`record_verdict:job=<job>`, `print_by_plan:job=<job>`, `refit:<part>+<part>@<recorded>`): the same work owed on another day gives the same key, so a tool that files duties elsewhere can tell a new duty from one it filed before. The command exits 0 whatever is owed (owed work is not an error), and 2 when the path holds no records. When the records have errors it says so on stderr, since a duty read from a malformed field may be wrong, and still lists what it can read. `--json` prints the duties with the schema `agentcad.duties/1`. The command never edits a record and does not decide who owes the work.

## 6 Writing Structured Fields from Prose

An older record states its facts in prose: "PRINTED 2026-10-07; quality pending", "FITS at nominal". When a structured field is filled in from such a record:

- Take the value only from what the record (or a file it names) says, never from memory or from what is likely. A print whose outcome is not written down is `pending`, not `success`.
- Keep the prose. Put the structured value beside it, and when it is read off a sentence, say which: a key such as `verdict_source` quoting the sentence it came from.
- A word that once held prose and now must hold one word (a fit's `verdict`) keeps its sentence under another key (`verdict_note`).
- A snapshot is recorded only when the file is known to be the one the fit measured (for example, it has not changed since the fit's day); otherwise leave snapshots out, and the fit reads as not anchored to its sources.
- Run the check after every batch of edits; a record the check reads cleanly is one a tool can rely on.

## 7 Integration with Other Policies

- `agentcad-fit`: measuring a fit, and the fit records it writes into both projects' manifests.
- `agentcad-print-intent`: the print manifest, where fit records are kept for a project.
- `agentcad-targets`: staging a job for a printer or slicer; the job record says when it was staged.
- `agentcad-gcode`: checking a sliced file, the evidence behind many verdicts.
- `agentcad-policies`: how this policy is found and read.

## 8 Anti-Patterns

- **Prose in a structured field**: `verdict = "FITS at nominal, mostly"` cannot be read by a tool; write `verdict = "pass"` and put the sentence beside it.
- **A guessed verdict**: marking an unjudged print `success` because nothing bad was reported hides the work of judging it.
- **A date written twice**: a part record that repeats its jobs' print dates will disagree with them one day; the job record holds the date.
- **A fit on one side**: the part that does not record the fit is the one whose next change breaks it unnoticed.
- **A fit without snapshots**: it cannot say whether it still holds after either part changes.
- **Fixing the check by deleting the record**: a record with an error is history to correct, not to remove.

## 9 Evolution and Feedback

This policy ships with agentcad and changes with the record contract; a new structured field, enumeration or check updates this policy, the check and its tests in the same pull request.
