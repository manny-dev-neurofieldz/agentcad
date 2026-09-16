"""Engine-neutral camera presets and their OpenSCAD derivation."""

import math

import pytest

from agentcad.camera import CameraPreset, MULTI_VIEW_DEFAULT, STANDARD_PRESETS


@pytest.mark.parametrize("name,rotate", [
    ("iso", (55, 0, 45)),
    ("front", (90, 0, 0)),
    ("top", (0, 0, 0)),
    ("right", (90, 0, 90)),
    ("back", (90, 0, 180)),
])
def test_presets_keep_legacy_openscad_rotation(name, rotate):
    """The historical gimbal angles are reproduced from the stored eye direction."""
    preset = STANDARD_PRESETS[name]
    assert tuple(round(v) for v in preset.rotate) == rotate
    assert preset.camera_string == f"0,0,0,{rotate[0]},0,{rotate[2]},0"


def test_eye_directions_point_where_the_view_says():
    """Front looks from -Y, right from +X, top from +Z, iso from front-right-top."""
    p = STANDARD_PRESETS
    assert p["front"].eye == pytest.approx((0, -1, 0))
    assert p["right"].eye == pytest.approx((1, 0, 0))
    assert p["back"].eye == pytest.approx((0, 1, 0))
    assert p["top"].eye == pytest.approx((0, 0, 1))
    ex, ey, ez = p["iso"].eye
    assert ex > 0 and ey < 0 and ez > 0


def test_rotation_round_trip_for_arbitrary_angles():
    preset = CameraPreset.from_rotation("odd", 30, 120)
    rx, ry, rz = preset.rotate
    assert (rx, ry, rz) == pytest.approx((30, 0, 120))


def test_eye_is_normalized_and_up_not_parallel_for_top():
    preset = CameraPreset("x", eye=(0, -3, 4))
    assert math.isclose(sum(c * c for c in preset.eye), 1.0)
    top = STANDARD_PRESETS["top"]
    dot = sum(a * b for a, b in zip(top.eye, top.up))
    assert abs(dot) < 1e-9


def test_eye_position_fits_the_bounding_sphere():
    preset = STANDARD_PRESETS["front"]
    pos = preset.eye_position(center=(1, 2, 3), radius=4)
    assert pos == pytest.approx((1, 2 - 10, 3))
    fixed = CameraPreset("f", eye=(0, -1, 0), distance=7)
    assert fixed.eye_position((0, 0, 0), 100) == pytest.approx((0, -7, 0))


def test_default_views_are_presets():
    assert all(v in STANDARD_PRESETS for v in MULTI_VIEW_DEFAULT)
