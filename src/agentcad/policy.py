"""Policies that ship with each capability, readable through ``agentcad policy``.

A policy is a markdown file in the package's ``policies/`` folder, written in
a shared policy format so another reader of the format can mount it
unchanged: a header (``**Type**``, ``**Scope**``, ``**Status**``,
and here also ``**Commands**``, the CLI commands the policy governs), a
``## Purpose``, a ``## CEP Navigation Guide`` of numbered topics with
questions, the boundary line, then content sections numbered like the guide.

The parsing rules are fixed so every reader of the format extracts the same
text: the navigation guide is everything before the first boundary marker; a section is
found by its heading's first word, a subsection belongs to it, and a code
fence is any line starting with three backticks or three tildes. Matching
those rules exactly is what lets one file serve both readers.
"""

from dataclasses import dataclass, field
from importlib import resources
from typing import Dict, List, Optional, Tuple

BOUNDARY = "=== CEP_NAV_BOUNDARY ==="
PREFIX = "agentcad-"
_NO_BOUNDARY_LINES = 100


class PolicyError(LookupError):
    """A policy or one of its sections could not be found."""


@dataclass
class Policy:
    name: str
    text: str
    header: Dict[str, str] = field(default_factory=dict)

    @property
    def title(self) -> str:
        for line in self.text.split("\n"):
            if line.startswith("# "):
                return line[2:].strip()
        return self.name

    @property
    def commands(self) -> List[Tuple[str, ...]]:
        """The leaf commands this policy governs, as word tuples without ``agentcad``; ``none`` for a
        policy about a practice rather than a command."""
        value = self.header.get("Commands", "")
        if value.strip().lower() == "none":
            return []
        out = []
        for item in value.split(","):
            words = item.split()
            if words and words[0] == "agentcad":
                words = words[1:]
            if words:
                out.append(tuple(words))
        return out


def _header(text: str) -> Dict[str, str]:
    """``**Key**: value`` lines before the first ``##`` heading."""
    fields: Dict[str, str] = {}
    for line in text.split("\n"):
        if line.startswith("## "):
            break
        if line.startswith("**") and "**:" in line:
            key, _, value = line[2:].partition("**:")
            fields[key.strip()] = value.strip()
    return fields


def policy_dir():
    return resources.files("agentcad") / "policies"


def all_policies() -> List[Policy]:
    folder = policy_dir()
    if not folder.is_dir():
        return []
    found = []
    for entry in sorted(folder.iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".md") and not entry.name.startswith("_"):
            text = entry.read_text(encoding="utf-8")
            found.append(Policy(entry.name[:-3], text, _header(text)))
    return found


def get_policy(name: str) -> Policy:
    """A policy by its file stem, with or without the ``agentcad-`` prefix."""
    wanted = {name, PREFIX + name}
    for policy in all_policies():
        if policy.name in wanted:
            return policy
    raise PolicyError(f"no policy named {name!r} (agentcad policy list shows them)")


def navigation(text: str) -> Tuple[List[str], Optional[str]]:
    """The navigation guide's lines, numbered from 1, and a note when the file has no boundary."""
    if BOUNDARY in text:
        return text.split(BOUNDARY)[0].split("\n"), None
    return text.split("\n")[:_NO_BOUNDARY_LINES], f"no {BOUNDARY} line: showing the first {_NO_BOUNDARY_LINES} lines"


def _matches(heading_num: str, target: str) -> bool:
    return heading_num == target or heading_num.startswith(target + ".")


def section(text: str, target: str) -> Tuple[int, List[str]]:
    """(first line number, lines) of section ``target`` and its subsections."""
    lines = text.split("\n")
    target = str(target)
    captured: List[str] = []
    start = 0
    level = 0
    in_section = False
    in_fence = False
    for i, line in enumerate(lines):
        if line.startswith("```") or line.startswith("~~~"):
            in_fence = not in_fence
        if line.startswith("#") and not in_fence:
            heading_level = len(line) - len(line.lstrip("#"))
            heading = line.lstrip("#").strip()
            if heading:
                number = heading.split()[0].rstrip(".")
                if _matches(number, target):
                    if not in_section:
                        in_section, start, level = True, i + 1, heading_level
                elif in_section and heading_level <= level:
                    break
        if in_section:
            captured.append(line)
    if not captured:
        raise PolicyError(f"section {target} not found")
    return start, captured


