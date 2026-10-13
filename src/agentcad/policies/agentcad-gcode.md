# Sliced Files: Reading What Will Actually Print

**Type**: Capability Policy (print verification)
**Scope**: Any agent or person checking a sliced file before it prints
**Status**: ACTIVE
**Commands**: agentcad gcode decode, agentcad gcode info, agentcad gcode summary, agentcad gcode check, agentcad gcode supports, agentcad gcode view, agentcad gcode thumbnails, agentcad gcode compare

## Purpose

The sliced file is the last artifact before plastic and the only one that records what the slicer decided: where supports go, which settings were really used, how much material each part takes. The `agentcad gcode` commands read it in pure Python, with no slicer installed. This policy says how to read one before a print, and how not to over-read what the commands report.

## CEP Navigation Guide

**1 What the Commands Read**
- Which files do the gcode commands accept?
- What does verification of a binary file check?
- Which command also accepts a project file, and what does it read from it?

**2 Decoding and Inspecting**
- How is a binary file turned into plain G-code?
- What does the block table and metadata show?

**3 The Summary**
- What does the summary report?
- How is a summary checked for being right?

**4 Settings Against Intent**
- How is a file's slicing checked against what the project intended?
- What happens when no intent is declared?

**5 Where Supports Touch**
- What is a contact band?
- In which frame are bands reported, and how are they placed on the part?

**5.1 Testing a Band Without Placement**
- How can a band be judged before the part's placement is known?

**6 The Toolpath Page**
- What does the toolpath page show, and how big may it get?

**7 Comparing Two Slices**
- What does the comparison report, and for which files?
- What does its exit status mean?

**7.1 What the Numbers Are**
- Where does the time come from, and when is it missing?
- How are objects matched, and what happens to one that is in only one file?
- Why can a band count change when the supports did not?

**7.2 Settings That Are Never Compared**
- Which settings does the comparison leave out, and why?

**8 Integration with Other Policies**
- Where do sliced files meet the session and the manifest?

**9 Anti-Patterns**
- Which readings of these reports are wrong?

**10 Evolution and Feedback**
- How does this policy change?

=== CEP_NAV_BOUNDARY ===

## 1 What the Commands Read

Every gcode command accepts a Prusa binary G-code file (`.bgcode`) or a plain G-code file; a plain file passes through decoding unchanged, so the same command works on either. `agentcad gcode check` also accepts a PrusaSlicer project (a 3MF, told by its first bytes): it checks the configuration the project carries, as it checks a sliced file's. A 3MF written by another tool carries none, and the command says so. The other commands read toolpaths, which a project does not hold.

A binary file is a sequence of blocks (file metadata, printer metadata, thumbnails, print metadata, slicer metadata, G-code), each with a checksum. The checksums are verified on every read; `--no-verify` skips them and says so on stderr. Use it only to inspect a file already known to be damaged. A file that is not what the command reads (a checksum that fails, a plain file given to `info` or `thumbnails`, which read only the binary format) is an error that names the file and the reason, with exit status 1.

## 2 Decoding and Inspecting

`agentcad gcode decode FILE` writes the plain G-code to stdout, or to the file `-o`/`--output` names. `agentcad gcode info FILE` prints the header, the block table and the printer and print metadata. `agentcad gcode thumbnails FILE -o DIR` writes the preview images the file carries into the folder `-o`/`--output` names (required).

## 3 The Summary

