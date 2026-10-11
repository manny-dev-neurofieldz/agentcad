"""Part, job and fit records: the structured fields, read and checked (``agentcad records check``)."""

import json
import shutil
from pathlib import Path

import pytest

from agentcad import records
from agentcad.cli import main

LIBRARY = Path(__file__).parent / "data" / "records_library"


@pytest.fixture
def library(tmp_path):
    """A copy of the fixture library to break one field at a time."""
    root = tmp_path / "library"
    shutil.copytree(LIBRARY, root)
    return root


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text, f"{old!r} not in {path}"
    path.write_text(text.replace(old, new, 1))


def _cli(argv):
    """The exit status of an agentcad command line (main exits only on a failure)."""
    try:
        return main(argv) or 0
    except SystemExit as e:
        return e.code


def _problems(root, severity=None):
    found = records.load(root).problems
    return [(p.severity, p.path, p.key, p.message) for p in found if severity is None or p.severity == severity]


def test_the_fixture_library_reads_clean_and_completely():
    found = records.load(LIBRARY)
    assert found.problems == []
    assert sorted(p.slug for p in found.parts) == ["bracket", "clip"]            # the template is not a part
    assert found.catalog == ["gasket"]
    jobs = {j.slug: j for j in found.jobs}
    assert len(jobs) == 5
    assert (jobs["2026-02-01_mk4_pla_clip"].staged, jobs["2026-02-01_mk4_pla_clip"].printed) == ("2026-02-01", "2026-02-01")
    assert jobs["2026-02-01_mk4_pla_clip"].verdict == "pending"
    assert jobs["2026-03-01_mk4_petg_bracket_v2"].planned == "2026-03-10"
    assert jobs["2026-03-01_mk4_petg_bracket_v2"].printed is None
    assert jobs["2026-03-02_form3_resin_gasket"].verdict == "cancelled"
    assert [(i.part, i.quantity) for i in jobs["2026-02-01_mk4_pla_clip"].items] == [("clip", 4)]
    fits = {(f.part, f.counterpart): f for f in found.fits}
    assert set(fits) == {("bracket", "clip"), ("clip", "bracket"), ("latch", "clip")}
    assert fits[("bracket", "clip")].recorded == "2026-01-04T10:00:00"
    assert fits[("clip", "bracket")].recorded == "2026-01-04T10:00:00"           # a string and a TOML date-time agree
    assert fits[("latch", "clip")].origin == "manifest"
    # every snapshot names its file from the checked folder, whichever folder the record names it from
    assert [s["file"] for s in fits[("clip", "bracket")].snapshots] == ["parts/bracket/source/bracket.py",
                                                                         "parts/clip/source/clip.scad"]
    assert [s["file"] for s in fits[("latch", "clip")].snapshots] == ["projects/latch/source/latch.py",
                                                                       "parts/clip/source/clip.scad"]


def test_the_expected_duties_fixture_names_records_that_exist():
    """The duties written down before any code derives them refer to jobs and parts the library has."""
    expected = json.loads((LIBRARY / "expected_duties.json").read_text())
    found = records.load(LIBRARY)
    jobs = {j.slug for j in found.jobs}
    parts = {p.slug for p in found.parts} | {f.part for f in found.fits}
    for duty in expected["duties"] + expected["not_owed"]:
        if "job" in duty:
            assert duty["job"] in jobs
        for part in duty.get("parts", duty.get("fit", [])):
            assert part in parts


