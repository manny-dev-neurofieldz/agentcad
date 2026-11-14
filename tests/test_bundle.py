"""The bundle: agentcad read once into five layers, and every export target written from it. The claude-code
target is held to the bytes it wrote before the bundle existed; the maceff target (a policy root for the MacEff
framework, https://github.com/cversek/MacEff) to the shipped policies byte for byte; the tool definitions to the
real parser, which must accept the command line each one stands for."""
import argparse
import contextlib
import io
import json
import stat

import pytest

import agentcad
from agentcad import bundle, plugin, policy
from agentcad.bundle import Agent, Argument, Bundle, BundleError, Hook, PolicyDoc, Skill, Tool
from agentcad.cli import build_parser
from tests.gcode_fixtures import run_cli

FIXED = Bundle(
    name="agentcad", version="1.2.3", description="A fixed bundle", author=(("name", "A. Maker"), ("email", "a@b.c")),
    license="MIT",
    tools=(Tool(("probe", "rays"), "Rays.", (Argument("source", (), "A file", "value", required=True),)),),
    policies=(PolicyDoc("agentcad-one", "One", ("agentcad probe rays",),
                        "# One\n\n**Commands**: agentcad probe rays\n\n## Purpose\n\nP.\n\n## CEP Navigation Guide\n\n"
                        "**1 Rays**\n- What is a ray?\n\n=== CEP_NAV_BOUNDARY ===\n\n## 1 Rays\n\nA line.\n"),),
    skills=(Skill("walk", "Use when walking.", (("SKILL.md", b"---\nname: walk\n---\nWalk.\n"),)),),
    agents=(Agent("reviewer.md", b"---\nname: reviewer\n---\nReview.\n"),),
    hooks=(Hook("PostToolUse", "Bash", "post-tool-use"), Hook("SessionStart", None, "session-start")))


def _tree(root):
    return {str(p.relative_to(root)): (stat.S_IMODE(p.stat().st_mode), p.read_bytes() if p.is_file() else None)
            for p in sorted(root.rglob("*"))}


def test_a_fixed_bundle_writes_exactly_these_plugin_files():
    files = plugin.files_for(FIXED, "claude-code", with_marketplace=True)
    assert sorted(files) == [".claude-plugin/marketplace.json", ".claude-plugin/plugin.json", "agents/reviewer.md",
                             "hooks/hooks.json", "hooks/run.sh", "skills/walk/SKILL.md"]
    assert files[".claude-plugin/plugin.json"] == (
        b'{\n  "author": {\n    "email": "a@b.c",\n    "name": "A. Maker"\n  },\n  "description": "A fixed bundle",\n'
        b'  "license": "MIT",\n  "name": "agentcad",\n  "version": "1.2.3"\n}\n')
    assert json.loads(files["hooks/hooks.json"]) == {"hooks": {
        "PostToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": '"${CLAUDE_PLUGIN_ROOT}/hooks/run.sh" post-tool-use'}]}],
        "SessionStart": [{"hooks": [
            {"type": "command", "command": '"${CLAUDE_PLUGIN_ROOT}/hooks/run.sh" session-start'}]}]}}
    assert b'--plugin-version "1.2.3"' in files["hooks/run.sh"] and b"install agentcad 1.2.3" in files["hooks/run.sh"]
    assert files["skills/walk/SKILL.md"] == b"---\nname: walk\n---\nWalk.\n"
    assert files["agents/reviewer.md"] == b"---\nname: reviewer\n---\nReview.\n"
    market = json.loads(files[".claude-plugin/marketplace.json"])
    assert market["plugins"] == [{"name": "agentcad", "source": "./", "description": "A fixed bundle",
                                  "version": "1.2.3"}] and market["owner"] == {"email": "a@b.c", "name": "A. Maker"}


def test_the_package_is_read_into_five_layers():
    b = plugin.collect()
    assert b.name == "agentcad" and b.version == agentcad.__version__ and b.description
    assert [p.name for p in b.policies] == [p.name for p in policy.all_policies()] and len(b.policies) >= 20
    assert {s.name for s in b.skills} >= {"design-session", "fit-check", "review"}
    assert all(s.description.startswith("Use ") for s in b.skills), "a skill's description says when to use it"
    assert [a.filename for a in b.agents] == ["design-reviewer.md"]
    assert [(h.harness_event, h.event) for h in b.hooks] == [(e, ev) for e, _, ev in plugin.HOOKS]
    claimed = {c for p in b.policies for c in p.commands}
    assert {t.command for t in b.tools} <= claimed, "every tool's command is one a policy governs"


