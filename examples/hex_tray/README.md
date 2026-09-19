# hex_tray (OpenSCAD)

A tray of hexagonal pockets for small parts: nested loops place staggered
hex pockets, a hull chamfers the rim, and a difference cuts them from the
block. No libraries.

What it exercises: plain CSG (`difference`, `hull`), `$fn = 6` hexagons,
loops with a stagger, and derived dimensions from a few top-level variables.
