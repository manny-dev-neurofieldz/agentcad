"""Owed work declared as duties on a role of the MacEff framework (https://github.com/cversek/MacEff), through a
stand-in for its command that keeps the role's duties in a file: what a dry run shows, what --apply declares,
that a second run declares nothing, and that a role that cannot be read is an error and never an empty role."""
import json
import os
import shutil
import stat
from datetime import date
from pathlib import Path

import pytest

from agentcad import duties, duty_roles, records
from agentcad.cli import main

LIBRARY = Path(__file__).parent / "data" / "records_library"
AS_OF = json.loads((LIBRARY / "expected_duties.json").read_text())["as_of"]

# A stand-in for the role commands the adapter uses: `role show ROLE --all --json` and
# `role duty add ROLE TITLE --body BODY`. State lives in $ROLE_STORE; $ROLE_FAIL makes it fail a named verb.
STAND_IN = r'''#!/usr/bin/env python3
import json, os, sys
store = os.environ["ROLE_STORE"]
state = json.load(open(store)) if os.path.exists(store) else {"id": "r1-keeper", "title": "Keeper", "duties": []}
argv = sys.argv[1:]
fail = os.environ.get("ROLE_FAIL", "")
if argv[:2] == ["role", "show"]:
    if fail == "show" or not "r1-keeper".startswith(argv[2]):
        print("no role " + argv[2], file=sys.stderr); sys.exit(1)
    assert argv[3:] == ["--all", "--json"], argv
    print("not json" if fail == "garbage" else json.dumps({"id": "r1-keeper"} if fail == "shape" else state))
elif argv[:3] == ["role", "duty", "add"]:
    if fail == "add":
        print("refused: a duty needs a title", file=sys.stderr); sys.exit(2)
    role, title, flag, body = argv[3:7]
    assert flag == "--body" and len(argv) == 7, argv
    state["duties"].append({"id": "d%d" % (len(state["duties"]) + 1), "title": title, "body": body, "state": "pending"})
    json.dump(state, open(store, "w"))
else:
    print("unexpected: " + " ".join(argv), file=sys.stderr); sys.exit(64)
'''


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "library"
    shutil.copytree(LIBRARY, root)
    return root


