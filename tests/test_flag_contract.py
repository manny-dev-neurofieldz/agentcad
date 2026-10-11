"""Every flag of a command that reads more than one kind of input does something on each kind it reads.

A flag that does nothing on some kind of input, and says nothing, passes every test written for the input it
was made for. ``probe section --arcs`` printed no arcs for an STL and exited 0; ``gcode check`` read a
``[slice.prusaslicer]`` table as one setting and never compared ``[print]``. Both had tests, for the inputs
their authors had in mind.

So each command that reads more than one kind of input is listed here with those kinds, and every flag with
what it does on each of them:

* CHANGES: the run's result (exit status, stdout, the files it writes) differs from the same run without the
  flag; a cell may also name a text the run must print (``shows``) or the exit status it must end with;
* REFUSES: the run exits non-zero with a message on stderr that names the flag;
* SAYS: the run's result is what it is without the flag, and stderr names the flag (ignored, and why);
* Same(why): the run's result is what it is without the flag, for the reason the cell gives.

A cell may run its flag together with others (``needs``); it is then compared with the run of those others
alone. Every run gets a fresh copy of the fixtures, and the run without the flag is made twice: a result that
differs between two identical runs could pass for an effect, so it fails instead.

Two walls keep the table whole. Every flag of a listed command has a cell (a new flag fails here until its
cell says what it does), and every command is either listed or exempt with a reason; the exempt list may only
shrink.
"""

import argparse
import contextlib
import hashlib
import io
import os
import re
import shutil
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple
from unittest import mock

import pytest

from agentcad import cli
from agentcad.engines import get_engine, list_engines
from tests import gcode_fixtures as gf

B3D = "build123d" in list_engines() and get_engine("build123d").available()

CHANGES, REFUSES, SAYS = "changes", "refuses", "says"


@dataclass(frozen=True)
class Same:
    why: str


@dataclass(frozen=True)
class Cell:
    """A flag on a command: ``argv`` adds it with its value; ``needs`` is carried by both runs; ``outcome``
    holds for every kind, or is a {kind: outcome} map; ``shows`` is a text the flagged run must print and
    ``exit`` the status it must end with (default: the status of the run without the flag)."""
    flag: str
    argv: Tuple[str, ...]
    outcome: object
    needs: Tuple[str, ...] = ()
    shows: Optional[str] = None
    exit: Optional[int] = None

    def on(self, kind):
        return self.outcome[kind] if isinstance(self.outcome, dict) else self.outcome


@dataclass(frozen=True)
class Command:
    path: Tuple[str, ...]
    kinds: Dict[str, Tuple[str, ...]]               # kind -> the input words, paths under {D}
    cells: Tuple[Cell, ...]
    base: Tuple[str, ...] = ()                      # words every run carries after the inputs
    refused: Tuple[Tuple[str, Tuple[str, ...], str], ...] = ()   # (kind, inputs, a word the refusal names)
    geometry: bool = False                          # needs the build123d backend

    @property
    def name(self):
        return " ".join(self.path)


# --- fixtures: every kind of input, written once per session and copied for every run ---------------------

BLOCK = (
    "from math import cos, pi, sin\n"
    "from build123d import *\n"
    "\n"
    "def build(bore=10.0, length=40.0):\n"
    "    part = Box(length, 30, 20) - Pos(5, 0, 0) * Cylinder(bore / 2, 30)\n"
    "    part = fillet(part.edges().group_by(Axis.Z)[-1].filter_by(GeomType.LINE), radius=2)\n"
    "    with BuildSketch(Plane.XY.offset(10)) as pocket:\n"
    "        with BuildLine():\n"
    "            Line((-14, -3), (-6, -3))\n"
    "            ThreePointArc((-6, -3), (-3, 0), (-6, 3))\n"
    "            Line((-6, 3), (-14, 2.2))\n"
    "            Line((-14, 2.2), (-14, -3))\n"
    "        make_face()\n"
    "    part -= extrude(pocket.sketch, amount=-3)\n"
    "    ring = [((3.02, 3.0)[i % 2] * cos(pi * i / 12), (3.02, 3.0)[i % 2] * sin(pi * i / 12)) for i in range(24)]\n"
    "    return part - Pos(-12, 9, 0) * extrude(Polygon(*ring, align=None), amount=15, both=True)\n"
)
"""A 40 x 30 x 20 block (z -10..10) with a through bore of `bore` at x 5, its top edges rounded; a pocket 3 mm
deep at the top whose outline joins an arc of r 3 to a line 0.015 mm off tangent; and a through hole at
(-12, 9) whose 24 straight sides alternate between radii 3.02 and 3.0. z=mid cuts three loops (outer, bore,
the polygon, whose vertices fit one arc only at a tolerance over 0.01 mm); z=8.5 cuts the pocket, whose joint
is judged not tangent at the default tolerance."""

FILLETS = (
    "from build123d import *\n"
    "\n"
    "def build(r=1.0):\n"
    "    part = Box(20, 20, 10)\n"
    "    part = fillet(part.edges().filter_by(Axis.Z), radius=r)\n"
    "    part = chamfer(part.edges().group_by(Axis.Z)[-1], length=0.5)\n"
    "    part = fillet(part.edges().group_by(Axis.Z)[0], radius=0.5)\n"
    "    return part\n"
)

