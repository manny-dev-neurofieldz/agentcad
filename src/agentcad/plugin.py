"""agentcad's know-how written out for an agent harness: every target is generated from one bundle
(agentcad.bundle), so a harness added later reads the package through the same door.

    claude-code   a Claude Code plugin: the skills, the reviewer agent and the hooks, laid out where Claude Code
                  looks for them (checked with ``claude plugin validate --strict``)
    maceff        the policies as a policy root for the MacEff framework (https://github.com/cversek/MacEff):
                  a folder it mounts through its MACEFF_POLICY_ROOTS variable
    agents-md     one AGENTS.md for harnesses that read that file: the commands, each policy's navigation guide,
                  the skills
    api-tools     tool definitions for a model API, one per leaf command, with the mapping from a tool call back
                  to a command line

No export holds agentcad code or permission rules. The skills and tools call the ``agentcad`` command, which must
be installed where the export is used; the policies they read come from that install (``agentcad policy``), and so
do the hooks (agentcad.plugin_hooks). The claude-code layout:

    .claude-plugin/plugin.json        name, version (the package's), description, author, license
    .claude-plugin/marketplace.json   with ``marketplace``: a local marketplace offering this plugin from "./"
    skills/<name>/SKILL.md            each skill, invoked as /agentcad:<name>
    agents/design-reviewer.md         the reviewer agent, agentcad:design-reviewer
    hooks/hooks.json                  SessionStart, PostToolUse on Bash, PreToolUse on edits
    hooks/run.sh                      runs ``agentcad plugin hook EVENT``, or says agentcad is missing

The same package always exports the same bytes: files in name order, JSON with sorted keys, modes 0644 (run.sh
0755) and 0755 for folders.
"""
import json
import shutil
from pathlib import Path
from typing import Callable, Dict, List, Optional, Union

from agentcad import bundle as bundles
from agentcad.bundle import Bundle, Hook

NAME = bundles.NAME
TARGETS = ("claude-code", "maceff", "agents-md", "api-tools")
#: What a claude-code export writes at the top of its folder; an earlier export holds only these.
WRITTEN = (".claude-plugin", "agents", "hooks", "skills")
#: The file that marks every other target's export as agentcad's, so a re-export may replace it.
MARKER = "agentcad-export.json"
MACEFF_LINK = "https://github.com/cversek/MacEff"

#: The harness events the plugin hooks, each with the tools it listens to (None: every occurrence) and the
#: ``agentcad plugin hook`` event that answers it (agentcad.plugin_hooks).
HOOKS = (("PostToolUse", "Bash", "post-tool-use"),
         ("PreToolUse", "Edit|Write|MultiEdit|NotebookEdit", "pre-tool-use"),
         ("SessionStart", None, "session-start"))
RUNNER = "hooks/run.sh"
#: The runner the harness calls. It holds no logic of its own: it hands the payload to the installed command, and
#: without one it says so once, at session start, and stays silent for every other event (a missing install must
#: not fail each tool call).
RUN_SH = """#!/bin/sh
# Runs one of the agentcad plugin's hooks through the installed agentcad command.
# Written by: agentcad plugin export (agentcad {version}). Do not edit; export again.
event="$1"
if command -v agentcad >/dev/null 2>&1; then
    exec agentcad plugin hook "$event" --plugin-version "{version}"
fi
cat >/dev/null
if [ "$event" = "session-start" ]; then
    printf '%s\\n' '{missing}'
fi
exit 0
"""


class PluginError(Exception):
    pass


def collect() -> Bundle:
    """The installed package as a bundle, with the hooks this module answers."""
    return bundles.collect(hooks=tuple(Hook(*h) for h in HOOKS))


def _json(value) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


# --- claude-code ------------------------------------------------------------------------------------

def manifest(b: Optional[Bundle] = None) -> Dict[str, object]:
    """plugin.json: what the installed package's metadata says about itself."""
    b = b or collect()
    out = {"name": b.name, "version": b.version, "description": b.description, "author": dict(b.author)}
    if b.license:
        out["license"] = b.license
    return out


def marketplace(b: Optional[Bundle] = None) -> Dict[str, object]:
    meta = manifest(b)
    return {"name": meta["name"], "description": f"A local marketplace offering the {meta['name']} plugin",
            "owner": meta["author"],
            "plugins": [{"name": meta["name"], "source": "./", "description": meta["description"],
                         "version": meta["version"]}]}


def hooks(b: Optional[Bundle] = None) -> Dict[str, object]:
    """hooks.json: each event handed to the runner, which hands it to ``agentcad plugin hook``."""
    out: Dict[str, list] = {}
    for hook in (b or collect()).hooks:
        entry: Dict[str, object] = {"hooks": [{"type": "command",
                                               "command": f'"${{CLAUDE_PLUGIN_ROOT}}/{RUNNER}" {hook.event}'}]}
        if hook.matcher:
            entry["matcher"] = hook.matcher
        out[hook.harness_event] = [entry]
    return {"hooks": out}


