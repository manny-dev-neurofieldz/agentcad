# gyroid_support_plug (VoxelCAD)

A flexible gyroid body, a tapered friction-fit plug and a stem between them,
built as one voxel union. Adapted from the VoxelCAD package's
`examples/gyroid_electrode_support_plug_conn.py` (Craig Wm. Versek,
p-v-o-s / mechanical-CAD, MIT), a real part from the NeuroVEP electrode work.

What it exercises: intersection (gyroid body = cylinder & lattice), a union of
four components, tapered cylinders (`r1` / `r2`), a translate chain, and the
surface pipeline settings in `[engine.voxelcad]`: `surface_method =
"fast_smooth"` is VoxelCAD's fused streaming pipeline (packed bits through a
Butterworth low-pass into marching cubes and straight to STL, no intermediate
volumes), used for the renders and the export alike so the picture is the
file; `lowpass_cutoff` is raised from 0.25 to 0.35 because the lattice walls
are a few voxels wide at this grid. The session record's `surface` block says
which pipeline ran, with the triangle count and time.

Try: `agentcad render examples/gyroid_support_plug/source/gyroid_support_plug.py --report`,
then `-D wall=0.2 -D lattice=0.75` (the original's thinner lattice): the
report counts the loose slivers a cylinder leaves when it trims a thin
lattice, ten of them, which the original hid at export with
`only_largest_component`. A thicker wall and a coarser lattice make the body
one solid; that is the exercise, and `expected_solids = 1` holds it.
