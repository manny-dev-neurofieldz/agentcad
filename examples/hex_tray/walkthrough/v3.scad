// A tray of hexagonal pockets for small parts. Plain OpenSCAD, no libraries.
cols = 4;
rows = 3;
across = 14;     // pocket across flats
depth = 10;
wall = 2;
floor_t = 2;
rim = 1;         // chamfer on the top edge

corner = across / cos(30);          // pocket across corners
pitch_x = across + wall;            // neighbours in a row meet flat to flat
pitch_y = pitch_x * cos(30);        // and so do neighbours in the next row
size_x = (cols - 1) * pitch_x + pitch_x / 2 + across + 2 * wall;   // odd rows sit half a pitch over
size_y = (rows - 1) * pitch_y + corner + 2 * wall;

module pocket() {
    rotate([0, 0, 30]) cylinder(d = corner, h = depth + 1, $fn = 6);   // flats facing along x
}

difference() {
    hull() {
        cube([size_x, size_y, depth + floor_t - rim]);
        translate([rim, rim, 0]) cube([size_x - 2 * rim, size_y - 2 * rim, depth + floor_t]);
    }
    for (r = [0 : rows - 1]) for (c = [0 : cols - 1])
        translate([wall + across / 2 + c * pitch_x + (r % 2) * pitch_x / 2, wall + corner / 2 + r * pitch_y, floor_t])
            pocket();
}
