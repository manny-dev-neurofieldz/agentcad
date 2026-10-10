"""Skills and agents ship with the package and ask the policies; they never name what does not exist.

Each ``skills/<name>/SKILL.md`` and ``agents/<name>.md`` carries frontmatter (its name and a
description that says when to use it). Every policy it names and every ``agentcad`` command it
names must exist in this version, so a skill cannot send an agent to a policy that was renamed
or a command that was removed. The texts follow the public-text rules the policies do.
"""

import argparse
import re
from importlib import resources

import pytest

from agentcad import cli, policy as pol

LAB_NAMES = re.compile(r"\b(Manny|Craig|NeuroFieldz|Dropbox|pa_manny\w*)\b")
ABS_PATH = re.compile(r"(^|[\s(`'\"])/(home|opt|tmp|Users|shared_workspace|mnt|var)/")
COMMAND = re.compile(r"`agentcad ([^`]+)`")
POLICY_ITEM = re.compile(r"^\d+\. `([a-z0-9-]+)`((?:(?:,| and) `[a-z0-9-]+`)*)", re.M)
POLICY_READ = re.compile(r"agentcad policy (?:read|navigate) ([a-z0-9-]+)")


def _texts():
    root = resources.files("agentcad")
    found = []
    skills = root / "skills"
    if skills.is_dir():
        for folder in sorted(skills.iterdir(), key=lambda e: e.name):
            if (folder / "SKILL.md").is_file():
                found.append(("skill", folder.name, (folder / "SKILL.md").read_text(encoding="utf-8")))
    agents = root / "agents"
    if agents.is_dir():
        for entry in sorted(agents.iterdir(), key=lambda e: e.name):
            if entry.name.endswith(".md"):
                found.append(("agent", entry.name[:-3], entry.read_text(encoding="utf-8")))
    return found


TEXTS = _texts()
IDS = [f"{kind}:{name}" for kind, name, _ in TEXTS]


def _frontmatter(text):
    if not text.startswith("---\n"):
        return {}
    head = text[4:text.index("\n---", 4)]
    return dict(line.split(": ", 1) for line in head.split("\n") if ": " in line)


def _subparsers(parser):
    return next((a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None)


def command_problem(words, root=None):
    """Why ``agentcad WORDS`` names no command, or None when it does. Words after a leaf command are
    its arguments; after a group, the next word must be one of its subcommands."""
    parser = root or cli.build_parser()
    path = []
    for word in words:
        sub = _subparsers(parser)
        if sub is None:
            return None                          # a leaf: the rest are its arguments
        if word not in sub.choices:
            return f"`agentcad {' '.join(path + [word])}` is not a command"
        parser = sub.choices[word]
        path.append(word)
    return None if path else "no command named"


def policies_named(text):
    names = set(POLICY_READ.findall(text)) - {"NAME", "list"}
    for first, rest in POLICY_ITEM.findall(text):
        names.add(first)
        names.update(re.findall(r"`([a-z0-9-]+)`", rest))
    return names


def test_the_package_ships_the_skills_and_the_reviewer():
    names = {(kind, name) for kind, name, _ in TEXTS}
    for skill in ("design-session", "render-gate", "reverse-engineer", "fit-check", "print-prep", "review"):
        assert ("skill", skill) in names
    assert ("agent", "design-reviewer") in names


@pytest.mark.parametrize("kind,name,text", TEXTS, ids=IDS)
def test_frontmatter_names_it_and_says_when_to_use_it(kind, name, text):
    meta = _frontmatter(text)
    assert meta.get("name") == name, "the frontmatter name matches the file"
    assert meta.get("description", "").startswith("Use "), "the description says when to use it"


@pytest.mark.parametrize("kind,name,text", TEXTS, ids=IDS)
def test_every_policy_named_exists(kind, name, text):
    named = policies_named(text)
    assert named, "it asks at least one policy"
    missing = []
    for policy_name in sorted(named):
        try:
            pol.get_policy(policy_name)
        except pol.PolicyError:
            missing.append(policy_name)
    assert not missing, "names policies that do not exist: " + ", ".join(missing)


@pytest.mark.parametrize("kind,name,text", TEXTS, ids=IDS)
def test_every_command_named_exists(kind, name, text):
    root = cli.build_parser()
    problems = [p for words in COMMAND.findall(text) for p in [command_problem(words.split(), root)] if p]
    assert not problems, "; ".join(problems)


@pytest.mark.parametrize("kind,name,text", TEXTS, ids=IDS)
def test_public_text_rules(kind, name, text):
    assert text.isascii(), "plain ASCII"
    assert not ABS_PATH.search(text), "no absolute file paths"
    assert not LAB_NAMES.search(text), "no particular people, agents or labs"
    assert not re.search(r"--section \d", text), "cite a policy by its questions, not a section number"


def test_the_checks_have_teeth():
    root = cli.build_parser()
    assert command_problem(["session", "iterate", "PROJECT"], root) is None
    assert command_problem(["probe"], root) is None
    assert command_problem(["probe", "nonesuch"], root)
    assert command_problem(["nonesuch"], root)
    assert policies_named("1. `design-review` - x\n2. `compare`, `probe-inspect` and `nonesuch` - y") == \
        {"design-review", "compare", "probe-inspect", "nonesuch"}
    with pytest.raises(pol.PolicyError):
        pol.get_policy("nonesuch")
