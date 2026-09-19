"""The feature-effect report: deltas between two metadata records and the
warnings that name this project's failure modes. Pure functions, no engine.
"""

from agentcad.report import feature_effect, render_lines

BOX = {
    "volume": 1000.0, "area": 600.0, "bbox_size": [10.0, 10.0, 10.0],
    "counts": {"solids": 1, "faces": 6, "edges": 12, "vertices": 8},
    "face_census": {"plane": 6, "cylinder": 0, "cone": 0, "sphere": 0, "torus": 0, "bspline": 0, "other": 0},
    "is_valid": True, "short_edges": 0, "min_edge_mm": 10.0, "expected_solids": 1,
}


def _with(**changes):
    md = {k: (dict(v) if isinstance(v, dict) else v) for k, v in BOX.items()}
    for k, v in changes.items():
        if isinstance(v, dict) and isinstance(md.get(k), dict):
            md[k].update(v)
        else:
            md[k] = v
    return md


def test_deltas_name_what_a_feature_added():
    cur = _with(volume=980.0, counts={"faces": 7}, face_census={"cone": 1})
    rep = feature_effect(BOX, cur, source_changed=True)
    assert rep.changed is True
    assert rep.deltas["volume"] == -20.0
    assert rep.deltas["census.cone"] == 1 and rep.deltas["counts.faces"] == 1
    text = "\n".join(render_lines(rep))
    assert "cone 1 (+1)" in text and "-20" in text
    assert not rep.warnings


def test_a_source_change_with_no_measurable_effect_warns():
    rep = feature_effect(BOX, _with(), source_changed=True)
    assert rep.changed is False
    assert any("nothing measurable" in w for w in rep.warnings), rep.warnings
    # the same numbers with an unchanged source are simply a no-op, not a warning
    quiet = feature_effect(BOX, _with(), source_changed=False)
    assert not quiet.warnings


def test_solids_short_edges_and_validity_each_warn():
    rep = feature_effect(None, _with(counts={"solids": 3}, short_edges=2, min_edge_mm=0.14, is_valid=False))
    joined = " | ".join(rep.warnings)
    assert "solids 3 != expected 1" in joined
    assert "2 edge(s) shorter than 0.25" in joined and "0.14" in joined
    assert "invalid" in joined
    assert rep.changed is None  # nothing to compare against


def test_missing_keys_print_as_not_available_never_as_a_guess():
    rep = feature_effect(None, {"volume": 12.5, "counts": {"solids": 1}})
    text = "\n".join(render_lines(rep))
    assert "area       n/a" in text and "census     n/a" in text
    assert "12.5" in text
    assert not any("expected" in w for w in rep.warnings)


def test_measurement_errors_surface_as_warnings():
    rep = feature_effect(None, _with(volume_error="kernel refused"))
    assert any("volume not measured: kernel refused" in w for w in rep.warnings), rep.warnings
