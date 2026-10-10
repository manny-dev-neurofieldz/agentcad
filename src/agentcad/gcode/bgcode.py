"""Reader for Prusa binary G-code (.bgcode), in pure Python.

The format, as published in the libbgcode specification (doc/specifications.md):
a 10-byte file header (magic ``GCDE``, version, checksum type), then blocks.
Each block is a header (type, compression, uncompressed size, and a
compressed size when compressed), a parameters field (2 bytes, or 6 for a
thumbnail), the payload, and a CRC32 over all three when the file declares
checksums. G-code blocks are usually heatshrink-compressed and MeatPack-
encoded; metadata blocks are INI text, often deflated.

This module is written from that specification and the published descriptions
of heatshrink and MeatPack; it does not translate libbgcode's code.
"""

import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple, Union

MAGIC = b"GCDE"
SUPPORTED_VERSIONS = (1,)

BLOCK_FILE_METADATA = 0
BLOCK_GCODE = 1
BLOCK_SLICER_METADATA = 2
BLOCK_PRINTER_METADATA = 3
BLOCK_PRINT_METADATA = 4
BLOCK_THUMBNAIL = 5
BLOCK_NAMES = {
    BLOCK_FILE_METADATA: "file_metadata", BLOCK_GCODE: "gcode", BLOCK_SLICER_METADATA: "slicer_metadata",
    BLOCK_PRINTER_METADATA: "printer_metadata", BLOCK_PRINT_METADATA: "print_metadata",
    BLOCK_THUMBNAIL: "thumbnail",
}

COMPRESSION_NONE, COMPRESSION_DEFLATE, COMPRESSION_HEATSHRINK_11_4, COMPRESSION_HEATSHRINK_12_4 = 0, 1, 2, 3
ENCODING_NONE, ENCODING_MEATPACK, ENCODING_MEATPACK_COMMENTS = 0, 1, 2
THUMBNAIL_FORMATS = {0: "png", 1: "jpg", 2: "qoi"}


class BGCodeError(ValueError):
    """A .bgcode file this reader cannot read. ``offset`` is the byte offset in the file, ``block`` the block
    index (None for the file header)."""

    def __init__(self, message: str, offset: int, block: Optional[int] = None):
        where = f"file header at byte {offset}" if block is None else f"block {block} at byte {offset}"
        super().__init__(f"{message} ({where})")
        self.offset = offset
        self.block = block


class BadMagic(BGCodeError):
    pass


class UnsupportedVersion(BGCodeError):
    pass


class UnknownCode(BGCodeError):
    """An unknown block type, compression or encoding code."""


class ChecksumMismatch(BGCodeError):
    pass


class TruncatedFile(BGCodeError):
    pass


@dataclass
class Block:
    index: int
    offset: int
    type: int
    compression: int
    uncompressed_size: int
    compressed_size: int
    params: bytes
    payload: bytes
    checksum_ok: Optional[bool]          # None when the file declares no checksums or verification was skipped

    @property
    def name(self) -> str:
        return BLOCK_NAMES.get(self.type, f"type_{self.type}")

    @property
    def encoding(self) -> int:
        return struct.unpack_from("<H", self.params, 0)[0]

    def data(self) -> bytes:
        """The payload decompressed (still MeatPack-encoded for G-code blocks)."""
        return decompress(self.payload, self.compression, self.uncompressed_size, self.index, self.offset)


@dataclass
class Thumbnail:
    format: str
    width: int
    height: int
    data: bytes


@dataclass
class BGCode:
    version: int
    checksum_type: int
    blocks: List[Block]
    metadata: Dict[str, Dict[str, str]] = field(default_factory=dict)

    def thumbnails(self) -> List[Thumbnail]:
        out = []
        for b in self.blocks:
            if b.type == BLOCK_THUMBNAIL:
                fmt, w, h = struct.unpack_from("<HHH", b.params, 0)
                out.append(Thumbnail(THUMBNAIL_FORMATS.get(fmt, f"format_{fmt}"), w, h, b.data()))
        return out

    def gcode(self) -> str:
        """The G-code text of all G-code blocks, decoded and joined."""
        decoder = MeatPackDecoder()
        parts = []
        packed = False
        for b in self.blocks:
            if b.type != BLOCK_GCODE:
                continue
            enc = b.encoding
            raw = b.data()
            if enc == ENCODING_NONE:
                parts.append(raw.decode("latin-1"))
            elif enc in (ENCODING_MEATPACK, ENCODING_MEATPACK_COMMENTS):
                parts.append(decoder.decode(raw))
                packed = True
            else:
                raise UnknownCode(f"unknown G-code encoding {enc}", b.offset, b.index)
        text = "".join(parts)
        # spaces are restored once over the whole text: a line may be split across two blocks
        return _respace(text) if packed and decoder.used_no_spaces else text


# --- reading -----------------------------------------------------------------------------------------------

