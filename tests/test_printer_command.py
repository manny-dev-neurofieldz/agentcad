"""``agentcad printer``: the four commands against the fake PrusaLink, the exit statuses, the
downloads, and the promise that no credential is ever printed, logged, put in JSON or written.
"""

import argparse
import base64
import hashlib
import json
import logging
import os
import re

import pytest

from agentcad import cli, hosts
from agentcad import policy as pol
from tests.hostfakes import PASSWORD, USER, FakePrusaLink, default_tree, file_node, loopback_only  # noqa: F401

pytestmark = pytest.mark.usefixtures("loopback_only")


def run(argv, capsys):
    try:
        cli.main(argv)
        code = 0
    except SystemExit as e:
        code = e.code
    out, err = capsys.readouterr()
    return code, out, err


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A project folder as the working directory, an empty user config folder, no host variables set."""
    for key in [k for k in os.environ if k.startswith("AGENTCAD_PRUSALINK_")]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    folder = tmp_path / "project"
    folder.mkdir()
    (folder / "agentcad.toml").write_text('[project]\nname = "demo"\n')
    monkeypatch.chdir(folder)
    return folder


@pytest.fixture
def printer(project, monkeypatch):
    started = []

    def start(**options):
        fake = FakePrusaLink(**options)
        started.append(fake)
        monkeypatch.setenv("AGENTCAD_PRUSALINK_URL", fake.url)
        monkeypatch.setenv("AGENTCAD_PRUSALINK_USER", fake.user)
        monkeypatch.setenv("AGENTCAD_PRUSALINK_PASSWORD", fake.password)
        monkeypatch.setenv("AGENTCAD_PRUSALINK_TIMEOUT", "2")
        return fake
    yield start
    for fake in started:
        fake.close()


def test_list_files_and_status_print_text_and_json_with_a_schema(printer, capsys):
    printer()
    code, out, _ = run(["printer", "list"], capsys)
    assert code == 0 and out.splitlines()[0] == "prusalink: 1 printer(s)" and "bench-mk4  IDLE  nozzle 0.4 mm" in out
    code, out, _ = run(["printer", "files"], capsys)
    lines = out.splitlines()
    assert code == 0 and lines[0] == "usb:/: 4 item(s), newest first"
    assert "bracket_v2_x1_PETG_MK4_0.4n_0.2mm_PETG_MK4IS_44m.bgcode  [BRACKE~1.BGC]  195.3 KiB" in lines[1]
    assert "bracket_v2" in lines[1] and "bracket_v1" in lines[2] and "(folder)" in lines[4]       # newest first, folder last
    code, out, _ = run(["printer", "files", "--limit", "2", "--json"], capsys)
    record = json.loads(out)
    assert record["schema"] == "agentcad.printer.files/1" and record["host"] == "prusalink"
    assert record["total"] == 4 and len(record["entries"]) == 2 and record["entries"][0]["name"] == "BRACKE~1.BGC"
    code, out, _ = run(["printer", "files", "old"], capsys)
    assert code == 0 and "spare_part_0.15mm.bgcode  [SPARE~1.BGC]" in out and out.startswith("usb:/OLD: 1 item(s)")
    code, out, _ = run(["printer", "status"], capsys)
    assert code == 0 and out.splitlines()[0] == "prusalink: IDLE" and "nozzle 30.9/0 C, bed 31.3/0 C" in out and "no job" in out
    for sub, schema in (("list", "list"), ("status", "status")):
        code, out, _ = run(["printer", sub, "--json"], capsys)
        assert code == 0 and json.loads(out)["schema"] == f"agentcad.printer.{schema}/1"


def test_status_shows_the_running_job(printer, capsys):
    printer(printer_state="PRINTING", job={"id": 9, "progress": 12.5, "time_remaining": 3000,
                                           "file": {"name": "LID~1.BGC", "display_name": "lid.bgcode"}})
    code, out, _ = run(["printer", "status"], capsys)
    assert code == 0 and "job 9: lid.bgcode, 12.5%, 50 min left" in out


def test_get_writes_a_file_a_folder_entry_or_the_display_name_and_reports_the_hash(printer, project, capsys):
    printer()
    want = default_tree()[1]["data"]
    display = default_tree()[1]["display_name"]
    code, out, _ = run(["printer", "get", display, "-o", "fixtures/bracket.bgcode", "--json"], capsys)
    record = json.loads(out)
    assert code == 0 and record["schema"] == "agentcad.printer.get/1" and record["bytes"] == len(want)
    assert (project / "fixtures" / "bracket.bgcode").read_bytes() == want            # a missing folder is created
    assert record["sha256"] == hashlib.sha256(want).hexdigest() and record["output"] == str(project / "fixtures" / "bracket.bgcode")
    code, out, _ = run(["printer", "get", "BRACKE~1.BGC", "-o", "fixtures/"], capsys)   # a folder: the display name is kept
    assert code == 0 and (project / "fixtures" / display).read_bytes() == want
    assert f"{len(want)} bytes, sha256 {hashlib.sha256(want).hexdigest()}" in out
    code, out, _ = run(["printer", "get", "lid.bgcode"], capsys)                       # no -o: the current folder
    assert code == 0 and (project / "lid.bgcode").read_bytes() == default_tree()[2]["data"]
    assert not list(project.rglob("*.part"))


def test_get_does_not_replace_a_file_without_force_and_a_hostile_name_stays_in_the_folder(printer, project, capsys):
    printer(tree=[file_node("EVIL~1.BGC", "../../evil.bgcode", 5, b"payload"), file_node("DOTS~1.BGC", "..", 4, b"dots")])
    (project / "out").mkdir()
    code, out, err = run(["printer", "get", "EVIL~1.BGC", "-o", "out"], capsys)       # out is an existing folder
    assert code == 0 and (project / "out" / "evil.bgcode").read_bytes() == b"payload"
    assert not (project.parent / "evil.bgcode").exists()                              # not where ../../ would have put it
    code, out, err = run(["printer", "get", "EVIL~1.BGC", "-o", "out"], capsys)
    assert code == 2 and "evil.bgcode exists; use --force to replace it" in err and (project / "out" / "evil.bgcode").read_bytes() == b"payload"
    code, _, _ = run(["printer", "get", "EVIL~1.BGC", "-o", "out", "--force"], capsys)
    assert code == 0
    code, _, _ = run(["printer", "get", "DOTS~1.BGC", "-o", "out"], capsys)           # a name that is only dots falls back to the short name
    assert code == 0 and (project / "out" / "DOTS~1.BGC").read_bytes() == b"dots"
    assert sorted(p.name for p in (project / "out").iterdir()) == ["DOTS~1.BGC", "evil.bgcode"]


def test_a_failed_or_truncated_download_leaves_no_file_and_exit_status_says_why(printer, project, capsys):
    printer(truncate=True)
    code, out, err = run(["printer", "get", "BRACKE~1.BGC", "-o", "got.bgcode"], capsys)
    assert code == 1 and "incomplete reply" in err and out == ""
    assert not list(project.glob("got*")) and not list(project.rglob("*.part"))


def test_exit_statuses_and_one_line_messages(printer, project, monkeypatch, capsys):
    fake = printer()
    code, out, err = run(["printer"], capsys)
    assert code == 2 and err.startswith("Error: name a subcommand")
    code, out, err = run(["printer", "--host", "nope", "list"], capsys)
    assert code == 2 and "unknown printer host 'nope'; registered: prusalink" in err
    code, out, err = run(["printer", "get", "no-such-file.bgcode"], capsys)
    assert code == 1 and err.startswith("Error: no file named 'no-such-file.bgcode' on the printer") and err.count("\n") == 1
    monkeypatch.setenv("AGENTCAD_PRUSALINK_PASSWORD", "wrong-" + PASSWORD)
    code, out, err = run(["printer", "status"], capsys)
    assert code == 1 and "rejected the credentials (from environment)" in err
    monkeypatch.delenv("AGENTCAD_PRUSALINK_PASSWORD")
    code, out, err = run(["printer", "status"], capsys)
    assert code == 2 and "no password: set AGENTCAD_PRUSALINK_PASSWORD" in err
    monkeypatch.setenv("AGENTCAD_PRUSALINK_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("AGENTCAD_PRUSALINK_PASSWORD", PASSWORD)
    code, out, err = run(["printer", "status"], capsys)
    assert code == 1 and "cannot reach 127.0.0.1:1" in err


def test_a_group_readable_credentials_file_stops_every_command_with_the_fix(project, monkeypatch, capsys, tmp_path):
    folder = tmp_path / "xdg" / "agentcad"
    folder.mkdir(parents=True)
    path = folder / "hosts.toml"
    path.write_text(f'[prusalink]\nurl = "192.0.2.10"\nuser = "{USER}"\npassword = "{PASSWORD}"\n')
    path.chmod(0o640)
    for sub in ("list", "files", "get x", "status"):
        code, out, err = run(["printer", *sub.split()], capsys)
        assert code == 2 and f"chmod 600 {path}" in err and PASSWORD not in err + out and USER not in err + out
    path.chmod(0o600)
    with FakePrusaLink() as fake:
        path.write_text(f'[prusalink]\nurl = "{fake.url}"\nuser = "{fake.user}"\npassword = "{fake.password}"\n')
        code, out, err = run(["printer", "status"], capsys)                         # the file alone is enough
        assert code == 0 and "prusalink: IDLE" in out


def test_host_may_come_before_or_after_the_subcommand_and_a_host_without_a_capability_says_so(printer, capsys):
    printer()
    for argv in (["printer", "--host", "prusalink", "list"], ["printer", "list", "--host", "prusalink"]):
        assert run(argv, capsys)[0] == 0

    class Lister(hosts.PrinterHost):
        name = "lister"
        capabilities = frozenset({"list_files"})

        def list_files(self, path="", storage=None):
            return {"storage": "card", "path": path, "entries": []}

    hosts.register_host("lister", Lister)
    try:
        code, out, err = run(["printer", "--host", "lister", "files"], capsys)
        assert code == 0 and out.startswith("card:/: 0 item(s)")
        code, out, err = run(["printer", "files", "--host", "lister", "--json"], capsys)
        assert json.loads(out)["host"] == "lister"
        code, out, err = run(["printer", "--host", "lister", "status"], capsys)
        assert code == 2 and "host 'lister' does not job status (its capabilities: list_files)" in err
    finally:
        hosts.unregister_host("lister")


def _leaves_of(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from _leaves_of(v)
    elif isinstance(value, list):
        for v in value:
            yield from _leaves_of(v)
    else:
        yield str(value)


def test_credentials_never_appear_in_output_logs_json_or_files(printer, project, capsys, caplog, monkeypatch):
    """Every command, text and JSON, on success and on each kind of failure, with distinctive credentials:
    neither the user, the password, their Basic encoding, nor anything computed from them (the Digest
    response hashes, the client nonces) appears in what is printed, logged or written."""
    fake = printer()
    caplog.set_level(logging.DEBUG, logger="agentcad")
    runs = [["printer", "list"], ["printer", "files"], ["printer", "status"], ["printer", "get", "lid.bgcode", "-o", "a.bgcode"],
            ["printer", "list", "--json"], ["printer", "files", "--json"], ["printer", "status", "--json"],
            ["printer", "get", "lid.bgcode", "-o", "b.bgcode", "--json"], ["printer", "get", "nope", "--json"]]
    streams = []
    for argv in runs:
        code, out, err = run(argv, capsys)
        streams += [out, err]
        if "--json" in argv and code == 0:
            for leaf in _leaves_of(json.loads(out)):                                # no key or value is a credential
                assert leaf not in (USER, PASSWORD, "user", "password")
    for failing in (dict(password="wrong-" + PASSWORD), dict(url="http://127.0.0.1:1")):
        for name, value in failing.items():
            monkeypatch.setenv("AGENTCAD_PRUSALINK_" + name.upper(), value)
            streams += list(run(["printer", "status"], capsys)[1:])
            monkeypatch.setenv("AGENTCAD_PRUSALINK_" + name.upper(), {"password": PASSWORD, "url": fake.url}[name])
    fake.close()
    bad = printer(truncate=True, fail={"/api/v1/info": 500})
    streams += list(run(["printer", "get", "BRACKE~1.BGC", "-o", "c.bgcode"], capsys)[1:])
    streams += list(run(["printer", "list"], capsys)[1:])
    secrets = {USER, PASSWORD, base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode(), "wrong-" + PASSWORD}
    secrets |= fake.derived_secrets() | bad.derived_secrets()
    assert len(secrets) > 8 and any(len(s) == 32 for s in secrets)                   # the hashes were really collected
    assert any(r.name.startswith("agentcad") for r in caplog.records)                # there were log lines to look in
    haystack = "\n".join(streams + [r.getMessage() for r in caplog.records] + [str(r.args) for r in caplog.records])
    for secret in secrets:
        assert secret not in haystack, f"{secret[:6]}... leaked into output or logs"
    assert not re.search(r"Authorization|Digest username", haystack, re.I)
    for path in project.rglob("*"):                                                  # nothing written into the project holds one
        if path.is_file():
            content = path.read_bytes()
            assert not any(s.encode() in content for s in secrets), path


def test_the_policy_names_every_flag_and_claims_the_four_commands():
    p = pol.get_policy("printer-hosts")
    assert set(p.commands) == {("printer", "list"), ("printer", "files"), ("printer", "get"), ("printer", "status")}
    parser = cli.build_parser()
    printer_parser = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction)).choices["printer"]
    sub = next(a for a in printer_parser._actions if isinstance(a, argparse._SubParsersAction))
    missing = []
    for command in p.commands:
        for action in sub.choices[command[1]]._actions:
            if isinstance(action, argparse._HelpAction):
                continue
            missing += [o for o in action.option_strings if o not in p.text]
    assert not missing, f"flags the policy does not mention: {missing}"
    for variable in ("URL", "USER", "PASSWORD", "TIMEOUT", "STORAGE"):
        assert f"AGENTCAD_PRUSALINK_{variable}" in p.text


def test_a_tiny_file_shows_its_size_in_bytes(printer, capsys):
    printer(tree=[file_node("TINY~1.BGC", "tiny.bgcode", 100, b"abc", size=True)])
    code, out, _ = run(["printer", "files"], capsys)
    assert code == 0 and "tiny.bgcode  [TINY~1.BGC]  3 B" in out


def test_a_destination_that_cannot_be_written_is_exit_2_and_leaves_nothing(printer, project, monkeypatch, capsys):
    printer()
    (project / "a-file").write_text("not a folder")
    code, out, err = run(["printer", "get", "lid.bgcode", "-o", "a-file/inside.bgcode"], capsys)
    assert code == 2 and err.startswith("Error: cannot write ") and "a-file" in err
    import agentcad.commands.printer as command

    def failing_replace(src, dst):
        raise OSError(13, "Permission denied")
    monkeypatch.setattr(command.os, "replace", failing_replace)
    code, out, err = run(["printer", "get", "lid.bgcode", "-o", "never.bgcode"], capsys)
    assert code == 2 and "Permission denied" in err
    assert not (project / "never.bgcode").exists() and not list(project.glob("*.part"))