@pytest.mark.parametrize("file, old, new, severity, key, says", [
    ("parts/bracket/part.toml", 'verdict = "pass"', 'verdict = "FITS at nominal"', "error", "[fit.clip] verdict",
     "verdict_note"),
    ("parts/bracket/part.toml", "recorded = 2026-01-04T10:00:00\n", "", "error", "[fit.clip] recorded", "when it was measured"),
    ("parts/bracket/part.toml", "recorded = 2026-01-04T10:00:00", 'recorded = "last week"', "error", "[fit.clip] recorded",
     "not a date"),
    ("parts/bracket/part.toml", 'counterpart = "clip"', 'counterpart = "bracket"', "error", "[fit.clip] counterpart",
     "does not fit itself"),
    ("parts/bracket/part.toml", 'sha256 = "66cff9', 'sha256 = "XYZ', "error", "[fit.clip] snapshots[0] sha256", "64"),
    ("parts/bracket/part.toml", 'path = "source/bracket.py"', 'path = "source/gone.py"', "warning",
     "[fit.clip] snapshots[0] path", "moved or gone"),
    ("parts/bracket/part.toml", 'state = "print-tested"', 'state = "done"', "error", "[status] state", "draft"),
    ("parts/bracket/part.toml", 'mates_with = ["clip"]', 'mates_with = ["clip", "hinge"]', "warning",
     "[relations] mates_with", "'hinge'"),
    ("parts/bracket/part.toml", 'mates_with = ["clip"]', 'mates_with = "clip"', "error", "[relations] mates_with",
     "list"),
    ("parts/bracket/part.toml", 'slug = "bracket"', 'slug = "bracket-2"', "warning", "[identity] slug", "folder name"),
    ("parts/clip/part.toml", 'slug = "clip"', 'slug = "bracket"', "error", "[identity] slug", "also the slug"),
    ("print_jobs/2026-01-05_mk4_pla_bracket/job.toml", 'verdict = "success"', 'verdict = "great"', "error",
     "[outcome] verdict", "result"),
    ("print_jobs/2026-01-05_mk4_pla_bracket/job.toml", 'date = "2026-01-05"', 'date = "next week"', "error",
     "[job] date", "not a date"),
    ("print_jobs/2026-01-05_mk4_pla_bracket/job.toml", 'date = "2026-01-05"\n', "", "error", "[job] date", "staged"),
    ("print_jobs/2026-01-05_mk4_pla_bracket/job.toml", 'date_printed = "2026-01-05"', 'date_printed = "2025-12-30"',
     "warning", "[outcome] date_printed", "before the day the job was staged"),
    ("print_jobs/2026-01-05_mk4_pla_bracket/job.toml", 'date_printed = "2026-01-05"', 'date_printed = ""', "error",
     "[outcome] verdict", "date_printed is empty"),
    ("print_jobs/2026-03-02_form3_resin_gasket/job.toml", 'verdict = "cancelled"',
     'verdict = "cancelled"\ndate_printed = "2026-03-03"', "error", "[outcome] verdict", "never printed"),
    ("print_jobs/2026-01-05_mk4_pla_bracket/job.toml", 'part = "bracket"', 'part = "wheel"', "warning",
     "[[item]] 1 part", "'wheel'"),
    ("print_jobs/2026-01-05_mk4_pla_bracket/job.toml", 'part = "bracket"', 'part = ""', "error", "[[item]] 1 part",
     "by slug"),
    ("print_jobs/2026-01-05_mk4_pla_bracket/job.toml", "quantity = 1", "quantity = 0", "error", "[[item]] 1 quantity",
     "at least 1"),
    ("print_jobs/2026-01-05_mk4_pla_bracket/job.toml", 'stl = "bracket.stl"', 'stl = "bracket_v9.stl"', "warning",
     "[[item]] 1 stl", "not in the job folder"),
    ("print_jobs/2026-03-01_mk4_petg_bracket_v2/job.toml", "quantity = 2", 'quantity = 2\nverdict = "success"', "error",
     "[[item]] 1 verdict", "date_printed is empty"),
    ("print_jobs/2026-03-01_mk4_petg_bracket_v2/job.toml", 'planned = "2026-03-10"', 'planned = "soon"', "error",
     "[job] planned", "not a date"),
    ("projects/latch/exports/latch.print.json", '"verdict": "pass"', '"verdict": "ok"', "error", "fit[0] verdict",
     "not one of"),
    ("projects/latch/exports/latch.print.json", '"sha256": "d97274e8', '"sha256": "d9', "error",
     "fit[0] snapshots[0] sha256", "64"),
])
def test_each_contract_rule_reports_at_its_file_and_key(library, file, old, new, severity, key, says):
    _edit(library / file, old, new)
    hits = [p for p in _problems(library) if p[1] == file and p[2] == key]
    assert hits, f"no problem at {file} {key}: {_problems(library)}"
    assert any(p[0] == severity and says in p[3] for p in hits), hits


def test_a_fit_recorded_on_one_side_only_is_reported_on_the_side_that_has_it(library):
    _edit(library / "parts/clip/part.toml", 'counterpart = "bracket"', 'counterpart = "gasket"')
    warned = _problems(library, "warning")
    assert ("warning", "parts/bracket/part.toml", "[fit.clip]") in [p[:3] for p in warned]
    assert any("recorded on this side only" in p[3] for p in warned)
    # a counterpart only the catalog knows is known: nothing to say about clip's fit itself
    assert not [p for p in warned if p[1] == "parts/clip/part.toml"]


