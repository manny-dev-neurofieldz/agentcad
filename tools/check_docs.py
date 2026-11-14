"""Check that agentcad's documentation is true where a machine can tell.

Usage: python tools/check_docs.py [--no-mermaid] [--root DIR] [--mermaid-js FILE]

Over README.md, AGENTS.md, docs/**/*.md, examples/*/WALKTHROUGH.md, examples/*/README.md and
src/agentcad/policies/*.md it checks:

  a. every relative link and image target resolves to a file (http(s):, mailto: and pure #anchors are skipped;
     a #fragment is stripped; targets resolve relative to the file that holds them)
  b. every ```mermaid block starts with a diagram kind a code host renders (policy.MERMAID_KINDS) and, unless
     --no-mermaid, parses with Mermaid 11.4.1 in headless Chromium (Playwright). The Mermaid bundle comes from
     --mermaid-js or the MERMAID_JS environment variable; when blocks exist and either Playwright or the bundle
     is missing the check says so and exits 2 instead of passing silently
  c. no flowchart is drawn as text art: a fenced block with no info string (or text/txt/ascii) holding arrows
     (-->, <--, a line that is only v or ^), box corners or +-- joints should be a mermaid diagram. Directory
     box-drawing trees and tables are not flagged
  d. AGENTS.md at the root, when present, equals what `agentcad plugin export --target agents-md` writes

Each problem prints as FILE:LINE: what. Exit status: 0 clean, 1 problems, 2 the Mermaid parse could not run.
"""

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
MERMAID_VERSION = "11.4.1"
PLAIN_INFO = ("", "text", "txt", "ascii")
LINK = re.compile(r"\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
REF_DEF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s+.*)?$")
SKIP_SCHEMES = ("http://", "https://", "mailto:", "ftp://", "data:")
ARROWS = re.compile(r"-->|<--|==>|<==|[\u25bc\u25b2\u25ba\u25c4\u25b6\u25c0\u2192\u2190\u2193\u2191\u21d2\u21d0]")
CORNERS = re.compile(r"[\u250c\u2510\u2518\u252c\u2534\u253c\u2554\u2557\u255a\u255d\u256d\u256e\u2570\u256f]|\+-{2,}|-{2,}\+")
LONE_CONNECTOR = re.compile(r"^\s*[vV^|]\s*$")


def doc_files(root: Path) -> List[Path]:
    found = [root / "README.md", root / "AGENTS.md"]
    found += sorted((root / "docs").glob("**/*.md"))
    found += sorted((root / "examples").glob("*/WALKTHROUGH.md"))
    found += sorted((root / "examples").glob("*/README.md"))
    found += sorted((root / "src" / "agentcad" / "policies").glob("*.md"))
    return [p for p in found if p.is_file()]


def fences(text: str) -> List[Tuple[int, str, List[str]]]:
    """(line of the opening fence, info string, body lines) for each fenced block, by the policy parser's own
    rule (a fence is a line starting with three backticks or three tildes), so docs and policies agree."""
    from agentcad.policy import _fences

    return _fences(text)


def _outside_fences(text: str):
    """(line number, line) for every line not inside a fenced block (fence lines themselves excluded)."""
    inside, marker = False, ""
    for n, line in enumerate(text.split("\n"), 1):
        if inside:
            if line.startswith(marker):
                inside = False
            continue
        if line.startswith("```") or line.startswith("~~~"):
            inside, marker = True, line[:3]
            continue
        yield n, line


def check_links(path: Path, text: str, root: Path) -> List[str]:
    problems = []
    for n, line in _outside_fences(text):
        bare = re.sub(r"`[^`]*`", "", line)
        targets = LINK.findall(bare)
        ref = REF_DEF.match(bare)
        if ref:
            targets.append(ref.group(1))
        for target in targets:
            if target.startswith(SKIP_SCHEMES) or target.startswith("#"):
                continue
            file_part = target.split("#", 1)[0].split("?", 1)[0]
            if not file_part:
                continue
            base = root if file_part.startswith("/") else path.parent
            if not (base / file_part.lstrip("/")).exists():
                problems.append(f"{_rel(path, root)}:{n}: link target {target!r} does not exist")
    return problems


def mermaid_blocks(text: str) -> List[Tuple[int, str]]:
    return [(at, "\n".join(body)) for at, info, body in fences(text) if info == "mermaid"]


def _kind(src: str) -> str:
    for line in src.split("\n"):
        s = line.strip()
        if s and not s.startswith("%%"):
            return s.split()[0]
    return ""


