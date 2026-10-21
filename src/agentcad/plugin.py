"""agentcad as a Claude Code plugin: the skills and the reviewer agent that ship in the package, laid out where
Claude Code looks for them.

The export holds no code and no permissions. The skills call the ``agentcad`` command, which must be installed
where the plugin is used; the policies they read come from that install (``agentcad policy``). The layout, checked
with ``claude plugin validate --strict`` (Claude Code 2.1.302):

    .claude-plugin/plugin.json        name, version (the package's), description, author, license
    .claude-plugin/marketplace.json   with ``marketplace``: a local marketplace offering this plugin from "./"
    skills/<name>/SKILL.md            each skill, invoked as /agentcad:<name>
    agents/design-reviewer.md         the reviewer agent, agentcad:design-reviewer
    hooks/hooks.json                  no hooks yet

The same package always exports the same bytes: files in name order, JSON with sorted keys, modes 0644 and 0755.
"""
import json
import shutil
from email.utils import parseaddr
from importlib import metadata, resources
from pathlib import Path
from typing import Dict, List, Union

import agentcad

NAME = "agentcad"
TARGETS = ("claude-code",)
#: What an export writes at the top of its folder; an earlier export holds only these.
WRITTEN = (".claude-plugin", "agents", "hooks", "skills")


class PluginError(Exception):
    pass


def _metadata() -> Dict[str, str]:
    try:
        meta = metadata.metadata(NAME)
    except metadata.PackageNotFoundError:
        return {}
    return {k: meta.get(k) or "" for k in ("Summary", "Author", "Author-email", "License-Expression", "License")}


def _author(meta: Dict[str, str]) -> Dict[str, str]:
    """The package's author as its metadata states it, else the package's name."""
    name, email = parseaddr(meta.get("Author-email", ""))
    name = name or meta.get("Author") or NAME
    return {"name": name, "email": email} if email else {"name": name}


def manifest() -> Dict[str, object]:
    """plugin.json: what the installed package's metadata says about itself."""
    meta = _metadata()
    out = {"name": NAME, "version": agentcad.__version__, "description": meta.get("Summary") or NAME,
           "author": _author(meta)}
    licence = meta.get("License-Expression") or meta.get("License")
    if licence:
        out["license"] = licence
    return out


def marketplace() -> Dict[str, object]:
    meta = manifest()
    return {"name": NAME, "description": f"A local marketplace offering the {NAME} plugin", "owner": meta["author"],
            "plugins": [{"name": NAME, "source": "./", "description": meta["description"],
                         "version": meta["version"]}]}


def _shipped(folder: str) -> list:
    root = resources.files(NAME) / folder
    return sorted((e for e in root.iterdir() if not e.name.startswith(("_", "."))), key=lambda e: e.name) \
        if root.is_dir() else []


def _files(with_marketplace: bool) -> Dict[str, bytes]:
    """Every file of the export, by its path inside the export folder."""
    def as_json(value) -> bytes:
        return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")

    files = {".claude-plugin/plugin.json": as_json(manifest()), "hooks/hooks.json": as_json({"hooks": {}})}
    if with_marketplace:
        files[".claude-plugin/marketplace.json"] = as_json(marketplace())
    for skill in _shipped("skills"):
        if skill.is_dir():
            for entry in sorted(skill.iterdir(), key=lambda e: e.name):
                if entry.is_file() and not entry.name.startswith(("_", ".")):
                    files[f"skills/{skill.name}/{entry.name}"] = entry.read_bytes()
    for agent in _shipped("agents"):
        if agent.is_file() and agent.name.endswith(".md"):
            files[f"agents/{agent.name}"] = agent.read_bytes()
    if not any(p.startswith("skills/") for p in files):
        raise PluginError("this agentcad ships no skills; the install is incomplete")
    return files


def _clear(out: Path) -> None:
    """Make ``out`` ready for an export: missing or empty, or an earlier export, which is removed. At the top of
    ``out`` an export owns only the four entries it writes, and anything else there is refused by name; inside
    those entries everything is the export's, so a file added there by hand is removed with the rest."""
    if not out.exists():
        return
    if not out.is_dir():
        raise PluginError(f"{out} is a file, not a folder")
    other = sorted(e.name for e in out.iterdir() if e.name not in WRITTEN)
    if other:
        raise PluginError(f"{out} holds files an export does not write ({', '.join(other[:5])}); "
                          f"give an empty folder or an earlier export")
    present = [e for e in out.iterdir()]
    if present:
        try:
            earlier = json.loads((out / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            earlier = None
        if not isinstance(earlier, dict) or earlier.get("name") != NAME:
            raise PluginError(f"{out} is not an earlier agentcad export (no .claude-plugin/plugin.json naming "
                              f"{NAME}); give an empty folder")
        for entry in present:
            shutil.rmtree(entry) if entry.is_dir() and not entry.is_symlink() else entry.unlink()


def export(out: Union[str, Path], target: str = "claude-code", with_marketplace: bool = False) -> List[Path]:
    """Write the plugin for ``target`` into ``out``; the files written, in order. A refusal (PluginError) is said
    before anything is removed or written; a failure while writing (a full disk) can leave a partial export, which
    the next export replaces. A folder ``out`` that already existed keeps its own mode."""
    if target not in TARGETS:
        raise PluginError(f"no plugin target {target!r} (there is: {', '.join(TARGETS)})")
    out = Path(out)
    files = _files(with_marketplace)
    _clear(out)
    created = not out.exists()
    written = []
    for rel in sorted(files):
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(files[rel])
        path.chmod(0o644)
        written.append(path)
    inside = {parent for p in written for parent in p.relative_to(out).parents if str(parent) != "."}
    for folder in sorted(inside):
        (out / folder).chmod(0o755)
    if created:
        out.chmod(0o755)
    return written
