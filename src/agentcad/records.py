"""Records: the structured fields of part and job records, read and checked.

A library is a folder of record files: a ``part.toml`` in each part's folder, a ``job.toml`` in each
print job's folder, the print manifests agentcad writes into a project's ``exports/`` folder, and
optionally a ``catalog.toml`` at the top that lists parts which have no folder yet. Most of a record
is prose for people. A few fields are structured, so that tools can rely on them:

* a part's ``[identity] slug``, ``[status] state`` and the slugs under ``[relations]``;
* a part's fit records, ``[fit.<mate>]``: when the fit was measured (``recorded``), the other part
  (``counterpart``), the verdict, and optionally a snapshot of each source it measured;
* a job's ``[job] date`` (the day it was staged) and ``planned`` (the day it should print), each
  ``[[item]]``'s ``part`` and ``quantity``, and the ``[outcome]``'s ``date_printed`` and ``verdict``.

This module reads those fields into one model and checks them: types, enumerations, dates, and the
references between records (a job's part, a fit's counterpart, a fit recorded on both sides). It
never edits a record. What the fields are for (owed work: a fit to re-run after its sources changed,
a print past its planned date, a verdict to record) is derived from the model, not stored in it.
"""

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

#: A part's ``[status] state``.
PART_STATES = ("draft", "print-tested", "validated", "superseded")
#: A fit's verdict, in the words ``agentcad fit`` writes.
FIT_VERDICTS = ("pass", "fail", "unmeasured", "measured")
#: A job's (or an item's) verdict. ``pending``: printed, not judged yet; ``cancelled``: never printed.
JOB_VERDICTS = ("success", "partial", "failed", "pending", "cancelled")
#: The verdicts that say a print happened.
PRINTED_VERDICTS = ("success", "partial", "failed", "pending")
#: The record files a library holds.
PART_FILE, JOB_FILE, CATALOG_FILE = "part.toml", "job.toml", "catalog.toml"
SCHEMA = "agentcad.records/1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")

When = Union[date, datetime]


def _toml(path: Path) -> Dict[str, Any]:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore
    with open(path, "rb") as f:
        return tomllib.load(f)


def parse_when(value: Any) -> Optional[When]:
    """A date or a date and time from a TOML value: a native TOML date or date-time, or a string in
    ISO form (``2026-09-16``, ``2026-09-16T23:28``, ``2026-09-16 23:28``). None when it is not one."""
    if isinstance(value, (date, datetime)):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        return date.fromisoformat(text) if len(text) == 10 else datetime.fromisoformat(text)
    except ValueError:
        return None


def day_of(when: Optional[When]) -> Optional[date]:
    return when.date() if isinstance(when, datetime) else when


@dataclass
class Problem:
    severity: str              # error | warning
    path: str                  # the record file, relative to the checked folder
    key: str                   # where in the file, e.g. "[outcome] verdict"
    message: str

    def line(self) -> str:
        return f"{self.path} {self.key}: {self.message}"


@dataclass
class Fit:
    part: str                  # the part whose record holds it
    counterpart: str           # the other part
    name: str                  # the mate's name (the table name in a part record)
    recorded: Optional[str]    # ISO date or date and time
    verdict: str
    snapshots: List[Dict[str, Any]]
    path: str                  # the record file
    origin: str                # "part" (a part.toml table) or "manifest" (written by agentcad fit)


@dataclass
class Item:
    part: str
    quantity: Optional[int]
    verdict: Optional[str]


@dataclass
class Job:
    slug: str                  # the job folder's name
    path: str
    staged: Optional[str]      # [job] date
    planned: Optional[str]
    printed: Optional[str]     # [outcome] date_printed
    verdict: Optional[str]
    items: List[Item]


@dataclass
class Part:
    slug: str
    path: str
    state: Optional[str]
    mates_with: List[str]
    supersedes: List[str]
    superseded_by: str
    fits: List[str]            # the names of its fit records


