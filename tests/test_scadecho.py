"""Declarations read back from OpenSCAD's ECHO output: the value grammar (including the strings
OpenSCAD 2021.01 prints unescaped), the declaration rules, the lines the engine takes from stderr,
and the records that come out, validated by the same code as a Python program's calls. None of
this needs OpenSCAD: the lines below are what 2021.01 printed for the echoes in the comments."""

import pytest

from agentcad import annotate, qc, scadecho
from agentcad.scadecho import EchoError

# echo("AGENTCAD_QC", "feature", name="pin \"hole\"", box=[-6, -6, 0, 6, 6, 12.5], kind="hole",
#      why="a, b; [c]", min_wall_mm=0.5, knobs=["wall=0.2", "r"]);
FEATURE = ('ECHO: "AGENTCAD_QC", "feature", name = "pin "hole"", box = [-6, -6, 0, 6, 6, 12.5], kind = "hole", '
           'why = "a, b; [c]", min_wall_mm = 0.5, knobs = ["wall=0.2", "r"]')
# echo("AGENTCAD_QC", "suppress", rule="max_overhang", why="planned supports", box=undef);
SUPPRESS = 'ECHO: "AGENTCAD_QC", "suppress", rule = "max_overhang", why = "planned supports", box = undef'
# echo("AGENTCAD_QC", "pose", up=[0, -1, 0], spin_deg=90, flag=true, tiny=1e-7, big=123456789);
POSE = 'ECHO: "AGENTCAD_QC", "pose", up = [0, -1, 0], spin_deg = 90, flag = true, tiny = 1e-7, big = 1.23457e+8'
# echo("AGENTCAD_QC", "feature", name="rib 0", box=[0, 0, 0, 1, 1, 1]);
RIB = 'ECHO: "AGENTCAD_QC", "feature", name = "rib 0", box = [0, 0, 0, 1, 1, 1]'


@pytest.fixture(autouse=True)
def _clean_registry():
    annotate.reset()
    yield
    annotate.reset()


# --- the value grammar -------------------------------------------------------------------------------

def test_the_lines_openscad_2021_prints_are_read_value_by_value():
    positional, named = scadecho.items(FEATURE)
    assert positional == ["AGENTCAD_QC", "feature"]
    assert named["name"] == 'pin "hole"'                       # the quote OpenSCAD 2021.01 did not escape
    assert named["why"] == "a, b; [c]"                          # a comma, a semicolon and brackets inside a string
    assert named["box"] == [-6, -6, 0, 6, 6, 12.5] and named["knobs"] == ["wall=0.2", "r"]
    assert scadecho.items(SUPPRESS)[1] == {"rule": "max_overhang", "why": "planned supports", "box": None}
    _, pose = scadecho.items(POSE)
    assert pose["flag"] is True and pose["tiny"] == pytest.approx(1e-7) and pose["big"] == pytest.approx(1.23457e8)
    assert pose["up"] == [0, -1, 0] and pose["spin_deg"] == 90
    assert scadecho.items(RIB)[1]["name"] == "rib 0"


def test_escaped_quotes_backslashes_nested_vectors_and_odd_numbers_are_read():
    line = ('ECHO: "AGENTCAD_QC", "feature", name = "say \\"hi\\", then go", why = "a\\\\b", '
            'box = [-1.5e-3, +2, 1E3, inf, -inf, 0.5], matrix = [[1, 0, 0], [0, 0, -1], [0, 1, 0]], '
            'off = false, none = undef, empty = []')
    _, named = scadecho.items(line)
    assert named["name"] == 'say "hi", then go'                # \" is a quote, even before a comma
    assert named["why"] == "a\\b"                              # \\ is one backslash
    assert named["box"][:3] == [-1.5e-3, 2, 1000.0] and named["box"][3] == float("inf")
    assert named["matrix"] == [[1, 0, 0], [0, 0, -1], [0, 1, 0]]
    assert named["off"] is False and named["none"] is None and named["empty"] == []


