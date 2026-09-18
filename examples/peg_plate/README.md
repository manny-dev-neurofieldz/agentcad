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
middle hole with a 0.05 mm nominal gap); `agentcad fit` reads it with
`--mates-from examples/peg_plate` and records the result in the print
manifest with `--record`.
