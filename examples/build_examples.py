"""Run every example project through a design session, from scratch.

For each ``examples/<name>/agentcad.toml``: archive any previous session,
start one, iterate the source once, and finalize (exports, print manifest,
viewer). A project that declares parts starts each part's session with
``-D part=<part>`` and iterates and finalizes them with ``--all``. A failure
in any example fails the run, so the gallery workflow doubles as an
end-to-end test of the tool on every engine.

Usage: python examples/build_examples.py [--only NAME ...] [--keep]
  --keep   do not archive a previous session first (re-run in place)
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run(*args: str) -> None:
    cmd = ["agentcad", *args]
    print("+", " ".join(str(a) for a in cmd), flush=True)
    result = subprocess.run(cmd, text=True)
    if result.returncode != 0:
        raise SystemExit(f"example step failed ({result.returncode}): {' '.join(cmd)}")


def build(example: Path, keep: bool) -> None:
    from agentcad.config import find_project

    project = find_project(example)
    if project is None:
        raise SystemExit(f"{example}: no agentcad.toml")
    cfg = {"project": {"name": project.name, "parts": project.parts}}
    name = cfg["project"]["name"]
    parts = cfg["project"].get("parts") or []
    import re
    # the session copies each iteration back as <name>_vN.<ext>; the hand-written source is the other file
    sources = sorted(p for p in (example / "source").iterdir() if p.is_file() and not re.search(r"_v\d+\.", p.name))
    if not sources:
        raise SystemExit(f"{example}: no source file")
    source = sources[0]

    start = ["session", "start", str(example)] + ([] if keep else ["-f"])
    run(*start)
    part_folders = []
    for pattern in ([parts] if isinstance(parts, str) else parts):
        part_folders += sorted(p for p in example.glob(pattern) if (p / "agentcad.toml").exists())
    for folder in part_folders:
        run("session", "start", str(folder), "-D", f"part={folder.name}", *([] if keep else ["-f"]))
    run("session", "iterate", str(example), str(source), *(["--all"] if part_folders else []))
    run("session", "note", str(example), f"built by examples/build_examples.py from {source.name}")
    run("session", "finalize", str(example), *(["--all"] if part_folders else []))
    print(f"= {name}: ok", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", nargs="*", default=None, help="example names to build (default: all)")
    ap.add_argument("--keep", action="store_true", help="re-run in place without archiving")
    args = ap.parse_args(argv)
    examples = sorted(p.parent for p in ROOT.glob("*/agentcad.toml"))
    if args.only:
        examples = [e for e in examples if e.name in args.only]
    if not examples:
        print("no examples found", file=sys.stderr)
        return 1
    for example in examples:
        build(example, args.keep)
    print(f"built {len(examples)} example(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