@dataclass
class Records:
    root: str
    parts: List[Part] = field(default_factory=list)
    jobs: List[Job] = field(default_factory=list)
    fits: List[Fit] = field(default_factory=list)
    catalog: List[str] = field(default_factory=list)        # slugs a catalog lists without a part record
    problems: List[Problem] = field(default_factory=list)
    alone: bool = False        # one record file read alone: references to other records are not checked

    def errors(self) -> List[Problem]:
        return [p for p in self.problems if p.severity == "error"]

    def warnings(self) -> List[Problem]:
        return [p for p in self.problems if p.severity == "warning"]

    def to_dict(self) -> Dict[str, Any]:
        return {"schema": SCHEMA, "root": self.root,
                "counts": {"parts": len(self.parts), "jobs": len(self.jobs), "fits": len(self.fits),
                           "catalog_only": len(self.catalog), "errors": len(self.errors()),
                           "warnings": len(self.warnings())},
                "parts": [asdict(p) for p in self.parts], "jobs": [asdict(j) for j in self.jobs],
                "fits": [asdict(f) for f in self.fits], "catalog_only": list(self.catalog),
                "references_checked": not self.alone, "problems": [asdict(p) for p in self.problems]}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def _iso(when: Optional[When]) -> Optional[str]:
    return when.isoformat() if when is not None else None


def _skipped(path: Path, root: Path) -> bool:
    """Folders whose names begin with ``_`` or ``.`` hold templates, tools and caches, not records."""
    return any(part.startswith(("_", ".")) for part in path.relative_to(root).parts[:-1])


def _files(root: Path, name: str) -> List[Path]:
    return sorted(p for p in root.rglob(name) if p.is_file() and not _skipped(p, root))


