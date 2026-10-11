"""A gyroid cube whose sheets are thinner than a printer can lay a line: about 0.33 mm of material,
against the 0.45 mm of one extrusion line of a 0.4 mm nozzle.

``frequency`` is the lattice's cycles per mm (0.5: a cell every 2 mm), ``sheet`` the field value that
bounds the material, which sets the sheet's thickness. The lattice is declared as a feature, so QC
attributes a thin sheet to it and names the line below. The voxel size is the project's setting
(``[engine.voxelcad]``), never the program's: it decides what the mesh can show.
"""
try:
    from agentcad.annotate import feature, suppress, print_pose
except ImportError:                       # without agentcad the annotations do nothing
    def feature(*args, **kwargs):
        pass
    suppress = print_pose = feature

from voxelcad import GyroidCube


def build(size=4.0, frequency=0.5, sheet=0.7):
    lattice = GyroidCube(size, center=True, lattice_param=[frequency] * 3, thresh1=-sheet, thresh2=sheet)
    reach = size / 2.0 + 0.5
    feature("lattice", box=(-reach, -reach, -reach, reach, reach, reach), kind="wall")
    return lattice
