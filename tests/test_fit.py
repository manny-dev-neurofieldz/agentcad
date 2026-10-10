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


def test_pose_matrix_moves_a_body_by_a_rigid_transform():
    pytest.importorskip("build123d")
    from agentcad import fit as fitmod
    b3d = fitmod._b3d()
    box = b3d.Box(2, 4, 6)                         # centred at the origin
    quarter_turn_and_shift = [[0, -1, 0, 10], [1, 0, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    moved = fitmod.pose_matrix(box, quarter_turn_and_shift)
    bb = moved.bounding_box()
    assert abs(bb.size.X - 4) < 1e-6 and abs(bb.size.Y - 2) < 1e-6   # x and y swap under the turn
    assert abs(bb.center().X - 10) < 1e-6


def test_map_and_offset_spin_pose_a_body_identically():
    pytest.importorskip("build123d")
    from agentcad import fit as fitmod, mates
    box = fitmod._b3d().Box(2, 4, 6)
    old = fitmod.pose(box, (5, 1, 0), 30, "z").bounding_box()
    new = fitmod.pose_matrix(box, mates.map_transform("z", 30, (5, 1, 0))).bounding_box()
    for a, b in ((old.min, new.min), (old.max, new.max)):
        assert abs(a.X - b.X) < 1e-6 and abs(a.Y - b.Y) < 1e-6 and abs(a.Z - b.Z) < 1e-6


def test_judge_windows_fails_below_nominal_and_never_passes_an_unmeasured_window():
    from agentcad import fit as fitmod
    results = {"tight": {"min_mm": 0.05}, "ok": {"min_mm": 0.19}, "empty": {"note": "one side has no surface"}}
    v = fitmod.judge_windows(results, {"tight": (0.2, None), "ok": (0.2, None), "empty": (0.2, 0.1),
                                       "undeclared": (None, None)})
    assert v["tight"]["verdict"] == "fail"
    assert v["ok"]["verdict"] == "pass"            # within the default 0.05 mm tolerance
    assert v["empty"]["verdict"] == "unmeasured"
    assert "undeclared" not in v


def test_fit_cli_with_output_dir_step_and_sweep_steps(tmp_path, monkeypatch, capsys):
    """The sampling options reach fit() and an output directory still works with them."""
    pytest.importorskip("build123d")
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_text("from build123d import Box\npart = Box(10, 10, 2)\n")
    b.write_text("from build123d import Box\npart = Box(4, 4, 2)\n")
    out = tmp_path / "out"
    from agentcad import cli
    monkeypatch.setattr("agentcad.fit._render_pair", lambda a, b, d: {})   # renders are not under test here
    cli.main(["fit", str(a), str(b), "--offset", "0,0,3", "--sweep", "z", "--travel", "2",
              "--sweep-steps", "3", "--step", "0.5", "-o", str(out)])
    import json
    rec = json.loads((out / "fit.json").read_text())
    assert len(rec["insertion"]) in (3, 4)
    assert rec["clearance_mm"] > 0


def test_closest_points_on_triangles_cover_every_region():
    import numpy as np
    from agentcad import fit as fitmod
    A, B, C = np.array([0.0, 0, 0]), np.array([4.0, 0, 0]), np.array([0.0, 4, 0])
    cases = {(1, 1, 3): (1, 1, 0),        # above the face
             (-1, -1, 0): (0, 0, 0),      # beyond corner A
             (6, -1, 0): (4, 0, 0),       # beyond corner B
             (-1, 6, 0): (0, 4, 0),       # beyond corner C
             (2, -2, 1): (2, 0, 0),       # outside edge AB
             (-2, 2, 0): (0, 2, 0),       # outside edge AC
             (3, 3, 0): (2, 2, 0)}        # outside edge BC
    P = np.array(list(cases), dtype=float)
    n = len(P)
    Q = fitmod._closest_on_triangles(P, np.tile(A, (n, 1)), np.tile(B, (n, 1)), np.tile(C, (n, 1)))
    assert np.allclose(Q, np.array(list(cases.values()), dtype=float))
    flat = fitmod._closest_on_triangles(P[:1], A[None], A[None], B[None])    # a degenerate triangle
    assert np.isfinite(flat).all()


def test_contacts_find_where_two_bodies_touch():
    pytest.importorskip("build123d")
    pytest.importorskip("scipy")
    from agentcad import fit as fitmod
    b3d = fitmod._b3d()
    base = b3d.Box(10, 10, 2)                                   # top face at z = 1
    lid = fitmod.pose(b3d.Box(4, 4, 2), (0, 0, 2))               # bottom face at z = 1: touching
    found = fitmod.contacts(base, lid, threshold=0.05)
    assert len(found) == 1                                       # one patch, not a grid of cells
    patch = found[0]
    assert abs(patch["centroid"][2] - 1.0) < 1e-6 and patch["min_mm"] < 1e-6
    assert patch["min"][0] == pytest.approx(-2.0, abs=0.3) and patch["max"][0] == pytest.approx(2.0, abs=0.3)
    assert patch["min"][1] == pytest.approx(-2.0, abs=0.3) and patch["max"][1] == pytest.approx(2.0, abs=0.3)
    near = fitmod.pose(b3d.Box(4, 4, 2), (0, 0, 2.03))           # 0.03 mm apart: within the threshold
    assert fitmod.contacts(base, near, threshold=0.05)[0]["min_mm"] == pytest.approx(0.03, abs=0.005)
    apart = fitmod.pose(b3d.Box(4, 4, 2), (0, 0, 2.2))           # 0.2 mm apart: no contact
    assert fitmod.contacts(base, apart, threshold=0.05) == []


def test_contacts_on_two_ears_are_two_regions():
    pytest.importorskip("build123d")
    pytest.importorskip("scipy")
    from agentcad import fit as fitmod
    b3d = fitmod._b3d()
    base = b3d.Box(30, 10, 2)
    ears = fitmod.pose(b3d.Box(3, 3, 2), (-10, 0, 2)) + fitmod.pose(b3d.Box(3, 3, 2), (10, 0, 2))
    found = fitmod.contacts(base, ears, threshold=0.05)
    assert len(found) == 2
    assert sorted(round(r["centroid"][0]) for r in found) == [-10, 10]


# --- a key posed into its slot from the datums each part declares ------------------

SLOT = ("from build123d import *\n\ndef build(width=6.2):\n"
        "    return Box(20, 20, 10) - Pos(0, 0, 2.5) * Box(width, 30, 5)\n")     # slot floor at z = 0
KEY = "from build123d import *\n\ndef build():\n    return Box(10, 6, 4)\n"      # its own frame: width along y


def _key_and_slot(tmp_path, nominal=0.1, key_datums=True):
    (tmp_path / "slot" / "source").mkdir(parents=True)
    (tmp_path / "key" / "source").mkdir(parents=True)
    (tmp_path / "slot" / "source" / "slot.py").write_text(SLOT)
    (tmp_path / "key" / "source" / "key.py").write_text(KEY)
    (tmp_path / "slot" / "agentcad.toml").write_text(
        '[mates.key_in_slot]\ncounterpart = "key"\n'
        f'nominal_mm = {nominal}\nwindow = [-3.6, -4, 0.5, 3.6, 4, 3.5]\n'
        '[mates.key_in_slot.axis]\npoint = [0, 0, 0]\ndirection = [0, 0, 1]\n'
        '[mates.key_in_slot.key_line]\npoint = [0, 0, 0]\ndirection = [1, 0, 0]\n'
        '[mates.key_in_slot.rim_plane]\npoint = [0, 0, 0]\nnormal = [0, 0, 1]\n')
    (tmp_path / "key" / "part.toml").write_text(
        '[mates.key_in_slot]\ncounterpart = "slot"\n' + (
            '[mates.key_in_slot.axis]\npoint = [0, 0, 0]\ndirection = [0, 0, 1]\n'
            '[mates.key_in_slot.key_line]\npoint = [0, 0, 0]\ndirection = [0, 1, 0]\n'
            '[mates.key_in_slot.rim_plane]\npoint = [0, 0, -2]\nnormal = [0, 0, -1]\n' if key_datums else ""))
    return tmp_path / "slot" / "source" / "slot.py", tmp_path / "key" / "source" / "key.py"


def _fit_cli(argv, monkeypatch):
    from agentcad import cli
    monkeypatch.setattr("agentcad.fit._render_pair", lambda a, b, d: {})
    try:
        cli.main(["fit", *map(str, argv)])
        return 0
    except SystemExit as e:
        return e.code or 0


def test_a_key_is_posed_into_its_slot_from_datums_alone(tmp_path, monkeypatch, capsys):
    import json
    slot, key = _key_and_slot(tmp_path)
    code = _fit_cli([slot, key, "--mate", "key_in_slot", "-o", tmp_path / "mate"], monkeypatch)
    out = capsys.readouterr().out
    assert code == 0, out
    rec = json.loads((tmp_path / "mate" / "fit.json").read_text())
    assert rec["interference_mm3"] == pytest.approx(0.0, abs=1e-6)
    assert rec["windows"]["key_in_slot"]["min_mm"] == pytest.approx(0.1, abs=0.005)   # 6.2 slot, 6.0 key
    assert rec["verdicts"]["key_in_slot"]["verdict"] == "pass"
    assert rec["pose"]["mate"] == "key_in_slot" and rec["pose"]["b_declared_in"].endswith("part.toml")
    assert any(abs(r["centroid"][2]) < 1e-6 for r in rec["contacts"])                 # seated on the floor
    # --map with the same turn and offset is the same pose and the same measurement
    code = _fit_cli([slot, key, "--map", "axis=z", "spin=-90", "offset=0,0,2", "--mates-from", tmp_path / "slot",
                     "-o", tmp_path / "map"], monkeypatch)
    mapped = json.loads((tmp_path / "map" / "fit.json").read_text())
    assert code == 0
    for row_d, row_m in zip(rec["pose"]["transform"], mapped["pose"]["transform"]):
        assert row_d == pytest.approx(row_m, abs=1e-9)
    assert mapped["windows"]["key_in_slot"]["min_mm"] == pytest.approx(rec["windows"]["key_in_slot"]["min_mm"], abs=1e-9)


def test_a_clearance_below_nominal_fails_and_at_nominal_passes(tmp_path, monkeypatch, capsys):
    slot, key = _key_and_slot(tmp_path, nominal=0.2)        # the slot gives 0.1 a side
    assert _fit_cli([slot, key, "--mate", "key_in_slot"], monkeypatch) == 1
    assert "BELOW NOMINAL" in capsys.readouterr().err
    assert _fit_cli([slot, key, "--mate", "key_in_slot", "--a-define", "width=6.4"], monkeypatch) == 0


def test_a_mate_without_datums_asks_for_map(tmp_path, monkeypatch, capsys):
    slot, key = _key_and_slot(tmp_path, key_datums=False)
    assert _fit_cli([slot, key, "--mate", "key_in_slot"], monkeypatch) == 2
    err = capsys.readouterr().err
    assert "has no axis" in err and "--map" in err
    assert _fit_cli([slot, key, "--mate", "no_such_mate"], monkeypatch) == 2
    assert "declares no [mates.no_such_mate]" in capsys.readouterr().err
