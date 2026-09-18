"""Fit: interference, clearance, mate windows and the insertion sweep on
two boxes whose overlap is known exactly."""

from pathlib import Path

import pytest

from agentcad.engines import get_engine, list_engines

pytestmark = pytest.mark.skipif("build123d" not in list_engines() or not get_engine("build123d").available(),
                                reason="build123d backend not available")

BOX = "from build123d import *\n\ndef build(size=10.0):\n    return Box(size, size, size)\n"


@pytest.fixture
def box(tmp_path) -> Path:
    p = tmp_path / "box.py"
    p.write_text(BOX)
    return p


def test_overlap_volume_and_clearance_are_measured(box):
    from agentcad import fit
    touching = fit.fit(box, box, offset=(10, 0, 0))
    assert touching["interference_mm3"] == pytest.approx(0.0, abs=1e-6)
    assert touching["clearance_mm"] == pytest.approx(0.0, abs=1e-6)
    apart = fit.fit(box, box, offset=(12.5, 0, 0))
    assert apart["clearance_mm"] == pytest.approx(2.5, abs=1e-6)
    overlapping = fit.fit(box, box, offset=(8, 0, 0))
    assert overlapping["interference_mm3"] == pytest.approx(2 * 10 * 10, rel=1e-6)


def test_windows_read_the_gap_where_it_is(box):
    from agentcad import fit
    res = fit.fit(box, box, offset=(11, 0, 0), windows={"gap": [4, -6, -6, 7, 6, 6], "far": [-6, -6, -6, -4, 6, 6]})
    assert res["windows"]["gap"]["min_mm"] == pytest.approx(1.0, abs=0.05)
    assert "note" in res["windows"]["far"]          # only one body has surface there


def test_insertion_sweep_goes_from_clear_to_full_overlap(box):
    from agentcad import fit
    res = fit.fit(box, box, offset=(0, 0, 0), sweep_axis="x", sweep_travel=10.0)
    rows = res["insertion"]
    assert rows[0]["offset_mm"] == 10.0 and rows[0]["interference_mm3"] == pytest.approx(0.0, abs=1e-6)
    assert rows[-1]["offset_mm"] == 0.0 and rows[-1]["interference_mm3"] == pytest.approx(1000.0, rel=1e-6)
    assert all(rows[i]["interference_mm3"] <= rows[i + 1]["interference_mm3"] + 1e-9 for i in range(len(rows) - 1))
