# gyroid_mold (VoxelCAD)

A bottle-shaped gyroid lattice with a solid base and neck, and, with
`-D mold=true`, the negative mold around it. Adapted from the VoxelCAD
package's `examples/gyroid_mold.py`.

What it exercises: voxel booleans (intersection, union, difference), a
translate chain, a lattice primitive with two thresholds, and the grid
target (`[engine.voxelcad] grid`) sizing the build from the model's extent.

Try: `agentcad render examples/gyroid_mold/source/gyroid_mold.py --report`
and again with `-D mold=true`.

The skin around the lattice makes the body one printable solid except for
one lattice sliver behind the windows, which the session report counts
(`expected_solids = 2` in the project's config records that rather than
hiding it). Closing it, by moving or narrowing the windows, is the exercise.
