# thread_pair (build123d)

An M6 bolt and its nut with printed ISO threads from `bd_warehouse`, laid
side by side for one print plate. Two bodies are the design, so
`[engine.build123d] expected_solids = 2` keeps the report quiet about them.

What it exercises: external and internal `IsoThread`, a hex head and nut
from `RegularPolygon`, a bore under the major diameter so the internal
thread fuses, chamfers on selected edges, a `Compound` of two parts, and the
clearance knob a printed thread needs (`-D clearance=0.25`).
