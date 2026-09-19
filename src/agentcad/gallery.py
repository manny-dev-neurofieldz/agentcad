"""The gallery: a static catalogue of project viewers.

``build`` scans project folders (each with an ``agentcad.toml``), writes an
``index.html`` of cards, one per project, with the latest iso render as a
thumbnail, the engine, the description, the iteration count and the
headline numbers of the last session iteration, and links each card to the
project's own viewer. With ``copy`` the viewer page and its renders are
copied under the gallery folder so the result is self-contained and can be
served as a static site; a project whose files exceed the size budget is
listed but not copied, and the build says so.

``check`` verifies a built gallery: every card's link and thumbnail
resolves and no reference is an absolute path.

The gallery never modifies a project; it reads what sessions produced.
"""

import html
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class Card:
    name: str
    engine: str
    description: str
    folder: Path
    viewer: Optional[Path]
    thumbnail: Optional[Path]
    iterations: int = 0
    finalized: Optional[str] = None
    headline: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    part_of: Optional[str] = None
    copied: bool = False
    skipped_reason: str = ""


def _folder_bytes(folder: Path) -> int:
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())


def _read_session(folder: Path) -> Dict[str, Any]:
    state = folder / "_work" / "session.json"
    if not state.exists():
        return {}
    try:
        return json.loads(state.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"agentcad warning: {state}: unreadable session record ({e}); card built without it", file=sys.stderr)
        return {}


def collect(folders: List[Path]) -> List[Card]:
    """One card per project folder, in the order given."""
    from agentcad.config import find_project

    cards: List[Card] = []
    for folder in folders:
        cfg = find_project(folder)
        if cfg is None:
            continue
        renders = folder / "renders"
        thumbs = sorted(renders.glob("*_iso.png"), key=lambda p: int(re.search(r"_v(\d+)_", p.name).group(1))
                        if re.search(r"_v(\d+)_", p.name) else 0)
        record = _read_session(folder)
        iterations = record.get("iterations") or []
        last = iterations[-1] if iterations else {}
        md = last.get("metadata") or {}
        headline = {}
        if "volume" in md:
            headline["volume"] = md["volume"]
        if (md.get("counts") or {}).get("solids") is not None:
            headline["solids"] = md["counts"]["solids"]
        tags = sorted((folder / "tags").glob("*/TAG.json")) if (folder / "tags").exists() else []
        cards.append(Card(
            name=cfg.name or folder.name, engine=cfg.engine, description=cfg.description, folder=folder,
            viewer=(folder / "index.html") if (folder / "index.html").exists() else None,
            thumbnail=thumbs[-1] if thumbs else None,
            iterations=len(iterations),
            finalized=(record.get("project_metadata") or {}).get("finalized"),
            headline=headline, tags=[t.parent.name for t in tags],
            part_of=cfg.parent_name,
        ))
    return cards


