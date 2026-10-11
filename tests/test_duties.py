"""Owed work derived from records (``agentcad duties``), checked against the duties written down for the
fixture library before this code existed."""

import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from agentcad import duties, records
from agentcad.cli import main

LIBRARY = Path(__file__).parent / "data" / "records_library"
EXPECTED = json.loads((LIBRARY / "expected_duties.json").read_text())
AS_OF = date.fromisoformat(EXPECTED["as_of"])
OLD_CLIP = "// the clip before its tab grew\ntab = 3.8;\ncube([tab, 10, 2]);\n"     # the clip the fit measured


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "library"
    shutil.copytree(LIBRARY, root)
    return root


def _cli(argv):
    try:
        return main(argv) or 0
    except SystemExit as e:
        return e.code


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text, f"{old!r} not in {path}"
    path.write_text(text.replace(old, new, 1))


def _owed(root, as_of=AS_OF):
    return duties.derive(records.load(root), as_of)


def _as_written(duty):
    """A duty in the terms the expected list uses: its kind and what it is about."""
    return dict(duty.subject, kind=duty.kind)


def test_the_fixture_library_owes_exactly_the_duties_written_down_before_this_code():
    owed = [_as_written(d) for d in _owed(LIBRARY)]
    expected = [{k: v for k, v in d.items() if k != "why"} for d in EXPECTED["duties"]]
    canon = lambda d: json.dumps(d, sort_keys=True)
    assert sorted(owed, key=canon) == sorted(expected, key=canon)
    owed_jobs = {d.subject.get("job") for d in _owed(LIBRARY)}
    for item in EXPECTED["not_owed"]:
        if "job" in item:
            assert item["job"] not in owed_jobs
        else:
            assert not [d for d in _owed(LIBRARY) if d.kind == "refit" and d.subject["parts"] == sorted(item["fit"])]


def test_keys_are_stable_and_distinct_and_each_duty_names_its_evidence():
    first, second = _owed(LIBRARY), _owed(LIBRARY, date(2027, 1, 1))
    assert [d.key for d in first] == [d.key for d in second]           # the same work, another day: the same keys
    assert len({d.key for d in first}) == len(first)
    assert "record_verdict:job=2026-02-01_mk4_pla_clip" in {d.key for d in first}
    assert "refit:bracket+clip@2026-01-04T10:00:00" in {d.key for d in first}
    for d in first:
        assert d.evidence and all("toml" in e or "print.json" in e for e in d.evidence)


def test_a_verdict_is_owed_after_a_print_and_not_once_it_is_judged(library):
    job = library / "print_jobs/2026-02-01_mk4_pla_clip/job.toml"
    assert "record_verdict:job=2026-02-01_mk4_pla_clip" in {d.key for d in _owed(library)}
    _edit(job, 'verdict = "pending"', 'verdict = "success"')
    assert "record_verdict:job=2026-02-01_mk4_pla_clip" not in {d.key for d in _owed(library)}


def test_item_verdicts_decide_a_job_that_has_none_of_its_own(library):
    job = library / "print_jobs/2026-03-05_mk4_pla_clip_pair/job.toml"
    _edit(job, "quantity = 2", 'quantity = 2\nverdict = "failed"')
    assert "record_verdict:job=2026-03-05_mk4_pla_clip_pair" not in {d.key for d in _owed(library)}
    _edit(job, 'verdict = "failed"', 'verdict = "pending"')
    duty = next(d for d in _owed(library) if d.key == "record_verdict:job=2026-03-05_mk4_pla_clip_pair")
    assert "pending: clip" in duty.why


def test_a_plan_is_owed_only_once_its_day_has_passed_and_never_when_cancelled(library):
    key = "print_by_plan:job=2026-03-01_mk4_petg_bracket_v2"
    assert key not in {d.key for d in _owed(library, date(2026, 3, 10))}     # on the day itself: not yet
    assert key in {d.key for d in _owed(library, date(2026, 3, 11))}
    job = library / "print_jobs/2026-03-01_mk4_petg_bracket_v2/job.toml"
    _edit(job, "quantity = 2", 'quantity = 2\n\n[outcome]\nverdict = "cancelled"')
    assert key not in {d.key for d in _owed(library, date(2026, 3, 11))}


