"""agentcad plugin export: the package's skills and reviewer agent as a Claude Code plugin, the same bytes every
time, never deleting what it did not write, and valid by ``claude plugin validate --strict`` where Claude Code is
installed."""
import json
import shutil
import stat
import subprocess
from importlib import resources

import pytest

import agentcad
from agentcad import plugin
from tests.gcode_fixtures import run_cli


def _tree(root):
    """Every file and folder under ``root``: relative path -> (mode bits, bytes or None for a folder)."""
    out = {}
    for path in sorted(root.rglob("*")):
        mode = stat.S_IMODE(path.stat().st_mode)
        out[str(path.relative_to(root))] = (mode, path.read_bytes() if path.is_file() else None)
    return out


def _shipped_skills():
    return sorted(e.name for e in (resources.files("agentcad") / "skills").iterdir()
                  if e.is_dir() and not e.name.startswith(("_", ".")))


def test_an_export_holds_the_manifest_the_skills_the_reviewer_and_no_hooks(tmp_path):
    out = tmp_path / "plug"
    written = plugin.export(out)
    rel = sorted(str(p.relative_to(out)) for p in written)
    assert rel == sorted([".claude-plugin/plugin.json", "hooks/hooks.json", "agents/design-reviewer.md"]
                         + [f"skills/{s}/SKILL.md" for s in _shipped_skills()])
    assert len(_shipped_skills()) >= 6
    meta = json.loads((out / ".claude-plugin/plugin.json").read_text())
    assert meta["name"] == "agentcad" and meta["version"] == agentcad.__version__
    assert meta["description"] and meta["author"]["name"]
    assert json.loads((out / "hooks/hooks.json").read_text()) == {"hooks": {}}
    for s in _shipped_skills():
        shipped = (resources.files("agentcad") / "skills" / s / "SKILL.md").read_bytes()
        assert (out / "skills" / s / "SKILL.md").read_bytes() == shipped, f"{s} copied byte for byte"
    assert not (out / ".claude-plugin/marketplace.json").exists()
    assert not list(out.rglob("*.py")) and not (out / "policies").exists(), "no code and no copied policies"


def test_the_same_package_exports_the_same_bytes_and_modes(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    plugin.export(a, with_marketplace=True)
    plugin.export(b, with_marketplace=True)
    assert _tree(a) == _tree(b)
    modes = {mode for mode, data in _tree(a).values() if data is not None}
    folders = {mode for mode, data in _tree(a).values() if data is None}
    assert modes == {0o644} and folders == {0o755}


def test_a_marketplace_offers_the_plugin_from_its_own_folder(tmp_path):
    out = tmp_path / "plug"
    plugin.export(out, with_marketplace=True)
    market = json.loads((out / ".claude-plugin/marketplace.json").read_text())
    assert market["name"] == "agentcad" and market["description"] and market["owner"]["name"]
    assert market["plugins"] == [{"name": "agentcad", "source": "./", "description": plugin.manifest()["description"],
                                  "version": agentcad.__version__}]


def test_an_earlier_export_is_replaced_whole_so_a_stale_skill_does_not_survive(tmp_path):
    out = tmp_path / "plug"
    plugin.export(out, with_marketplace=True)
    stale = out / "skills" / "retired-skill"
    stale.mkdir()
    (stale / "SKILL.md").write_text("---\nname: retired-skill\n---\n")
    plugin.export(out)
    assert not stale.exists() and not (out / ".claude-plugin/marketplace.json").exists()
    assert (out / "skills" / _shipped_skills()[0] / "SKILL.md").is_file()


@pytest.mark.parametrize("setup,said", [
    (lambda d: (d / "notes.txt").write_text("mine"), "notes.txt"),
    (lambda d: ((d / "skills").mkdir(), (d / "skills" / "x.md").write_text("mine")), "not an earlier agentcad export"),
    (lambda d: ((d / ".claude-plugin").mkdir(),
                (d / ".claude-plugin" / "plugin.json").write_text('{"name": "other"}')), "not an earlier agentcad export"),
])
def test_a_folder_holding_anything_else_is_refused_and_left_alone(tmp_path, setup, said):
    out = tmp_path / "plug"
    out.mkdir()
    setup(out)
    before = _tree(out)
    with pytest.raises(plugin.PluginError, match=said):
        plugin.export(out)
    assert _tree(out) == before, "nothing removed or written"


def test_the_command_writes_the_plugin_and_refuses_with_exit_2(tmp_path, capsys):
    out = tmp_path / "plug"
    rc, printed, _ = run_cli(capsys, "plugin", "export", "--target", "claude-code", "-o", out, "--marketplace")
    assert rc == 0 and "plugin.json" in printed and "claude plugin validate --strict" in printed
    assert (out / ".claude-plugin/marketplace.json").is_file()
    (tmp_path / "busy").mkdir()
    (tmp_path / "busy" / "mine.txt").write_text("x")
    rc, _, err = run_cli(capsys, "plugin", "export", "--target", "claude-code", "-o", tmp_path / "busy")
    assert rc == 2 and err.startswith("Error:") and "mine.txt" in err
    assert run_cli(capsys, "plugin", "export", "--target", "codex", "-o", out)[0] == 2


@pytest.mark.skipif(shutil.which("claude") is None, reason="Claude Code is not installed here")
def test_claude_code_validates_the_export_strictly(tmp_path):
    out = tmp_path / "plug"
    plugin.export(out, with_marketplace=True)
    for manifest in ("plugin.json", "marketplace.json"):
        done = subprocess.run(["claude", "plugin", "validate", "--strict", "--json",
                               str(out / ".claude-plugin" / manifest)], capture_output=True, text=True, timeout=120)
        report = json.loads(done.stdout)
        assert done.returncode == 0 and report["success"], (manifest, done.stdout[-2000:])
        assert not report["manifest"]["warnings"] and not report["manifest"]["errors"]
        assert all(not c["warnings"] and not c["errors"] for c in report["contents"])
