"""What agentcad knows, as one bundle that every export target is generated from.

A harness (the program an agent runs in) finds know-how only in its own layout. Writing each layout from the
package directly would give as many readers of the package as there are harnesses; instead the package is read
once, into a Bundle, and each target is a function of the bundle alone. The bundle keeps five layers apart,
because targets use different subsets of them and a layer folded into another cannot be exported on its own:

    tools     what the command line can do: every leaf command with its arguments (from the argparse tree)
    policies  what each capability means and how to use it (the package's policies, in their own format)
    skills    the workflows, as rituals that read the policies
    agents    a stance to delegate to (the design reviewer)
    hooks     what a harness is told or refused around the commands

Targets (agentcad.plugin writes them): ``claude-code`` (skills, agents, hooks as a plugin), ``maceff`` (the
policies as a policy root for the MacEff framework, https://github.com/cversek/MacEff), ``agents-md`` (one
AGENTS.md naming the commands, the policies' navigation guides and the skills) and ``api-tools`` (tool definitions
for a model API, one per leaf command, with the mapping back to a command line).
"""
import argparse
import re
from dataclasses import dataclass, field
from email.utils import parseaddr
from importlib import metadata, resources
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

NAME = "agentcad"
#: A model API's limit on a tool's name.
TOOL_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


class BundleError(Exception):
    pass


@dataclass(frozen=True)
class Argument:
    """One argument of a leaf command. ``flags`` is empty for a positional. ``kind`` is "flag" (present or not),
    "value" (one value) or "list" (several: a repeated option, or one option or positional taking several)."""
    name: str
    flags: Tuple[str, ...]
    help: str
    kind: str
    type: str = "string"
    choices: Optional[Tuple[Any, ...]] = None
    required: bool = False
    repeat: bool = False


@dataclass(frozen=True)
class Tool:
    path: Tuple[str, ...]
    help: str
    arguments: Tuple[Argument, ...] = ()

    @property
    def name(self) -> str:
        return "_".join((NAME,) + self.path).replace("-", "_")

    @property
    def command(self) -> str:
        return " ".join((NAME,) + self.path)


@dataclass(frozen=True)
class PolicyDoc:
    name: str
    title: str
    commands: Tuple[str, ...]
    text: str


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    files: Tuple[Tuple[str, bytes], ...]


@dataclass(frozen=True)
class Agent:
    filename: str
    data: bytes


@dataclass(frozen=True)
class Hook:
    """A harness event the bundle answers: the harness's name for it, the tools it listens to (None: every
    occurrence) and the ``agentcad plugin hook`` event that answers."""
    harness_event: str
    matcher: Optional[str]
    event: str


@dataclass(frozen=True)
class Bundle:
    name: str
    version: str
    description: str
    author: Tuple[Tuple[str, str], ...]
    license: str = ""
    tools: Tuple[Tool, ...] = ()
    policies: Tuple[PolicyDoc, ...] = ()
    skills: Tuple[Skill, ...] = ()
    agents: Tuple[Agent, ...] = ()
    hooks: Tuple[Hook, ...] = field(default=())


# --- tools, from the argparse tree ------------------------------------------------------------------

def leaves(parser, path: Tuple[str, ...] = (), help_text: Optional[str] = None) -> Iterator[Tuple[tuple, Any, str]]:
    """(path, parser, help) of every leaf command under ``parser``."""
    subs = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    if not subs:
        yield path, parser, help_text or ""
        return
    for action in subs:
        helps = {c.dest: c.help for c in action._choices_actions}
        for name, child in action.choices.items():
            yield from leaves(child, path + (name,), helps.get(name))


_TYPES = {int: "integer", float: "number"}


def _argument(action) -> Optional[Argument]:
    if isinstance(action, (argparse._HelpAction, argparse._VersionAction, argparse._SubParsersAction)):
        return None
    flags = tuple(action.option_strings)
    several = action.nargs in ("*", "+") or (isinstance(action.nargs, int) and action.nargs > 1)
    repeat = isinstance(action, argparse._AppendAction)
    if isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction, argparse._StoreConstAction,
                           argparse._CountAction)):
        kind = "flag"
    elif several or repeat:
        kind = "list"
    else:
        kind = "value"
    required = bool(action.required) if flags else action.nargs not in ("?", "*")
    return Argument(name=action.dest, flags=flags, help=(action.help or "").replace("%(default)s", str(action.default)),
                    kind=kind, type=_TYPES.get(action.type, "string"),
                    choices=tuple(action.choices) if action.choices is not None else None,
                    required=required, repeat=repeat and not several)


def tools_of(parser) -> Tuple[Tool, ...]:
    out = []
    for path, leaf, help_text in leaves(parser):
        args = tuple(a for a in (_argument(action) for action in leaf._actions) if a is not None)
        out.append(Tool(path=path, help=help_text, arguments=args))
    names = [t.name for t in out]
    for t in out:
        if not TOOL_NAME.match(t.name):
            raise BundleError(f"the command {t.command!r} makes the tool name {t.name!r}, which a model API refuses")
        if names.count(t.name) > 1:
            raise BundleError(f"two commands make the tool name {t.name!r}")
    return tuple(sorted(out, key=lambda t: t.path))