def runner(b: Optional[Bundle] = None) -> bytes:
    b = b or collect()
    missing = json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": (
        f"The agentcad plugin is loaded, but no agentcad command is on PATH here. Its skills call that command "
        f"and will fail at their first step: install agentcad {b.version} (pip install agentcad), "
        f"then start the session again.")}}, sort_keys=True)
    if "'" in missing:
        raise PluginError("the runner's message holds a quote the shell script cannot carry")
    return RUN_SH.format(version=b.version, missing=missing).encode("ascii")


def claude_code(b: Bundle, with_marketplace: bool = False) -> Dict[str, bytes]:
    files = {".claude-plugin/plugin.json": _json(manifest(b)), "hooks/hooks.json": _json(hooks(b)),
             RUNNER: runner(b)}
    if with_marketplace:
        files[".claude-plugin/marketplace.json"] = _json(marketplace(b))
    for skill in b.skills:
        for filename, data in skill.files:
            files[f"skills/{skill.name}/{filename}"] = data
    for agent in b.agents:
        files[f"agents/{agent.filename}"] = agent.data
    if not b.skills:
        raise PluginError("this agentcad ships no skills; the install is incomplete")
    return files


# --- maceff -----------------------------------------------------------------------------------------

def _marker(b: Bundle, target: str) -> bytes:
    return _json({"name": b.name, "target": target, "version": b.version})


def maceff(b: Bundle) -> Dict[str, bytes]:
    """The policies as a policy root: ``policies/`` is the folder to mount; the note beside it says how."""
    if not b.policies:
        raise PluginError("this agentcad ships no policies; the install is incomplete")
    readme = f"""# {b.name} {b.version}: policies for MacEff

The {len(b.policies)} files in `policies/` are {b.name}'s policies, byte for byte as the package ships them. They
are written in the policy format MacEff reads ({MACEFF_LINK}), so MacEff can mount this folder as one more
policy root, beside its own:

    MACEFF_POLICY_ROOTS={b.name}=/path/to/this/folder/policies

After that, `macf_tools policy list` shows them and `macf_tools policy navigate {b.name}:<name>` reads one.
MacEff refuses a root that anyone but its own user can write.

This folder is a copy, taken from {b.name} {b.version}. It stops changing when {b.name} does. Where MacEff runs
with the same Python that has {b.name} installed, mount the installed folder instead and nothing goes stale;
`{b.name} plugin export --target maceff` prints that folder when it runs. Export again after upgrading.
"""
    files = {MARKER: _marker(b, "maceff"), "README.md": readme.encode("ascii")}
    for p in b.policies:
        files[f"policies/{p.name}.md"] = p.text.encode("utf-8")
    return files


# --- agents-md --------------------------------------------------------------------------------------

def _navigation(text: str) -> str:
    """A policy's navigation guide: the questions under its guide heading, up to the boundary."""
    from agentcad import policy

    lines, _ = policy.navigation(text)
    start = next((i for i, line in enumerate(lines) if line.strip() == "## CEP Navigation Guide"), None)
    if start is None:
        return ""
    return "\n".join(lines[start + 1:]).strip()


def agents_md(b: Bundle) -> Dict[str, bytes]:
    out = [f"# {b.name} {b.version}", "", b.description, "",
           f"This file was written by `{b.name} plugin export --target agents-md`. It names what {b.name} can do "
           f"and where its know-how lives; the know-how itself stays in the installed command, so read it there "
           f"and export again after upgrading.", "",
           "## How to use it", "",
           f"- Every capability is a command: `{b.name} --help`, then `{b.name} <command> --help`.",
           f"- Every command has a policy that says what it means and how to use it. Before using a command, find "
           f"its policy below, pick the question you have, and read that section: "
           f"`{b.name} policy read <name> --section <number>`. `{b.name} policy navigate <name>` shows a guide "
           f"again.",
           "- The skills are workflows that read the policies in the right order; follow one when its moment "
           "comes.",
           f"- The policies are written in the policy format the [MacEff]({MACEFF_LINK}) agent framework reads; "
           f"`{b.name} plugin export --target maceff` writes them as a policy root it can mount.", "",
           "## Skills", ""]
    for skill in b.skills:
        out.append(f"- **{skill.name}**: {skill.description or 'see the skill file'}")
    out += ["", "## Commands", ""]
    for tool in b.tools:
        out.append(f"- `{tool.command}`: {tool.help}")
    out += ["", "## Policies: what to ask of each", ""]
    for p in b.policies:
        out += [f"### {p.name}: {p.title}", ""]
        if p.commands:
            out += ["Commands: " + ", ".join(f"`{c}`" for c in p.commands), ""]
        guide = _navigation(p.text)
        out += [guide or "(this policy has no navigation guide)", ""]
    return {MARKER: _marker(b, "agents-md"), "AGENTS.md": ("\n".join(out).rstrip("\n") + "\n").encode("utf-8")}


# --- api-tools --------------------------------------------------------------------------------------

