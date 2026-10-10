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
        """The leaf commands this policy governs, as word tuples without ``agentcad``."""
        out = []
        for item in self.header.get("Commands", "").split(","):
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