def argv_for(tool: Tool, values: Dict[str, Any]) -> List[str]:
    """The command line (after ``agentcad``) a tool call stands for: the command's path, then each given option in
    the command's own order, then ``--`` and the positionals. The ``--`` is always written before positionals: an
    option that takes several values would otherwise read the positionals as more of its values. An option with one
    value, or repeated once per value, is written as one word (``--length=4.5``), so a value starting with a dash is
    not read as an option. A name the command does not have, and a required one left out, are refused by name."""
    known = {a.name: a for a in tool.arguments}
    unknown = sorted(set(values) - set(known))
    if unknown:
        raise BundleError(f"{tool.name} has no argument {', '.join(unknown)} (it has: {', '.join(known) or 'none'})")
    missing = [a.name for a in tool.arguments if a.required and values.get(a.name) in (None, [], "")]
    if missing:
        raise BundleError(f"{tool.name} needs {', '.join(missing)}")
    options: List[str] = []
    positionals: List[str] = []
    for a in tool.arguments:
        if a.name not in values or values[a.name] is None:
            continue
        v = values[a.name]
        if a.kind == "flag":
            if v is True:
                options.append(a.flags[0])
            elif v is not False:
                raise BundleError(f"{tool.name}: {a.name} is a flag, given true or false, not {v!r}")
            continue
        items = [str(x) for x in v] if a.kind == "list" else [str(v)]
        if a.kind == "list" and isinstance(v, (str, bytes)):
            raise BundleError(f"{tool.name}: {a.name} takes a list")
        if not a.flags:
            positionals += items
        elif a.kind == "list" and not a.repeat:
            if items:
                options += [a.flags[0], *items]
        else:
            options += [_joined(a.flags, item) for item in items]
    return list(tool.path) + options + (["--"] + positionals if positionals else [])


def _joined(flags: Tuple[str, ...], value: str) -> str:
    """One option and its value as one word, so a value that starts with a dash (``-5``) is never read as another
    option: ``--long=value`` when the option has a long spelling, else the short one with the value attached."""
    long = next((f for f in flags if f.startswith("--")), None)
    return f"{long}={value}" if long else f"{flags[0]}{value}"


def tool_schema(tool: Tool) -> Dict[str, Any]:
    """One tool definition: name, description and a JSON Schema for its input."""
    properties: Dict[str, Any] = {}
    for a in tool.arguments:
        if a.kind == "flag":
            prop: Dict[str, Any] = {"type": "boolean"}
        else:
            prop = {"type": a.type}
            if a.choices is not None:
                prop["enum"] = list(a.choices)
            if a.kind == "list":
                prop = {"type": "array", "items": prop}
        said = a.help or a.name
        prop["description"] = said + (f" ({', '.join(a.flags)})" if a.flags else " (positional)")
        properties[a.name] = prop
    return {"name": tool.name,
            "description": f"{(tool.help or tool.command).rstrip('.')}. Runs: {tool.command}.",
            "input_schema": {"type": "object", "properties": properties,
                             "required": [a.name for a in tool.arguments if a.required],
                             "additionalProperties": False}}


# --- the package, read once -------------------------------------------------------------------------

def _package_metadata() -> Dict[str, str]:
    try:
        meta = metadata.metadata(NAME)
    except metadata.PackageNotFoundError:
        return {}
    return {k: meta.get(k) or "" for k in ("Summary", "Author", "Author-email", "License-Expression", "License")}


def _author(meta: Dict[str, str]) -> Tuple[Tuple[str, str], ...]:
    """The package's author as its metadata states it, else the package's name."""
    name, email = parseaddr(meta.get("Author-email", ""))
    name = name or meta.get("Author") or NAME
    return (("name", name), ("email", email)) if email else (("name", name),)


def _shipped(folder: str) -> list:
    root = resources.files(NAME) / folder
    return sorted((e for e in root.iterdir() if not e.name.startswith(("_", "."))), key=lambda e: e.name) \
        if root.is_dir() else []


def _frontmatter(text: str, key: str) -> str:
    """The value of ``key`` in a file's leading ``---`` block, or ""."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return ""
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith(key + ":"):
            return line[len(key) + 1:].strip()
    return ""


def _skills() -> Tuple[Skill, ...]:
    out = []
    for skill in _shipped("skills"):
        if not skill.is_dir():
            continue
        files = tuple((entry.name, entry.read_bytes()) for entry in sorted(skill.iterdir(), key=lambda e: e.name)
                      if entry.is_file() and not entry.name.startswith(("_", ".")))
        main = dict(files).get("SKILL.md", b"").decode("utf-8", errors="replace")
        out.append(Skill(name=skill.name, description=_frontmatter(main, "description"), files=files))
    return tuple(out)


def _policies() -> Tuple[PolicyDoc, ...]:
    from agentcad import policy

    out = []
    for p in policy.all_policies():
        commands = tuple(c.strip() for c in p.header.get("Commands", "").split(",") if c.strip())
        out.append(PolicyDoc(name=p.name, title=p.title, commands=commands, text=p.text))
    return tuple(out)


def collect(hooks: Sequence[Hook] = ()) -> Bundle:
    """The installed package as a bundle. ``hooks`` come from the module that answers them (agentcad.plugin)."""
    import agentcad
    from agentcad.cli import build_parser

    meta = _package_metadata()
    return Bundle(name=NAME, version=agentcad.__version__, description=meta.get("Summary") or NAME,
                  author=_author(meta), license=meta.get("License-Expression") or meta.get("License") or "",
                  tools=tools_of(build_parser()), policies=_policies(), skills=_skills(),
                  agents=tuple(Agent(a.name, a.read_bytes()) for a in _shipped("agents")
                               if a.is_file() and a.name.endswith(".md")),
                  hooks=tuple(hooks))