@pytest.mark.parametrize("line,why", [
    ('ECHO: "AGENTCAD_QC", "feature", name = "no end', "unterminated string"),
    ('ECHO: "AGENTCAD_QC", "feature", box = [1, 2', "unterminated vector"),
    ('ECHO: "AGENTCAD_QC", "feature", box = [1 2]', "expected , or ]"),
    ('ECHO: "AGENTCAD_QC", "feature", box = [0 : 1 : 10]', "expected , or ]"),
    ('ECHO: "AGENTCAD_QC", "feature", name = ', "a value"),
    ('ECHO: "AGENTCAD_QC", "feature", wall = 5 6', "expected a comma"),
    ('ECHO: "AGENTCAD_QC", "feature", wall = 0.5.5', "not a value"),
    ('ECHO: "AGENTCAD_QC", "feature", name = function(x) x', "not a value"),
])
def test_a_line_that_is_not_a_declaration_is_an_error_naming_the_line(line, why):
    with pytest.raises(EchoError) as e:
        scadecho.items(line)
    assert why in str(e.value) and line[:30] in str(e.value)


# --- the declaration rules ---------------------------------------------------------------------------

def test_a_declaration_is_its_type_and_its_named_arguments_and_undef_is_not_passed():
    assert scadecho.parse(FEATURE) == ("feature", {
        "name": 'pin "hole"', "box": [-6, -6, 0, 6, 6, 12.5], "kind": "hole", "why": "a, b; [c]",
        "min_wall_mm": 0.5, "knobs": ["wall=0.2", "r"]})
    assert scadecho.parse(SUPPRESS) == ("suppress", {"rule": "max_overhang", "why": "planned supports"})
    assert scadecho.parse('ECHO: "AGENTCAD_QC", "pose", up = [0, -1, 0], spin_deg = 90')[0] == "pose"


@pytest.mark.parametrize("line,message", [
    ('ECHO: "AGENTCAD_QC", "feeture", name = "a", box = [0, 0, 0, 1, 1, 1]', "unknown declaration 'feeture'"),
    ('ECHO: "AGENTCAD_QC", "feature", name = "a", box = [0, 0, 0, 1, 1, 1], colour = "red"', "unknown argument 'colour'"),
    ('ECHO: "AGENTCAD_QC", "suppress", rule = "max_overhang", why = "x", min_wall_mm = 1', "unknown argument 'min_wall_mm'"),
    ('ECHO: "AGENTCAD_QC", "pose", up = [0, 0, 1], flag = true', "unknown argument 'flag'"),
    ('ECHO: "AGENTCAD_QC", "feature", name = "a"', "needs box"),
    ('ECHO: "AGENTCAD_QC", "feature", name = "a", box = undef', "needs box"),
    ('ECHO: "AGENTCAD_QC", "suppress", rule = "max_overhang"', "needs why"),
    ('ECHO: "AGENTCAD_QC", "feature", "a name", box = [0, 0, 0, 1, 1, 1]', "name its arguments"),
    ('ECHO: "AGENTCAD_QC", "feature", name = "a", name = "b", box = [0, 0, 0, 1, 1, 1]', "given twice"),
    ('ECHO: "AGENTCAD_QC"', "needs a type"),
    ('ECHO: "AGENTCAD_QC", 5', "type"),
])
def test_an_unknown_type_or_argument_or_a_missing_one_is_an_error_naming_the_line(line, message):
    with pytest.raises(EchoError) as e:
        scadecho.parse(line)
    assert message in str(e.value) and line[:40] in str(e.value)


