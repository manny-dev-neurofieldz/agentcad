"""The plugin's hooks: what a harness session is told, or refused, around agentcad's own commands.

Each hook reads the harness's JSON payload on stdin and answers with JSON on stdout, or with nothing when it has
nothing to say. They run through the installed ``agentcad plugin hook EVENT`` (the plugin's hooks/run.sh finds it,
or says how to install it), so the plugin holds no agentcad code:

    session-start   agentcad is installed at the plugin's version, or the session is told what differs.
    post-tool-use   after a shell call that ran ``agentcad session iterate``: the iteration's tray warnings and
                    findings, and the renders to read before the next iterate.
    pre-tool-use    an edit (Edit, Write, MultiEdit, NotebookEdit) of a file a library's [library] table guards
                    is denied, with the library's own practice as the reason.

The guard sees the edits the harness makes through those tools, not what a program it runs writes.
"""
import fnmatch
import json
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import agentcad
from agentcad.config import tomllib

EVENTS = ("session-start", "post-tool-use", "pre-tool-use")
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
#: How many tray warnings and findings one iteration's context carries before it says how many more there are.
SHOWN = 8
#: Where the reasoning behind a hook's refusal or warning lives; said with each one.
WHY = "Why: agentcad policy navigate agentcad-plugin (the hooks, the library guard)."


def _warn(text: str) -> None:
    """A hook that cannot do its work says so on stderr, where the harness's hook log shows it, and stays out of
    the session's way; it never fails a tool call over its own trouble."""
    print(f"agentcad plugin hook: {text}", file=sys.stderr)


def _context(event: str, text: str) -> Dict[str, Any]:
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}


def session_start(payload: Dict[str, Any], plugin_version: Optional[str]) -> Optional[Dict[str, Any]]:
    """Nothing when the installed agentcad is the plugin's version; else what differs and what to do."""
    if not plugin_version or plugin_version == agentcad.__version__:
        return None
    return _context("SessionStart", (
        f"The agentcad plugin was exported from agentcad {plugin_version}, but the agentcad command here is "
        f"{agentcad.__version__}. Its skills may name commands or flags this install does not have, or miss "
        f"ones it has: install agentcad {plugin_version}, or export the plugin again from this install "
        f"(agentcad plugin export --target claude-code -o DIR). {WHY}"))


# --- after agentcad session iterate ---------------------------------------------------------------

def _iterate_projects(command: str) -> List[str]:
    """The project of each ``agentcad session iterate PROJECT SOURCE`` in a shell command line."""
    try:
        words = shlex.split(command, comments=False, posix=True)
    except ValueError:
        return []
    found = []
    for i, w in enumerate(words):
        if Path(w).name == "agentcad" and words[i + 1:i + 3] == ["session", "iterate"]:
            rest = [a for a in words[i + 3:] if a not in ("&&", "||", ";", "|")]
            if rest and not rest[0].startswith("-"):
                found.append(rest[0])
    return found


def _project_dir(project: str, cwd: Optional[str]) -> Optional[Path]:
    from agentcad.config import OutputConfig

    for candidate in (OutputConfig().designs_dir / project, Path(cwd or ".") / project, Path(project)):
        if (candidate / "_work" / "session.json").is_file():
            return candidate
    return None


def _iteration_context(project: str, project_dir: Path) -> Optional[str]:
    try:
        state = json.loads((project_dir / "_work" / "session.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        _warn(f"{project_dir / '_work' / 'session.json'} cannot be read ({e}); nothing said about the iteration")
        return None
    iterations = state.get("iterations") or []
    if not iterations:
        return None
    it = iterations[-1]
    lines = [f"agentcad session iterate recorded iteration {it.get('number')} of {project}."]
    warnings = list((it.get("report") or {}).get("warnings") or [])
    findings = [f for f in ((it.get("judgments") or {}).get("findings") or [])
                if f.get("severity") != "ok" and f.get("message") not in warnings]
    said = [f"tray: {w}" for w in warnings] + [
        f"{f.get('rule') or f.get('key')}: {f.get('sentence') or f.get('message') or f.get('why') or ''}".rstrip(": ")
        for f in findings]
    if said:
        lines.append(f"{len(said)} warning(s) and finding(s):")
        lines += [f"- {s}" for s in said[:SHOWN]]
        if len(said) > SHOWN:
            lines.append(f"- and {len(said) - SHOWN} more: agentcad session status {project}")
    else:
        lines.append("No tray warnings or findings.")
    images = sorted((it.get("image_paths") or {}).values())
    if images:
        lines.append("Read these renders, and say what each shows, before the next iterate (the render gate): "
                     + ", ".join(images))
    return "\n".join(lines)


def post_tool_use(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if payload.get("tool_name") != "Bash":
        return None
    command = str((payload.get("tool_input") or {}).get("command") or "")
    texts = []
    for project in _iterate_projects(command):
        folder = _project_dir(project, payload.get("cwd"))
        text = _iteration_context(project, folder) if folder else None
        if text:
            texts.append(text)
    return _context("PostToolUse", "\n\n".join(texts)) if texts else None


# --- the library guard ----------------------------------------------------------------------------

def _library(start: Path) -> Optional[tuple]:
    """(folder, table) of the nearest agentcad.toml above ``start`` that has a [library] table."""
    if tomllib is None:
        _warn("no TOML reader in this Python (install tomli); no library guard is applied")
        return None
    for folder in [start, *start.parents]:
        config = folder / "agentcad.toml"
        if config.is_file():
            try:
                with open(config, "rb") as fh:
                    table = tomllib.load(fh).get("library")
            except (OSError, ValueError) as e:
                _warn(f"{config} cannot be read ({e}); a [library] guard it may hold is not applied")
                continue
            if isinstance(table, dict):
                return folder, table
    return None


def guarded_by(path: Path) -> Optional[str]:
    """The reason an edit of ``path`` is refused, or None. A [library] table's ``guarded`` globs are relative to
    its agentcad.toml; ``practice`` says what to do instead."""
    path = path.resolve()
    found = _library(path.parent)
    if not found:
        return None
    folder, table = found
    globs = table.get("guarded") or []
    globs = [globs] if isinstance(globs, str) else [str(g) for g in globs]
    try:
        rel = path.relative_to(folder).as_posix()
    except ValueError:
        return None
    for pattern in globs:
        if fnmatch.fnmatchcase(rel, pattern):
            practice = str(table.get("practice") or "").strip()
            return (f"{rel} is guarded by the [library] table of {folder / 'agentcad.toml'} (pattern {pattern!r})."
                    + (f" {practice}" if practice else " Change it the way the library's own notes say, not by "
                                                       "editing it in place.") + f" {WHY}")
    return None


def pre_tool_use(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if payload.get("tool_name") not in EDIT_TOOLS:
        return None
    tool_input = payload.get("tool_input") or {}
    target = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not target:
        return None
    path = Path(target)
    if not path.is_absolute():
        path = Path(payload.get("cwd") or ".") / path
    reason = guarded_by(path)
    if not reason:
        return None
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def run(event: str, payload: Dict[str, Any], plugin_version: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if event == "session-start":
        return session_start(payload, plugin_version)
    if event == "post-tool-use":
        return post_tool_use(payload)
    if event == "pre-tool-use":
        return pre_tool_use(payload)
    raise ValueError(f"no hook {event!r} (there is: {', '.join(EVENTS)})")
