"""Policies ship with each capability: the reader, the contract and the lints.

Parity: agentcad's reader extracts exactly what a reference reader of the same
format extracts from the same files (goldens in ``tests/data/policy_golden/``).
Contract: every leaf command is governed by at most one policy, and a command
no policy governs must be on a frozen allow-list that may only shrink, so a
new command arrives with its policy. Lints: every packaged policy is ASCII,
names no absolute path or particular person or lab, keeps fences at column 0,
carries the header fields, and numbers its content like its navigation guide.
"""

import argparse
import json
import re
from pathlib import Path

import pytest

from agentcad import cli, policy as pol

DATA = Path(__file__).resolve().parent / "data"
GOLDENS = json.loads((DATA / "policy_golden" / "goldens.json").read_text())

# Leaf commands no policy governed when the policy format arrived. A command may
# leave this list (its policy written) but never join it: a new command ships
# with its policy.
UNCLAIMED_ALLOWED = {
    ("render",), ("export",), ("info",), ("new-project",), ("projects",), ("status",), ("open",),
    ("config-init",), ("config-show",), ("probe", "section"),
    ("probe", "fillet"), ("probe", "draft"), ("compare",), ("fit",), ("gallery", "build"),
    ("gallery", "check"), ("viewer",), ("check",),
}

LAB_NAMES = re.compile(r"\b(Manny|Craig|NeuroFieldz|Dropbox|pa_manny\w*)\b")
ABS_PATH = re.compile(r"(^|[\s(`'\"])/(home|opt|tmp|Users|shared_workspace|mnt|var)/")


def _text(name):
    if name == "policy_fixture.md":
        return (DATA / name).read_text()
    return pol.get_policy(name[:-3]).text


def _numbered(first, lines):
    return [[n, line] for n, line in enumerate(lines, first)]


# --- parity with the reference reader ------------------------------------------------------

@pytest.mark.parametrize("name", sorted(GOLDENS))
def test_navigation_matches_the_reference(name):
    lines, _ = pol.navigation(_text(name))
    assert _numbered(1, lines) == GOLDENS[name]["navigate"]["lines"]


@pytest.mark.parametrize("name,number", [(n, s) for n in sorted(GOLDENS) for s in GOLDENS[n]["sections"]])
def test_sections_match_the_reference(name, number):
    golden = GOLDENS[name]["sections"][number]
    assert golden["rc"] == 0
    first, lines = pol.section(_text(name), number)
    assert _numbered(first, lines) == golden["lines"]


@pytest.mark.parametrize("name", sorted(GOLDENS))
def test_boundary_and_line_reads_match_the_reference(name):
    first, lines = pol.after_boundary(_text(name))
    assert _numbered(first, lines) == GOLDENS[name]["from_nav_boundary"]["lines"]
    first, lines = pol.line_range(_text(name), "3:9")
    assert _numbered(first, lines) == GOLDENS[name]["lines_3_9"]["lines"]


def test_a_missing_section_is_a_named_error():
    with pytest.raises(pol.PolicyError, match="section 7 not found"):
        pol.section(_text("policy_fixture.md"), "7")


# --- the contract ------------------------------------------------------------------

def _leaves(parser, path=()):
    subs = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    if not subs:
        yield path
        return
    for action in subs:
        for name, child in action.choices.items():
            yield from _leaves(child, path + (name,))


def _claims():
    claims = {}
    for p in pol.all_policies():
        for command in p.commands:
            claims.setdefault(command, []).append(p.name)
    return claims


def test_every_command_is_governed_by_at_most_one_policy():
    doubled = {c: names for c, names in _claims().items() if len(names) > 1}
    assert not doubled, f"commands claimed by several policies: {doubled}"


def test_a_command_without_a_policy_must_be_on_the_frozen_list():
    claimed = set(_claims())
    unclaimed = set(_leaves(cli.build_parser())) - claimed
    newcomers = unclaimed - UNCLAIMED_ALLOWED
    assert not newcomers, ("new commands without a policy (write one; do not extend the list): "
                           + ", ".join(" ".join(c) for c in sorted(newcomers)))