def api_tools(b: Bundle) -> Dict[str, bytes]:
    if not b.tools:
        raise PluginError("this agentcad has no commands to offer as tools")
    readme = f"""# {b.name} {b.version}: tool definitions for a model API

`tools.json` holds {len(b.tools)} tool definitions, one per {b.name} command: a `name`, a `description` and an
`input_schema` (JSON Schema). Pass the list as the `tools` of a model API request.

A tool only names a command line; your program runs it. From a tool call to the command:

1. The tool's name is the command with underscores: `{b.name}_probe_rays` is `{b.name} probe rays`, and
   `{b.name}_new_project` is `{b.name} new-project`. Each description ends with the exact command.
2. Each input property is one argument; its description ends with the option it stands for, or `(positional)`.
3. A boolean set true adds its option; false or absent adds nothing. A value adds the option and the value as
   one word, `--option=value`, so a value starting with a dash is not read as an option. A list adds that word
   once per item where the option repeats, else the option followed by the items as separate words; there an
   item starting with a dash would be read as another option, and `argv_for` refuses it.
   Then `--`, then the positionals in the schema's order. The `--` is needed: an option that takes several
   values would otherwise read the positionals as more of its values.

`{b.name}.bundle.argv_for(tool, values)` does exactly this for a tool of `{b.name}.plugin.collect().tools`, and
refuses a name the command does not have or a required one left out. Run the result with the installed command,
return its output and exit status as the tool result, and treat a non-zero status as the tool's error.

The definitions say what a command takes, not when to use it. That is in the policies: `{b.name} policy list`.
"""
    return {MARKER: _marker(b, "api-tools"), "README.md": readme.encode("ascii"),
            "tools.json": _json([bundles.tool_schema(t) for t in b.tools])}


WRITERS: Dict[str, Callable[[Bundle], Dict[str, bytes]]] = {
    "maceff": maceff, "agents-md": agents_md, "api-tools": api_tools}


def files_for(b: Bundle, target: str, with_marketplace: bool = False) -> Dict[str, bytes]:
    """Every file of an export of ``b`` for ``target``, by its path inside the export folder."""
    if target not in TARGETS:
        raise PluginError(f"no plugin target {target!r} (there is: {', '.join(TARGETS)})")
    if target == "claude-code":
        return claude_code(b, with_marketplace)
    if with_marketplace:
        raise PluginError(f"only the claude-code target has a marketplace manifest, not {target}")
    return WRITERS[target](b)


def _earlier(out: Path, target: str) -> bool:
    """Whether ``out`` holds an earlier agentcad export for the same target."""
    try:
        if target == "claude-code":
            return json.loads((out / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")).get("name") == NAME
        mark = json.loads((out / MARKER).read_text(encoding="utf-8"))
        return mark.get("name") == NAME and mark.get("target") == target
    except (OSError, ValueError, AttributeError):
        return False


def _clear(out: Path, target: str, written: tuple) -> None:
    """Make ``out`` ready for an export: missing or empty, or an earlier export for the same target, which is
    removed. At the top of ``out`` an export owns only the entries it writes, and anything else there is refused by
    name; inside those entries everything is the export's, so a file added there by hand is removed with the
    rest."""
    if not out.exists():
        return
    if not out.is_dir():
        raise PluginError(f"{out} is a file, not a folder")
    other = sorted(e.name for e in out.iterdir() if e.name not in written)
    if other:
        raise PluginError(f"{out} holds files an export does not write ({', '.join(other[:5])}); "
                          f"give an empty folder or an earlier export")
    present = [e for e in out.iterdir()]
    if present:
        if not _earlier(out, target):
            where = ".claude-plugin/plugin.json" if target == "claude-code" else MARKER
            raise PluginError(f"{out} is not an earlier agentcad export (no {where} naming "
                              f"{NAME}); give an empty folder")
        for entry in present:
            shutil.rmtree(entry) if entry.is_dir() and not entry.is_symlink() else entry.unlink()


def export(out: Union[str, Path], target: str = "claude-code", with_marketplace: bool = False,
           bundle: Optional[Bundle] = None) -> List[Path]:
    """Write the export for ``target`` into ``out``; the files written, in order. A refusal (PluginError) is said
    before anything is removed or written; a failure while writing (a full disk) can leave a partial export, which
    the next export replaces. A folder ``out`` that already existed keeps its own mode."""
    if target not in TARGETS:
        raise PluginError(f"no plugin target {target!r} (there is: {', '.join(TARGETS)})")
    out = Path(out)
    files = files_for(bundle or collect(), target, with_marketplace)
    written_top = WRITTEN if target == "claude-code" else tuple(sorted({rel.split("/")[0] for rel in files}))
    _clear(out, target, written_top)
    created = not out.exists()
    written = []
    for rel in sorted(files):
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(files[rel])
        path.chmod(0o755 if rel == RUNNER else 0o644)
        written.append(path)
    inside = {parent for p in written for parent in p.relative_to(out).parents if str(parent) != "."}
    for folder in sorted(inside):
        (out / folder).chmod(0o755)
    if created:
        out.chmod(0o755)
    return written
