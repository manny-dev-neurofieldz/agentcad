# bracket_bosl2 (OpenSCAD + BOSL2)

An L-bracket: two rounded plates, a triangular gusset in the corner, and
two clearance holes in each leg, using BOSL2's `cuboid` rounding, `diff`
and `tag` for the holes, and `cyl` anchors.

What it exercises: BOSL2 attachments and rounding, the diff/tag idiom for
subtractions, top-level variables reachable by `-D leg=60`, and the
`[engine.openscad] fa/fs` facet settings.
