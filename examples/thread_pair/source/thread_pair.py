"""An M6 bolt and nut with printed ISO threads, side by side.

The bolt is a shank fused with an external thread; the nut is a hex body
bored under the thread's major diameter so the internal thread fuses to it.
Two separate bodies are the design, so the project sets expected_solids = 2
and the session report does not warn about them.

Operations: bd_warehouse IsoThread (external and internal), Cylinder,
RegularPolygon extrude, boolean difference and union, chamfers.
"""
from build123d import *
from bd_warehouse.thread import IsoThread


def build(major=6.0, pitch=1.0, length=14.0, head_af=10.0, head_h=4.0, nut_af=10.0, nut_h=5.0, gap=4.0, clearance=0.15):
    ext = IsoThread(major_diameter=major - clearance, pitch=pitch, length=length, external=True,
                    end_finishes=("chamfer", "fade"))
    shank = Cylinder(ext.min_radius, length, align=(Align.CENTER, Align.CENTER, Align.MIN))
    head = Pos(0, 0, -head_h) * extrude(RegularPolygon(head_af / 2 / 0.866, 6), head_h)
    head = chamfer(head.edges().group_by(Axis.Z)[0], 0.6)
    bolt = shank + ext + head

    nut_body = extrude(RegularPolygon(nut_af / 2 / 0.866, 6), nut_h)
    nut_body = chamfer(nut_body.edges().filter_by(Plane.XY), 0.5)
    bore = Cylinder(major / 2 - 0.1, nut_h + 2, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(Pos(0, 0, -1))
    inner = IsoThread(major_diameter=major + clearance, pitch=pitch, length=nut_h, external=False,
                      end_finishes=("fade", "fade"))
    nut = (nut_body - bore) + inner
    nut = Pos(major + nut_af / 2 + gap, 0, 0) * nut
    return Compound(children=[bolt, nut])