PLATE = (
    "from build123d import *\n"
    "\n"
    "def build(hole=2.0):\n"
    "    part = Box(40, 20, 6)\n"
    "    corner = part.edges().filter_by(Axis.Z).filter_by(lambda e: e.center().X > 19 and e.center().Y > 9)\n"
    "    return fillet(corner, 4) - Pos(10, 5, 0) * Cylinder(hole, 10)\n"
)
"""The solid the synthetic design dump's first sketch describes (tests/test_probe_recover.py)."""

SLOT = ("from build123d import *\n\ndef build(width=6.2):\n"
        "    return Box(20, 20, 10) - Pos(0, 0, 2.5) * Box(width, 30, 5)\n")
KEY = "from build123d import *\n\ndef build(width=6.0):\n    return Box(10, width, 4)\n"
MATES_SLOT = ('[mates.key_in_slot]\ncounterpart = "key"\n'
              'nominal_mm = {nominal}\nwindow = [-3.6, -4, 0.5, 3.6, 4, 3.5]\n'
              '[mates.key_in_slot.axis]\npoint = [0, 0, 0]\ndirection = [0, 0, 1]\n'
              '[mates.key_in_slot.key_line]\npoint = [0, 0, 0]\ndirection = [1, 0, 0]\n'
              '[mates.key_in_slot.rim_plane]\npoint = [0, 0, 0]\nnormal = [0, 0, 1]\n')
MATES_KEY = ('[mates.key_in_slot]\ncounterpart = "slot"\n'
             '[mates.key_in_slot.axis]\npoint = [0, 0, 0]\ndirection = [0, 0, 1]\n'
             '[mates.key_in_slot.key_line]\npoint = [0, 0, 0]\ndirection = [0, 1, 0]\n'
             '[mates.key_in_slot.rim_plane]\npoint = [0, 0, -2]\nnormal = [0, 0, -1]\n')
MATES_KEY_AWAY = MATES_KEY.replace("point = [0, 0, -2]", "point = [0, 0, -1]")


def _write_geometry(root: Path):
    from build123d import export_step, export_stl
    from agentcad import probe

    def program(rel, text, step=True, stl=False):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        shape = probe.load_shape(path) if (step or stl) else None
        if step:
            export_step(shape, str(path.with_suffix(".step")))
        if stl:
            export_stl(shape, str(path.with_suffix(".stl")), tolerance=0.01, angular_tolerance=0.2)

    program("block.py", BLOCK, stl=True)
    program("fillets.py", FILLETS, step=True)
    program("plate.py", PLATE)
    program("slot/source/slot.py", SLOT)
    program("key/source/key.py", KEY)
    (root / "slot" / "agentcad.toml").write_text(MATES_SLOT.format(nominal=0.1))
    (root / "key" / "part.toml").write_text(MATES_KEY)
    (root / "alt_slot").mkdir()
    (root / "alt_slot" / "agentcad.toml").write_text(MATES_SLOT.format(nominal=0.5))
    (root / "alt_key").mkdir()
    (root / "alt_key" / "part.toml").write_text(MATES_KEY_AWAY)
    from agentcad.manifest import PrintManifest
    (root / "slot" / "exports").mkdir()
    PrintManifest(part_name="slot", project_name="slot").save(root / "slot" / "exports" / "slot.print.json")
    shutil.copy(Path(__file__).parent / "data" / "design_dump_synthetic.json", root / "dump.json")


def _crc_broken(data: bytes) -> bytes:
    """The .bgcode with the last byte of its last block's CRC flipped."""
    return data[:-1] + bytes([data[-1] ^ 0xFF])


SETTINGS_MANY_A = {f"zz_setting_{i:02d}": "1" for i in range(30)}
SETTINGS_MANY_B = {f"zz_setting_{i:02d}": "2" for i in range(30)}


