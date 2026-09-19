# j_hook (build123d)

A pegboard J-hook: a 5 mm round section swept along a polyline path with
filleted corners, plus a chamfered peg that plugs the board.

What it exercises: `FilletPolyline`, a section placed on the path's start
plane, `sweep`, a union with a positioned cylinder, `chamfer` on a selected
edge group, and parameters for every dimension (`-D reach=40 -D wire_d=6`).
