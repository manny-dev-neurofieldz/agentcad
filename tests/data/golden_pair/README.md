# Golden pair: one real slice in both formats

`peg.bgcode` and `peg.gcode.gz` are the same slice written twice by PrusaSlicer 2.9.6 (headless, Linux):
the peg of `examples/peg_plate` (one copy), staged with `agentcad stage --target prusaslicer --copies 1`
on an Original Prusa MK4 Input Shaper 0.4 nozzle configuration (ASA, 0.2 mm layers), then sliced from that
one project with `prusa-slicer --export-gcode --binary-gcode` and `--no-binary-gcode`. The filament and
print profile names in the configuration were set to generic ones before slicing. The text file is gzipped
(`gzip -9n`) to keep the repository small; the tests unpack it.

`tests/test_gcode_golden_pair.py` says what is compared and what the binary format keeps differently.