def _write_sliced(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    (root / "a.gcode").write_text(gf.BODY_A + gf.trailer(gf.TIME_A, gf.FILAMENT_A, dict(gf.CONFIG_A, **SETTINGS_MANY_A),
                                                         gf.GRAMS_A, 1.0))
    (root / "b.gcode").write_text(gf.BODY_B + gf.trailer(gf.TIME_B, gf.FILAMENT_B, dict(gf.CONFIG_B, **SETTINGS_MANY_B),
                                                         gf.GRAMS_B, 0.9))
    a_bg = gf.bgcode_bytes(gf.BODY_A, dict(gf.CONFIG_A, **SETTINGS_MANY_A), gf.TIME_A, gf.FILAMENT_A, gf.GRAMS_A)
    (root / "a.bgcode").write_bytes(a_bg)
    (root / "b.bgcode").write_bytes(gf.bgcode_bytes(gf.BODY_B, dict(gf.CONFIG_B, **SETTINGS_MANY_B), gf.TIME_B,
                                                    gf.FILAMENT_B, gf.GRAMS_B))
    (root / "a_badcrc.bgcode").write_bytes(_crc_broken(a_bg))
    # intent in each shape a reader meets: a project's flat [slice], a job's [print], a job's [slice.<target>]
    (root / "proj").mkdir()
    (root / "proj" / "agentcad.toml").write_text('[project]\nname = "proj"\n\n[slice]\nlayer_height = 0.2\n')
    (root / "job_print.toml").write_text('[print]\nlayer_height = 0.2\n')
    (root / "job_native.toml").write_text('[slice.prusaslicer]\nfill_density = "15%"\n')
    # a placement naming slice A's peg, its STL kept apart from the sidecar so --stl-root has work to do
    (root / "stls").mkdir()
    _write_box_stl(root / "stls" / "peg.stl", (0, 0, 0), (60, 60, 2))
    (root / "plate.placement.json").write_text(
        '{"schema": "agentcad.placement/1", "objects": [{"name": "peg.stl", "stl": "peg.stl", '
        '"instances": [{"label": "peg.stl", "bed_offset": [0, 0, 0]}]}]}')


def _write_box_stl(path: Path, lo, hi):
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7),
             (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    with open(path, "wb") as fh:
        fh.write(b"\0" * 80 + struct.pack("<I", len(faces)))
        for f in faces:
            fh.write(struct.pack("<12fH", 0, 0, 0, *[c for i in f for c in v[i]], 0))


def _write_records(root: Path):
    shutil.copytree(Path(__file__).parent / "data" / "records_library", root / "lib")


@pytest.fixture(scope="session")
def fixtures(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("flag_contract_inputs")
    if B3D:
        _write_geometry(root)
    _write_sliced(root)
    _write_records(root)
    return root


# --- running a command the way the CLI runs it --------------------------------------------------------------

@dataclass
class Run:
    code: object
    out: str
    err: str
    files: Dict[str, str]
    crash: Optional[str] = None

    def result(self):
        return self.code, self.out, tuple(sorted(self.files.items()))


def _content(path: Path, d: Path) -> str:
    """A file as the result sees it: text with the run's folder named <D>, an image by its presence (a render
    may carry a timestamp), other bytes by their digest."""
    if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".qoi"):
        return "image"
    data = path.read_bytes()
    try:
        return data.decode("utf-8").replace(str(d), "<D>")
    except UnicodeDecodeError:
        return "sha256:" + hashlib.sha256(data).hexdigest()


def _snapshot(d: Path) -> Dict[str, str]:
    return {str(p.relative_to(d)): _content(p, d) for p in sorted(d.rglob("*")) if p.is_file()}


def _no_render(*args, **kwargs):
    return {}


def _stub_png(out, *args, **kwargs):
    Path(out).write_bytes(b"\x89PNG stub")


_RUNS = [0]


def run(fixtures: Path, scratch: Path, words) -> Run:
    """``agentcad <words>`` in-process, in a fresh copy of the fixtures ({D} in the words is that copy), with
    the renderers that need a display replaced by stubs that write their file."""
    _RUNS[0] += 1
    d = scratch / f"run{_RUNS[0]:05d}"
    shutil.copytree(fixtures, d)
    before = _snapshot(d)
    argv = [str(w).replace("{D}", str(d)) for w in words]
    out, err = io.StringIO(), io.StringIO()
    code, crash = 0, None
    cwd = os.getcwd()
    os.chdir(d)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch("agentcad.fit._render_pair", _no_render), mock.patch("agentcad.cli._supports_png", _stub_png):
            cli.main(argv)
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except Exception as e:                              # a traceback is never an answer: it fails every outcome
        crash, code = f"{type(e).__name__}: {e}", "crash"
    finally:
        os.chdir(cwd)
    after = _snapshot(d)
    files = {k: v for k, v in after.items() if before.get(k) != v}
    shutil.rmtree(d, ignore_errors=True)
    norm = str(d)
    return Run(code, out.getvalue().replace(norm, "<D>"), err.getvalue().replace(norm, "<D>"), files, crash)


def _command_parser(path):
    parser = cli.build_parser()
    for word in path:
        parser = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction)).choices[word]
    return parser


def _options(path, flag):
    """Every spelling of ``flag`` on the command at ``path`` (``--define`` -> ("-D", "--define"))."""
    for action in _command_parser(path)._actions:
        if flag in action.option_strings:
            return tuple(action.option_strings)
    raise KeyError(f"{' '.join(path)} has no {flag}")


def _names(text, options):
    return any(re.search(r"(?<![\w-])" + re.escape(o) + r"(?![\w-])", text) for o in options)


def _echo(options):
    """A pattern for the flag's own name followed by a number: ``fit-tol 2 mm``, ``"fit_tol": 2.0``."""
    names = {o.lstrip("-") for o in options if len(o.lstrip("-")) > 1}
    names |= {n.replace("-", "_") for n in names}
    if not names:
        return None
    alt = "|".join(sorted(map(re.escape, names), key=len, reverse=True))
    return re.compile(r"(?<![\w-])(" + alt + r")([\"']?\s*[:=]?\s*)(-?\d[\d.]*(?:[eE][-+]?\d+)?)")


def _view(r: "Run", options, echo):
    """What a run says once the lines that merely name the flag are set aside and, when the run echoes the
    flag's value, every number after the flag's name is masked: a flag that prints itself back has not, by
    that alone, changed anything."""
    def mask(text):
        return echo.sub(r"\1\2<v>", text) if echo is not None else text
    out = "\n".join(line for line in r.out.splitlines() if not _names(line, options))
    return r.code, mask(out), tuple(sorted((k, mask(v)) for k, v in r.files.items()))