def check_mermaid_kinds(path: Path, text: str, root: Path) -> List[str]:
    from agentcad.policy import MERMAID_KINDS

    problems = []
    for at, src in mermaid_blocks(text):
        kind = _kind(src)
        if kind not in MERMAID_KINDS:
            problems.append(f"{_rel(path, root)}:{at}: mermaid block starts with {kind!r}, not one of "
                            f"{', '.join(MERMAID_KINDS)}")
    return problems


def _art(body: List[str]) -> bool:
    """True when a plain block draws a diagram: arrows, a lone v/^ connector, box corners or +-- joints."""
    has_tree = any(re.search(r"[\u251c\u2514]\u2500\u2500|\|--|`--", line) for line in body)
    text = "\n".join(body)
    if ARROWS.search(text) or CORNERS.search(text):
        return True
    if has_tree:
        return False
    return sum(bool(LONE_CONNECTOR.match(line) and line.strip() != "|") for line in body) >= 1 and \
        sum(1 for line in body if line.strip()) >= 3


def check_ascii_art(path: Path, text: str, root: Path) -> List[str]:
    return [f"{_rel(path, root)}:{at}: text-art diagram in a plain fenced block; draw it as a ```mermaid block"
            for at, info, body in fences(text) if info.lower() in PLAIN_INFO and _art(body)]


def check_agents_md(root: Path) -> List[str]:
    target = root / "AGENTS.md"
    if not target.is_file():
        return []
    import contextlib
    import io

    from agentcad import cli

    with tempfile.TemporaryDirectory(prefix="check_docs_") as tmp:
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                cli.main(["plugin", "export", "--target", "agents-md", "-o", tmp])
        except SystemExit as e:
            if e.code not in (0, None):
                return [f"AGENTS.md:1: `agentcad plugin export --target agents-md` failed ({e.code})"]
        made = Path(tmp) / "AGENTS.md"
        if not made.is_file():
            return ["AGENTS.md:1: the export wrote no AGENTS.md"]
        want, have = made.read_text(encoding="utf-8"), target.read_text(encoding="utf-8")
    if want == have:
        return []
    a, b = want.split("\n"), have.split("\n")
    first = next((i for i, (x, y) in enumerate(zip(a, b), 1) if x != y), min(len(a), len(b)) + 1)
    return [f"AGENTS.md:{first}: differs from `agentcad plugin export --target agents-md` "
            f"(first difference here); regenerate it"]


def parse_mermaid(blocks: List[Tuple[Path, int, str]], js: Path, root: Path) -> List[str]:
    from playwright.sync_api import sync_playwright

    problems = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content("<html><body></body></html>")
        page.add_script_tag(path=str(js))
        for path, at, src in blocks:
            result = page.evaluate("async s => { try { await mermaid.parse(s); return 'ok'; } "
                                   "catch (e) { return String(e.message || e); } }", src)
            if result != "ok":
                first = " ".join(result.split())[:240]
                problems.append(f"{_rel(path, root)}:{at}: mermaid does not parse: {first}")
        browser.close()
    return problems


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--no-mermaid", action="store_true", help="skip parsing Mermaid blocks (kinds are still checked)")
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="the repository root to check")
    ap.add_argument("--mermaid-js", type=Path, default=None, help=f"mermaid.min.js of Mermaid {MERMAID_VERSION} "
                    f"(default: $MERMAID_JS)")
    args = ap.parse_args(argv)
    root = args.root.resolve()

    problems: List[str] = []
    blocks: List[Tuple[Path, int, str]] = []
    for path in doc_files(root):
        text = path.read_text(encoding="utf-8")
        problems += check_links(path, text, root)
        problems += check_mermaid_kinds(path, text, root)
        problems += check_ascii_art(path, text, root)
        blocks += [(path, at, src) for at, src in mermaid_blocks(text)]
    problems += check_agents_md(root)

    incomplete = None
    if blocks and not args.no_mermaid:
        js = args.mermaid_js or (Path(os.environ["MERMAID_JS"]) if os.environ.get("MERMAID_JS") else None)
        try:
            import playwright.sync_api  # noqa: F401
        except ImportError:
            incomplete = "Playwright is not installed (python -m pip install playwright; playwright install chromium)"
        else:
            if js is None or not js.is_file():
                incomplete = (f"no Mermaid bundle: pass --mermaid-js or set MERMAID_JS to the mermaid.min.js of "
                              f"mermaid@{MERMAID_VERSION}" + (f" ({js} is not a file)" if js else ""))
        if incomplete is None:
            problems += parse_mermaid(blocks, js, root)
    for p in problems:
        print(p)
    if incomplete:
        print(f"check_docs: {len(blocks)} mermaid block(s) could not be parsed: {incomplete}", file=sys.stderr)
        return 2
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