def read_blocks(data: bytes, verify: bool = True) -> Tuple[int, int, Iterator[Block]]:
    """(version, checksum_type, block iterator) for the bytes of a .bgcode file."""
    if len(data) < 10:
        raise TruncatedFile("file is shorter than the 10-byte header", 0)
    if data[:4] != MAGIC:
        raise BadMagic(f"magic is {data[:4]!r}, expected {MAGIC!r}", 0)
    version, checksum_type = struct.unpack_from("<IH", data, 4)
    if version not in SUPPORTED_VERSIONS:
        raise UnsupportedVersion(f"version {version} is not supported (known: {SUPPORTED_VERSIONS})", 4)
    if checksum_type not in (0, 1):
        raise UnknownCode(f"unknown checksum type {checksum_type}", 8)

    def blocks() -> Iterator[Block]:
        off, i = 10, 0
        while off < len(data):
            if off + 8 > len(data):
                raise TruncatedFile("block header runs past the end of the file", off, i)
            btype, comp, usize = struct.unpack_from("<HHI", data, off)
            hsize = 8
            csize = usize
            if comp != COMPRESSION_NONE:
                if off + 12 > len(data):
                    raise TruncatedFile("block header runs past the end of the file", off, i)
                csize = struct.unpack_from("<I", data, off + 8)[0]
                hsize = 12
            if btype not in BLOCK_NAMES:
                raise UnknownCode(f"unknown block type {btype}", off, i)
            if comp not in (0, 1, 2, 3):
                raise UnknownCode(f"unknown compression {comp}", off, i)
            psize = 6 if btype == BLOCK_THUMBNAIL else 2
            pstart = off + hsize
            dstart = pstart + psize
            dend = dstart + csize
            cend = dend + (4 if checksum_type == 1 else 0)
            if cend > len(data):
                raise TruncatedFile(f"{BLOCK_NAMES[btype]} block needs {cend - off} bytes, "
                                    f"{len(data) - off} remain", off, i)
            ok = None
            if checksum_type == 1 and verify:
                stored = struct.unpack_from("<I", data, dend)[0]
                ok = (zlib.crc32(data[off:dend]) & 0xFFFFFFFF) == stored
                if not ok:
                    raise ChecksumMismatch(f"CRC32 mismatch in the {BLOCK_NAMES[btype]} block", off, i)
            yield Block(i, off, btype, comp, usize, csize, data[pstart:dstart], data[dstart:dend], ok)
            off, i = cend, i + 1

    return version, checksum_type, blocks()


