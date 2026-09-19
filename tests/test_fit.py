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


def test_build123d_sources_are_fitted_in_the_assembly_frame_by_default(tmp_path):
    """A build() that takes print_orient gets False unless the caller says otherwise."""
    from agentcad import fit
    src = tmp_path / "oriented.py"
    src.write_text("from build123d import *\n\ndef build(size=10.0, print_orient=True):\n"
                   "    p = Box(size, size, size)\n    return Pos(0, 0, 100) * p if print_orient else p\n")
    res = fit.fit(src, src, offset=(10, 0, 0))
    assert res["clearance_mm"] == pytest.approx(0.0, abs=1e-6)         # both in the assembly frame
    lifted = fit.fit(src, src, offset=(10, 0, 0), b_defines={"print_orient": "true"})
    assert lifted["clearance_mm"] > 50                                 # the caller's choice is kept


PLATE = "from build123d import *\n\ndef build():\n    return Box(100.0, 100.0, 2.0)\n"


def test_a_window_in_the_middle_of_a_flat_face_still_sees_surface(tmp_path):
    """Tessellation puts a plane's vertices at its corners; a window in the middle of two
    facing plates must still read the gap (the FS-4DA ears window read empty on one side)."""
    from agentcad import fit
    p = tmp_path / "plate.py"
    p.write_text(PLATE)
    res = fit.fit(p, p, offset=(0, 0, 3.0), windows={"mid": [-5, -5, -2, 5, 5, 5]})
    assert res["windows"]["mid"]["min_mm"] == pytest.approx(1.0, abs=0.02)
    assert res["windows"]["mid"]["n_a"] > 4 and res["windows"]["mid"]["n_b"] > 4


def test_mates_are_checked_only_for_their_counterpart(tmp_path, monkeypatch, capsys):
    """A [mates] table lists every pair of a project; fit on one pair reads only that pair's windows."""
    from agentcad import cli
    p = tmp_path / "plate.py"
    p.write_text("from build123d import *\n\ndef build(part='base'):\n    return Box(100.0, 100.0, 2.0)\n")
    (tmp_path / "agentcad.toml").write_text(
        '[mates.lid_on_base]\nwindow = [-5, -5, -2, 5, 5, 5]\nparts = ["base", "lid"]\n'
        '[mates.foot_on_base]\nwindow = [-5, -5, -2, 5, 5, 5]\ncounterpart = "foot"\n'
        '[mates.lid_on_foot]\nwindow = [-5, -5, -2, 5, 5, 5]\nparts = ["foot", "lid"]\n')
    monkeypatch.setattr("sys.argv", ["agentcad", "fit", str(p), str(p), "--offset", "0,0,3",
                                     "--a-define", "part=base", "--b-define", "part=lid", "--mates-from", str(tmp_path)])
    try:
        cli.main()
    except SystemExit as e:
        assert e.code in (0, None)
    out = capsys.readouterr().out
    assert "lid_on_base" in out and "foot_on_base" not in out and "lid_on_foot" not in out
