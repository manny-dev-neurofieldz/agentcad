"""Run the walkthroughs and keep their pictures true.

A walkthrough is ``examples/<name>/WALKTHROUGH.md``: prose plus fenced ``console`` blocks in the recipe format the
policies use (first line ``# recipe: examples|fixtures|empty``, ``$ agentcad ...`` steps, the output lines each must
show, ``# exit N``). One line more is understood here: inside a block,

    # image: SRC -> DEST

means "after the step just above ran, take SRC (a path relative to the scratch workspace root) as the picture
``docs/images/<name>/DEST``". Each block of a file runs in a scratch workspace of its own, as a recipe does, so a block is
self-contained: a later block repeats the earlier steps it builds on.

Usage: python examples/build_walkthroughs.py [--only NAME ...] [--verify] [--root DIR] [--images DIR]
  (none)    run each walkthrough, check every step, write the images (longest side <= 768 px, PNG < 150 kB)
  --verify  run each walkthrough and check every SRC was produced and every DEST already exists; images are not
            compared, because renders differ between machines
  --root    the folder holding <name>/WALKTHROUGH.md (default: this folder)
  --examples the examples/ folder a scratch workspace copies (default: this folder); needed with --root when
            the walkthroughs live in another checkout
  --images  the folder the pictures live in, <images>/<name>/DEST (default: <repo>/docs/images)

A walkthrough whose engine is not installed is skipped with the reason, except under --verify with
AGENTCAD_DOCS_STRICT=1 (CI), where that is an error. Exit status: 0 all good, 1 a problem, 2 a usage error.
"""

import argparse
import contextlib
import io
import os
import re
import shlex
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
EXAMPLES = HERE  # the examples/ folder copied into a scratch workspace; see --examples
FIXTURES = REPO / "tests" / "data"
DEFAULT_IMAGES = REPO / "docs" / "images"
#: Generated folders an example may hold in a working checkout; a walkthrough starts without them.
GENERATED = ("_work", "exports", "renders", "viewer", "_archive", "__pycache__")
IMAGE_MARK = "# image:"
MAX_SIDE = 768
MAX_BYTES = 150_000


class WalkthroughError(Exception):
    """A problem in a walkthrough's text or in what its steps did; the message names file and line."""


@dataclass
class Image:
    line: int
    src: str
    dest: str


@dataclass
class Item:
    """One step as the builder runs it: the command, what it must show, and the pictures that follow it."""
    line: int
    argv: List[str]
    exit: int
    expect: List[str]
    images: List[Image] = field(default_factory=list)


@dataclass
class Block:
    """One recipe block: it runs in a scratch workspace of its own, so a block is self-contained."""
    line: int
    workspace: str
    items: List[Item]


@dataclass
class Walkthrough:
    name: str
    path: Path
    blocks: List[Block]

    @property
    def items(self) -> List[Item]:
        return [i for b in self.blocks for i in b.items]


def _import_policy():
    from agentcad import policy
    return policy


def parse(name: str, path: Path) -> Walkthrough:
    """Read a walkthrough: its recipe blocks (through the policy parser, so the format is one format) and its
    image lines. Raises WalkthroughError for a file with no recipe, an image line under no step, or a
    destination that leaves docs/images/<name>/."""
    pol = _import_policy()
    text = path.read_text(encoding="utf-8")
    shown = str(path)
    try:
        recipes = pol.recipes(pol.Policy(shown, text, {}))
    except pol.PolicyError as e:
        raise WalkthroughError(str(e)) from None
    if not recipes:
        raise WalkthroughError(f"{shown}: no recipe block (a ```console block whose first line is '# recipe: ...')")
    marked = [(at, body) for at, info, body in pol._fences(text)
              if info == "console" and body and body[0].startswith(pol.RECIPE_MARK)]
    blocks: List[Block] = []
    for recipe, (at, body) in zip(recipes, marked):
        items: List[Item] = []
        blocks.append(Block(at, recipe.workspace, items))
        steps = iter(recipe.steps)
        current: Optional[Item] = None
        for n, line in enumerate(body, at + 1):
            if line.startswith("$ "):
                step = next(steps)
                current = Item(n, step.argv, step.exit, step.expect)
                items.append(current)
            elif line.startswith(IMAGE_MARK):
                image = _image(shown, name, n, line[len(IMAGE_MARK):])
                if current is None:
                    raise WalkthroughError(f"{shown}:{n}: an image line must come under a step "
                                           f"(a '$ agentcad ...' line), not before the first")
                current.images.append(image)
    return Walkthrough(name, path, blocks)


