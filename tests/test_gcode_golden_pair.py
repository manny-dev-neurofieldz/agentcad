"""One real slice in both of PrusaSlicer's formats: what the binary reader decodes is what the slicer wrote as text.

tests/data/golden_pair holds the peg of examples/peg_plate staged by the prusaslicer target and sliced by
PrusaSlicer 2.9.6 from that one project twice: ``peg.bgcode`` (binary_gcode on: heatshrink 12/4 blocks,
MeatPack keeping comments) and ``peg.gcode.gz`` (binary_gcode off, gzipped here to keep the repository small).
The synthetic fixtures of tests/gcode_fixtures.py prove each code path; this pair proves the reader against
the slicer that writes the files.

What the binary format keeps differently, and so what the comparison allows:
- a comment after a command (``M17 ; enable steppers``) is left out of the binary file's G-code;
- the header statistics and the configuration a text file writes as comments live in the binary file's
  metadata blocks instead, and are compared there.
"""
import gzip
import re
from pathlib import Path

import pytest

from agentcad.gcode import bgcode, sliced

DATA = Path(__file__).resolve().parent / "data" / "golden_pair"
BINARY = DATA / "peg.bgcode"

_SPACE = re.compile(r"\s+")


@pytest.fixture(scope="module")
def text_file(tmp_path_factory):
    path = tmp_path_factory.mktemp("golden_pair") / "peg.gcode"
    path.write_bytes(gzip.decompress((DATA / "peg.gcode.gz").read_bytes()))
    return path


def _lines(text):
    """Non-empty lines, trailing space dropped and runs of space made one."""
    return [_SPACE.sub(" ", line.rstrip()) for line in text.splitlines() if line.strip()]


def _commands(lines):
    return [c for c in (line.split(";", 1)[0].rstrip() for line in lines) if c]


def test_the_decoded_commands_are_the_text_files_commands_line_for_line(text_file):
    decoded, text = _lines(bgcode.gcode_text(BINARY)), _lines(text_file.read_text())
    assert len(_commands(decoded)) > 5000
    assert _commands(decoded) == _commands(text)


def test_every_comment_the_binary_file_keeps_is_the_text_files_in_the_same_order(text_file):
    decoded = [line for line in _lines(bgcode.gcode_text(BINARY)) if line.startswith(";")]
    text = iter(line for line in _lines(text_file.read_text()) if line.startswith(";"))
    assert len(decoded) > 300
    assert all(any(line == other for other in text) for line in decoded)    # an ordered subsequence


def test_the_text_files_configuration_comments_are_the_binary_files_metadata(text_file):
    text = text_file.read_text()
    meta = bgcode.read(BINARY).metadata
    held = {k: v for block in meta.values() for k, v in block.items()}
    pairs = re.findall(r"^; ([a-z][a-z0-9_]*) = (.+)$", text, flags=re.M)
    settings = [(k, v.strip()) for k, v in pairs                     # statistics (max_layer_z) are written differently
                if sliced.is_setting_key(k) and k not in ("binary_gcode", "prusaslicer_config")]
    assert len(settings) > 300
    assert [k for k, v in settings if held.get(k, "").strip() != v] == []
    assert held["binary_gcode"] == "1" and "; binary_gcode = 0" in text


@pytest.mark.parametrize("key", ["estimated printing time (normal mode)", "filament used [mm]", "filament used [g]"])
def test_the_metadata_states_what_the_text_files_trailer_states(text_file, key):
    stated = sliced.load(text_file).stated
    assert sliced.load(BINARY).stated[key] == stated[key]


def test_one_slice_summarizes_the_same_in_either_format(text_file):
    binary, text = (sliced.summary_record(sliced.load(p)) for p in (BINARY, text_file))
    assert binary == text
    assert binary["filament_used_stated_mm"] == pytest.approx(binary["filament_used"]["filament_mm"], rel=0.01)
    assert binary["filament_used"]["mass_g"] is not None
