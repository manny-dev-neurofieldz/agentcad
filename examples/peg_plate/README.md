# peg_plate (build123d, an assembly with parts)

A plate with three holes and the peg that presses into them. The parent
project declares `parts = ["parts/*"]`; `parts/plate` and `parts/peg` are
subprojects whose sessions are started with `-D part=plate` and
`-D part=peg`, and `session iterate --all` / `finalize --all` run them with
the parent. The gallery's viewer shows the assembly with one toggle per
part and the peg's quantity (3).

What it exercises: one source for several parts, a shared mate parameter
with a clearance, a `Compound` assembly, and the parts workflow.

The project declares its mate (`[mates.middle_peg]`, the middle peg in the
middle hole with a 0.05 mm nominal gap, `parts = ["plate", "peg"]`), and each
part declares its own side: the hole's axis and the plate's underside, the
peg's axis and its base. `session finalize --all` poses the peg in the hole
from those datums, measures the gap against the nominal, reports where the
parts touch, and records the fit in the plate's, the peg's and the
assembly's print manifests. By hand:

    agentcad fit source/peg_plate.py source/peg_plate.py \
        --a-define part=plate --b-define part=peg \
        --mate middle_peg --a-mates parts/plate --b-mates parts/peg --record

(one source builds both parts, so `--a-mates` and `--b-mates` say where each
part declares its side; the window and nominal come from the assembly's
declaration above the plate's, and the record goes to each part's manifest).
