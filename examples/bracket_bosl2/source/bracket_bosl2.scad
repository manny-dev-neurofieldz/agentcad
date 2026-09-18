// L-bracket with rounded edges, a gusset and countersunk screw holes (BOSL2).
// Every dimension is a top-level variable so -D overrides reach it.
include <BOSL2/std.scad>

leg = 40;        // length of each leg
width = 25;      // bracket width
thick = 4;       // wall thickness
round_r = 2;     // edge rounding
hole_d = 4.5;    // screw clearance
gusset = 12;     // gusset size

module leg_plate(len) {
    cuboid([len, width, thick], rounding=round_r, edges="Z", anchor=BOTTOM+LEFT);
}

diff("holes")
union() {
    leg_plate(leg);
    up(thick) yrot(-90) leg_plate(leg);
    // gusset in the corner
    translate([thick, -thick / 2, thick])
        rotate([90, 0, 0]) linear_extrude(thick) polygon([[0, 0], [gusset, 0], [0, gusset]]);
    tag("holes") {
        for (x = [leg * 0.5, leg * 0.8]) translate([x, 0, thick]) cyl(d=hole_d, h=thick * 3, anchor=TOP);
        for (z = [leg * 0.5, leg * 0.8]) translate([thick, 0, z]) yrot(-90) cyl(d=hole_d, h=thick * 3, anchor=BOTTOM);
    }
}
