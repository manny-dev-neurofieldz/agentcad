"""Gyroid mold: a bottle-shaped gyroid body with a solid base and neck, and
the negative mold around it.

Adapted from the VoxelCAD package's examples/gyroid_mold.py (Craig Wm. Versek,
MIT) to the agentcad build(**params) contract, with one addition: a thin
cylindrical skin unions with the lattice so the body is one connected solid
(the lattice alone is trimmed into loose slivers where the cylinder cuts it,
which the session report counts as extra solids).

Operations: intersection (body = cylinder & lattice), union (skin, base,
neck), difference (a window in the skin; mold = blank - model), translate.
"""
from voxelcad import Cube, Cylinder, GyroidCube


def build(body_r=2.5, body_h=6.0, base_h=1.0, neck_h=1.5, neck_r=1.0, skin=0.35, window=0.6,
          lattice=1.0, thresh1=0.75, thresh2=3.0, mold_r=3.5, mold=False):
    lattice_cube = GyroidCube(2 * body_r + 1, center=True, lattice_param=lattice,
                              thresh1=thresh1, thresh2=thresh2).translate([0, 0, body_h / 2.0])
    core = Cylinder(h=body_h, r=body_r) & lattice_cube
    shell = Cylinder(h=body_h, r=body_r) - Cylinder(h=body_h + 0.2, r=body_r - skin).translate([0, 0, -0.1])
    # two windows in the skin (a fraction of the height, one side) show the
    # lattice; the mullion between them keeps every lattice sliver tied
    half = body_r * 0.5
    for y in (-half / 2 - 0.2, half / 2 + 0.2):
        cut = Cube([body_r, half, body_h * window], center=True).translate([body_r, y, body_h / 2.0])
        shell = shell - cut
    body = core | shell
    base = Cylinder(h=base_h, r=body_r).translate([0, 0, body_h - 0.1])
    neck = Cylinder(h=neck_h, r=neck_r).translate([0, 0, body_h + base_h - 0.1])
    model = (base | neck) | body
    if not mold:
        return model
    mold_h = body_h + base_h + neck_h - 0.5
    return Cylinder(h=mold_h, r=mold_r) - model.translate([0, 0, -1.0])