def test_the_frozen_list_only_shrinks():
    stale = UNCLAIMED_ALLOWED & set(_claims())
    assert not stale, ("commands now governed by a policy: remove them from UNCLAIMED_ALLOWED: "
                       + ", ".join(" ".join(c) for c in sorted(stale)))


def test_no_policy_claims_a_command_that_does_not_exist():
    leaves = set(_leaves(cli.build_parser()))
    ghosts = set(_claims()) - leaves
    assert not ghosts, f"policies claim missing commands: {sorted(ghosts)}"


def _command_parser(path):
    parser = cli.build_parser()
    for word in path:
        parser = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction)).choices[word]
    return parser


def test_the_inspection_policy_names_every_flag_of_the_commands_it_governs():
    p = pol.get_policy("probe-inspect")
    assert p.commands, "the policy claims its commands in the header"
    missing = []
    for command in p.commands:
        for action in _command_parser(command)._actions:
            if isinstance(action, argparse._HelpAction):
                continue
            for option in action.option_strings:
                if option not in p.text:
                    missing.append(f"{' '.join(command)} {option}")
    assert not missing, "flags the policy does not mention: " + ", ".join(missing)


# --- lints ---------------------------------------------------------------------------

POLICIES = [p.name for p in pol.all_policies()]


def test_the_package_ships_policies():
    assert {"agentcad-policies", "agentcad-session", "agentcad-gcode"} <= set(POLICIES)


@pytest.mark.parametrize("name", POLICIES)
def test_policy_lints(name):
    p = pol.get_policy(name)
    text = p.text
    assert text.isascii(), "policies are plain ASCII"
    assert not ABS_PATH.search(text), "no absolute file paths"
    assert not LAB_NAMES.search(text), f"no particular people, agents or labs: {LAB_NAMES.search(text).group(0)}"
    fences = [line for line in text.split("\n") if line.lstrip().startswith(("```", "~~~"))]
    assert all(line.startswith(("```", "~~~")) for line in fences), "code fences start at column 0"
    assert len(fences) % 2 == 0, "code fences are balanced"
    for field in ("Type", "Scope", "Status", "Commands"):
        assert field in p.header, f"header field **{field}** missing"
    lines = text.split("\n")
    assert lines.count(pol.BOUNDARY) == 1, "exactly one line is the boundary"
    boundary_at = lines.index(pol.BOUNDARY)
    assert not any(pol.BOUNDARY in line for line in lines[:boundary_at]), \
        "no mention of the boundary before it (navigation splits at the first occurrence)"
    guide, content = "\n".join(lines[:boundary_at]), "\n".join(lines[boundary_at + 1:])
    assert "## Purpose" in guide and "## CEP Navigation Guide" in guide
    guide_numbers = re.findall(r"^\*\*(\d+(?:\.\d+)*) ", guide, flags=re.M)
    content_numbers = [m.rstrip(".") for m in re.findall(r"^#{2,4} (\d+(?:\.\d+)*\.?) ", content, flags=re.M)]
    assert guide_numbers == content_numbers, "the navigation guide numbers its topics like the content"


# --- the command ---------------------------------------------------------------------

def test_policy_list_names_each_policy(capsys):
    cli.main(["policy", "list"])
    out = capsys.readouterr().out
    for name in ("agentcad-policies", "agentcad-session", "agentcad-gcode"):
        assert name in out
    cli.main(["policy", "list", "--json"])
    records = json.loads(capsys.readouterr().out)
    assert any("agentcad session iterate" in r["commands"] for r in records)


def test_policy_navigate_and_read(capsys):
    cli.main(["policy", "navigate", "session"])
    assert "1.2 Iterating" in capsys.readouterr().out
    cli.main(["policy", "read", "session", "--section", "2.1"])
    out = capsys.readouterr().out
    assert "The Tray" in out and "Render Gate" not in out


def test_policy_read_of_an_unknown_name_fails(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["policy", "read", "no-such-policy"])
    assert exc.value.code == 1
    assert "no policy named" in capsys.readouterr().err
