"""Declarations read back from OpenSCAD's ECHO output.

OpenSCAD cannot import ``agentcad.annotate``, so an OpenSCAD program declares its features, its
suppressions and its print pose with ``echo`` statements whose arguments are the Python call's
keyword arguments, one to one::

    echo("AGENTCAD_QC", "feature", name="socket wall", box=[-6, -6, 0, 6, 6, 12], kind="wall",
         min_wall_mm=0.5, why="the beam is the spring", knobs=["wall=0.2"]);
    echo("AGENTCAD_QC", "suppress", rule="max_overhang", why="planned supports", box=[0, 0, 20, 30, 10, 22]);
    echo("AGENTCAD_QC", "pose", up=[0, -1, 0], spin_deg=0);          // or matrix=[[..], [..], [..]]

The engine takes the lines OpenSCAD prints for them from its standard error::

    ECHO: "AGENTCAD_QC", "feature", name = "socket wall", box = [-6, -6, 0, 6, 6, 12], kind = "wall", ...

This module finds those lines, reads their values and checks each declaration with the code a Python
program's calls go through (``agentcad.annotate``). What the lines look like is whatever OpenSCAD
prints, which this reads rather than assumes:

* a string is not escaped by OpenSCAD 2021.01 (newer releases print ``\\"`` and ``\\\\``), so a string
  ends at a quote followed by optional spaces and then ``,``, ``]`` or the end of the line, and both
  spellings of an embedded quote are read; a quote that looks like such an end cannot be told from
  one, which is why annotation strings keep to plain text;
* a number carries six significant digits (``123456789`` prints as ``1.23457e+8``);
* ``undef`` is None, and an argument given as ``undef`` counts as not passed;
* the echo carries no line number, so a record's ``line`` is None.
"""

import math
import re
from typing import Any, Dict, Iterable, List, Tuple

from agentcad import annotate

#: The first value of every declaration's echo.
MARKER = "AGENTCAD_QC"

_DECLARATION = re.compile(r'ECHO: "' + MARKER + r'"(?:,|\s*\Z)')
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?=\s*=)")
_TOKEN = re.compile(r"[^\s,\[\]]+")
_INTEGER = re.compile(r"[+-]?\d+\Z")
_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?\Z")
_STRING_END = re.compile(r"\s*(?:[,\]]|\Z)")
_WORDS = {"true": True, "false": False, "undef": None, "inf": math.inf, "+inf": math.inf, "-inf": -math.inf,
          "nan": math.nan, "+nan": math.nan, "-nan": math.nan}
_SHOWN = 240


class EchoError(ValueError):
    """A declaration line that cannot be read or is refused; the message names the line."""


def _say(problem: str, line: str) -> str:
    shown = line if len(line) <= _SHOWN else line[:_SHOWN] + "..."
    return f"{problem}, in: {shown}"


