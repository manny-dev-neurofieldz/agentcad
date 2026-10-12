"""Parameter override coercion shared by the Python-source engines.

The rule under test: a ``-D name=value`` string becomes the type of
``build()``'s default for that name, a typo in the value is an error rather
than a silent string, and an unknown name is rejected unless the function
takes ``**kwargs``.
"""

import pytest

from agentcad.params import coerce_defines, coerce_to_type_of, parse_define_value


def build(size=10, ratio=0.5, mirror=False, label="a", raw=None):
    return None


def build_kwargs(size=10, **extra):
    return None


def test_values_take_the_type_of_the_default():
    params = coerce_defines({"size": "20", "ratio": "0.25", "mirror": "yes", "label": "7"}, build)
    assert params == {"size": 20, "ratio": 0.25, "mirror": True, "label": "7"}
    assert isinstance(params["size"], int) and isinstance(params["ratio"], float)


def test_a_typo_in_a_typed_value_is_an_error_not_a_string():
    with pytest.raises(ValueError):
        coerce_defines({"size": "twenty"}, build)
    with pytest.raises(ValueError):
        coerce_to_type_of("maybe", True)


def test_untyped_defaults_parse_as_literals_and_fall_back_to_text():
    assert coerce_defines({"raw": "[1, 2]"}, build) == {"raw": [1, 2]}
    assert coerce_defines({"raw": "plain text"}, build) == {"raw": "plain text"}
    assert parse_define_value("3.5") == 3.5 and parse_define_value("abc") == "abc"


def test_unknown_names_are_rejected_unless_kwargs_are_accepted():
    with pytest.raises(ValueError) as exc:
        coerce_defines({"nope": "1"}, build)
    assert "nope" in str(exc.value) and "size" in str(exc.value)
    assert coerce_defines({"nope": "1", "size": "3"}, build_kwargs) == {"nope": 1, "size": 3}


def test_no_overrides_is_an_empty_mapping():
    assert coerce_defines(None, build) == {}
    assert coerce_defines({}, build) == {}


# --- reading a source's parameters without running it -------------------------------------------------------

def test_build_parameters_are_read_from_the_signature_not_run():
    from agentcad.params import build_parameters
    text = "raise SystemExit('never run')\n\ndef build(size=6.0, *, wall=1, flat=True):\n    pass\n"
    assert build_parameters(text) == {"size", "wall", "flat"}


def test_build_parameters_cannot_tell_without_a_closed_build():
    from agentcad.params import build_parameters
    assert build_parameters("def build(size=1, **more):\n    pass\n") is None     # takes any name
    assert build_parameters("result = 1\n") is None                               # no build(): harvested by name
    assert build_parameters("def build(:\n") is None                              # the engine reports the syntax


def test_openscad_parameters_are_the_top_level_assignments():
    from agentcad.engines.openscad import top_level_assignments
    text = ('size = 6; // width = 3\n/* depth = 2 */ label = "a = b";\nh=2;\n'
            'module m(r = 1) { inner = 2; }\nfunction f(x = 1) = x;\ncube([size, 4, h]);\nok = size == 6;\n')
    assert top_level_assignments(text) == {"size", "label", "h", "ok"}


def test_openscad_parameters_cannot_be_told_when_another_file_is_included():
    from agentcad.engines.openscad import top_level_assignments
    assert top_level_assignments("include <lib.scad>\nsize = 6;\n") is None
    assert top_level_assignments("use <lib.scad>\nsize = 6;\n") is None