def test_the_arguments_a_declaration_takes_are_the_ones_the_python_calls_take():
    import inspect
    for kind, function in (("feature", annotate.feature), ("suppress", annotate.suppress), ("pose", annotate.print_pose)):
        params = {p.name for p in inspect.signature(function).parameters.values() if p.kind != p.VAR_KEYWORD}
        assert set(annotate.ARGUMENTS[kind]) == params | (set(annotate.LIMIT_KEYS) if kind == "feature" else set())
        assert set(annotate.REQUIRED[kind]) <= set(annotate.ARGUMENTS[kind])


# --- the lines the engine takes from stderr -----------------------------------------------------------

def test_declaration_lines_are_found_among_the_rest_and_each_taken_once_in_order():
    other = ['ECHO: "hello", 5', "WARNING: something", 'ECHO: "NOT_AGENTCAD_QC", "feature"',
             'ECHO: "AGENTCAD_QCX", "feature"', 'note ECHO: "AGENTCAD_QC", "feature"', "Facets: 6", ""]
    view_a = "\n".join([other[0], FEATURE, other[1], SUPPRESS, other[2], other[3], other[4]])
    view_b = "\r\n".join([FEATURE, RIB, other[5], SUPPRESS, other[6]])         # another process: the lines repeat
    assert scadecho.declaration_lines(view_a, view_b) == [FEATURE, SUPPRESS, RIB]
    assert scadecho.declaration_lines("") == [] and scadecho.declaration_lines() == []
    assert scadecho.declaration_lines('ECHO: "AGENTCAD_QC"') == ['ECHO: "AGENTCAD_QC"']     # a typo is not silence


# --- the records ---------------------------------------------------------------------------------------

def test_records_are_validated_by_the_same_code_as_the_python_calls_and_name_the_file_alone():
    lines = [FEATURE, SUPPRESS, 'ECHO: "AGENTCAD_QC", "pose", up = [0, -1, 0], spin_deg = 90', RIB]
    recs = scadecho.records(lines, "designs/part.scad")
    assert [r["type"] for r in recs] == ["feature", "suppress", "pose", "feature"]
    feature = recs[0]
    assert feature["file"] == "designs/part.scad" and feature["line"] is None          # ECHO carries no line
    assert feature["name"] == 'pin "hole"' and feature["box"] == [-6.0, -6.0, 0.0, 6.0, 6.0, 12.5]
    assert feature["limits"] == {"min_wall_mm": 0.5} and feature["knobs"] == ["wall=0.2", "r=10%"]
    assert recs[1]["box"] is None and recs[2]["pose"] == {"up": [0.0, -1.0, 0.0], "spin_deg": 90.0}
    assert annotate.records() == []                            # the reader keeps its own registry


@pytest.mark.parametrize("lines,message", [
    (['ECHO: "AGENTCAD_QC", "suppress", rule = "max_overhang", why = ""'], "needs its reason"),
    (['ECHO: "AGENTCAD_QC", "suppress", rule = "nonesuch", why = "x"'], "unknown rule"),
    (['ECHO: "AGENTCAD_QC", "feature", name = "a", box = [0, 0, 0, 1, 1]'], "six"),
    (['ECHO: "AGENTCAD_QC", "feature", name = "a", box = [0, 0, 0, 1, 1, 1], min_wall_mm = -1'], "positive"),
    (['ECHO: "AGENTCAD_QC", "feature", name = "a", box = [0, 0, 0, 1, 1, inf]'], "finite"),
    (['ECHO: "AGENTCAD_QC", "feature", name = "a", box = [0, 0, 0, 1, 1, 1], knobs = 5'], "knobs"),
    (['ECHO: "AGENTCAD_QC", "pose", matrix = [[1, 0, 0], [0, 1, 0], [0, 0, -1]]'], "reflection"),
    (['ECHO: "AGENTCAD_QC", "pose", up = [0, 0, 1]', 'ECHO: "AGENTCAD_QC", "pose", up = [1, 0, 0]'], "twice"),
    ([RIB, 'ECHO: "AGENTCAD_QC", "feature", name = "rib 0", box = [0, 0, 0, 2, 2, 2]'], "declared twice"),
])
def test_a_declaration_the_validator_refuses_is_an_error_naming_its_line(lines, message):
    with pytest.raises(EchoError) as e:
        scadecho.records(lines, "part.scad")
    assert message in str(e.value) and lines[-1][:40] in str(e.value)