def test_every_leaf_command_is_a_tool_with_a_name_a_model_api_accepts():
    b = plugin.collect()
    paths = {path for path, _, _ in bundle.leaves(build_parser())}
    assert {t.path for t in b.tools} == paths and len(paths) >= 50
    assert len({t.name for t in b.tools}) == len(b.tools)
    for t in b.tools:
        assert bundle.TOOL_NAME.match(t.name) and t.name.startswith("agentcad_") and t.help, t.command
        schema = bundle.tool_schema(t)
        assert set(schema) == {"name", "description", "input_schema"}
        assert schema["description"].endswith(f"Runs: {t.command}.")
        inp = schema["input_schema"]
        assert inp["type"] == "object" and inp["additionalProperties"] is False
        assert inp["required"] == [a.name for a in t.arguments if a.required]
        assert list(inp["properties"]) == [a.name for a in t.arguments]
        for name, prop in inp["properties"].items():
            assert prop["type"] in ("boolean", "string", "integer", "number", "array") and prop["description"], name
            if prop["type"] == "array":
                assert prop["items"]["type"] in ("string", "integer", "number")


def test_a_schema_requires_what_the_command_requires_and_no_more():
    it = next(t for t in plugin.collect().tools if t.path == ("session", "iterate"))
    inp = bundle.tool_schema(it)["input_schema"]
    assert inp["required"] == ["project", "source_file"]
    assert inp["properties"]["define"]["type"] == "array" and inp["properties"]["all"]["type"] == "boolean"
    assert inp["properties"]["define"]["description"].endswith("(-D, --define)")
    assert inp["properties"]["project"]["description"].endswith("(positional)")


def test_the_tool_schemas_are_valid_json_schema():
    jsonschema = pytest.importorskip("jsonschema")
    for t in plugin.collect().tools:
        jsonschema.Draft202012Validator.check_schema(bundle.tool_schema(t)["input_schema"])


def _sample(a):
    v = a.choices[0] if a.choices else {"integer": 3, "number": 1.5}.get(a.type, "x")
    return True if a.kind == "flag" else [v, v] if a.kind == "list" else v


@pytest.mark.parametrize("everything", [False, True], ids=["required only", "every argument"])
def test_the_real_parser_accepts_the_command_line_each_tool_call_stands_for(everything):
    parser = build_parser()
    for t in plugin.collect().tools:
        values = {a.name: _sample(a) for a in t.arguments if a.required or everything}
        argv = bundle.argv_for(t, values)
        assert tuple(argv[:len(t.path)]) == t.path
        try:
            ns = parser.parse_args(argv)
        except SystemExit:
            if everything:      # some options exclude each other; the required-only pass holds every command
                continue
            raise AssertionError(f"{t.command}: the parser refused {argv}")
        for name, v in values.items():
            got = getattr(ns, name)
            assert (list(got) == list(v)) if isinstance(v, list) else got == v, (t.command, name, got, v)


def test_each_list_option_alone_still_leaves_the_positionals_to_the_command():
    """An option that takes several values, written last, would swallow the positionals after it: each list option
    is given alone, beside the required arguments, and the parser must accept the line and return every value."""
    parser = build_parser()
    tried = 0
    for t in plugin.collect().tools:
        required = {a.name: _sample(a) for a in t.arguments if a.required}
        for a in t.arguments:
            if a.kind != "list" or a.required:
                continue
            values = dict(required, **{a.name: _sample(a)})
            argv = bundle.argv_for(t, values)
            try:
                ns = parser.parse_args(argv)
            except SystemExit:
                raise AssertionError(f"{t.command}: the parser refused {argv}")
            for name, v in values.items():
                got = getattr(ns, name)
                assert (list(got) == list(v)) if isinstance(v, list) else got == v, (t.command, name, got, v)
            tried += 1
    assert tried >= 20, "the list options of the command tree were all tried"


