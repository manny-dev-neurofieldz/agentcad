"""How PrusaSlicer spells string settings in a configuration, read and written the same way everywhere.

A single string setting (start_gcode, printer_notes) is written bare, with its line breaks and backslashes escaped
and its quotes and tabs as they are. A list of strings (one item per extruder: filament_notes, filament_settings_id,
filament_type, ...) is written as its items joined by semicolons, each item quoted and escaped only when it needs to
be. Both are read the same way: \\n and \\r are a line feed and a carriage return, any other escaped character is
itself (\\t is the letter t, not a tab). Measured on PrusaSlicer 2.9.6, by loading a configuration and saving it
back, and by the start G-code a slice emitted:

    "first; with \\"quote\\"";"second\\\\path"   saved unchanged
    "a" ; "b"                                  saved as  a;b
    plain;"q\\x"                                saved as  plain;qx      (an unknown escape loses its backslash)
    "";"x"                                     saved as  ;x            (an empty item among others is bare)
    ""                                         saved as  ""            (one empty item, told from no items)
    (nothing)                                  saved as  (nothing)     (no items)
    "<tab>";"esc\\ttab"                        saved as  "<tab>";escttab   (a real tab quoted, kept raw)
    single: say \\"hi\\" tab\\there C:\\path     saved as  say "hi" tabthere C:path
    single: "; quoted whole"                   held with its quotes
    single: ends in a lone backslash           refused (Invalid value provided)
"""
from typing import List

_ESCAPES = {"n": "\n", "r": "\r"}
_WRITTEN = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r"}
_WRITTEN_SINGLE = {"\\": "\\\\", "\n": "\\n", "\r": "\\r"}

#: Settings PrusaSlicer keeps as a list of strings. A one-word value of one of these is written bare, so the base
#: configuration's spelling alone cannot tell such a setting from a single string.
STRING_LISTS = frozenset({
    "filament_settings_id", "filament_notes", "filament_type", "filament_vendor", "filament_colour",
    "extruder_colour", "filament_start_gcode", "filament_end_gcode", "filament_ramming_parameters",
    "compatible_printers", "compatible_prints"})

#: Settings PrusaSlicer keeps as one string (the G-code templates and the notes), as the golden pair's embedded
#: configuration writes them: bare, never as a list. Such a value that starts and ends with a quote holds those quotes.
SINGLE_STRINGS = frozenset({
    "start_gcode", "end_gcode", "before_layer_gcode", "layer_gcode", "toolchange_gcode", "between_objects_gcode",
    "color_change_gcode", "pause_print_gcode", "template_custom_gcode", "printer_notes", "notes"})


def unescape(text: str) -> str:
    """Backslash escapes read: \\n and \\r as their characters, any other escaped character (\\t included) as
    itself. A lone backslash at the very end is kept, not dropped."""
    out, i = [], 0
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text):
            out.append(_ESCAPES.get(text[i + 1], text[i + 1]))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def escape(text: str) -> str:
    """One item of a list of strings, escaped as the slicer escapes it inside quotes; a tab stays a tab."""
    return "".join(_WRITTEN.get(c, c) for c in text)


def escape_single(text: str) -> str:
    """A single string setting as the slicer writes it: line breaks and backslashes escaped, quotes and tabs as
    they are."""
    return "".join(_WRITTEN_SINGLE.get(c, c) for c in text)


def ends_in_lone_backslash(written: str) -> bool:
    """Whether a written value ends in a backslash that escapes nothing, which the slicer refuses to load."""
    return (len(written) - len(written.rstrip("\\"))) % 2 == 1


def split_list(written: str) -> List[str]:
    """The items of a list-of-strings value as the slicer writes it: separated by semicolons outside quotes, a
    quoted item unescaped, a bare one taken as written (space around it dropped). Nothing written is no items."""
    s = written.strip()
    if not s:
        return []
    items, cur, quoted, i = [], [], False, 0
    while i < len(s):
        c = s[i]
        if quoted:
            if c == "\\" and i + 1 < len(s):
                cur.append(c + s[i + 1])
                i += 2
                continue
            if c == '"':
                quoted = False
            cur.append(c)
        elif c == '"':
            quoted = True
            cur.append(c)
        elif c == ";":
            items.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    items.append("".join(cur))
    out = []
    for item in items:
        item = item.strip()
        out.append(unescape(item[1:-1]) if len(item) >= 2 and item[0] == item[-1] == '"' else item)
    return out


def _needs_quotes(item: str) -> bool:
    return any(c in item for c in ' ;"\\\n\r\t')


def join_list(items: List[str]) -> str:
    """Items written the way the slicer writes them: joined by semicolons, each quoted and escaped only when it
    needs to be; one empty item quoted so it reads apart from no items."""
    if len(items) == 1 and items[0] == "":
        return '""'
    return ";".join('"' + escape(i) + '"' if _needs_quotes(i) else i for i in items)


def is_string_list(key: str, written: str) -> bool:
    """Whether a setting is a list of strings: a key PrusaSlicer keeps as one, or a value written with a quoted
    item. A semicolon alone says nothing: a single string such as start_gcode carries G-code comments."""
    return key in STRING_LISTS or written.strip().startswith('"')