def parse_ini(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def read(source: Union[str, Path, bytes], verify: bool = True) -> BGCode:
    """Parse a .bgcode file (path or bytes): header, every block, and the metadata blocks as key/value maps."""
    data = source if isinstance(source, (bytes, bytearray)) else Path(source).read_bytes()
    version, ctype, it = read_blocks(bytes(data), verify)
    blocks = list(it)
    meta: Dict[str, Dict[str, str]] = {}
    for b in blocks:
        if b.type in (BLOCK_FILE_METADATA, BLOCK_PRINTER_METADATA, BLOCK_PRINT_METADATA, BLOCK_SLICER_METADATA):
            if b.encoding != 0:
                raise UnknownCode(f"unknown metadata encoding {b.encoding}", b.offset, b.index)
            meta.setdefault(b.name, {}).update(parse_ini(b.data().decode("utf-8", errors="replace")))
    return BGCode(version, ctype, blocks, meta)


def is_bgcode(path: Union[str, Path]) -> bool:
    with open(path, "rb") as f:
        return f.read(4) == MAGIC


def gcode_text(path: Union[str, Path], verify: bool = True) -> str:
    """G-code text from a .bgcode or a plain G-code file (plain files pass through unchanged)."""
    if is_bgcode(path):
        return read(path, verify).gcode()
    return Path(path).read_text(encoding="utf-8", errors="replace")


# --- decompression -------------------------------------------------------------------------------------------

def decompress(payload: bytes, compression: int, expected_size: int, block: int = 0, offset: int = 0) -> bytes:
    if compression == COMPRESSION_NONE:
        out = payload
    elif compression == COMPRESSION_DEFLATE:
        try:
            out = zlib.decompress(payload)
        except zlib.error as e:
            raise BGCodeError(f"deflate stream is corrupt: {e}", offset, block) from e
    elif compression in (COMPRESSION_HEATSHRINK_11_4, COMPRESSION_HEATSHRINK_12_4):
        window = 11 if compression == COMPRESSION_HEATSHRINK_11_4 else 12
        out = heatshrink_decompress(payload, window, 4, expected_size)
    else:
        raise UnknownCode(f"unknown compression {compression}", offset, block)
    if len(out) != expected_size:
        raise BGCodeError(f"decompressed to {len(out)} bytes, the header says {expected_size}", offset, block)
    return out


def heatshrink_decompress(data: bytes, window_bits: int, lookahead_bits: int, expected_size: int) -> bytes:
    """Heatshrink: an LZSS bit stream, most significant bit first. A 1 bit is followed by an 8-bit literal; a 0
    bit by a back-reference: (index - 1) in window_bits bits, then (count - 1) in lookahead_bits bits, copying
    count bytes starting index bytes back in the output. The stream ends when the expected size is reached or
    the remaining bits cannot hold another token (padding)."""
    out = bytearray()
    nbits = len(data) * 8
    padded = bytes(data) + b"\x00\x00\x00\x00"

    def bits(pos: int, width: int) -> int:
        """width (<= 24) bits starting at bit pos, most significant bit first."""
        byte = pos >> 3
        chunk = int.from_bytes(padded[byte:byte + 4], "big")
        return (chunk >> (32 - (pos & 7) - width)) & ((1 << width) - 1)

    pos = 0
    lit_len = 9
    ref_len = 1 + window_bits + lookahead_bits
    lmask = (1 << lookahead_bits) - 1
    while len(out) < expected_size:
        if pos >= nbits:
            break
        if bits(pos, 1):
            if pos + lit_len > nbits:
                break
            out.append(bits(pos + 1, 8))
            pos += lit_len
        else:
            if pos + ref_len > nbits:
                break
            v = bits(pos + 1, window_bits + lookahead_bits)
            index = (v >> lookahead_bits) + 1
            count = (v & lmask) + 1
            if index > len(out):
                raise ValueError(f"heatshrink back-reference {index} bytes back with only {len(out)} written")
            start = len(out) - index
            for k in range(count):                       # byte by byte: a reference may overlap its own output
                out.append(out[start + k])
            pos += ref_len
    return bytes(out)


# --- MeatPack ------------------------------------------------------------------------------------------------

_SIGNAL = 0xFF
_CMD_ENABLE_PACKING, _CMD_DISABLE_PACKING = 251, 250
_CMD_ENABLE_NO_SPACES, _CMD_DISABLE_NO_SPACES = 247, 246
_CMD_RESET_ALL = 249
_TABLE = "0123456789. \nGX"                             # nibble 0..14; 0b1111 = a full-width character follows


class MeatPackDecoder:
    """MeatPack: two common G-code characters per byte (low nibble first), 0xF in a nibble meaning a full-width
    byte follows; two consecutive 0xFF bytes and a command byte switch packing and 'no spaces' mode (in which
    nibble 0b1011 means 'E' instead of a space, and spaces are dropped from command lines, so they are
    re-inserted before each parameter letter here). State persists across blocks of one file."""

    def __init__(self) -> None:
        self.packing = False
        self.no_spaces = False
        self.used_no_spaces = False

    def decode(self, data: bytes) -> str:
        out = bytearray()
        i, n = 0, len(data)
        pending_full = 0                                 # full-width bytes still owed to the current packed byte
        queue: List[int] = []                            # characters of the current packed byte, in order
        while i < n:
            b = data[i]
            if b == _SIGNAL and i + 2 < n + 1 and i + 1 < n and data[i + 1] == _SIGNAL and not pending_full:
                cmd = data[i + 2] if i + 2 < n else None
                if cmd == _CMD_ENABLE_PACKING:
                    self.packing = True
                elif cmd == _CMD_DISABLE_PACKING:
                    self.packing = False
                elif cmd == _CMD_ENABLE_NO_SPACES:
                    self.no_spaces = True
                    self.used_no_spaces = True
                elif cmd == _CMD_DISABLE_NO_SPACES:
                    self.no_spaces = False
                elif cmd == _CMD_RESET_ALL:
                    self.packing = False
                    self.no_spaces = False
                i += 3
                continue
            if not self.packing:
                out.append(b)
                i += 1
                continue
            lo, hi = b & 0x0F, (b >> 4) & 0x0F
            i += 1
            chars: List[Optional[int]] = []
            for nib in (lo, hi):
                if nib == 0x0F:
                    chars.append(None)                   # placeholder for a full-width byte
                else:
                    c = _TABLE[nib]
                    if nib == 0b1011 and self.no_spaces:
                        c = "E"
                    chars.append(ord(c))
            for c in chars:
                if c is None:
                    if i >= n:
                        break
                    out.append(data[i])
                    i += 1
                else:
                    out.append(c)
        return out.decode("latin-1")


_FREE_TEXT = ("M117", "M118", "M486")                  # their arguments are free text (messages, object names)


def _respace(text: str) -> str:
    """Re-insert the spaces 'no spaces' MeatPack removed from command lines: before a parameter letter that
    follows a number (G1X1.5Y2 -> G1 X1.5 Y2). Comments, quoted strings and the free-text arguments of
    M117/M118/M486 are left as they are. Blank lines are dropped (the encoding doubles some newlines)."""
    lines = []
    for line in text.split("\n"):
        if not line:
            continue
        if line.startswith(";"):
            lines.append(line)
            continue
        code, sep, comment = line.partition(";")
        rebuilt = []
        in_quote = False
        free = code.upper().startswith(_FREE_TEXT)
        for k, ch in enumerate(code):
            if ch == '"':
                in_quote = not in_quote
            elif (not in_quote and k > 0 and "A" <= ch <= "Z" and (code[k - 1].isdigit() or code[k - 1] == ".")
                  and not (free and rebuilt and " " in "".join(rebuilt).strip())):
                rebuilt.append(" ")
            rebuilt.append(ch)
        lines.append("".join(rebuilt) + (sep + comment if sep else ""))
    return "\n".join(lines) + ("\n" if lines else "")
