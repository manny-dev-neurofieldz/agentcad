"""Gyroid electrode support plug: a flexible gyroid body, a tapered friction-fit
plug and a stem between them, as one voxel union.

Source: VoxelCAD's examples/gyroid_electrode_support_plug_conn.py (Craig Wm.
Versek, p-v-o-s / mechanical-CAD, MIT), a real part from the NeuroVEP
electrode work, re-authored to the agentcad build(**params) contract. The
original chose its own voxel size from a fixed 1024-cell resolution and
exported through the older distance-transform mesh; here the engine sizes the
grid from the model (``[engine.voxelcad] grid``) and both the renders and the
STL come from VoxelCAD's fused streaming pipeline (packed bits, Butterworth
low-pass, marching cubes, no intermediate volumes), with its knobs in the
project's ``[engine.voxelcad]`` table.

Operations: intersection (gyroid body = cylinder & lattice), union of four
components, tapered cylinders (r1 / r2), a translate chain. The lattice's two
thresholds set the wall thickness; ``nudge`` overlaps the stacked volumes so
the union is one solid.
"""
from voxelcad import Cylinder, GyroidCube


def build(body_h=5.0, body_r=3.0, lattice=1.0, wall=0.35,
          plug_d=3.05, plug_len=12.5, taper_h=1.0, taper_step=0.5,
          stem_h=None, nudge=0.06):
    plug_r = plug_d / 2.0
    stem_h = body_h / 2.0 if stem_h is None else stem_h
    plug_h = plug_len - taper_h
    # the gyroid lattice, centred on X and Y, trimmed to the body's cylinder
    cube = GyroidCube(2 * body_r, center=True, lattice_param=lattice,
                      thresh1=-wall, thresh2=wall).translate([0, 0, body_r])
    body = Cylinder(h=body_h, r=body_r) & cube
    # a stem widening into the plug ties the lattice to it
    stem = Cylinder(h=stem_h, r1=plug_r / 2.0, r2=plug_r).translate([0, 0, body_h / 2.0 + nudge])
    plug = Cylinder(h=plug_h, r=plug_r).translate([0, 0, body_h])
    taper = Cylinder(h=taper_h, r1=plug_r, r2=plug_r - taper_step).translate([0, 0, body_h + plug_h - nudge])
    return taper | plug | stem | body
