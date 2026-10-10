# Sliced Files: Reading What Will Actually Print

**Type**: Capability Policy (print verification)
**Scope**: Any agent or person checking a sliced file before it prints
**Status**: ACTIVE
**Commands**: agentcad gcode decode, agentcad gcode info, agentcad gcode summary, agentcad gcode check, agentcad gcode supports, agentcad gcode view, agentcad gcode thumbnails

## Purpose

The sliced file is the last artifact before plastic and the only one that records what the slicer decided: where supports go, which settings were really used, how much material each part takes. The `agentcad gcode` commands read it in pure Python, with no slicer installed. This policy says how to read one before a print, and how not to over-read what the commands report.

## CEP Navigation Guide

**1 What the Commands Read**
- Which files do the gcode commands accept?
- What does verification of a binary file check?

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

**7 Integration with Other Policies**
- Where do sliced files meet the session and the manifest?

**8 Anti-Patterns**
- Which readings of these reports are wrong?

**9 Evolution and Feedback**
- How does this policy change?

=== CEP_NAV_BOUNDARY ===

## 1 What the Commands Read

Every gcode command accepts a Prusa binary G-code file (`.bgcode`) or a plain G-code file; a plain file passes through decoding unchanged, so the same command works on either.

A binary file is a sequence of blocks (file metadata, printer metadata, thumbnails, print metadata, slicer metadata, G-code), each with a checksum. The checksums are verified on every read; `--no-verify` skips them and says so on stderr. Use it only to inspect a file already known to be damaged.

## 2 Decoding and Inspecting

`agentcad gcode decode FILE [-o OUT]` writes the plain G-code (stdout by default). `agentcad gcode info FILE` prints the header, the block table and the printer and print metadata. `agentcad gcode thumbnails FILE -o DIR` writes the preview images the file carries.

## 3 The Summary

`agentcad gcode summary FILE` models the file by layer, object and feature (perimeters, infill kinds, bridges, support material, support interface, skirt and brim) and reports: layers and top height, filament used, extrusion per object and per feature, the support share and the first and last layers that carry supports. `--json` prints the record (schema `agentcad.gcode.summary/1`).

The summary checks itself: its filament total is computed the way the slicer reports it and is printed beside the total the file states. The two must agree. A disagreement means the reader or the file is wrong; stop and find out which before trusting any other number.

## 4 Settings Against Intent

`agentcad gcode check FILE --project DIR` (or `--intent FILE.toml`) compares the slicer settings embedded in the file with a `[slice]` table of intended values, keyed by the slicer's own setting names. A violated value is an error and the command exits 1; findings are sentences that name the key, both values and the declared reason. `--json` prints each finding with its key, severity, found and intended values, reason, source and sentence, and also the rule (`slice_setting`), the layer that set the limit (the intent's source) and the usual fix.

With no `[slice]` table the command prints the file's key settings and says there is nothing to check against. That is not a pass. Print-host credentials in an embedded configuration are never printed.

## 5 Where Supports Touch

`agentcad gcode supports FILE` finds the contact bands: the regions where support material lies within the contact distance (the file's own `support_material_contact_distance` unless `--contact-distance` is given) of a part, with each band's object, height range, area and bed position. Bands smaller than `--min-area` are hidden.

Bands are reported in the bed frame. With a placement sidecar (`--placement`, schema `agentcad.placement/1`), each band is also placed in its part's own frame, and a band inside a cavity of the part is reported as such and makes the command exit 1. `--png` renders the parts with their contact cells.

### 5.1 Testing a Band Without Placement

A band's height needs no placement: add the contact distance to the band's top height and compare it with the height of the overhang the supports were meant for. A band at a height where no overhang was intended is a finding before any placement is known.

## 6 The Toolpath Page

`agentcad gcode view FILE` writes a standalone page of the toolpaths: per-feature colours with toggles and a layer range. Toolpaths are embedded up to `--budget-mb`; above it every Nth layer is kept and the page says so. With `--placement` the support contact cells are marked. `--artifact DIR` writes a page fragment for an artifact host.

## 7 Integration with Other Policies

- `agentcad-session`: a finalized project's print manifest lists the sliced files found among its exports, with a toolpath page for each, and carries the project's `[slice]` intent.
- `agentcad-policies`: how this policy is found and read.

## 8 Anti-Patterns

- **A clean check without intent**: no `[slice]` table means no verdict, not a passing one.
- **Bed coordinates as part coordinates**: without placement, a band's x and y say where on the plate it is, not where on the part.
- **Trusting a summary that disagrees with the file's stated total**: the disagreement is the first finding.
- **Reading past a failed checksum**: `--no-verify` is for inspecting damage, not for silencing it.

## 9 Evolution and Feedback

This policy ships with agentcad and changes with the commands it governs; a change to a gcode command's behaviour updates this policy in the same pull request.