_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  :root {{ --bg: #1a1a2e; --card: #16213e; --accent: #0f3460; --text: #e0e0e0; --highlight: #e94560; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); padding: 2rem; }}
  h1 {{ color: #fff; margin-bottom: 0.25rem; }}
  .subtitle {{ color: #888; margin-bottom: 1.5rem; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 1.25rem; }}
  .card {{ background: var(--card); border-radius: 12px; overflow: hidden; display: flex; flex-direction: column; }}
  .card img {{ width: 100%; aspect-ratio: 1; object-fit: cover; background: #fff; }}
  .card .none {{ width: 100%; aspect-ratio: 1; display: flex; align-items: center; justify-content: center; color: #666; }}
  .card .body {{ padding: 0.9rem 1rem 1rem; display: flex; flex-direction: column; gap: 0.35rem; flex: 1; }}
  .card h2 {{ font-size: 1.05rem; color: #fff; }}
  .card h2 a {{ color: inherit; text-decoration: none; }}
  .card h2 a:hover {{ color: var(--highlight); }}
  .engine {{ display: inline-block; background: var(--accent); color: #fff; border-radius: 4px; padding: 1px 8px;
    font-size: 0.75rem; letter-spacing: 0.04em; text-transform: uppercase; }}
  .desc {{ color: #aaa; font-size: 0.9rem; line-height: 1.4; flex: 1; }}
  .facts {{ color: #888; font-size: 0.8rem; font-variant-numeric: tabular-nums; }}
  .facts span {{ margin-right: 0.8rem; }}
  .note {{ color: #f0c674; font-size: 0.8rem; }}
  footer {{ color: #666; font-size: 0.8rem; margin-top: 2rem; }}
</style>
</head>
<body>
<h1>{title}</h1>
<p class="subtitle">{count} project(s) &middot; built {built}</p>
<div class="grid">
{cards}
</div>
<footer>Generated by agentcad gallery build</footer>
</body>
</html>
"""

_CARD = """<div class="card">
{image}
<div class="body">
<h2>{link}</h2>
<span class="engine">{engine}</span>
<p class="desc">{description}</p>
<p class="facts">{facts}</p>
{note}
</div>
</div>"""


def _fmt_headline(card: Card) -> str:
    parts = []
    if card.iterations:
        parts.append(f"<span>{card.iterations} iteration{'s' if card.iterations != 1 else ''}</span>")
    if "volume" in card.headline:
        parts.append(f"<span>volume {float(card.headline['volume']):.4g}</span>")
    if "solids" in card.headline:
        parts.append(f"<span>solids {card.headline['solids']}</span>")
    if card.tags:
        parts.append(f"<span>tags: {', '.join(html.escape(t) for t in card.tags)}</span>")
    if card.part_of:
        parts.append(f"<span>part of {html.escape(card.part_of)}</span>")
    return " ".join(parts) or "<span>no session record</span>"


def build(folders: List[Path], out_dir: Path, *, title: str = "agentcad gallery",
          copy: bool = True, max_mb: float = 200.0) -> Path:
    """Write the gallery to ``out_dir/index.html``; returns that path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cards = collect([Path(f) for f in folders])
    budget = int(max_mb * 1024 * 1024)
    used = 0
    rendered = []
    for card in cards:
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", card.name)
        target = out_dir / slug
        link_href = None
        thumb_href = None
        if copy and card.viewer is not None:
            size = card.viewer.stat().st_size + (_folder_bytes(card.folder / "renders") if (card.folder / "renders").exists() else 0)
            if used + size > budget:
                card.skipped_reason = f"{size / 1048576:.1f} MB would exceed the {max_mb:g} MB budget; not copied"
                print(f"agentcad gallery: {card.name}: {card.skipped_reason}", file=sys.stderr)
            else:
                if target.exists():
                    shutil.rmtree(target)
                target.mkdir(parents=True)
                shutil.copy2(card.viewer, target / "index.html")
                if (card.folder / "renders").exists():
                    shutil.copytree(card.folder / "renders", target / "renders")
                used += size
                card.copied = True
                link_href = f"{slug}/index.html"
                if card.thumbnail is not None:
                    thumb_href = f"{slug}/renders/{card.thumbnail.name}"
        elif card.viewer is not None:
            link_href = _relative_href(out_dir, card.viewer)
            if card.thumbnail is not None:
                thumb_href = _relative_href(out_dir, card.thumbnail)
        name = html.escape(card.name)
        link = f'<a href="{html.escape(link_href)}">{name}</a>' if link_href else name
        image = (f'<a href="{html.escape(link_href)}"><img src="{html.escape(thumb_href)}" alt="{name} iso render"></a>'
                 if thumb_href and link_href else
                 (f'<img src="{html.escape(thumb_href)}" alt="{name} iso render">' if thumb_href else '<div class="none">no render</div>'))
        note = f'<p class="note">{html.escape(card.skipped_reason)}</p>' if card.skipped_reason else ""
        rendered.append(_CARD.format(image=image, link=link, engine=html.escape(card.engine),
                                     description=html.escape(card.description or ""), facts=_fmt_headline(card), note=note))
    page = out_dir / "index.html"
    page.write_text(_PAGE.format(title=html.escape(title), count=len(cards),
                                 built=datetime.now().strftime("%Y-%m-%d %H:%M"), cards="\n".join(rendered)))
    return page


def _relative_href(out_dir: Path, target: Path) -> str:
    import os
    return os.path.relpath(target.resolve(), out_dir.resolve()).replace(os.sep, "/")


def check(out_dir: Path) -> List[str]:
    """Problems with a built gallery: unresolved links or thumbnails, absolute references."""
    out_dir = Path(out_dir)
    page = out_dir / "index.html"
    problems: List[str] = []
    if not page.exists():
        return [f"no index.html in {out_dir}"]
    text = page.read_text()
    refs = re.findall(r'(?:href|src)="([^"]+)"', text)
    if not refs:
        problems.append("the page references nothing")
    for ref in refs:
        if ref.startswith(("http://", "https://", "#", "data:")):
            continue
        if ref.startswith("/"):
            problems.append(f"absolute reference: {ref}")
            continue
        if not (out_dir / ref).exists():
            problems.append(f"missing: {ref}")
    for viewer in out_dir.glob("*/index.html"):
        body = viewer.read_text()
        for src in re.findall(r'<img[^>]+src="([^"]+)"', body):
            if src.startswith(("http", "data:")):
                continue
            if src.startswith("/"):
                problems.append(f"{viewer.parent.name}: absolute image reference: {src}")
            elif not (viewer.parent / src).exists():
                problems.append(f"{viewer.parent.name}: missing image: {src}")
    return problems