def _image(shown: str, name: str, n: int, spec: str) -> Image:
    if "->" not in spec:
        raise WalkthroughError(f"{shown}:{n}: an image line reads '# image: SRC -> DEST'")
    src, dest = (part.strip() for part in spec.split("->", 1))
    if not src or not dest:
        raise WalkthroughError(f"{shown}:{n}: an image line needs both a SRC and a DEST")
    d = Path(dest)
    if d.is_absolute() or ".." in d.parts or dest.startswith("~"):
        raise WalkthroughError(f"{shown}:{n}: image destination {dest!r} leaves docs/images/{name}/; "
                               f"give a plain file name or a path below it")
    if d.suffix.lower() != ".png":
        raise WalkthroughError(f"{shown}:{n}: image destination {dest!r} is not a .png file")
    s = Path(src)
    if s.is_absolute() or ".." in s.parts:
        raise WalkthroughError(f"{shown}:{n}: image source {src!r} must be relative to the scratch workspace")
    return Image(n, src, dest)


def _engines_named(wt: Walkthrough) -> List[str]:
    from agentcad.config import find_project

    names = set()
    for item in wt.items:
        for word in item.argv:
            if word.startswith("examples/"):
                project = find_project(EXAMPLES / Path(word).relative_to("examples").parts[0])
                if project is not None:
                    names.add(project.engine)
    return sorted(names)


def missing_engines(wt: Walkthrough) -> List[str]:
    from agentcad.engines import get_engine

    return [n for n in _engines_named(wt) if not get_engine(n).available()]


def make_workspace(kind: str, scratch: Path) -> None:
    """The scratch workspace test_recipes.py gives a recipe: a copy of examples/ and, for `fixtures`,
    tests/data as ./fixtures."""
    if kind in ("examples", "fixtures"):
        shutil.copytree(EXAMPLES, scratch / "examples", ignore=shutil.ignore_patterns(*GENERATED))
    if kind == "fixtures":
        shutil.copytree(FIXTURES, scratch / "fixtures")


@contextlib.contextmanager
def _in(scratch: Path):
    """cd into the scratch folder with a config folder of its own, so a walkthrough never sees the reader's
    printer hosts or settings; restore both afterwards."""
    old_cwd, old_xdg = os.getcwd(), os.environ.get("XDG_CONFIG_HOME")
    os.environ["XDG_CONFIG_HOME"] = str(scratch / ".config")
    os.chdir(scratch)
    try:
        yield
    finally:
        os.chdir(old_cwd)
        if old_xdg is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = old_xdg


def run_cli(argv: List[str]) -> Tuple[int, str, str]:
    """(exit status, stdout, stderr) of agentcad.cli.main(argv), run in this process."""
    from agentcad import cli

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            cli.main([str(a) for a in argv])
            rc = 0
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    return rc, out.getvalue(), err.getvalue()


def run_steps(wt: Walkthrough, block: Block, scratch: Path) -> List[Tuple[Image, Path]]:
    """Run the block's steps in order inside its scratch workspace. Returns (image, produced SRC path) for each image
    line; a SRC that was not produced is returned as a path that does not exist, for the caller to name."""
    pol = _import_policy()
    produced: List[Tuple[Image, Path]] = []
    with _in(scratch):
        for item in block.items:
            said = f"{wt.path}:{item.line}: step 'agentcad {' '.join(shlex.quote(a) for a in item.argv)}'"
            rc, out, err = run_cli(item.argv)
            if rc != item.exit:
                raise WalkthroughError(f"{said} ended with {rc}, the walkthrough says {item.exit}:\n{out}\n{err}")
            missing = pol.expect_matches(item.expect, out + "\n" + err)
            if missing is not None:
                raise WalkthroughError(f"{said} did not show {missing!r}:\n{out}\n{err}")
            for image in item.images:
                produced.append((image, scratch / image.src))
    return produced