def after_boundary(text: str) -> Tuple[int, List[str]]:
    """(first line number, lines) after the first line containing the boundary; the whole file without one."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if BOUNDARY in line:
            return i + 2, lines[i + 1:]
    return 1, lines


def line_range(text: str, spec: str) -> Tuple[int, List[str]]:
    """(first line number, lines) for ``START:END`` (1-indexed, END inclusive, either may be omitted)."""
    lines = text.split("\n")
    try:
        start_s, _, end_s = spec.partition(":")
        start = int(start_s) - 1 if start_s else 0
        end = int(end_s) if end_s else len(lines)
    except ValueError:
        raise PolicyError(f"bad line range {spec!r}: expected START:END, for example 50:100")
    return start + 1, lines[start:end]


def numbered(first: int, lines: List[str]) -> str:
    return "\n".join(f"{n:4d}| {line}" for n, line in enumerate(lines, first))


# --- the enabling pattern: sections every policy carries, and the recipes CI runs ---------------

#: The heading above the navigation guide that says when to reach for a capability (shown by navigate).
REACHING = "Reaching for It"
#: The two numbered content sections the enabling pattern adds, in this order, before integration.
PATTERN_SECTIONS = ("Recipes", "Constraints to Probe")
#: The first line of a fenced ``console`` block that is a recipe, and the workspaces a recipe may name.
RECIPE_MARK = "# recipe:"
WORKSPACES = ("examples", "empty")
#: Diagram kinds a policy may draw in a ``mermaid`` block (the ones a code host renders).
MERMAID_KINDS = ("flowchart", "graph", "sequenceDiagram", "stateDiagram-v2", "stateDiagram")


@dataclass
class Step:
    """One command of a recipe: the words after ``$ agentcad``, the exit status it must end with, and the lines
    its output must show, in order (``...`` inside a line stands for any text)."""
    argv: List[str]
    exit: int = 0
    expect: List[str] = field(default_factory=list)


@dataclass
class Recipe:
    policy: str
    line: int
    workspace: str
    steps: List[Step]


def _fences(text: str) -> List[Tuple[int, str, List[str]]]:
    """(line number of the opening fence, info string, body lines) of every fenced block."""
    out, lines, i = [], text.split("\n"), 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```") or line.startswith("~~~"):
            marker, info, body, j = line[:3], line[3:].strip(), [], i + 1
            while j < len(lines) and not lines[j].startswith(marker):
                body.append(lines[j])
                j += 1
            out.append((i + 1, info, body))
            i = j + 1
        else:
            i += 1
    return out


def recipes(policy: Policy) -> List[Recipe]:
    """The recipes in a policy: ``console`` blocks whose first line is ``# recipe: WORKSPACE``. A ``$ agentcad``
    line is a step; the lines under it until the next step are what its output must show, except ``# exit N``
    (the status it must end with, 0 when not said) and other ``#`` lines, which are commentary. A malformed
    recipe is a PolicyError naming the policy and line, so a recipe that would test nothing cannot pass."""
    import shlex

    found = []
    for at, info, body in _fences(policy.text):
        if info != "console" or not body or not body[0].startswith(RECIPE_MARK):
            continue
        workspace = body[0][len(RECIPE_MARK):].strip()
        if workspace not in WORKSPACES:
            raise PolicyError(f"{policy.name} line {at}: recipe workspace {workspace!r} is not one of "
                              f"{', '.join(WORKSPACES)}")
        steps: List[Step] = []
        for n, line in enumerate(body[1:], at + 2):
            if line.startswith("$ "):
                words = shlex.split(line[2:])
                if not words or words[0] != "agentcad":
                    raise PolicyError(f"{policy.name} line {n}: a recipe step runs agentcad, not {line[2:]!r}")
                steps.append(Step(words[1:]))
            elif not steps:
                if line.strip() and not line.startswith("#"):
                    raise PolicyError(f"{policy.name} line {n}: output before the first step")
            elif line.startswith("# exit "):
                steps[-1].exit = int(line[len("# exit "):].strip())
            elif line.strip() and not line.startswith("#"):
                steps[-1].expect.append(line.strip())
        if not steps:
            raise PolicyError(f"{policy.name} line {at}: a recipe with no step")
        if not any(s.expect for s in steps):
            raise PolicyError(f"{policy.name} line {at}: a recipe that expects no output tests nothing")
        found.append(Recipe(policy.name, at, workspace, steps))
    return found


def mermaid_blocks(policy: Policy) -> List[Tuple[int, List[str]]]:
    """(line, body) of every ``mermaid`` block in a policy."""
    return [(at, body) for at, info, body in _fences(policy.text) if info == "mermaid"]


def expect_matches(expected: List[str], output: str) -> Optional[str]:
    """None when every expected line matches an output line, in order; else the first that does not."""
    import re

    lines = output.split("\n")
    i = 0
    for want in expected:
        pattern = re.compile(".*".join(re.escape(part) for part in want.split("...")))
        while i < len(lines) and not pattern.search(lines[i]):
            i += 1
        if i == len(lines):
            return want
        i += 1
    return None
