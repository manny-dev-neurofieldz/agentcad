"""Reading Prusa binary G-code: the container, each compression, MeatPack, and the named errors.

The fixtures are built here, byte by byte, from the published format: a heatshrink writer that emits
literals and one back-reference, and a MeatPack packer with 'no spaces' on. Real slicer output is
checked outside the suite (the decoded extrusion must match the file's own filament total).
"""
import struct
import subprocess
import sys
import zlib

import pytest

from agentcad.gcode import bgcode as bg

GCODE = (
    "; generated for a test\n"
    "M486 S0\n"
    "M486 Atest_part_X2.stl\n"
    'M862.3 P "MK4"\n'
    ";LAYER_CHANGE\n"
    ";Z:0.2\n"
    "G1 Z.2 F720\n"
    ";TYPE:Support material\n"
    "G1 X10.5 Y-3.25 E.0123\n"
    "G1 X11 Y-3 E.5\n"
    "M486 S-1\n"
)


# --- writers used only by the tests ------------------------------------------------------------------------

class _Bits:
    def __init__(self):
        self.bits = []

    def put(self, value, width):
        self.bits += [(value >> (width - 1 - k)) & 1 for k in range(width)]

    def bytes(self):
        b = self.bits + [0] * (-len(self.bits) % 8)
        return bytes(int("".join(map(str, b[i:i + 8])), 2) for i in range(0, len(b), 8))


def heatshrink(data, window_bits, repeat=None):
    """Literals for every byte; if ``repeat`` = (index, count) is given, the last ``count`` bytes are written
    as one back-reference instead (they must repeat the bytes ``index`` back)."""
    w = _Bits()
    lits = data if repeat is None else data[:-repeat[1]]
    for c in lits:
        w.put(1, 1)
        w.put(c, 8)
    if repeat:
        w.put(0, 1)
        w.put(repeat[0] - 1, window_bits)
        w.put(repeat[1] - 1, 4)
    return w.bytes()


_PACK = {c: i for i, c in enumerate("0123456789.E\nGX")}   # no-spaces table: 0b1011 is 'E'


def meatpack(text):
    """Packing and no-spaces on; command lines lose their spaces (comments, and lines with a quoted string,
    keep them, as the slicer's own output shows: M862.3 P "MK4" decodes with its space)."""
    out = bytearray(b"\xff\xff\xfb\xff\xff\xf7")
    stripped = "".join((ln if ln.startswith(";") or '"' in ln else ln.split(";")[0].replace(" ", "")) + "\n"
                       for ln in text.splitlines())
    chars = list(stripped)
    if len(chars) % 2:
        chars.append("\n")
    for a, b in zip(chars[0::2], chars[1::2]):
        na, nb = _PACK.get(a, 0xF), _PACK.get(b, 0xF)
        out.append(na | (nb << 4))
        for c, n in ((a, na), (b, nb)):
            if n == 0xF:
                out.append(ord(c))
    return bytes(out)


def block(btype, payload, compression=0, params=b"\x00\x00", usize=None):
    usize = len(payload) if usize is None else usize
    head = struct.pack("<HHI", btype, compression, usize)
    if compression:
        head += struct.pack("<I", len(payload))
    body = head + params + payload
    return body + struct.pack("<I", zlib.crc32(body) & 0xFFFFFFFF)


def bgcode_file(gcode_payload, gcode_compression, packed_size):
    meta = b"filament used [mm]=1.23\nestimated printing time (normal mode)=1m 2s\n"
    png = b"\x89PNG fake"
    return (b"GCDE" + struct.pack("<IH", 1, 1)
            + block(3, b"printer_model=MK4IS\n")
            + block(5, png, params=struct.pack("<HHH", 0, 16, 12))
            + block(4, zlib.compress(meta), 1, usize=len(meta))
            + block(2, b"temperature = 280\n")
            + block(1, gcode_payload, gcode_compression, params=b"\x02\x00", usize=packed_size))


def normalised(text):
    return [ln for ln in text.splitlines() if ln]


# --- tests --------------------------------------------------------------------------------------------------

def test_a_file_decodes_to_its_gcode_with_metadata_and_thumbnail():
    packed = meatpack(GCODE)
    f = bgcode_file(heatshrink(packed, 12), 3, len(packed))
    g = bg.read(f)
    assert normalised(g.gcode()) == normalised(GCODE)
    assert g.metadata["print_metadata"]["filament used [mm]"] == "1.23"
    assert g.metadata["slicer_metadata"]["temperature"] == "280"
    (t,) = g.thumbnails()
    assert (t.format, t.width, t.height, t.data[:4]) == ("png", 16, 12, b"\x89PNG")
    assert all(b.checksum_ok for b in g.blocks)


@pytest.mark.parametrize("compression", [0, 1, 2, 3])
def test_every_compression_code_round_trips(compression):
    data = b"G1X1Y2E.5\n" * 3
    if compression == 0:
        payload = data
    elif compression == 1:
        payload = zlib.compress(data)
    else:   # the last 16 bytes (the 4-bit lookahead's maximum) as one back-reference 10 back: an overlapping copy
        payload = heatshrink(data, 11 if compression == 2 else 12, repeat=(10, 16))
    assert bg.decompress(payload, compression, len(data)) == data


def test_errors_name_the_block_and_offset():
    packed = meatpack(GCODE)
    good = bgcode_file(heatshrink(packed, 12), 3, len(packed))
    corrupt = bytearray(good)
    corrupt[-6] ^= 0x01                        # one bit in the last (G-code) block's payload
    with pytest.raises(bg.ChecksumMismatch) as e:
        bg.read(bytes(corrupt))
    assert e.value.block == 4 and "block 4" in str(e.value)
    assert bg.read(bytes(corrupt), verify=False).blocks[4].checksum_ok is None
    with pytest.raises(bg.TruncatedFile):
        bg.read(good[:-10])
    with pytest.raises(bg.BadMagic):
        bg.read(b"GCDX" + good[4:])
    with pytest.raises(bg.UnsupportedVersion):
        bg.read(b"GCDE" + struct.pack("<I", 2) + good[8:])


def test_spaces_return_to_commands_but_not_to_quoted_or_free_text():
    text = bg._respace('G1X10.5Y-3.25E.0123\nM862.3P"MK4 IS"\nM486Apart_X2_MK4IS.stl\n;keep  THIS\n')
    assert text.splitlines() == ["G1 X10.5 Y-3.25 E.0123", 'M862.3 P"MK4 IS"', "M486 Apart_X2_MK4IS.stl",
                                 ";keep  THIS"]


def test_plain_gcode_passes_through(tmp_path):
    p = tmp_path / "plain.gcode"
    p.write_text(GCODE)
    assert bg.gcode_text(p) == GCODE


def test_cli_decode_and_info(tmp_path):
    packed = meatpack(GCODE)
    src = tmp_path / "t.bgcode"
    src.write_bytes(bgcode_file(heatshrink(packed, 12), 3, len(packed)))
    out = tmp_path / "t.gcode"
    run = [sys.executable, "-c", "import sys; from agentcad.cli import main; sys.exit(main())"]
    r = subprocess.run(run + ["gcode", "decode", str(src), "-o", str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert normalised(out.read_text()) == normalised(GCODE)
    r = subprocess.run(run + ["gcode", "info", str(src)], capture_output=True, text=True)
    assert "gcode x1" in r.stdout and "thumbnail png 16x12" in r.stdout and "printer_model = MK4IS" in r.stdout