class _Reader:
    def __init__(self, root: Path):
        self.root = root
        self.out = Records(root=str(root))
        self.known: Dict[str, Path] = {}         # part slug -> its record file

    def rel(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            try:
                return str(Path(path).resolve().relative_to(self.root.resolve()))
            except ValueError:
                return str(path)

    def problem(self, severity: str, path: Path, key: str, message: str) -> None:
        self.out.problems.append(Problem(severity, self.rel(path), key, message))

    def load(self, path: Path) -> Optional[Dict[str, Any]]:
        try:
            return _toml(path)
        except Exception as e:  # a record that is not TOML says why; the others are still read
            self.problem("error", path, "(file)", f"not readable as TOML: {e}")
            return None

    # --- parts --------------------------------------------------------------------------------

    def read_part(self, path: Path, data: Dict[str, Any]) -> None:
        identity = data.get("identity") or {}
        slug = identity.get("slug")
        if not isinstance(slug, str) or not slug.strip():
            self.problem("error", path, "[identity] slug", "a part record names its slug")
            slug = path.parent.name
        elif slug != path.parent.name:
            self.problem("warning", path, "[identity] slug",
                         f"{slug!r} differs from the folder name {path.parent.name!r}")
        if slug in self.known:
            self.problem("error", path, "[identity] slug",
                         f"{slug!r} is also the slug of {self.rel(self.known[slug])}")
            return
        self.known[slug] = path
        status = data.get("status") or {}
        state = status.get("state")
        if state is not None and state not in PART_STATES:
            self.problem("error", path, "[status] state", f"{state!r} is not one of {', '.join(PART_STATES)}")
        relations = data.get("relations") or {}
        lists = {}
        for key in ("mates_with", "supersedes"):
            value = relations.get(key, [])
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                self.problem("error", path, f"[relations] {key}", "is a list of part slugs")
                value = []
            lists[key] = value
        superseded_by = relations.get("superseded_by", "")
        if not isinstance(superseded_by, str):
            self.problem("error", path, "[relations] superseded_by", "is a part slug, or empty")
            superseded_by = ""
        fits = data.get("fit") or {}
        if not isinstance(fits, dict):
            self.problem("error", path, "[fit]", "fit records are tables, [fit.<mate>]")
            fits = {}
        self.out.parts.append(Part(slug, self.rel(path), state if isinstance(state, str) else None,
                                   lists["mates_with"], lists["supersedes"], superseded_by, sorted(fits)))
        for name, table in sorted(fits.items()):
            self.read_part_fit(path, slug, name, table)

    def read_part_fit(self, path: Path, slug: str, name: str, table: Any) -> None:
        key = f"[fit.{name}]"
        if not isinstance(table, dict):
            self.problem("error", path, key, "a fit record is a table")
            return
        recorded = parse_when(table.get("recorded"))
        if "recorded" not in table:
            self.problem("error", path, f"{key} recorded", "a fit record says when it was measured "
                                                            "(recorded = YYYY-MM-DDTHH:MM)")
        elif recorded is None:
            self.problem("error", path, f"{key} recorded", f"{table['recorded']!r} is not a date or a date and time")
        counterpart = table.get("counterpart")
        if not isinstance(counterpart, str) or not counterpart.strip():
            self.problem("error", path, f"{key} counterpart", "a fit record names the other part's slug")
            counterpart = ""
        elif counterpart == slug:
            self.problem("error", path, f"{key} counterpart", "a part does not fit itself")
        verdict = table.get("verdict")
        if verdict not in FIT_VERDICTS:
            self.problem("error", path, f"{key} verdict",
                         ("missing" if verdict is None else f"{_short(verdict)!r} is not")
                         + f" one of {', '.join(FIT_VERDICTS)}; a sentence about the fit belongs in verdict_note")
            verdict = verdict if isinstance(verdict, str) else ""
        snapshots = self.snapshots(path, f"{key} snapshots", table.get("snapshots", []), path.parent)
        self.out.fits.append(Fit(slug, counterpart, name, _iso(recorded), verdict, snapshots,
                                 self.rel(path), "part"))

    def snapshots(self, path: Path, key: str, value: Any, base: Path) -> List[Dict[str, Any]]:
        if not isinstance(value, list):
            self.problem("error", path, key, "is a list of {path, sha256} tables")
            return []
        out = []
        for i, snap in enumerate(value):
            if not isinstance(snap, dict) or not isinstance(snap.get("path"), str):
                self.problem("error", path, f"{key}[{i}]", "names the measured file: {path = ..., sha256 = ...}")
                continue
            digest = snap.get("sha256")
            target = (base / snap["path"]).resolve()
            if not isinstance(digest, str) or not _SHA256.match(digest):
                self.problem("error", path, f"{key}[{i}] sha256",
                             "is the file's SHA-256 as 64 lower-case hex digits")
            elif not target.is_file():
                self.problem("warning", path, f"{key}[{i}] path",
                             f"{snap['path']} is not there: the source the fit measured has moved or gone")
            # the same file named from the checked folder, whatever folder the record names it from
            out.append(dict(snap, file=self.rel(target)))
        return out

    # --- manifests (fit records agentcad wrote) -----------------------------------------------------

    def read_manifest(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError) as e:
            self.problem("error", path, "(file)", f"not readable as JSON: {e}")
            return
        own = data.get("project_name") or path.parent.parent.name
        for i, rec in enumerate(data.get("fit") or []):
            key = f"fit[{i}]"
            if not isinstance(rec, dict):
                self.problem("error", path, key, "a fit record is an object")
                continue
            recorded = parse_when(rec.get("recorded"))
            if recorded is None:
                self.problem("error", path, f"{key} recorded", "missing, or not a date and time")
            verdict = rec.get("verdict")
            if verdict not in FIT_VERDICTS:
                self.problem("error", path, f"{key} verdict", f"{_short(verdict)!r} is not one of {', '.join(FIT_VERDICTS)}")
            listed = [{"path": snap["source"], "sha256": snap.get("sha256"),
                       **({"params": snap["params"]} if "params" in snap else {})}
                      for snap in (rec.get(side) for side in ("a_snapshot", "b_snapshot"))
                      if isinstance(snap, dict) and snap.get("source")]
            snaps = self.snapshots(path, f"{key} snapshots", listed, path.parent.parent)
            counterpart = _other_side(rec, path.parent.parent)
            self.out.fits.append(Fit(own, counterpart, str(rec.get("mate") or ""), _iso(recorded),
                                     verdict if isinstance(verdict, str) else "", snaps, self.rel(path), "manifest"))

    # --- jobs ---------------------------------------------------------------------------------

    def read_job(self, path: Path, data: Dict[str, Any]) -> None:
        job = data.get("job") or {}
        staged = parse_when(job.get("date"))
        if "date" not in job:
            self.problem("error", path, "[job] date", "a job record says the day it was staged (date = YYYY-MM-DD)")
        elif staged is None:
            self.problem("error", path, "[job] date", f"{job['date']!r} is not a date")
        planned = None
        if job.get("planned") not in (None, ""):
            planned = parse_when(job["planned"])
            if planned is None:
                self.problem("error", path, "[job] planned", f"{job['planned']!r} is not a date")
        outcome = data.get("outcome") or {}
        printed = None
        if outcome.get("date_printed") not in (None, ""):
            printed = parse_when(outcome["date_printed"])
            if printed is None:
                self.problem("error", path, "[outcome] date_printed", f"{outcome['date_printed']!r} is not a date")
        verdict = self.verdict(path, "[outcome] verdict", outcome.get("verdict"), printed)
        if printed is not None and staged is not None and day_of(printed) < day_of(staged):
            self.problem("warning", path, "[outcome] date_printed",
                         f"{_iso(printed)} is before the day the job was staged ({_iso(staged)})")
        items = data.get("item") or []
        if not isinstance(items, list) or not items:
            self.problem("error", path, "[[item]]", "a job record lists what it prints, one [[item]] per part")
            items = []
        parsed = []
        for i, item in enumerate(items):
            key = f"[[item]] {i + 1}"
            if not isinstance(item, dict):
                self.problem("error", path, key, "an item is a table")
                continue
            part = item.get("part")
            if not isinstance(part, str) or not part.strip():
                self.problem("error", path, f"{key} part", "an item names the part it prints, by slug")
                part = ""
            quantity = item.get("quantity")
            if quantity is not None and (not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1):
                self.problem("error", path, f"{key} quantity", f"{quantity!r} is not a whole number of at least 1")
                quantity = None
            stl = item.get("stl")
            if isinstance(stl, str) and stl and not (path.parent / stl).is_file():
                self.problem("warning", path, f"{key} stl", f"{stl} is not in the job folder")
            parsed.append(Item(part, quantity, self.verdict(path, f"{key} verdict", item.get("verdict"), printed)))
        self.out.jobs.append(Job(path.parent.name, self.rel(path), _iso(staged), _iso(planned), _iso(printed),
                                 verdict, parsed))

    def verdict(self, path: Path, key: str, value: Any, printed: Optional[When]) -> Optional[str]:
        if value is None:
            return None
        if value not in JOB_VERDICTS:
            self.problem("error", path, key, f"{_short(value)!r} is not one of {', '.join(JOB_VERDICTS)}; "
                                             "a sentence about the print belongs in result")
            return None
        if value in PRINTED_VERDICTS and printed is None:
            self.problem("error", path, key, f"{value!r} says the job printed, but [outcome] date_printed is empty")
        if value == "cancelled" and printed is not None:
            self.problem("error", path, key, "'cancelled' says the job never printed, but it has a date_printed")
        return value

    # --- references between records -------------------------------------------------------------

    def cross_check(self) -> None:
        known = set(self.known) | set(self.out.catalog)
        for part in self.out.parts:
            path = self.root / part.path
            for key, slugs in (("mates_with", part.mates_with), ("supersedes", part.supersedes),
                               ("superseded_by", [part.superseded_by] if part.superseded_by else [])):
                for slug in slugs:
                    if slug not in known:
                        self.problem("warning", path, f"[relations] {key}", f"{slug!r} is not a part this library knows")
        by_part: Dict[str, List[Fit]] = {}
        for fit in self.out.fits:
            by_part.setdefault(fit.part, []).append(fit)
        for fit in self.out.fits:
            if fit.origin != "part" or not fit.counterpart:
                continue
            path = self.root / fit.path
            if fit.counterpart not in known:
                self.problem("warning", path, f"[fit.{fit.name}] counterpart",
                             f"{fit.counterpart!r} is not a part this library knows")
            elif fit.counterpart in self.known and not any(f.counterpart == fit.part for f in by_part.get(fit.counterpart, [])):
                self.problem("warning", path, f"[fit.{fit.name}]",
                             f"recorded on this side only: {self.rel(self.known[fit.counterpart])} has no fit "
                             f"record with counterpart {fit.part!r}")
        for job in self.out.jobs:
            path = self.root / job.path
            for i, item in enumerate(job.items):
                if item.part and item.part not in known:
                    self.problem("warning", path, f"[[item]] {i + 1} part",
                                 f"{item.part!r} is not a part this library knows")


def _short(value: Any, limit: int = 60) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit - 3] + "..."
    return value


