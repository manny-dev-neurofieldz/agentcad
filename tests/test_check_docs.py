"""tools/check_docs.py: red on each kind of untrue documentation, green on a clean tree.

The tool is a plain file under tools/ (not a package), loaded by path. Each case builds a tiny repository in
tmp_path and runs the tool on it with --root. The Mermaid parse needs Playwright with Chromium and the
mermaid.min.js named by $MERMAID_JS; without them that one case is skipped, while the kind check always runs.
"""
import importlib.util
import os
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "check_docs.py"
spec = importlib.util.spec_from_file_location("check_docs", SCRIPT)
cd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cd)

FLOW = "```mermaid\nflowchart TD\n  A[start] --> B[end]\n```\n"


def tree(tmp_path, readme="# Title\n\nHello.\n", **files):
    """A tiny repository: README.md plus files given as path=text, with __ standing for / and _ext for .ext."""
    (tmp_path / "README.md").write_text(readme)
    for rel, text in files.items():
        name, _, ext = rel.rpartition("_")
        p = tmp_path / (name.replace("__", "/") + "." + ext)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return tmp_path


def check(root, capsys, *extra):
    rc = cd.main(["--root", str(root), *extra])
    return rc, capsys.readouterr().out


def have_mermaid():
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


def test_a_clean_tree_passes(tmp_path, capsys):
    root = tree(tmp_path, readme=f"# T\n\nSee [guide](docs/guide.md#top), [web](https://x.example/a), [here](#t) "
                                 f"and `[not](a link.md)`.\n\n![pic](docs/images/a.png)\n\n{FLOW}\n"
                                 f"```text\nsrc/\n\u251c\u2500\u2500 a.py\n\u2514\u2500\u2500 b.py\n```\n",
                docs__guide_md="# G\n\n[back](../README.md)\n", docs__images__a_png="x")
    assert check(root, capsys, "--no-mermaid") == (0, "")


def test_a_broken_link_is_named_with_file_and_line(tmp_path, capsys):
    root = tree(tmp_path, readme="# T\n\nfine\n\nsee [gone](docs/gone.md)\n")
    rc, out = check(root, capsys, "--no-mermaid")
    assert rc == 1 and out.startswith("README.md:5:") and "docs/gone.md" in out


def test_a_link_resolves_from_the_file_that_holds_it(tmp_path, capsys):
    root = tree(tmp_path, docs__a_md="[ok](b.md) [bad](../b.md)\n")
    (root / "docs" / "b.md").write_text("b\n")
    rc, out = check(root, capsys, "--no-mermaid")
    assert rc == 1 and "docs/a.md:1" in out and out.count("\n") == 1


def test_a_missing_image_is_a_problem(tmp_path, capsys):
    root = tree(tmp_path, examples__hex__WALKTHROUGH_md="![v1](../../docs/images/hex/v1.png)\n")
    rc, out = check(root, capsys, "--no-mermaid")
    assert rc == 1 and "examples/hex/WALKTHROUGH.md:1" in out and "v1.png" in out


def test_a_mermaid_block_that_starts_with_no_known_kind_is_a_problem_even_without_the_parser(tmp_path, capsys):
    root = tree(tmp_path, readme="# T\n\n```mermaid\nflowchat TD\n  A --> B\n```\n")
    rc, out = check(root, capsys, "--no-mermaid")
    assert rc == 1 and "README.md:3" in out and "flowchat" in out


@pytest.mark.skipif(not have_mermaid(), reason="needs Playwright with Chromium and MERMAID_JS")
def test_a_mermaid_block_that_does_not_parse_is_a_problem_and_a_good_one_is_not(tmp_path, capsys):
    root = tree(tmp_path, readme=f"# T\n\n{FLOW}\n```mermaid\nflowchart TD\n  A --> \n  B[unclosed\n```\n")
    rc, out = check(root, capsys)
    assert rc == 1 and "README.md:8" in out and "does not parse" in out and "README.md:3" not in out


def test_blocks_without_playwright_or_the_bundle_exit_2_rather_than_pass(tmp_path, capsys, monkeypatch):
    root = tree(tmp_path, readme=f"# T\n\n{FLOW}")
    monkeypatch.delenv("MERMAID_JS", raising=False)
    rc, out = check(root, capsys)
    assert rc == 2
    assert check(root, capsys, "--mermaid-js", str(tmp_path / "nope.js"))[0] == 2


def test_no_mermaid_blocks_need_no_parser(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("MERMAID_JS", raising=False)
    assert check(tree(tmp_path), capsys)[0] == 0


@pytest.mark.parametrize("art", [
    "[start]\n   |\n   v\n[middle]\n   |\n   v\n[end]",
    "A --> B --> C",
    "+-----+     +-----+\n| one |---->| two |\n+-----+     +-----+",
    "\u250c\u2500\u2500\u2500\u2500\u2500\u2510\n\u2502 box \u2502\n\u2514\u2500\u2500\u2500\u2500\u2500\u2518",
])
def test_an_ascii_flowchart_is_reported_at_its_fence(tmp_path, capsys, art):
    root = tree(tmp_path, readme=f"# T\n\ntext\n\n```\n{art}\n```\n")
    rc, out = check(root, capsys, "--no-mermaid")
    assert rc == 1 and out.startswith("README.md:5:") and "mermaid" in out


@pytest.mark.parametrize("fenced", [
    "```text\nsrc/\n\u251c\u2500\u2500 a.py\n\u2502   \u2514\u2500\u2500 b.py\n\u2514\u2500\u2500 c.py\n```",
    "```\n| a | b |\n|---|---|\n| 1 | 2 |\n```",
    "```console\n$ agentcad info\nv1 --> kept, a console block is not art\n```",
    "```python\nx = a --> b\n```",
])
def test_trees_tables_and_other_languages_are_not_art(tmp_path, capsys, fenced):
    assert check(tree(tmp_path, readme=f"# T\n\n{fenced}\n"), capsys, "--no-mermaid")[0] == 0


def test_a_stale_agents_md_is_reported_and_a_fresh_one_passes(tmp_path, capsys):
    from agentcad import cli
    root = tree(tmp_path, AGENTS_md="# old\n")
    rc, out = check(root, capsys, "--no-mermaid")
    assert rc == 1 and out.startswith("AGENTS.md:1:") and "plugin export" in out
    cli.main(["plugin", "export", "--target", "agents-md", "-o", str(tmp_path / "out")])
    capsys.readouterr()
    (root / "AGENTS.md").write_bytes((tmp_path / "out" / "AGENTS.md").read_bytes())
    assert check(root, capsys, "--no-mermaid") == (0, "")


def test_no_agents_md_is_not_a_problem(tmp_path, capsys):
    assert check(tree(tmp_path), capsys, "--no-mermaid") == (0, "")