def test_a_call_becomes_options_in_the_commands_order_then_positionals():
    it = next(t for t in plugin.collect().tools if t.path == ("session", "iterate"))
    argv = bundle.argv_for(it, {"all": True, "source_file": "part.py", "project": "bracket", "define": ["w=3", "h=4"]})
    assert argv == ["session", "iterate", "--define=w=3", "--define=h=4", "--all", "--", "bracket", "part.py"]
    ns = build_parser().parse_args(argv)
    assert (ns.project, ns.source_file, ns.define, ns.all) == ("bracket", "part.py", ["w=3", "h=4"], True)
    assert bundle.argv_for(it, {"project": "b", "source_file": "p.py", "all": False}) == ["session", "iterate", "--", "b", "p.py"]
    assert bundle.argv_for(it, {"project": "b", "source_file": "-odd.py"})[-3:] == ["--", "b", "-odd.py"]
    section = next(t for t in plugin.collect().tools if t.path == ("probe", "section"))
    argv = bundle.argv_for(section, {"source": "part.scad", "planes": ["z=1", "z=2"]})
    assert argv == ["probe", "section", "--planes", "z=1", "z=2", "--", "part.scad"]
    ns = build_parser().parse_args(argv)
    assert (ns.source, ns.planes) == ("part.scad", ["z=1", "z=2"])
    rays = next(t for t in plugin.collect().tools if t.path == ("probe", "rays"))
    argv = bundle.argv_for(rays, {"source": "part.step", "length": 4.5})
    assert "--length=4.5" in argv


def test_a_value_that_starts_with_a_dash_reaches_its_option_and_is_not_read_as_another():
    """Every option with one value, and every repeated option, given a value that starts with a dash (-5 for a
    number, -odd for a name): the value must reach its option, where "--window -odd" reads as an option with no
    value. The option may still refuse it by its own check (a distance is 0 or more), and then its refusal names
    the value; it may never say the option got no value."""
    parser = build_parser()
    tried = judged = 0
    for t in plugin.collect().tools:
        required = {a.name: _sample(a) for a in t.arguments if a.required}
        for a in t.arguments:
            if not a.flags or a.kind == "flag" or a.choices or (a.kind == "list" and not a.repeat):
                continue
            dashed = {"integer": -5, "number": -5.0}.get(a.type, "-odd")
            values = dict(required, **{a.name: [dashed] if a.kind == "list" else dashed})
            argv = bundle.argv_for(t, values)
            said = io.StringIO()
            try:
                with contextlib.redirect_stderr(said):
                    ns = parser.parse_args(argv)
            except SystemExit:
                text = said.getvalue()
                assert "expected one argument" not in text and "unrecognized" not in text, (t.command, argv, text)
                assert str(dashed) in text.splitlines()[-1], (t.command, argv, text)
                judged += 1
            else:
                got = getattr(ns, a.name)
                assert (list(got) if a.kind == "list" else got) == values[a.name], (t.command, a.name, got)
            tried += 1
    assert tried >= 40 and judged < tried, "the single-valued and repeated options of the command tree were all tried"


@pytest.mark.parametrize("values, said", [
    ({"project": "b", "source_file": "p.py", "colour": "red"}, "no argument colour"),
    ({"project": "b"}, "needs source_file"),
    ({"project": "b", "source_file": "p.py", "all": "yes"}, "all is a flag"),
    ({"project": "b", "source_file": "p.py", "define": "w=3"}, "define takes a list"),
])
def test_a_call_the_command_cannot_take_is_refused_by_name(values, said):
    it = next(t for t in plugin.collect().tools if t.path == ("session", "iterate"))
    with pytest.raises(BundleError, match=said):
        bundle.argv_for(it, values)


def test_two_commands_that_make_one_tool_name_are_refused():
    parser = argparse.ArgumentParser(prog="agentcad")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("new-project", help="a")
    sub.add_parser("new_project", help="b")
    with pytest.raises(BundleError, match="two commands make the tool name"):
        bundle.tools_of(parser)


def test_the_maceff_target_is_the_shipped_policies_byte_for_byte_and_reads_as_policies(tmp_path):
    out = tmp_path / "root"
    plugin.export(out, target="maceff")
    shipped = {p.name: p.text.encode("utf-8") for p in policy.all_policies()}
    exported = {f.stem: f.read_bytes() for f in (out / "policies").iterdir()}
    assert exported == shipped and all(name.startswith("agentcad-") for name in exported)
    for f in (out / "policies").iterdir():
        guide, _ = policy.navigation(f.read_text(encoding="utf-8"))
        assert any(line.startswith("**1 ") for line in guide), f"{f.name} has a navigation guide a reader finds"
    readme = (out / "README.md").read_text()
    assert plugin.MACEFF_LINK in readme and "MACEFF_POLICY_ROOTS=agentcad=" in readme and "copy" in readme
    assert json.loads((out / plugin.MARKER).read_text()) == {"name": "agentcad", "target": "maceff",
                                                              "version": agentcad.__version__}
    assert not [p for p in out.rglob("*.md") if p.parent == out / "policies" and p.name == "README.md"], \
        "nothing but policies in the folder that is mounted"


