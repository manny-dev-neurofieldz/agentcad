"""The plugin's hooks: what each answers to a harness's payload (context, a refusal, or nothing), through the
function, through ``agentcad plugin hook`` and through the exported runner script."""
import io
import json
import os
import subprocess

import pytest

import agentcad
from agentcad import plugin, plugin_hooks
from tests.gcode_fixtures import run_cli


def _session(folder, warnings=(), findings=(), images=None, number=3):
    """A project folder holding the session record an iterate leaves."""
    work = folder / "_work"
    work.mkdir(parents=True)
    record = {"iterations": [{"number": 1, "report": {"warnings": ["an old warning"]}, "image_paths": {}},
                             {"number": number, "report": {"warnings": list(warnings)},
                              "judgments": {"findings": list(findings)},
                              "image_paths": images or {}}]}
    (work / "session.json").write_text(json.dumps(record))
    return folder


def _bash(command, cwd):
    return {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


def _edit(tool, path, cwd=None, key="file_path"):
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {key: str(path)}, "cwd": str(cwd or "/")}


def test_session_start_is_silent_at_the_plugins_version_and_names_both_versions_otherwise():
    assert plugin_hooks.run("session-start", {}, agentcad.__version__) is None
    assert plugin_hooks.run("session-start", {}, None) is None
    out = plugin_hooks.run("session-start", {}, "9.9.9")["hookSpecificOutput"]
    assert out["hookEventName"] == "SessionStart"
    assert "9.9.9" in out["additionalContext"] and agentcad.__version__ in out["additionalContext"]
    assert out["additionalContext"].endswith(plugin_hooks.WHY)
    assert "agentcad policy navigate agentcad-plugin" in plugin_hooks.WHY and not any(c.isdigit() for c in plugin_hooks.WHY)


def test_after_an_iterate_the_session_is_told_the_last_iterations_warnings_findings_and_renders(tmp_path):
    _session(tmp_path / "bracket", warnings=["2 solids: the part is in two pieces"],
             findings=[{"rule": "solid_count", "severity": "warning", "message": "2 solids: the part is in two pieces"},
                       {"rule": "min_wall", "severity": "error", "sentence": "wall 0.3 mm is under 0.8 mm."},
                       {"rule": "build_volume", "severity": "ok", "sentence": "fits the bed."}],
             images={"iso": "/x/v3_iso.png", "top": "/x/v3_top.png"})
    out = plugin_hooks.run("post-tool-use", _bash("agentcad session iterate bracket part.py -D w=3", tmp_path))
    text = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert "iteration 3 of bracket" in text and "an old warning" not in text
    assert "tray: 2 solids: the part is in two pieces" in text and text.count("2 solids") == 1, "a tray warning once"
    assert "min_wall: wall 0.3 mm is under 0.8 mm." in text and "fits the bed" not in text
    assert "2 warning(s) and finding(s)" in text
    assert "/x/v3_iso.png, /x/v3_top.png" in text and "before the next iterate" in text


def test_a_long_list_is_cut_with_the_count_left_and_a_clean_iteration_says_so(tmp_path):
    _session(tmp_path / "many", warnings=[f"warning {i}" for i in range(11)])
    text = plugin_hooks.run("post-tool-use", _bash("cd x && agentcad session iterate many p.py", tmp_path))[
        "hookSpecificOutput"]["additionalContext"]
    assert "warning 7" in text and "warning 8" not in text and "and 3 more: agentcad session status many" in text
    _session(tmp_path / "clean")
    text = plugin_hooks.run("post-tool-use", _bash("/opt/bin/agentcad session iterate clean p.py", tmp_path))[
        "hookSpecificOutput"]["additionalContext"]
    assert "No tray warnings or findings." in text


@pytest.mark.parametrize("payload", [
    {"tool_name": "Bash", "tool_input": {"command": "agentcad session status bracket"}},
    {"tool_name": "Bash", "tool_input": {"command": "agentcad session iterate nowhere p.py"}},
    {"tool_name": "Bash", "tool_input": {"command": "agentcad session iterate 'unclosed"}},
    {"tool_name": "Read", "tool_input": {"command": "agentcad session iterate bracket p.py"}},
    {"tool_name": "Bash"},
])
def test_other_calls_and_projects_without_a_record_get_no_context(tmp_path, payload):
    _session(tmp_path / "bracket", warnings=["w"])
    assert plugin_hooks.run("post-tool-use", dict(payload, cwd=str(tmp_path))) is None


def _library(root, table):
    root.mkdir(parents=True, exist_ok=True)
    (root / "agentcad.toml").write_text(table)
    (root / "parts" / "arm" / "source").mkdir(parents=True)
    return root