def _echoes(r: "Run", pattern, value) -> bool:
    if pattern is None or value is None:
        return False
    try:
        want = float(value)
    except ValueError:
        return False
    texts = [r.out, r.err, *r.files.values()]
    return any(float(m.group(3)) == want for t in texts for m in pattern.finditer(t) if m.group(3).strip("-."))


# --- the table --------------------------------------------------------------------------------------------

GEOMETRY = {"program": ("{D}/block.py",), "step": ("{D}/block.step",), "stl": ("{D}/block.stl",)}
EXACT = {k: v for k, v in GEOMETRY.items() if k != "stl"}
EXACT_ONLY = {"program": CHANGES, "step": SAYS, "stl": SAYS}     # -D: a program's parameters; a file has none
STL_ONLY = {"program": SAYS, "step": SAYS, "stl": CHANGES}
SLICED_A = {"gcode": ("{D}/a.gcode",), "bgcode": ("{D}/a.bgcode",)}

COMMANDS = (
    Command(("probe", "section"), GEOMETRY, geometry=True, cells=(
        Cell("--planes", ("--planes", "y=0"), CHANGES),
        Cell("--max-loops", ("--max-loops", "1"), CHANGES),
        Cell("--show", ("--show", "0"), CHANGES),
        Cell("--output", ("-o", "{D}/loops.json"), CHANGES),
        Cell("--define", ("-D", "bore=6"), EXACT_ONLY),
        Cell("--axis", ("--axis", "x"), STL_ONLY),
        Cell("--axis-center", ("--axis-center", "3,0"), STL_ONLY),
        Cell("--arcs", ("--arcs",), CHANGES, shows="arc"),
        Cell("--chain", ("--chain", "1"), CHANGES, shows="LOOP"),
        Cell("--min-len", ("--min-len", "35"), CHANGES, needs=("--chain", "1")),
        Cell("--min-len", ("--min-len", "1"), SAYS),
        Cell("--min-len", ("--min-len", "1"), SAYS, needs=("--arcs",)),
        Cell("--fit-tol", ("--fit-tol", "0.05"), CHANGES, needs=("--arcs",)),
        Cell("--fit-tol", ("--fit-tol", "0.05"), SAYS),
        Cell("--tangent-tol", ("--tangent-tol", "0.05"), CHANGES, needs=("--arcs", "--planes", "z=8.5")),
        Cell("--tangent-tol", ("--tangent-tol", "0.05"), SAYS),
    )),
    Command(("probe", "inventory"), EXACT, geometry=True,
            refused=(("stl", ("{D}/block.stl",), "STL"),), cells=(
        Cell("--planes", ("--planes", "z=mid"), CHANGES),
        Cell("--max-loops", ("--max-loops", "1"), CHANGES, needs=("--planes", "z=mid")),
        Cell("--max-loops", ("--max-loops", "1"), SAYS),
        Cell("--show", ("--show", "0"), CHANGES),
        Cell("--output", ("-o", "{D}/inv.json"), CHANGES),
        Cell("--define", ("-D", "bore=6"), {"program": CHANGES, "step": SAYS}),
    )),
    Command(("probe", "rays"), GEOMETRY, geometry=True, base=("--line", "-30,0,0:1,0,0"), cells=(
        Cell("--line", ("--line", "0,-20,0:0,1,0"), CHANGES),
        Cell("--fan", ("--fan", "5,0,0:0,0,1:90"), CHANGES),
        Cell("--length", ("--length", "10"), CHANGES),
        Cell("--show", ("--show", "0"), CHANGES),
        Cell("--output", ("-o", "{D}/rays.json"), CHANGES),
        Cell("--define", ("-D", "bore=6"), EXACT_ONLY),
    )),
    Command(("probe", "draft"), EXACT, geometry=True, refused=(("stl", ("{D}/block.stl",), "STL"),), cells=(
        Cell("--pull", ("--pull", "1,0,0"), CHANGES),
        Cell("--min-draft", ("--min-draft", "1"), CHANGES, exit=1),
        Cell("--samples", ("--samples", "2"), CHANGES, needs=("-o", "{D}/draft.json")),
        Cell("--show", ("--show", "0"), CHANGES, needs=("--min-draft", "1")),
        Cell("--show", ("--show", "0"), SAYS),
        Cell("--output", ("-o", "{D}/draft.json"), CHANGES),
        Cell("--define", ("-D", "length=50"), {"program": CHANGES, "step": SAYS}, needs=("-o", "{D}/draft.json")),
    )),
    Command(("probe", "fillet"), {"program": ("{D}/fillets.py",)}, geometry=True,
            refused=(("step", ("{D}/fillets.step",), "program"),), cells=(
        Cell("--at", ("--at", "chamfer"), CHANGES),
        Cell("--index", ("--index", "1"), CHANGES),
        Cell("--radii", ("--radii", "3"), CHANGES),
        Cell("--short", ("--short", "15"), CHANGES),
        Cell("--output", ("-o", "{D}/fillet.json"), CHANGES),
        Cell("--define", ("-D", "r=2"), CHANGES),
    )),
    Command(("probe", "knobs"), {"program": ("{D}/block.py",)}, geometry=True, base=("--knob", "bore=1"),
            refused=(("step", ("{D}/block.step",), "program"), ("stl", ("{D}/block.stl",), "program")), cells=(
        Cell("--knob", ("--knob", "length=2"), CHANGES),
        Cell("--output", ("-o", "{D}/knobs.json"), CHANGES),
        Cell("--define", ("-D", "length=50"), CHANGES),
    )),
    Command(("probe", "sketches"), {"dump": ("{D}/dump.json",)}, geometry=True, cells=(
        Cell("--sketch", ("--sketch", "side"), CHANGES),
        Cell("--against", ("--against", "{D}/plate.py"), CHANGES, shows="APPLIED"),
        Cell("--against", ("--against", "{D}/plate.step"), CHANGES, shows="APPLIED"),
        Cell("--tol", ("--tol", "5"), CHANGES, needs=("--against", "{D}/plate.step")),
        Cell("--tol", ("--tol", "5"), SAYS),
        Cell("--output", ("-o", "{D}/sk.json"), CHANGES),
    )),
    Command(("compare",), {k: v * 2 for k, v in GEOMETRY.items()}, geometry=True, cells=(
        Cell("--planes", ("--planes", "z=mid"), {"program": CHANGES, "step": CHANGES, "stl": CHANGES}),
        Cell("--window", ("--window", "w=-20,-15,20,15"), {"program": CHANGES, "step": CHANGES, "stl": SAYS},
             needs=("--planes", "z=mid")),
        Cell("--window", ("--window", "w=-20,-15,20,15"), SAYS),
        Cell("--max-loops", ("--max-loops", "1"), {"program": CHANGES, "step": CHANGES, "stl": SAYS},
             needs=("--planes", "z=mid")),
        Cell("--max-loops", ("--max-loops", "1"), SAYS),
        Cell("--output-dir", ("-o", "{D}/cmp"), CHANGES),
        Cell("--define", ("-D", "bore=6"), EXACT_ONLY),
    )),
    Command(("fit",), {"program": ("{D}/slot/source/slot.py", "{D}/key/source/key.py"),
                       "step": ("{D}/slot/source/slot.step", "{D}/key/source/key.step")}, geometry=True,
            refused=(("stl", ("{D}/block.stl", "{D}/key/source/key.step"), "mesh"),), cells=(
        Cell("--offset", ("--offset", "0,0,20"), CHANGES, exit=0),
        Cell("--spin", ("--spin", "90"), CHANGES),
        Cell("--spin-axis", ("--spin-axis", "x"), CHANGES, needs=("--spin", "90")),
        Cell("--spin-axis", ("--spin-axis", "x"), SAYS),
        Cell("--map", ("--map", "axis=z", "spin=90"), CHANGES),
        Cell("--mate", ("--mate", "key_in_slot"), CHANGES, exit=0),
        Cell("--a-mates", ("--a-mates", "{D}/alt_slot"), CHANGES, needs=("--mate", "key_in_slot"), shows="nominal 0.5",
             exit=1),
        Cell("--a-mates", ("--a-mates", "{D}/alt_slot"), SAYS),
        Cell("--b-mates", ("--b-mates", "{D}/alt_key"), CHANGES, needs=("--mate", "key_in_slot"), exit=1),
        Cell("--b-mates", ("--b-mates", "{D}/alt_key"), SAYS),
        Cell("--window", ("--window", "w=-3.6,-4,0.5,3.6,4,3.5"), CHANGES),
        Cell("--mates-from", ("--mates-from", "{D}/slot"), CHANGES),
        Cell("--sweep", ("--sweep", "z"), CHANGES),
        Cell("--travel", ("--travel", "4"), CHANGES, needs=("--sweep", "z")),
        Cell("--travel", ("--travel", "4"), SAYS),
        Cell("--sweep-steps", ("--sweep-steps", "3"), CHANGES, needs=("--sweep", "z")),
        Cell("--sweep-steps", ("--sweep-steps", "3"), SAYS),
        Cell("--step", ("--step", "2"), CHANGES),
        Cell("--contact-mm", ("--contact-mm", "-1"), CHANGES),
        Cell("--allow", ("--allow", "100000"), CHANGES, exit=0),
        Cell("--output-dir", ("-o", "{D}/fitout"), CHANGES),
        Cell("--record", ("--record",), CHANGES, needs=("--mate", "key_in_slot")),
        Cell("--a-define", ("--a-define", "width=8"), {"program": CHANGES, "step": SAYS}),
        Cell("--b-define", ("--b-define", "width=5"), {"program": CHANGES, "step": SAYS}),
    )),
    Command(("gcode", "decode"), dict(SLICED_A, badcrc=("{D}/a_badcrc.bgcode",)), cells=(
        Cell("--output", ("-o", "{D}/out.gcode"), {"gcode": CHANGES, "bgcode": CHANGES, "badcrc": Same(
            "a file whose checksum fails is refused, by name, before anything is written; --no-verify reads it")}),
        Cell("--no-verify", ("--no-verify",), {"gcode": SAYS, "bgcode": SAYS, "badcrc": CHANGES}, exit=0),
    )),
    Command(("gcode", "info"), {"bgcode": ("{D}/a.bgcode",), "badcrc": ("{D}/a_badcrc.bgcode",)},
            refused=(("gcode", ("{D}/a.gcode",), "bgcode"),), cells=(
        Cell("--no-verify", ("--no-verify",), {"bgcode": SAYS, "badcrc": CHANGES}, exit=0),
    )),
    Command(("gcode", "summary"), SLICED_A, refused=(("badcrc", ("{D}/a_badcrc.bgcode",), "CRC"),), cells=(
        Cell("--json", ("--json",), CHANGES),
    )),
    Command(("gcode", "check"), SLICED_A, refused=(("badcrc", ("{D}/a_badcrc.bgcode",), "CRC"),), cells=(
        Cell("--project", ("--project", "{D}/proj"), CHANGES, shows="ok: layer_height = 0.2"),
        Cell("--intent", ("--intent", "{D}/job_print.toml"), CHANGES, shows="ok: layer_height = 0.2"),
        Cell("--intent", ("--intent", "{D}/job_native.toml"), CHANGES, shows="ok: fill_density = 15%"),
        Cell("--intent", ("--intent", "{D}/job_print.toml"), REFUSES, needs=("--project", "{D}/proj")),
        Cell("--json", ("--json",), CHANGES, needs=("--intent", "{D}/job_print.toml")),
        Cell("--json", ("--json",), CHANGES),
    )),
    Command(("gcode", "supports"), SLICED_A, refused=(("badcrc", ("{D}/a_badcrc.bgcode",), "CRC"),), cells=(
        Cell("--contact-distance", ("--contact-distance", "0.05"), CHANGES),
        Cell("--min-area", ("--min-area", "100000"), CHANGES),
        Cell("--placement", ("--placement", "{D}/plate.placement.json"), CHANGES),
        Cell("--stl-root", ("--stl-root", "{D}/stls"), CHANGES, needs=("--placement", "{D}/plate.placement.json"),
             shows="Votes", exit=1),
        Cell("--stl-root", ("--stl-root", "{D}/stls"), SAYS),
        Cell("--png", ("--png", "{D}/s.png"), CHANGES),
        Cell("--png", ("--png", "{D}/s.png"), CHANGES, needs=("--json",)),
        Cell("--json", ("--json",), CHANGES),
    )),
    Command(("gcode", "view"), SLICED_A, refused=(("badcrc", ("{D}/a_badcrc.bgcode",), "CRC"),), cells=(
        Cell("--output", ("-o", "{D}/v.html"), CHANGES),
        Cell("--output", ("-o", "{D}/v.html"), REFUSES, needs=("--artifact", "{D}/art")),
        Cell("--budget-mb", ("--budget-mb", "0.00001"), CHANGES),
        Cell("--placement", ("--placement", "{D}/plate.placement.json"), CHANGES),
        Cell("--stl-root", ("--stl-root", "{D}/stls"), CHANGES, needs=("--placement", "{D}/plate.placement.json")),
        Cell("--stl-root", ("--stl-root", "{D}/stls"), SAYS),
        Cell("--artifact", ("--artifact", "{D}/art"), CHANGES),
    )),
    Command(("gcode", "compare"), {"gcode": ("{D}/a.gcode", "{D}/b.gcode"), "bgcode": ("{D}/a.bgcode", "{D}/b.bgcode")},
            refused=(("badcrc", ("{D}/a_badcrc.bgcode", "{D}/b.bgcode"), "CRC"),), cells=(
        Cell("--json", ("--json",), CHANGES),
        Cell("--all-settings", ("--all-settings",), CHANGES),
        Cell("--all-settings", ("--all-settings",), Same("the JSON record lists every differing setting"),
             needs=("--json",)),
        Cell("--min-area", ("--min-area", "100000"), CHANGES),
    )),
    Command(("records", "check"), {"library": ("{D}/lib",), "part": ("{D}/lib/parts/bracket/part.toml",),
                                   "job": ("{D}/lib/print_jobs/2026-02-01_mk4_pla_clip/job.toml",),
                                   "manifest": ("{D}/lib/projects/latch/exports/latch.print.json",)}, cells=(
        Cell("--json", ("--json",), CHANGES),
    )),
    Command(("duties",), {"library": ("{D}/lib",), "job": ("{D}/lib/print_jobs/2026-03-01_mk4_petg_bracket_v2/job.toml",),
                          "manifest": ("{D}/lib/projects/latch/exports/latch.print.json",)}, cells=(
        Cell("--as-of", ("--as-of", "2026-03-11"), CHANGES),
        Cell("--json", ("--json",), CHANGES),
    )),
)

