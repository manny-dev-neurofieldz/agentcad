"""Pegboard J-hook: a round section swept along a bent, filleted path.

The path is a polyline (down the board, out, up into the hook) whose
corners are rounded, and a circle is swept along it; a short peg at the top
plugs a 6.35 mm board hole. Every dimension is a parameter.

Operations: FilletPolyline path, sweep of a planar section, union with a
cylinder, a chamfer on the peg tip.
"""
from build123d import *

try:
    from agentcad.annotate import suppress
except ImportError:                       # without agentcad the annotations are only comments
    def suppress(*args, **kwargs):
        pass


def build(wire_d=5.0, drop=25.0, reach=30.0, lip=12.0, bend_r=6.0, peg_d=6.2, peg_len=6.0):
    pts = [(0, 0, 0), (0, 0, -drop), (reach, 0, -drop), (reach, 0, -drop + lip)]
    path = Wire(FilletPolyline(*pts, radius=bend_r).edges())
    plane = Plane(origin=path.position_at(0), z_dir=path.tangent_at(0))
    section = plane * Circle(wire_d / 2)
    hook = sweep(section, path=path)
    peg = Pos(0, 0, peg_len / 2 - 0.5) * Cylinder(peg_d / 2, peg_len + 1)
    peg = chamfer(peg.edges().group_by(Axis.Z)[-1], min(1.0, peg_d / 4))
    # Printed as modelled, peg up. Two overhangs remain, both named: the round underside of the bend, and the
    # underside of the peg's collar where it meets the wire. Laying the hook on its side was tried and is worse.
    suppress("max_overhang", box=(-wire_d, -wire_d, -drop - wire_d, reach + wire_d, wire_d, -drop + bend_r),
             why="the round underside of the bend; printed with supports under the bend")
    suppress("max_overhang", box=(-peg_d / 2, -peg_d / 2, -1.5, peg_d / 2, peg_d / 2, 0),
             why="the peg's collar over the wire; a 0.6 mm ledge round the wire")
    return hook + peg