def test_an_edit_of_a_guarded_file_is_denied_with_the_librarys_practice(tmp_path):
    lib = _library(tmp_path / "lib", '[library]\nguarded = ["parts/*/source/*", "CATALOG.md"]\n'
                                      'practice = "Copy the part to a new revision folder and edit the copy."\n')
    for tool, key in (("Edit", "file_path"), ("Write", "file_path"), ("MultiEdit", "file_path"),
                      ("NotebookEdit", "notebook_path")):
        out = plugin_hooks.run("pre-tool-use", _edit(tool, lib / "parts/arm/source/arm.py", key=key))
        got = out["hookSpecificOutput"]
        assert got["hookEventName"] == "PreToolUse" and got["permissionDecision"] == "deny", tool
        assert "parts/arm/source/arm.py is guarded" in got["permissionDecisionReason"]
        assert "Copy the part to a new revision folder" in got["permissionDecisionReason"]
        assert got["permissionDecisionReason"].endswith(plugin_hooks.WHY), "a refusal says where its reasoning lives"
    relative = plugin_hooks.run("pre-tool-use", _edit("Write", "CATALOG.md", cwd=lib))
    assert relative["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_edits_outside_the_guarded_patterns_and_other_tools_pass_untouched(tmp_path):
    lib = _library(tmp_path / "lib", '[library]\nguarded = "parts/*/source/*"\n')
    assert plugin_hooks.run("pre-tool-use", _edit("Edit", lib / "parts/arm/notes.md")) is None
    assert plugin_hooks.run("pre-tool-use", _edit("Edit", tmp_path / "elsewhere.py")) is None
    assert plugin_hooks.run("pre-tool-use", _edit("Bash", lib / "parts/arm/source/arm.py")) is None
    assert plugin_hooks.run("pre-tool-use", {"tool_name": "Edit", "tool_input": {}}) is None
    reason = plugin_hooks.run("pre-tool-use", _edit("Edit", lib / "parts/arm/source/arm.py"))[
        "hookSpecificOutput"]["permissionDecisionReason"]
    assert "the library's own notes" in reason, "without a practice the reason still says what to do"
    plain = _library(tmp_path / "plain", '[project]\nname = "x"\n')
    assert plugin_hooks.run("pre-tool-use", _edit("Edit", plain / "parts/arm/source/arm.py")) is None


def test_a_config_that_does_not_parse_is_said_on_stderr_and_the_next_one_up_still_guards(tmp_path, capsys):
    lib = _library(tmp_path / "lib", '[library]\nguarded = ["parts/*"]\n')
    (lib / "parts" / "agentcad.toml").write_text("not = [toml")
    out = plugin_hooks.run("pre-tool-use", _edit("Edit", lib / "parts/arm/source/arm.py"))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    err = capsys.readouterr().err
    assert "parts/agentcad.toml cannot be read" in err and "guard it may hold is not applied" in err


def test_a_session_record_that_does_not_parse_is_said_on_stderr_and_gives_no_context(tmp_path, capsys):
    _session(tmp_path / "bracket")
    (tmp_path / "bracket" / "_work" / "session.json").write_text("{half")
    assert plugin_hooks.run("post-tool-use", _bash("agentcad session iterate bracket p.py", tmp_path)) is None
    assert "session.json cannot be read" in capsys.readouterr().err


def test_the_command_answers_on_stdout_and_says_a_bad_payload_on_stderr(tmp_path, capsys, monkeypatch):
    lib = _library(tmp_path / "lib", '[library]\nguarded = ["parts/*"]\n')
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(_edit("Edit", lib / "parts/arm/x.py"))))
    rc, out, err = run_cli(capsys, "plugin", "hook", "pre-tool-use")
    assert rc == 0 and json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny" and not err
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(_edit("Edit", tmp_path / "free.py"))))
    assert run_cli(capsys, "plugin", "hook", "pre-tool-use") == (0, "", "")
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert run_cli(capsys, "plugin", "hook", "session-start", "--plugin-version", agentcad.__version__) == (0, "", "")
    monkeypatch.setattr("sys.stdin", io.StringIO("{not json"))
    rc, out, err = run_cli(capsys, "plugin", "hook", "post-tool-use")
    assert rc == 1 and not out and "not JSON" in err
    assert run_cli(capsys, "plugin", "hook", "no-such-event")[0] == 2
    with pytest.raises(ValueError, match="no hook"):
        plugin_hooks.run("no-such-event", {})


def _run_runner(tmp_path, event, path_dirs):
    out = tmp_path / "plug"
    if not out.exists():
        plugin.export(out)
    return subprocess.run([str(out / "hooks" / "run.sh"), event], input="{}", capture_output=True, text=True,
                          env={"PATH": os.pathsep.join(path_dirs)}, timeout=30)


def test_the_runner_hands_the_event_to_the_installed_command_with_the_plugins_version(tmp_path):
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "agentcad").write_text('#!/bin/sh\necho "called: $*"\n')
    (fake / "agentcad").chmod(0o755)
    done = _run_runner(tmp_path, "pre-tool-use", [str(fake), "/usr/bin", "/bin"])
    assert done.returncode == 0
    assert done.stdout.strip() == f"called: plugin hook pre-tool-use --plugin-version {agentcad.__version__}"


def test_without_the_command_the_runner_says_so_once_at_session_start_and_is_silent_otherwise(tmp_path):
    done = _run_runner(tmp_path, "session-start", ["/usr/bin", "/bin"])
    said = json.loads(done.stdout)["hookSpecificOutput"]
    assert done.returncode == 0 and said["hookEventName"] == "SessionStart"
    assert "no agentcad command is on PATH" in said["additionalContext"] and agentcad.__version__ in said["additionalContext"]
    for event in ("post-tool-use", "pre-tool-use"):
        done = _run_runner(tmp_path, event, ["/usr/bin", "/bin"])
        assert (done.returncode, done.stdout, done.stderr) == (0, "", ""), event