def _other_side(rec: Dict[str, Any], project: Path) -> str:
    """The part a manifest's fit record was measured against: the side whose source is not in this
    project, named by its project folder when it has one, else by the file's name."""
    from agentcad.fit import project_of
    for side in ("a", "b"):
        source = rec.get(side)
        if not source:
            continue
        p = Path(source)
        if not p.is_absolute():
            p = (project / p).resolve()
        if project.resolve() in p.parents:
            continue
        folder = project_of(p) if p.exists() else None
        return folder.name if folder else p.stem
    return ""


def load(where: Union[str, Path]) -> Records:
    """Every record under a folder (a library or a project), or one record file, read and checked."""
    where = Path(where)
    if not where.exists():
        raise FileNotFoundError(f"{where} does not exist")
    root = where if where.is_dir() else where.parent
    reader = _Reader(root)
    if where.is_dir():
        parts, jobs = _files(root, PART_FILE), _files(root, JOB_FILE)
        manifests = [p for p in sorted(root.rglob("*.print.json"))
                     if p.parent.name == "exports" and not _skipped(p, root)]
        catalog = root / CATALOG_FILE
    else:
        parts = [where] if where.name == PART_FILE else []
        jobs = [where] if where.name == JOB_FILE else []
        manifests = [where] if where.name.endswith(".print.json") else []
        catalog = None
        if not (parts or jobs or manifests):
            raise ValueError(f"{where.name} is not a record file ({PART_FILE}, {JOB_FILE} or a *.print.json manifest)")
    for path in parts:
        data = reader.load(path)
        if data is not None:
            reader.read_part(path, data)
    if catalog is not None and catalog.is_file():
        data = reader.load(catalog) or {}
        listed = [e.get("slug") for e in data.get("part") or [] if isinstance(e, dict)]
        reader.out.catalog = sorted({s for s in listed if isinstance(s, str) and s and s not in reader.known})
    for path in jobs:
        data = reader.load(path)
        if data is not None:
            reader.read_job(path, data)
    for path in manifests:
        reader.read_manifest(path)
    if where.is_dir():
        reader.cross_check()
    else:
        reader.out.alone = True
    return reader.out


def summary(records: Records) -> List[str]:
    """The check as lines of text: what was read, then each error and warning."""
    n = records.to_dict()["counts"]
    printed = [j for j in records.jobs if j.printed]
    lines = [f"Records under {records.root}: {n['parts']} part(s), {n['jobs']} job(s) "
             f"({len(printed)} printed, {sum(1 for j in printed if j.verdict in (None, 'pending'))} without a verdict), "
             f"{n['fits']} fit record(s)" + (f", {n['catalog_only']} part(s) listed only in the catalog" if n["catalog_only"] else "")]
    if records.alone:
        lines.append("One record read alone: references to other parts and fits are not checked (check its library for those).")
    for title, found in (("error", records.errors()), ("warning", records.warnings())):
        if found:
            lines.append(f"{len(found)} {title}(s):")
            lines.extend(f"  {p.line()}" for p in found)
    if not records.problems:
        lines.append("No problems: every structured field reads as its contract says.")
    return lines