`agentcad gcode summary FILE` models the file by layer, object and feature (perimeters, infill kinds, bridges, support material, support interface, skirt and brim) and reports: layers and top height, filament used, extrusion per object and per feature, the support share and the first and last layers that carry supports. `--json` prints the record (schema `agentcad.gcode.summary/1`), which also carries the printing time the file states for itself (`estimated_time`: seconds and the file's own text, or null when it states none). The time is read, never computed.

The summary checks itself: its filament total is computed the way the slicer reports it and is printed beside the total the file states. The two must agree. A disagreement means the reader or the file is wrong; stop and find out which before trusting any other number.

## 4 Settings Against Intent

`agentcad gcode check FILE --project DIR` (or `--intent FILE.toml`; one or the other, and given both the command refuses) compares the slicer settings embedded in the file with the intended values, keyed by the slicer's own setting names. The intent is read as the slicer's target sees it (`agentcad-print-intent`): the neutral `[print]` table as the target maps it (each mapped setting's reason names the `[print]` key it came from), then the bare `[slice]` table when the target is the file's default, then `[slice.<target>]`. A native value that differs from a mapped one wins, and the command prints the `conflict:`; each `[print]` key the target has no setting for is printed as `not checked:` with the reason; a `[print]` value the target cannot use is refused with exit status 2. A violated value is an error and the command exits 1; findings are sentences that name the key, both values and the declared reason. `--json` prints each finding with its key, severity, found and intended values, reason, source and sentence, and also the rule (`slice_setting`), the layer that set the limit (the intent's source) and the usual fix. With `--json`, stdout carries only the findings (`[]` when no intent is declared), and the `conflict:` and `not checked:` lines and the no-intent listing go to stderr.

With no print or slice intent the command prints the file's key settings and says there is nothing to check against. That is not a pass. Print-host credentials in an embedded configuration are never printed.

## 5 Where Supports Touch

`agentcad gcode supports FILE` finds the contact bands: the regions where support material lies within the contact distance (the file's own `support_material_contact_distance` unless `--contact-distance` is given) of a part, with each band's object, height range, area and bed position. Bands smaller than `--min-area` are hidden.

Bands are reported in the bed frame. With a placement sidecar (`--placement`, schema `agentcad.placement/1` or `/2`; its STL paths are relative to the sidecar's folder unless `--stl-root` names another; `--stl-root` takes effect with `--placement`, and alone it is named on stderr as ignored), each band is also placed in its part's own frame, and a band inside a cavity of the part is reported as such and makes the command exit 1. `--json` judges the same way and exits the same way: each band carries `region` (`cavity` or `outside`, or null when no placement or no STL let it be checked), `region_votes` (the rays' votes, or null) and `region_note` (why a region was not checked, or null when it was or no placement was given). The region check reads the STL with pyvista (the build123d extra); without it the bands are still listed, each says no region was checked and why, and nothing counts as a cavity. `--png`, which needs pyvista too, renders the parts with their contact cells, with `--json` too (the render's line then goes to stderr, so stdout stays JSON). Without pyvista, `--png` is refused before anything is read or printed: one `Error:` line saying it needs pyvista, exit 2.

### 5.1 Testing a Band Without Placement

A band's height needs no placement: add the contact distance to the band's top height and compare it with the height of the overhang the supports were meant for. A band at a height where no overhang was intended is a finding before any placement is known.

## 6 The Toolpath Page

`agentcad gcode view FILE` writes a standalone page of the toolpaths (to `<file>.toolpaths.html`, or the path `-o`/`--output` names): per-feature colours with toggles and a layer range. Toolpaths are embedded up to `--budget-mb`; above it every Nth layer is kept and the page says so. With `--placement` (and `--stl-root`, as for supports) the support contact cells are marked. `--artifact DIR` writes a page fragment for an artifact host instead of the page; `-o` and `--artifact` are one or the other.

## 7 Comparing Two Slices

`agentcad gcode compare A B` reads two sliced files, of either kind and in any mix, and reports for A, for B and as B minus A: the estimated printing time each file states; the filament used (the summary's own total beside the total the file states); layers and top height; the support share; the contact bands (their count and total area, found as `agentcad gcode supports` finds them); and the extrusion of each object. Below the table it lists the settings that differ between the two embedded configurations: values that differ, and settings only one file carries. `--json` prints the record (schema `agentcad.gcode.compare/1`) with every differing setting; the text lists the first 20 and counts the rest, and `--all-settings` lists them all.

The command gives no verdict. It exits 0 once both files are read, 1 when a file cannot be read (the message names which), and 2 on a usage error. A verdict needs an intent to judge against: that is `agentcad gcode check`.

### 7.1 What the Numbers Are

- The time is the slicer's own estimate, read from the file's metadata or from the estimate comment a plain export carries. It is never computed here. A file that states none shows none, and no time difference is reported.
- Objects are matched by the name the slicer gave them. An object in only one file has a row of its own, marked as such, and its difference counts it as no filament in the other file. Extrusion that belongs to no object (skirt, priming) is a row too.
- Contact bands smaller than `--min-area` (1 mm2 by default, as in `agentcad gcode supports`) are left out of the band rows, and the command says how many it left out. A band count that moves only through such small bands is not a change in where supports touch.
- A file without feature comments cannot say what is support, so its support figures are unknown, not zero.
- Every difference is computed from the values shown, to their precision: subtracting the two columns gives the third.

### 7.2 Settings That Are Never Compared

Settings that hold credentials or local paths (the print-host family and the post-processing scripts) are never compared, printed or put in the record. A plain file's settings are the ones inside its configuration block. The statistics and results it writes beside the block (filament used, estimated printing time, the highest layer, where the objects sit) are not settings and are not listed as such; a file without a block is read by name, since a setting's name has no spaces.

## 8 Integration with Other Policies

- `agentcad-session`: a finalized project's print manifest lists the sliced files found among its exports, with a toolpath page for each, and carries the project's `[slice]` intent.
- `agentcad-policies`: how this policy is found and read.

## 9 Anti-Patterns

- **A clean check without intent**: no `[print]` or `[slice]` intent means no verdict, not a passing one.
- **Bed coordinates as part coordinates**: without placement, a band's x and y say where on the plate it is, not where on the part.
- **Trusting a summary that disagrees with the file's stated total**: the disagreement is the first finding.
- **Reading past a failed checksum**: `--no-verify` is for inspecting damage, not for silencing it.
- **Taking a settings difference for the cause of a result difference**: the list shows what the two files carry. A result can move through a setting that did not change (the part moved, the model changed), and a setting that changed may do nothing for this part.
- **Comparing slices of differently named parts**: objects are matched by name, so two slices that name their parts differently share no object and every row reads "only in" one file. Compare slices of the same part.
- **Using a difference from a file that contradicts itself**: when a file's own filament total and the total it states disagree, the comparison says so. Settle that before using any number from that file.

## 10 Evolution and Feedback

This policy ships with agentcad and changes with the commands it governs; a change to a gcode command's behaviour updates this policy in the same pull request.
