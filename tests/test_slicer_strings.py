"""PrusaSlicer's spelling of string settings, pinned to what 2.9.6 saved when it loaded each spelling on the left."""
import pytest

from agentcad.gcode import check, slicer_strings as ss

#: (written, items): written is the spelling PrusaSlicer 2.9.6 saves for those items.
SAVED = [
    ('"first; with \\"quote\\"";"second\\\\path"', ['first; with "quote"', "second\\path"]),
    ("a;b", ["a", "b"]),
    ("plain;qx", ["plain", "qx"]),
    (";x", ["", "x"]),
    ('""', [""]),
    ("", []),
    ('"real\ttab";escttab;"q\\"z";"cr\\rx"', ["real\ttab", "escttab", 'q"z', "cr\rx"]),
]

#: (written, held): written is the spelling PrusaSlicer 2.9.6 saves for a single string setting holding ``held``
#: (start_gcode, notes, printer_notes); what it holds was read from the start G-code a real slice emitted.
SINGLE_SAVED = [
    ("line1\\nline2", "line1\nline2"),
    ('say "hi" and "esc"', 'say "hi" and "esc"'),
    ("C:\\\\path", "C:\\path"),
    ("real\ttab", "real\ttab"),
    ("cr\\rhere", "cr\rhere"),
    ('"; quoted whole"', '"; quoted whole"'),
    ("", ""),
]


@pytest.mark.parametrize("written,items", SAVED)
def test_a_list_reads_and_writes_the_way_the_slicer_saves_it(written, items):
    assert ss.split_list(written) == items
    assert ss.join_list(items) == written


@pytest.mark.parametrize("loaded,items", [('"a" ; "b"', ["a", "b"]), ('plain;"q\\x"', ["plain", "qx"]),
                                          ('"";"x"', ["", "x"])])
def test_a_list_written_loosely_reads_as_the_slicer_reads_it(loaded, items):
    """The slicer loaded these and saved them as the spellings above."""
    assert ss.split_list(loaded) == items


@pytest.mark.parametrize("written,held", SINGLE_SAVED)
def test_a_single_string_reads_and_writes_the_way_the_slicer_saves_it(written, held):
    assert ss.unescape(written) == held
    assert ss.escape_single(held) == written


@pytest.mark.parametrize("loaded,held", [("tab\\there", "tabthere"), ('say \\"esc\\"', 'say "esc"'),
                                         ("C:\\path", "C:path"), ("mid\\ space", "mid space"), ("x\\;y", "x;y")])
def test_a_single_string_written_loosely_reads_as_the_slicer_reads_it(loaded, held):
    """The slicer loaded these and held (and saved) the text on the right: an escape it does not know, \\t
    included, is the escaped character itself."""
    assert ss.unescape(loaded) == held


def test_a_lone_backslash_at_the_end_is_kept():
    assert ss.unescape("a\\") == "a\\" and ss.unescape("a\\nb") == "a\nb" and ss.unescape("\\x") == "x"


def test_a_semicolon_alone_does_not_make_a_list():
    assert not ss.is_string_list("start_gcode", "M17 ; enable steppers\\nG28")
    assert ss.is_string_list("filament_type", "ASA")                 # one word, written bare, still a list
    assert ss.is_string_list("some_future_list", '"a b";c')


def test_the_check_compares_an_asked_list_item_by_item():
    found = {"filament_notes": '"first; with \\"quote\\"";"second\\\\path"', "filament_type": "PLA;PETG"}
    asked = {"filament_notes": ['first; with "quote"', "second\\path"], "filament_type": ["PLA", "PETG"]}
    assert {f.key: f.severity for f in check.check(found, asked, "t")} == {"filament_notes": "ok", "filament_type": "ok"}
    assert check.check({"filament_type": "PLA;PETG"}, {"filament_type": ["PLA", "ASA"]}, "t")[0].severity == "error"