# Commands not in the table, each with why. The list may only shrink: a new command is listed above unless it
# reads a single kind of input, and an OWED entry is work still to do.
EXEMPT = {
    ("info",): "reads no input",
    ("projects",): "reads no input",
    ("config-show",): "reads no input (the current folder's config)",
    ("printers",): "reads no input",
    ("targets",): "reads no input",
    ("policy", "list"): "reads no input",
    ("policy", "navigate"): "one kind of input: a policy name",
    ("policy", "read"): "one kind of input: a policy name",
    ("new-project",): "one kind of input: a name",
    ("config-init",): "one kind of input: the current folder",
    ("status",): "one kind of input: a project",
    ("open",): "one kind of input: a project",
    ("viewer",): "one kind of input: a project",
    ("check",): "one kind of input: a page",
    ("gallery", "build"): "one kind of input: project folders",
    ("gallery", "check"): "one kind of input: a gallery folder",
    ("gcode", "thumbnails"): "one kind of input (.bgcode) and one flag, which is required",
    ("session", "reopen"): "one kind of input: a project",
    ("session", "tag"): "one kind of input: a project",
    ("session", "note"): "one kind of input: a project",
    ("session", "status"): "one kind of input: a project",
    ("printer", "list"): "one kind of input: a printer host; hosts are held to their contract in test_host_contract",
    ("printer", "files"): "one kind of input: a printer host; hosts are held to their contract in test_host_contract",
    ("printer", "get"): "one kind of input: a printer host; hosts are held to their contract in test_host_contract",
    ("printer", "status"): "one kind of input: a printer host; hosts are held to their contract in test_host_contract",
    ("render",): "OWED: its kinds are engines (OpenSCAD, VoxelCAD, build123d); every flag per engine, next",
    ("export",): "OWED: its kinds are engines; every flag per engine, next",
    ("qc",): "OWED: its kinds are engines; --fixes already refuses engines other than build123d",
    ("session", "start"): "OWED: its kinds are engines; every flag per engine, next",
    ("session", "iterate"): "OWED: its kinds are engines; every flag per engine, next",
    ("session", "finalize"): "OWED: its kinds are engines; every flag per engine, next",
    ("stage",): "OWED: its kinds are output targets; every flag per target, next",
}