class _Reader:
    """A cursor over one line's text after ``ECHO: ``."""

    def __init__(self, line: str, text: str):
        self.line, self.text, self.pos = line, text, 0

    def fail(self, problem: str) -> EchoError:
        return EchoError(_say(f"{problem} (at character {self.pos + len('ECHO: ')})", self.line))

    def skip(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def peek(self) -> str:
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def value(self) -> Any:
        self.skip()
        c = self.peek()
        if c == '"':
            return self.string()
        if c == "[":
            return self.vector()
        match = _TOKEN.match(self.text, self.pos)
        if not match:
            raise self.fail("expected a value")
        token = match.group()
        if token in _WORDS:
            word = _WORDS[token]
        elif _INTEGER.match(token):
            word = int(token)
        elif _NUMBER.match(token):
            word = float(token)
        else:
            raise self.fail(f"{token!r} is not a value (a string, a number, a vector, true, false or undef)")
        self.pos = match.end()
        return word

    def string(self) -> str:
        text, i, out = self.text, self.pos + 1, []
        while i < len(text):
            c = text[i]
            if c == "\\" and i + 1 < len(text) and text[i + 1] in '"\\':
                out.append(text[i + 1])
                i += 2
            elif c == '"' and _STRING_END.match(text, i + 1):
                self.pos = i + 1
                return "".join(out)
            else:
                out.append(c)
                i += 1
        raise self.fail("unterminated string (no closing quote before the end of the line)")

    def vector(self) -> List[Any]:
        self.pos += 1
        out: List[Any] = []
        self.skip()
        if self.peek() == "]":
            self.pos += 1
            return out
        while True:
            out.append(self.value())
            self.skip()
            c = self.peek()
            if c == ",":
                self.pos += 1
            elif c == "]":
                self.pos += 1
                return out
            elif not c:
                raise self.fail("unterminated vector (no closing ])")
            else:
                raise self.fail(f"expected , or ] in a vector, not {c!r}")


def items(line: str) -> Tuple[List[Any], Dict[str, Any]]:
    """The values of an ECHO line: the positional ones in order, and the ``name = value`` ones by name.
    Strings, numbers (ints stay ints), vectors of values, true, false and undef (None) are read; any
    other text, or a name given twice, is an EchoError naming the line."""
    if not line.startswith("ECHO: "):
        raise EchoError(_say("not an ECHO line", line))
    reader = _Reader(line, line[len("ECHO: "):])
    positional: List[Any] = []
    named: Dict[str, Any] = {}
    while True:
        reader.skip()
        match = _NAME.match(reader.text, reader.pos)
        if match:
            name = match.group()
            reader.pos = match.end()
            reader.skip()
            reader.pos += 1                                   # the =
            if name in named:
                raise reader.fail(f"argument {name!r} given twice")
            named[name] = reader.value()
        else:
            positional.append(reader.value())
        reader.skip()
        if reader.pos >= len(reader.text):
            return positional, named
        if reader.peek() != ",":
            raise reader.fail("expected a comma between the values")
        reader.pos += 1


def parse(line: str) -> Tuple[str, Dict[str, Any]]:
    """A declaration line as its type (``feature``, ``suppress`` or ``pose``) and its keyword arguments.
    An argument given as undef is dropped, as if not passed; an unknown type or argument, a value given
    by position, or a missing required argument is an EchoError naming the line."""
    positional, named = items(line)
    if not positional or positional[0] != MARKER:
        raise EchoError(_say(f"the first value of a declaration is \"{MARKER}\"", line))
    if len(positional) < 2:
        raise EchoError(_say('a declaration needs a type: echo("' + MARKER + '", "feature", ...)', line))
    kind = positional[1]
    if not isinstance(kind, str):
        raise EchoError(_say(f"the declaration type must be a string such as \"feature\", not {kind!r}", line))
    if kind not in annotate.ARGUMENTS:
        raise EchoError(_say(f"unknown declaration {kind!r} (known: {', '.join(annotate.ARGUMENTS)})", line))
    if len(positional) > 2:
        raise EchoError(_say(f"unexpected value {positional[2]!r}: name its arguments, as in name = \"a\"", line))
    unknown = [k for k in named if k not in annotate.ARGUMENTS[kind]]
    if unknown:
        raise EchoError(_say(f"unknown argument {unknown[0]!r} for {kind} "
                             f"(known: {', '.join(annotate.ARGUMENTS[kind])})", line))
    kwargs = {k: v for k, v in named.items() if v is not None}
    for required in annotate.REQUIRED[kind]:
        if required not in kwargs:
            raise EchoError(_say(f"{kind} needs {required} = ...", line))
    return kind, kwargs


def is_declaration(line: str) -> bool:
    """Whether a line of OpenSCAD's standard error is a declaration: an ECHO whose first value is
    the marker. (A bare marker counts, so that a declaration missing its type is an error and not
    a silence.)"""
    return _DECLARATION.match(line) is not None


def declaration_lines(*stderr: str) -> List[str]:
    """The declaration lines in the given standard-error texts (one per OpenSCAD run), each distinct
    line once, in the order it first appeared. The same line repeats in every run, and again where
    OpenSCAD evaluates a module more than once; other ECHO lines are not declarations."""
    seen, found = set(), []
    for text in stderr:
        for line in (text or "").splitlines():
            if is_declaration(line) and line not in seen:
                seen.add(line)
                found.append(line)
    return found


def _declare(kind: str, kw: Dict[str, Any], where: Dict[str, Any], registry: List[Dict[str, Any]]) -> None:
    """Hand a parsed declaration to the validator its Python spelling uses."""
    if kind == "feature":
        annotate._feature(where, registry, kw["name"], kw["box"], kind=kw.get("kind", "feature"),
                          why=kw.get("why", ""), knobs=kw.get("knobs", ()),
                          limits={k: kw[k] for k in annotate.LIMIT_KEYS if k in kw})
    elif kind == "suppress":
        annotate._suppress(where, registry, kw["rule"], why=kw["why"], box=kw.get("box"))
    else:
        annotate._print_pose(where, registry, **{k: kw[k] for k in ("up", "spin_deg", "matrix") if k in kw})


def records(lines: Iterable[str], source: Any) -> List[Dict[str, Any]]:
    """The records ``agentcad.annotate.records()`` would hold for these declaration lines, each made
    at ``source`` (the OpenSCAD file; ECHO carries no line, so the line is None). A line that cannot be
    read, or that the validator refuses (a rule that does not exist, a reason missing, a feature
    declared twice), is an EchoError naming it. The records are a registry of their own: the Python
    registry is not touched."""
    where = {"file": str(source), "line": None}
    registry: List[Dict[str, Any]] = []
    for line in lines:
        kind, kwargs = parse(line)
        try:
            _declare(kind, kwargs, where, registry)
        except (ValueError, TypeError) as e:
            raise EchoError(_say(str(e), line)) from None
    return registry


def read(stderr: Iterable[str], source: Any) -> List[Dict[str, Any]]:
    """The records for every declaration in the standard-error texts of an engine's OpenSCAD runs."""
    return records(declaration_lines(*stderr), source)
