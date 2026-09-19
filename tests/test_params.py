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