def test_a_template_folder_and_a_hidden_folder_are_not_read(library):
    (library / ".cache").mkdir()
    shutil.copy(library / "_templates/part.toml", library / ".cache/part.toml")
    found = records.load(library)
    assert found.problems == [] and len(found.parts) == 2


def test_an_unreadable_record_is_an_error_and_the_rest_are_still_read(library):
    (library / "parts/clip/part.toml").write_text("[identity\nslug = ")
    found = records.load(library)
    assert ("error", "parts/clip/part.toml", "(file)") in [(p.severity, p.path, p.key) for p in found.problems]
    assert [p.slug for p in found.parts] == ["bracket"]
    assert len(found.jobs) == 5


def test_one_record_read_alone_checks_its_own_fields_only(library):
    found = records.load(library / "parts/bracket/part.toml")
    assert found.alone and found.problems == []          # its counterpart is elsewhere: not a warning
    assert [f.counterpart for f in found.fits] == ["clip"]
    _edit(library / "parts/bracket/part.toml", 'verdict = "pass"', 'verdict = "yes"')
    assert [p.key for p in records.load(library / "parts/bracket/part.toml").errors()] == ["[fit.clip] verdict"]
    with pytest.raises(ValueError):
        records.load(library / "catalog.toml")


def test_parse_when_reads_dates_and_date_times_and_nothing_else():
    from datetime import date, datetime
    assert records.parse_when("2026-03-06") == date(2026, 3, 6)
    assert records.parse_when("2026-03-06 23:28") == datetime(2026, 3, 6, 23, 28)
    assert records.parse_when(date(2026, 3, 6)) == date(2026, 3, 6)
    for bad in ("", "next week", "2026-13-01", 20260306, None):
        assert records.parse_when(bad) is None


# --- the command --------------------------------------------------------------------------------

def test_check_prints_what_it_read_and_exits_zero_on_the_clean_library(capsys):
    assert _cli(["records", "check", str(LIBRARY)]) == 0
    out = capsys.readouterr().out
    assert "2 part(s), 5 job(s) (3 printed, 2 without a verdict), 3 fit record(s)" in out
    assert "1 part(s) listed only in the catalog" in out
    assert "No problems" in out


def test_check_exits_one_on_an_error_and_names_it(library, capsys):
    _edit(library / "print_jobs/2026-01-05_mk4_pla_bracket/job.toml", 'verdict = "success"', 'verdict = "great"')
    assert _cli(["records", "check", str(library)]) == 1
    out = capsys.readouterr().out
    assert "1 error(s):" in out
    assert "print_jobs/2026-01-05_mk4_pla_bracket/job.toml [outcome] verdict: 'great' is not one of" in out


def test_check_exits_zero_with_warnings_only(library, capsys):
    _edit(library / "print_jobs/2026-01-05_mk4_pla_bracket/job.toml", 'part = "bracket"', 'part = "wheel"')
    assert _cli(["records", "check", str(library)]) == 0
    assert "1 warning(s):" in capsys.readouterr().out


def test_check_json_is_the_whole_reading(capsys):
    assert _cli(["records", "check", str(LIBRARY), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema"] == "agentcad.records/1"
    assert data["counts"] == {"parts": 2, "jobs": 5, "fits": 3, "catalog_only": 1, "errors": 0, "warnings": 0}
    assert data["references_checked"] is True
    assert {j["slug"] for j in data["jobs"] if j["verdict"] == "pending"} == {"2026-02-01_mk4_pla_clip"}


def test_check_exits_two_for_a_missing_path_a_folder_without_records_or_a_file_that_is_not_one(tmp_path, capsys):
    assert _cli(["records", "check", str(tmp_path / "nowhere")]) == 2
    assert _cli(["records", "check", str(tmp_path)]) == 2
    (tmp_path / "notes.toml").write_text("x = 1\n")
    assert _cli(["records", "check", str(tmp_path / "notes.toml")]) == 2
    err = capsys.readouterr().err
    assert "does not exist" in err and "no part, job or fit records" in err and "is not a record file" in err


def test_records_without_a_subcommand_says_what_to_name(capsys):
    assert _cli(["records"]) == 2
    assert "check" in capsys.readouterr().err