def save_image(src: Path, dest: Path) -> str:
    """Write src as a PNG at dest, longest side <= MAX_SIDE, under MAX_BYTES (a 256-colour palette when a
    plain save is too big). Returns a description of what was written."""
    from PIL import Image as PILImage

    img = PILImage.open(src)
    img.load()
    if max(img.size) > MAX_SIDE:
        scale = MAX_SIDE / max(img.size)
        img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), PILImage.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "PNG", optimize=True)
    note = ""
    if dest.stat().st_size >= MAX_BYTES:
        img.convert("RGB").quantize(256).save(dest, "PNG", optimize=True)
        note = ", 256 colours"
    size = dest.stat().st_size
    if size >= MAX_BYTES:
        dest.unlink()
        raise WalkthroughError(f"{dest}: {size} bytes after palette reduction; the limit is {MAX_BYTES}. "
                               f"Render a simpler view or a smaller image_size")
    return f"{img.width}x{img.height}, {size / 1000:.1f} kB{note}"


def process(wt: Walkthrough, images_root: Path, verify: bool, strict: bool) -> List[str]:
    """Build or verify one walkthrough. Returns the problems (empty when all is well); prints progress."""
    absent = missing_engines(wt)
    if absent:
        reason = f"engine {', '.join(absent)} is not installed here"
        if verify and strict:
            return [f"{wt.path}: {reason} (AGENTCAD_DOCS_STRICT=1)"]
        print(f"skip {wt.name}: {reason}")
        return []
    problems: List[str] = []
    steps = images = 0
    for block in wt.blocks:
        scratch = Path(tempfile.mkdtemp(prefix=f"walkthrough_{wt.name}_"))
        try:
            make_workspace(block.workspace, scratch)
            try:
                produced = run_steps(wt, block, scratch)
            except WalkthroughError as e:
                problems.append(str(e))
                continue
            steps += len(block.items)
            images += len(produced)
            for image, src in produced:
                dest = images_root / wt.name / image.dest
                where = f"{wt.path}:{image.line}"
                if not src.is_file():
                    problems.append(f"{where}: the step did not produce {image.src}")
                elif verify:
                    if not dest.is_file():
                        problems.append(f"{where}: {dest} does not exist; run build_walkthroughs.py to write it")
                else:
                    try:
                        print(f"wrote {dest} ({save_image(src, dest)})")
                    except WalkthroughError as e:
                        problems.append(f"{where}: {e}")
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
    if not problems:
        print(f"ok   {wt.name}: {len(wt.blocks)} block(s), {steps} step(s), {images} image(s)")
    return problems


def find(root: Path, only: Optional[List[str]]) -> Dict[str, Path]:
    found = {p.parent.name: p for p in sorted(root.glob("*/WALKTHROUGH.md"))}
    if only:
        unknown = [n for n in only if n not in found]
        if unknown:
            raise SystemExit(f"no WALKTHROUGH.md for: {', '.join(unknown)} (under {root})")
        found = {n: found[n] for n in only}
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", nargs="+", metavar="NAME", help="only these walkthroughs")
    ap.add_argument("--verify", action="store_true", help="check that every picture exists; write nothing")
    ap.add_argument("--root", type=Path, default=HERE, help="folder holding <name>/WALKTHROUGH.md")
    ap.add_argument("--examples", type=Path, default=None, help="examples/ folder to copy into workspaces")
    ap.add_argument("--images", type=Path, default=DEFAULT_IMAGES, help="folder the pictures live in")
    args = ap.parse_args(argv)
    global EXAMPLES
    if args.examples is not None:
        EXAMPLES = args.examples.resolve()
    strict = os.environ.get("AGENTCAD_DOCS_STRICT") == "1"

    problems: List[str] = []
    walkthroughs = find(args.root, args.only)
    if not walkthroughs:
        print(f"no walkthroughs under {args.root}")
    for name, path in walkthroughs.items():
        try:
            wt = parse(name, path)
        except WalkthroughError as e:
            problems.append(str(e))
            continue
        problems += process(wt, args.images, args.verify, strict)
    for p in problems:
        print(f"PROBLEM {p}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
