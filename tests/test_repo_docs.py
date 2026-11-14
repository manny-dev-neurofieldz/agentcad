"""The repository's own documentation, checked by the two docs tools in the ordinary test run.

tests/test_check_docs.py and tests/test_walkthroughs.py show the tools red and green on small trees made in
tmp_path; these run them on README.md, docs/, the policies and examples/*/WALKTHROUGH.md as they are. The
walkthroughs replay in scratch workspaces (``--verify`` writes nothing), with PrusaSlicer hidden so a machine
that has it reads the same output as one that does not. On GitHub Actions a walkthrough whose engine is
missing is an error rather than a skip, so a silent skip cannot pass for a replay there.
"""
import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cd = _load("tools/check_docs.py", "check_docs")
bw = _load("examples/build_walkthroughs.py", "build_walkthroughs")


def _mermaid_here():
    js = os.environ.get("MERMAID_JS")
    if not js or not Path(js).is_file():
        return False
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            pw.chromium.launch().close()
    except Exception:
        return False
    return True


def test_the_repositorys_docs_have_no_broken_link_text_art_or_stale_agents_md(capsys):
    """Links, images, diagram kinds, text-art flowcharts and AGENTS.md; the Mermaid parse too where it can run."""
    extra = [] if _mermaid_here() else ["--no-mermaid"]
    rc = cd.main(["--root", str(ROOT), *extra])
    out = capsys.readouterr().out
    assert rc == 0, out


def test_every_walkthrough_replays_as_printed(capsys, monkeypatch):
    monkeypatch.setenv("AGENTCAD_PRUSASLICER", str(ROOT / "no-such-dir" / "prusa-slicer"))
    if os.environ.get("GITHUB_ACTIONS") == "true":
        monkeypatch.setenv("AGENTCAD_DOCS_STRICT", "1")
    rc = bw.main(["--verify"])
    captured = capsys.readouterr()
    if rc == 0 and "ok " not in captured.out:
        pytest.skip("no walkthrough could run here: " + captured.out.strip().replace("\n", "; "))
    assert rc == 0, captured.out + captured.err
