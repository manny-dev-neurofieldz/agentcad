// A 30 x 8 x 20 plate standing on its edge, with a pin hole through its thickness (along y).
//
// teardrop = false: the hole is round. The facets of its roof face down at up to 84 degrees from
//   vertical, past the 45 degree limit of an FDM printer, so QC reads them as an overhang and
//   attributes it to the "pin hole" feature declared below.
// teardrop = true: the hole's upper half is a house shape: vertical walls, then two flats rising
//   at 45 degrees to meet over the hole. The flats sit exactly at the limit, on whole-number
//   coordinates, so the mesh states their angle exactly and QC passes them.
teardrop = false;

// OpenSCAD cannot import agentcad, so the feature is declared with echo; the engine reads the line
// back from the output. The box is in the part's own frame (x0, y0, z0, x1, y1, z1).
echo("AGENTCAD_QC", "feature", name="pin hole", box=[9, -1, 6, 21, 9, 19], kind="hole",
     why="a pin runs through it");

difference() {
    cube([30, 8, 20]);
    translate([15, 9, 10]) rotate([90, 0, 0]) linear_extrude(10)
        union() {
            circle(r=4, $fn=32);
            if (teardrop) polygon([[-4, 0], [4, 0], [4, 4], [0, 8], [-4, 4]]);
        }
}
