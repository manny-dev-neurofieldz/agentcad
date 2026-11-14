"""A plate with a row of through holes, rebuilt from an original known only as a STEP file.

The defaults are the numbers the probes recovered from the original (WALKTHROUGH.md): its outline, the holes'
radius from a section, their pitch from the inventory's axes. They are parameters, so a revision changes a
relation, not a traced outline.
"""
from build123d import *


def build(length=60.0, width=20.0, thick=6.0, hole_d=5.0, pitch=15.0, n=3):
    plate = Box(length, width, thick)
    for i in range(n):
        plate -= Pos((i - (n - 1) / 2) * pitch, 0, 0) * Cylinder(hole_d / 2, thick + 2)
    return plate