@pytest.fixture
def role(tmp_path, monkeypatch):
    """The stand-in on PATH as macf_tools; returns the file its duties are kept in."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    tool = bindir / "macf_tools"
    tool.write_text(STAND_IN)
    tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    store = tmp_path / "role.json"
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("ROLE_STORE", str(store))
    return store


def _cli(capsys, *argv):
    try:
        rc = main([str(a) for a in argv]) or 0
    except SystemExit as e:
        rc = e.code
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _owed(root):
    return duties.derive(records.load(root), date.fromisoformat(AS_OF))


def test_a_duty_body_ends_with_its_key_and_only_such_a_body_has_one(library):
    duty = _owed(library)[0]
    text = duty_roles.body(duty)
    assert text.split("\n")[-1] == "agentcad-duty: " + duty.key and duty.why.strip() in text
    assert all(("Read from: " + e) in text for e in duty.evidence)
    assert duty_roles.key_of(text) == duty.key
    assert duty_roles.key_of("written by hand") is None and duty_roles.key_of("") is None
    assert duty_roles.key_of("agentcad-duty: \n") is None


def test_a_dry_run_shows_what_is_missing_and_changes_nothing(library, role, capsys):
    owed = _owed(library)
    rc, out, err = _cli(capsys, "duties", library, "--as-of", AS_OF, "--declare-on", "r1")
    assert rc == 0 and not role.exists(), "nothing was declared"
    assert f"Role r1-keeper: {len(owed)} to declare, 0 already declared, 0 closed and owed again, 0 declared earlier and no longer owed." in out
    assert all(f"would declare: {d.title}  [{d.key}]" in out for d in owed) and "Add --apply" in out


def test_apply_declares_each_owed_duty_once_and_a_second_run_declares_nothing(library, role, capsys):
    owed = _owed(library)
    assert len(owed) >= 4
    rc, out, _ = _cli(capsys, "duties", library, "--as-of", AS_OF, "--declare-on", "r1", "--apply")
    assert rc == 0 and f"Role r1-keeper: {len(owed)} to declare" in out and "  declared: " in out
    stored = json.loads(role.read_text())["duties"]
    assert [d["title"] for d in stored] == [d.title for d in owed]
    assert [duty_roles.key_of(d["body"]) for d in stored] == [d.key for d in owed]
    before = role.read_text()
    rc, out, _ = _cli(capsys, "duties", library, "--as-of", AS_OF, "--declare-on", "r1", "--apply", "--json")
    report = json.loads(out)["roles"]
    assert rc == 0 and role.read_text() == before, "applying twice changes nothing"
    assert report["declared"] == 0 and report["declare"] == [] and len(report["present"]) == len(owed)
    assert report["applied"] is True and report["lapsed"] == [] and report["reopened"] == []
    assert report["role"] == "r1-keeper", "the role is reported as the roles command resolved the name given"


def test_work_no_longer_owed_is_reported_for_its_holder_and_never_closed_here(library, role, capsys):
    _cli(capsys, "duties", library, "--as-of", AS_OF, "--declare-on", "r1", "--apply")
    job = library / "print_jobs/2026-02-01_mk4_pla_clip/job.toml"
    text = job.read_text()
    assert 'verdict = "pending"' in text
    job.write_text(text.replace('verdict = "pending"', 'verdict = "success"', 1))
    before = role.read_text()
    rc, out, _ = _cli(capsys, "duties", library, "--as-of", AS_OF, "--declare-on", "r1", "--apply")
    assert rc == 0 and role.read_text() == before
    assert "1 declared earlier and no longer owed" in out
    assert "no longer owed by the records: duty d" in out and "record_verdict:job=2026-02-01_mk4_pla_clip" in out
    state = json.loads(before)
    lapsed = next(d for d in state["duties"] if "2026-02-01_mk4_pla_clip" in d["body"])
    lapsed["state"] = "done"           # its holder closed it
    role.write_text(json.dumps(state))
    rc, out, _ = _cli(capsys, "duties", library, "--as-of", AS_OF, "--declare-on", "r1")
    assert "0 declared earlier and no longer owed" in out, "a duty its holder closed is not reported again"


def test_work_owed_again_whose_duty_was_closed_is_its_own_list_and_is_not_reopened_here(library, role, capsys):
    _cli(capsys, "duties", library, "--as-of", AS_OF, "--declare-on", "r1", "--apply")
    state = json.loads(role.read_text())
    closed = state["duties"][0]
    for gone in ("done", "deferred"):
        closed["state"] = gone
        role.write_text(json.dumps(state))
        before = role.read_text()
        rc, out, _ = _cli(capsys, "duties", library, "--as-of", AS_OF, "--declare-on", "r1", "--apply")
        assert rc == 0 and role.read_text() == before, "nothing declared again and nothing reopened"
        assert "1 closed and owed again" in out and f"owed again, but its duty is {gone}: duty d1" in out
        assert f"{len(state['duties']) - 1} already declared" in out


def test_duties_declared_by_hand_are_left_out_of_every_count(library, role, capsys):
    role.write_text(json.dumps({"id": "r1-keeper", "duties": [{"id": "h1", "title": "By hand", "body": "", "state": "pending"}]}))
    rc, out, _ = _cli(capsys, "duties", library, "--as-of", AS_OF, "--declare-on", "r1")
    assert rc == 0 and "0 already declared, 0 closed and owed again, 0 declared earlier" in out and "h1" not in out


@pytest.mark.parametrize("fail, said", [("show", "role show r1 failed"), ("garbage", "did not give a role with duties"),
                                         ("shape", "did not give a role with duties")])
def test_a_role_that_cannot_be_read_is_an_error_and_nothing_is_declared(library, role, capsys, monkeypatch, fail, said):
    monkeypatch.setenv("ROLE_FAIL", fail)
    rc, out, err = _cli(capsys, "duties", library, "--as-of", AS_OF, "--declare-on", "r1", "--apply")
    assert rc == 2 and said in err and not out and not role.exists()


def test_a_refused_declaration_stops_the_run_with_the_tools_own_words(library, role, capsys, monkeypatch):
    monkeypatch.setenv("ROLE_FAIL", "add")
    rc, _, err = _cli(capsys, "duties", library, "--as-of", AS_OF, "--declare-on", "r1", "--apply")
    assert rc == 2 and "role duty add failed" in err and "a duty needs a title" in err


def test_without_the_roles_command_or_the_role_the_refusal_names_what_is_missing(library, role, capsys, monkeypatch):
    rc, _, err = _cli(capsys, "duties", library, "--as-of", AS_OF, "--declare-on", "nobody")
    assert rc == 2 and "role show nobody failed" in err and "no role nobody" in err
    rc, _, err = _cli(capsys, "duties", library, "--as-of", AS_OF, "--apply")
    assert rc == 2 and "--declare-on ROLE" in err
    monkeypatch.setenv("PATH", "/nonexistent")
    rc, _, err = _cli(capsys, "duties", library, "--as-of", AS_OF, "--declare-on", "r1")
    assert rc == 2 and "no macf_tools command on PATH" in err


def test_records_with_errors_show_a_plan_but_are_not_applied(library, role, capsys):
    job = library / "print_jobs/2026-02-01_mk4_pla_clip/job.toml"
    job.write_text(job.read_text().replace('date_printed = 2026-02-01', 'date_printed = "soon"', 1))
    assert records.load(library).errors()
    rc, out, err = _cli(capsys, "duties", library, "--as-of", AS_OF, "--declare-on", "r1")
    assert rc == 0 and "would declare" in out and "record error(s)" in err
    rc, out, err = _cli(capsys, "duties", library, "--as-of", AS_OF, "--declare-on", "r1", "--apply")
    assert rc == 2 and "duties are not declared from records" in err and not role.exists()
