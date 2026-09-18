// A tray of hexagonal pockets for small parts. Plain OpenSCAD, no libraries.
cols = 4;
rows = 3;
across = 14;     // pocket across flats
depth = 10;
wall = 2;
floor_t = 2;
rim = 1;         // chamfer on the top edge

pitch_x = across + wall;
pitch_y = (across + wall) * 0.866;
size_x = cols * pitch_x + wall;
size_y = rows * pitch_y + across * 0.5 + wall;

module pocket() {
    cylinder(d = across / 0.866, h = depth + 1, $fn = 6);
}

difference() {
    hull() {
        cube([size_x, size_y, depth + floor_t - rim]);
        translate([rim, rim, 0]) cube([size_x - 2 * rim, size_y - 2 * rim, depth + floor_t]);
    }
    for (r = [0 : rows - 1]) for (c = [0 : cols - 1])
        translate([wall + across / 2 + c * pitch_x + (r % 2) * pitch_x / 2, wall + across / 2 + r * pitch_y, floor_t])
            pocket();
}