def test_the_agents_file_names_every_command_policy_and_skill_and_copies_no_policy_content(tmp_path):
    out = tmp_path / "a"
    plugin.export(out, target="agents-md")
    text = (out / "AGENTS.md").read_text(encoding="utf-8")
    b = plugin.collect()
    for t in b.tools:
        assert f"`{t.command}`" in text
    for p in b.policies:
        assert f"### {p.name}: " in text
    for s in b.skills:
        assert f"**{s.name}**" in text
    assert "agentcad policy read <name> --section <number>" in text
    assert policy.BOUNDARY not in text and "## Purpose" not in text, "guides only: the content stays in the command"
    assert "- Which targets are there, and what does each flag do?" in text, "a guide's questions are carried whole"


def test_the_api_tools_target_holds_one_definition_per_command_and_says_how_a_call_runs(tmp_path):
    out = tmp_path / "t"
    plugin.export(out, target="api-tools")
    tools = json.loads((out / "tools.json").read_text())
    assert [t["name"] for t in tools] == [t.name for t in plugin.collect().tools] and len(tools) >= 50
    readme = (out / "README.md").read_text()
    assert "agentcad.bundle.argv_for" in readme and "(positional)" in readme and "tools.json" in readme


@pytest.mark.parametrize("target", ["maceff", "agents-md", "api-tools"])
def test_each_target_exports_the_same_bytes_replaces_its_own_earlier_export_and_no_other(tmp_path, target):
    a, b = tmp_path / "a", tmp_path / "b"
    plugin.export(a, target=target)
    plugin.export(b, target=target)
    assert _tree(a) == _tree(b)
    assert {mode for mode, data in _tree(a).values() if data is not None} == {0o644}
    stale = next(p for p in sorted(a.rglob("*")) if p.is_file() and p.name != plugin.MARKER)
    stale.write_text("stale")
    plugin.export(a, target=target)
    assert _tree(a) == _tree(b), "an earlier export for the same target is replaced whole"
    other = "api-tools" if target != "api-tools" else "maceff"
    before = _tree(a)
    with pytest.raises(plugin.PluginError, match="does not write|not an earlier agentcad export"):
        plugin.export(a, target=other)
    with pytest.raises(plugin.PluginError, match="does not write|not an earlier agentcad export"):
        plugin.export(a, target="claude-code")
    assert _tree(a) == before, "nothing removed or written"
    with pytest.raises(plugin.PluginError, match="only the claude-code target has a marketplace"):
        plugin.export(tmp_path / "m", target=target, with_marketplace=True)
    assert not (tmp_path / "m").exists()


def test_a_folder_marked_as_another_targets_export_is_not_replaced(tmp_path):
    out = tmp_path / "o"
    out.mkdir()
    (out / plugin.MARKER).write_text(json.dumps({"name": "agentcad", "target": "maceff", "version": "0"}))
    (out / "README.md").write_text("the maceff export's note")
    before = _tree(out)
    with pytest.raises(plugin.PluginError, match="not an earlier agentcad export"):
        plugin.export(out, target="api-tools")
    assert _tree(out) == before
    (out / plugin.MARKER).write_text(json.dumps({"name": "agentcad", "target": "api-tools", "version": "0"}))
    plugin.export(out, target="api-tools")
    assert (out / "tools.json").is_file()


def test_the_command_writes_each_target_and_says_how_to_use_it(tmp_path, capsys):
    rc, printed, _ = run_cli(capsys, "plugin", "export", "--target", "maceff", "-o", tmp_path / "m")
    assert rc == 0 and f"MACEFF_POLICY_ROOTS=agentcad={tmp_path / 'm'}/policies" in printed
    assert str(policy.policy_dir()) in printed, "the installed folder, which never goes stale, is named too"
    rc, printed, _ = run_cli(capsys, "plugin", "export", "--target", "agents-md", "-o", tmp_path / "a")
    assert rc == 0 and "AGENTS.md" in printed
    rc, printed, _ = run_cli(capsys, "plugin", "export", "--target", "api-tools", "-o", tmp_path / "t")
    assert rc == 0 and "tools.json" in printed
    rc, _, err = run_cli(capsys, "plugin", "export", "--target", "api-tools", "-o", tmp_path / "x", "--marketplace")
    assert rc == 2 and "only the claude-code target has a marketplace" in err and not (tmp_path / "x").exists()
