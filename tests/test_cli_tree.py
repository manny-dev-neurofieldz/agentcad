"""The command tree is a value other code can walk.

``build_parser()`` returns the whole tree, every leaf command has a handler and
help, every argument says what it is for, ``main()`` takes an argument list, and
a command module registers new commands (top level or under a group) without
editing cli.py, so parallel branches add commands without colliding.
"""

import argparse
import sys

import pytest

from agentcad import cli


def _walk(parser, path=(), help_text=None):
    """Yield (path, parser, help) for every leaf command."""
    subs = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    if not subs:
        yield path, parser, help_text
        return
    for action in subs:
        helps = {c.dest: c.help for c in action._choices_actions}
        for name, child in action.choices.items():
            yield from _walk(child, path + (name,), helps.get(name))


def _leaves():
    return list(_walk(cli.build_parser()))


def test_build_parser_returns_the_whole_tree():
    paths = {path for path, _, _ in _leaves()}
    for expected in (("render",), ("session", "iterate"), ("gcode", "check"),
                     ("probe", "draft"), ("gallery", "check"), ("fit",)):
        assert expected in paths
    assert len(paths) >= 33


def test_every_leaf_has_a_handler_and_help():
    for path, parser, help_text in _leaves():
        assert callable(parser.get_default("func")), f"{' '.join(path)} has no handler"
        assert help_text, f"{' '.join(path)} has no help"


def test_every_argument_says_what_it_is_for():
    missing = []
    for path, parser, _ in _leaves():
        for action in parser._actions:
            if isinstance(action, argparse._HelpAction):
                continue
            if not (action.help or "").strip():
                name = "/".join(action.option_strings) or action.dest
                missing.append(f"{' '.join(path)}: {name}")
    assert not missing, "arguments without help:\n" + "\n".join(missing)


def test_main_takes_an_argument_list(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert "agentcad" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 0
    assert "usage" in capsys.readouterr().out.lower()


def _command_package(tmp_path, monkeypatch, name, modules):
    pkg = tmp_path / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    for mod, body in modules.items():
        (pkg / f"{mod}.py").write_text(body)
    monkeypatch.syspath_prepend(str(tmp_path))
    __import__(name)
    return sys.modules[name]


HELLO = '''
def register(subparsers, groups):
    p = subparsers.add_parser("hello", help="Say hello")
    p.add_argument("--name", default="world", help="Who to greet")
    p.set_defaults(func=lambda a: print("hello " + a.name))
    e = groups["probe"].add_parser("echo", help="Echo under the probe group")
    e.set_defaults(func=lambda a: print("echo"))
'''


def test_a_command_module_registers_without_editing_cli(tmp_path, monkeypatch, capsys):
    pkg = _command_package(tmp_path, monkeypatch, "fake_commands_ok", {"hello": HELLO})
    parser = cli.build_parser(command_packages=[pkg])
    args = parser.parse_args(["hello", "--name", "agent"])
    args.func(args)
    args = parser.parse_args(["probe", "echo"])
    args.func(args)
    assert capsys.readouterr().out.split() == ["hello", "agent", "echo"]


def test_a_broken_command_module_is_reported_and_the_rest_still_work(tmp_path, monkeypatch, capsys):
    pkg = _command_package(tmp_path, monkeypatch, "fake_commands_broken",
                           {"a_broken": "raise RuntimeError('boom')\n", "hello": HELLO})
    parser = cli.build_parser(command_packages=[pkg])
    assert parser.parse_args(["hello"]).command == "hello"
    err = capsys.readouterr().err
    assert "a_broken" in err and "boom" in err