def _cases():
    for command in COMMANDS:
        for cell in command.cells:
            for kind in command.kinds:
                needs = f" with {' '.join(cell.needs)}" if cell.needs else ""
                yield pytest.param(command, cell, kind,
                                   id=f"{command.name} {' '.join(cell.argv)}{needs} [{kind}]".replace("{D}/", ""),
                                   marks=[pytest.mark.skipif(command.geometry and not B3D, reason="build123d not available")])


_BASELINES: Dict[tuple, Run] = {}


def _baseline(fixtures, scratch, command, kind, needs):
    key = (command.path, kind, needs)
    if key not in _BASELINES:
        words = [*command.path, *command.kinds[kind], *command.base, *needs]
        first, second = run(fixtures, scratch, words), run(fixtures, scratch, words)
        assert first.crash is None, f"`agentcad {' '.join(words)}` crashed: {first.crash}"
        assert first.result() == second.result(), (
            f"`agentcad {' '.join(words)}` gives two results from one input, so no flag can be judged against it:\n"
            f"{first.result()}\n{second.result()}")
        _BASELINES[key] = first
    return _BASELINES[key]


@pytest.fixture(scope="session")
def scratch(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("flag_contract_runs")


@pytest.mark.parametrize("command, cell, kind", list(_cases()))
def test_a_flag_changes_the_result_refuses_or_says_why_not(fixtures, scratch, command, cell, kind):
    base = _baseline(fixtures, scratch, command, kind, cell.needs)
    words = [*command.path, *command.kinds[kind], *command.base, *cell.needs, *cell.argv]
    got = run(fixtures, scratch, words)
    want = cell.on(kind)
    options = _options(command.path, cell.flag)
    pattern = _echo(options)
    value = cell.argv[1] if len(cell.argv) > 1 else None
    echo = pattern if _echoes(got, pattern, value) else None
    base_lines = set(base.out.splitlines())
    said = _names(got.err, options) or any(_names(line, options) for line in got.out.splitlines() if line not in base_lines)
    effect = _view(got, options, echo) != _view(base, options, echo)
    seen = ("crashed: " + got.crash if got.crash else "changed the result" if effect
            else "said so" if said else "did nothing and said nothing")
    where = (f"`agentcad {' '.join(words)}` [{kind}]: expected {want}, it {seen}\n"
             f"exit {base.code} -> {got.code}\nstdout:\n{got.out[-1500:]}\nstderr:\n{got.err[-1500:]}")
    assert got.crash is None, where
    if want == CHANGES:
        assert effect, where
        assert got.code == (base.code if cell.exit is None else cell.exit), where
        if cell.shows:
            assert cell.shows not in base.out + base.err, (f"{where}\n(the run without the flag shows "
                                                           f"{cell.shows!r} too, so it cannot tell the effect)")
            assert cell.shows in got.out + got.err, f"{where}\n(it should show {cell.shows!r})"
    elif want == REFUSES:
        assert got.code not in (0, None) and _names(got.err, options), where
    elif want == SAYS:
        assert not effect and said and got.code == base.code, where
    else:
        assert isinstance(want, Same) and want.why and not effect, where


@pytest.mark.parametrize("command, kind, inputs, word",
                         [pytest.param(c, k, i, w, id=f"{c.name} [{k}]",
                                       marks=[pytest.mark.skipif(c.geometry and not B3D, reason="build123d not available")])
                          for c in COMMANDS for k, i, w in c.refused])
def test_a_kind_a_command_does_not_read_is_refused_by_name(fixtures, scratch, command, kind, inputs, word):
    got = run(fixtures, scratch, [*command.path, *inputs, *command.base])
    assert got.crash is None, f"{command.name} on {kind} crashed: {got.crash}"
    assert got.code not in (0, None) and word.lower() in got.err.lower(), (
        f"{command.name} on {kind}: exit {got.code}\nstderr:\n{got.err}")


# --- the walls --------------------------------------------------------------------------------------------

def _flags(path):
    return {next((o for o in a.option_strings if o.startswith("--")), a.option_strings[0])
            for a in _command_parser(path)._actions
            if a.option_strings and not isinstance(a, argparse._HelpAction) and not a.required}


@pytest.mark.parametrize("command", COMMANDS, ids=lambda c: c.name)
def test_every_flag_of_a_listed_command_has_a_cell(command):
    flags, cells = _flags(command.path), {c.flag for c in command.cells}
    assert not flags - cells, f"{command.name}: flags without a cell (say what each does on every kind): {sorted(flags - cells)}"
    assert not cells - flags, f"{command.name}: cells for flags it does not have: {sorted(cells - flags)}"


@pytest.mark.parametrize("command", COMMANDS, ids=lambda c: c.name)
def test_every_cell_says_what_happens_on_every_kind(command):
    for cell in command.cells:
        if isinstance(cell.outcome, dict):
            assert set(cell.outcome) == set(command.kinds), f"{command.name} {cell.flag}: kinds {sorted(cell.outcome)}"
        for kind in command.kinds:
            want = cell.on(kind)
            assert want in (CHANGES, REFUSES, SAYS) or (isinstance(want, Same) and want.why.strip())


def _leaves(parser, path=()):
    subs = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    if not subs:
        yield path
        return
    for action in subs:
        for name, child in action.choices.items():
            yield from _leaves(child, path + (name,))


def test_every_command_is_listed_or_exempt_with_a_reason():
    leaves = set(_leaves(cli.build_parser()))
    listed = {c.path for c in COMMANDS}
    assert not listed & set(EXEMPT), f"listed and exempt: {sorted(listed & set(EXEMPT))}"
    missing = leaves - listed - set(EXEMPT)
    assert not missing, ("commands neither listed nor exempt (list each with the kinds it reads, or exempt it "
                         "with a reason): " + ", ".join(" ".join(m) for m in sorted(missing)))
    ghosts = (listed | set(EXEMPT)) - leaves
    assert not ghosts, f"entries for commands that do not exist: {sorted(ghosts)}"
    assert all(why.strip() for why in EXEMPT.values())


def test_every_declared_dependency_names_flags_its_command_has():
    """A dependency spelled wrong would never fire: the flag it names would never be given."""
    wrong = []
    for path in _leaves(cli.build_parser()):
        parser = _command_parser(path)
        options = {o for a in parser._actions for o in a.option_strings}
        for flag, any_of in parser.get_default("_requires") or ():
            wrong += [f"{' '.join(path)} {f}" for f in (flag, *any_of) if f not in options]
    assert not wrong, f"dependencies naming flags the command does not have: {wrong}"
    assert any(_command_parser(("fit",)).get_default("_requires") or ())


def test_a_dependent_flag_is_not_given_by_its_default():
    """main() names a dependent flag as ignored when it is given without what it needs. A default that counts
    as given would be named on every run, given or not, and a cell for it would pass on that line alone; so
    each one defaults to None and the command resolves its documented default (0 is a value given)."""
    looks_given = []
    for path in _leaves(cli.build_parser()):
        parser = _command_parser(path)
        defaults = argparse.Namespace(**{a.dest: a.default for a in parser._actions})
        for flag, _ in parser.get_default("_requires") or ():
            if cli._given(defaults, flag):
                value = getattr(defaults, flag.lstrip("-").replace("-", "_"))
                looks_given.append(f"{' '.join(path)} {flag} (default {value!r})")
    assert not looks_given, f"dependent flags whose default counts as given: {looks_given}"
    assert any(_command_parser(("fit",)).get_default("_requires") or ())


def test_the_runner_sees_a_flag_that_does_nothing(fixtures, scratch):
    """The control: a run judged against itself is the same, so a silent flag cannot pass for an effect."""
    words = ["gcode", "summary", "{D}/a.gcode"]
    assert run(fixtures, scratch, words).result() == run(fixtures, scratch, words).result()
    assert run(fixtures, scratch, words).result() != run(fixtures, scratch, [*words, "--json"]).result()


def test_an_echoed_value_is_not_an_effect_and_a_named_line_is_not_a_change():
    options = ("--fit-tol",)
    pattern = _echo(options)
    base = Run(0, "loop 1: 4 line(s); fit-tol 0.005 mm\n", "", {"r.json": '{"fit_tol": 0.005}'})
    echoed = Run(0, "loop 1: 4 line(s); fit-tol 2 mm\n", "", {"r.json": '{"fit_tol": 2.0}'})
    moved = Run(0, "loop 1: 1 arc(s); fit-tol 2 mm\n", "", {"r.json": '{"fit_tol": 2.0}'})
    assert _echoes(echoed, pattern, "2") and not _echoes(echoed, pattern, "3")
    assert _view(echoed, options, pattern) == _view(base, options, pattern)
    assert _view(moved, options, pattern) != _view(base, options, pattern)
    noted = Run(0, "loop 1: 4 line(s)\nwarning: --fit-tol ignored\n", "", {})
    assert _view(noted, options, None) == _view(Run(0, "loop 1: 4 line(s)\n", "", {}), options, None)