def test_read_takes_the_lines_out_of_each_runs_stderr_once():
    recs = scadecho.read(["\n".join([RIB, "Facets: 6"]), "\n".join([RIB, SUPPRESS])], "part.scad")
    assert [r["type"] for r in recs] == ["feature", "suppress"]
    assert scadecho.read([""], "part.scad") == [] and scadecho.read([], "part.scad") == []


# --- the shared validator --------------------------------------------------------------------------------

def test_the_python_calls_record_their_caller_and_the_internal_ones_the_place_they_are_given():
    import sys
    annotate.feature("rib", box=(0, 0, 0, 1, 1, 1))
    line = sys._getframe().f_lineno - 1
    rec = annotate.records()[0]
    assert rec["file"] == __file__ and rec["line"] == line
    registry = []
    annotate._feature({"file": "x.scad", "line": None}, registry, "rib", (0, 0, 0, 1, 1, 1))
    annotate._suppress({"file": "x.scad", "line": 7}, registry, "max_overhang", why="planned")
    annotate._print_pose({"file": "x.scad", "line": None}, registry, up=(1, 0, 0))
    assert [(r["type"], r["file"], r["line"]) for r in registry] == [
        ("feature", "x.scad", None), ("suppress", "x.scad", 7), ("pose", "x.scad", None)]
    assert len(annotate.records()) == 1                         # the Python registry was not touched


@pytest.mark.parametrize("call,message", [
    (lambda: annotate.feature("a", box=("x", 0, 0, 1, 1, 1)), "six numbers"),
    (lambda: annotate.feature("a", box=(0, 0, 0, 1, 1, 1), knobs=("wall=abc",)), "knob"),
    (lambda: annotate.feature("a", box=(0, 0, 0, 1, 1, 1), min_wall_mm="thin"), "must be a number"),
    (lambda: annotate.print_pose(matrix=[[1, 0, 0], [0, 1, 0]]), "3x3"),
    (lambda: annotate.print_pose(matrix=[1, 2, 3]), "3x3"),
    (lambda: annotate.print_pose(up=5), "non-zero vector"),
    (lambda: annotate.print_pose(up=(0, 0)), "non-zero vector"),
    (lambda: annotate.print_pose(spin_deg="quarter"), "spin_deg"),
])
def test_a_value_that_is_not_what_a_declaration_needs_is_a_named_error_whatever_its_spelling(call, message):
    with pytest.raises(ValueError, match=message):
        call()
    assert annotate.records() == []


def test_a_feature_name_is_compared_as_it_is_stored():
    annotate.feature("rib", box=(0, 0, 0, 1, 1, 1))
    with pytest.raises(ValueError, match="declared twice"):
        annotate.feature(" rib ", box=(0, 0, 0, 2, 2, 2))
    with pytest.raises(ValueError, match="number"):
        annotate.feature("rod", box=(0, 0, 0, 1, 1, 1), min_wall_mm=True)       # a boolean is not a limit
    assert [r["name"] for r in annotate.records()] == ["rib"]


def test_a_record_with_no_line_names_the_file_alone():
    records = [{"type": "feature", "name": "rib", "kind": "rib", "box": [0, 0, 0, 1, 1, 1], "limits": {}, "why": "",
                "file": "copy/part.scad", "line": None},
               {"type": "suppress", "rule": "max_overhang", "why": "planned", "box": None, "file": "copy/part.scad",
                "line": 5}]
    ann = qc.Annotated.from_records(records, {"copy/part.scad": "/work/part.scad"})
    assert ann.features[0]["source"] == "/work/part.scad"
    assert ann.suppressions[0]["source"] == "/work/part.scad:5"
