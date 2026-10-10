"""The [mates] contract: window-only entries keep loading, datums parse and normalise,
and a malformed entry is an error that names the mate and the key."""

import math

import pytest

from agentcad import mates


def test_a_window_only_entry_loads_as_before():
    m = mates.parse("lid_on_base", {"window": [-5, -5, -2, 5, 5, 5], "nominal_mm": 0.2, "parts": ["base", "lid"]})
    assert m.window == [-5.0, -5.0, -2.0, 5.0, 5.0, 5.0]
    assert m.nominal_mm == 0.2 and m.parts == ["base", "lid"] and not m.has_datums


def test_datums_parse_and_directions_normalise():
    m = mates.parse("pin_in_bore", {
        "axis": {"point": [0, 0, 0], "direction": [0, 0, 2]},
        "rim_plane": {"point": [0, 0, 3], "normal": [0, 0, -5]},
        "key_line": {"point": [0, 0, 0], "direction": [3, 4, 0]},
        "insertion": [0, 0, -1],
        "dimensions": {"bore": {"value": 6.35, "datum": "axis"}},
        "counterpart": "pin"})
    assert m.has_datums and m.axis.direction == (0.0, 0.0, 1.0)
    assert m.rim_plane.direction == (0.0, 0.0, -1.0)
    assert math.isclose(m.key_line.direction[0], 0.6) and math.isclose(m.key_line.direction[1], 0.8)
    assert m.insertion == (0.0, 0.0, -1.0) and m.dimensions["bore"]["datum"] == "axis"


@pytest.mark.parametrize("entry,message", [
    ({"axis": {"point": [0, 0, 0], "direction": [0, 0, 0]}}, "axis.direction is a zero vector"),
    ({"axis": {"point": [0, 0], "direction": [0, 0, 1]}}, "axis.point must be three numbers"),
    ({"rim_plane": {"point": [0, 0, 0], "normal": [0, 0, 1]}}, "only with an axis"),
    ({"axis": {"point": [0, 0, 0]}}, "needs a point and a direction"),
    ({"window": [0, 0, 1]}, "window must be"),
])
def test_a_malformed_entry_names_the_mate_and_the_key(entry, message):
    with pytest.raises(mates.MateError, match=f"mate bad: .*{message}|mate bad: {message}"):
        mates.parse("bad", entry)


def test_load_reads_a_part_toml(tmp_path):
    (tmp_path / "part.toml").write_text(
        '[mates.key_in_slot]\ncounterpart = "slider"\nnominal_mm = 0.15\n'
        '[mates.key_in_slot.axis]\npoint = [0, 0, 0]\ndirection = [1, 0, 0]\n')
    found = mates.load(tmp_path)
    assert list(found) == ["key_in_slot"]
    assert found["key_in_slot"].axis.direction == (1.0, 0.0, 0.0)
    assert found["key_in_slot"].counterpart == "slider"


def test_no_toml_means_no_mates_with_a_note(tmp_path, capsys):
    assert mates.load(tmp_path) == {}
    assert "no mates read" in capsys.readouterr().err


def _apply(m, p):
    return tuple(sum(m[i][j] * p[j] for j in range(3)) + m[i][3] for i in range(3))


def test_pose_from_datums_puts_axis_key_and_rim_together():
    slot = mates.parse("key_in_slot", {"axis": {"point": [0, 0, 0], "direction": [0, 0, 1]},
                                       "key_line": {"point": [0, 0, 0], "direction": [1, 0, 0]},
                                       "rim_plane": {"point": [0, 0, 2], "normal": [0, 0, 1]}})
    key = mates.parse("key_in_slot", {"axis": {"point": [10, 0, 0], "direction": [0, 0, 1]},
                                      "key_line": {"point": [10, 0, 0], "direction": [0, 1, 0]},
                                      "rim_plane": {"point": [10, 0, 5], "normal": [0, 0, -1]}})
    m, notes = mates.pose_from_datums(slot, key)
    assert notes == []
    p = _apply(m, (10, 0, 0))                     # B's axis point lands on A's axis
    assert math.isclose(p[0], 0, abs_tol=1e-9) and math.isclose(p[1], 0, abs_tol=1e-9)
    q = _apply(m, (10, 1, 0))                     # B's key direction (+y) becomes A's (+x)
    assert math.isclose(q[0] - p[0], 1.0, abs_tol=1e-9) and math.isclose(q[1] - p[1], 0.0, abs_tol=1e-9)
    r = _apply(m, (10, 0, 5))                     # B's rim lands in A's rim plane (z = 2)
    assert math.isclose(r[2], 2.0, abs_tol=1e-9)


def test_pose_without_key_lines_says_the_spin_is_free():
    a = mates.parse("a", {"axis": {"point": [0, 0, 0], "direction": [0, 0, 1]}})
    b = mates.parse("b", {"axis": {"point": [0, 0, 0], "direction": [0, 0, 1]}})
    _, notes = mates.pose_from_datums(a, b)
    assert any("spin" in n for n in notes) and any("along the axis" in n for n in notes)