def test_a_fit_is_owed_again_when_a_source_changes_once_for_both_parts(library):
    pair = lambda: [d for d in _owed(library) if d.kind == "refit" and d.subject["parts"] == ["bracket", "clip"]]
    (library / "parts/clip/source/clip.scad").write_text(OLD_CLIP)          # the clip that fit measured: not owed
    assert not pair()
    # the latch fit measured today's clip, so putting the old one back makes that fit owed instead
    assert [d.subject["changed"] for d in _owed(library) if d.subject.get("parts") == ["clip", "latch"]] == \
        [["parts/clip/source/clip.scad"]]
    _edit(library / "parts/bracket/source/bracket.py", "slot=4.2", "slot=4.4")
    assert len(pair()) == 1                                                  # recorded on both parts: one duty
    assert pair()[0].subject["changed"] == ["parts/bracket/source/bracket.py"]
    assert len(pair()[0].evidence) == 2
    (library / "parts/bracket/source/bracket.py").unlink()
    assert "no longer there" in pair()[0].why


def test_a_fit_without_snapshots_is_owed_because_it_cannot_say_whether_it_holds(library):
    for part, other in (("bracket", "clip"), ("clip", "bracket")):
        path = library / f"parts/{part}/part.toml"
        text = path.read_text()
        start = text.index("snapshots = [")
        path.write_text(text[:start] + text[text.index("]\n", start) + 2:])
    refit = [d for d in _owed(library) if d.kind == "refit" and d.subject["parts"] == ["bracket", "clip"]]
    assert len(refit) == 1 and "no snapshot" in refit[0].why


def test_a_manifest_fit_whose_sources_are_unchanged_owes_nothing_and_a_changed_one_does(library):
    assert not [d for d in _owed(library) if d.subject.get("parts") == ["clip", "latch"]]
    _edit(library / "projects/latch/source/latch.py", "hook=2.0", "hook=2.5")
    refit = [d for d in _owed(library) if d.subject.get("parts") == ["clip", "latch"]]
    assert len(refit) == 1 and refit[0].subject["changed"] == ["projects/latch/source/latch.py"]


# --- the command --------------------------------------------------------------------------------

def test_duties_lists_what_is_owed_with_its_evidence(capsys):
    assert _cli(["duties", str(LIBRARY), "--as-of", "2026-10-10"]) == 0
    out = capsys.readouterr().out
    assert "4 duty(ies) owed" in out and "as of 2026-10-10" in out
    assert "[record_verdict] record the verdict of job 2026-02-01_mk4_pla_clip" in out
    assert "[print_by_plan] print job 2026-03-01_mk4_petg_bracket_v2, planned for 2026-03-10" in out
    assert "from print_jobs/2026-02-01_mk4_pla_clip/job.toml  [outcome] date_printed" in out


def test_duties_json_and_as_of(capsys):
    assert _cli(["duties", str(LIBRARY), "--json", "--as-of", "2026-03-05"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema"] == "agentcad.duties/1" and data["as_of"] == "2026-03-05" and data["record_errors"] == 0
    assert "print_by_plan" not in {d["kind"] for d in data["duties"]}       # 2026-03-10 had not come yet


def test_duties_says_when_nothing_is_owed_and_warns_on_record_errors(library, capsys):
    for path in library.rglob("job.toml"):
        if "_templates" not in path.parts:
            path.unlink()
    (library / "parts/clip/source/clip.scad").write_text(OLD_CLIP)          # the bracket fit's clip ...
    shutil.rmtree(library / "projects")                                      # ... and no latch fit on today's
    assert _cli(["duties", str(library)]) == 0
    assert "Nothing owed" in capsys.readouterr().out
    _edit(library / "parts/bracket/part.toml", 'verdict = "pass"', 'verdict = "fine"')
    assert _cli(["duties", str(library)]) == 0
    assert "1 record error(s)" in capsys.readouterr().err


def test_duties_refuses_a_bad_date_and_a_path_without_records(tmp_path, capsys):
    assert _cli(["duties", str(LIBRARY), "--as-of", "soon"]) == 2
    assert _cli(["duties", str(tmp_path)]) == 2
    assert _cli(["duties", str(tmp_path / "nowhere")]) == 2
    err = capsys.readouterr().err
    assert "not a date" in err and "no part, job or fit records" in err and "does not exist" in err
