"""Duties: the work a library's records say is owed, derived from the records alone.

Three kinds, each read off the structured fields of the records (``agentcad.records``):

* ``record_verdict``: a job that printed (``[outcome] date_printed``) and has no verdict, or a pending one.
  A job whose items all carry verdicts is judged by their sum when it has none of its own.
* ``print_by_plan``: a job whose planned day (``[job] planned``) is before the day asked about, that has
  not printed and is not cancelled.
* ``refit``: a fit whose sources have changed since it was recorded: a snapshot's SHA-256 differs from
  the file's now, or the file is gone; or a fit that recorded no snapshots, which cannot say whether it
  still holds. A fit recorded on both parts (the same two parts, the same time) is one duty.

Each duty has a stable key (the same work owed again gives the same key, so a tool that files duties
somewhere can match what it filed before), a line saying what is owed, why, and the evidence: the record
files and keys it was read from. Nothing here edits a record or decides who owes the work.
"""

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agentcad.records import Records, day_of, parse_when, sum_verdicts

SCHEMA = "agentcad.duties/1"
KINDS = ("record_verdict", "print_by_plan", "refit")


@dataclass
class Duty:
    kind: str
    key: str                       # stable: the same owed work gives the same key
    title: str                     # what is owed, in one line
    why: str
    subject: Dict[str, Any]        # the job or the parts, and the dates and files that make it owed
    evidence: List[str] = field(default_factory=list)      # "record file  key" pointers

    def line(self) -> str:
        return f"[{self.kind}] {self.title}: {self.why}"


def _sha256(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _verdict_owed(records: Records) -> List[Duty]:
    out = []
    for job in records.jobs:
        if not job.printed:
            continue
        verdict = job.verdict or sum_verdicts([i.verdict for i in job.items])
        if verdict not in (None, "pending"):
            continue
        why = "its verdict is pending" if verdict == "pending" else "it has no verdict"
        pending = [i.part for i in job.items if i.verdict == "pending"]
        if pending:
            why += f" (pending: {', '.join(pending)})"
        out.append(Duty("record_verdict", f"record_verdict:job={job.slug}",
                        f"record the verdict of job {job.slug}, printed {job.printed}", why,
                        {"job": job.slug, "printed": job.printed},
                        [f"{job.path}  [outcome] date_printed", f"{job.path}  [outcome] verdict"]))
    return out


def _plan_owed(records: Records, as_of: date) -> List[Duty]:
    out = []
    for job in records.jobs:
        planned = day_of(parse_when(job.planned)) if job.planned else None
        if planned is None or planned >= as_of or job.printed:
            continue
        if (job.verdict or sum_verdicts([i.verdict for i in job.items])) == "cancelled":
            continue
        out.append(Duty("print_by_plan", f"print_by_plan:job={job.slug}",
                        f"print job {job.slug}, planned for {job.planned}",
                        f"its planned day has passed ({(as_of - planned).days} day(s) before {as_of.isoformat()}) "
                        "and it has not printed", {"job": job.slug, "planned": job.planned},
                        [f"{job.path}  [job] planned", f"{job.path}  [outcome] date_printed"]))
    return out


def _refit_owed(records: Records) -> List[Duty]:
    root = Path(records.root)
    groups: Dict[Tuple[Tuple[str, ...], Optional[str]], List[Any]] = {}
    for fit in records.fits:
        if not fit.counterpart:
            continue
        groups.setdefault((tuple(sorted((fit.part, fit.counterpart))), fit.recorded), []).append(fit)
    out = []
    for (parts, recorded), fits in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
        snaps: Dict[str, str] = {}
        for fit in fits:
            for snap in fit.snapshots:
                if snap.get("file") and snap.get("sha256"):
                    snaps.setdefault(snap["file"], snap["sha256"])
        evidence = [f"{f.path}  " + (f"[fit.{f.name}]" if f.origin == "part" else "fit record") for f in fits]
        subject = {"parts": list(parts), "recorded": recorded}
        key = f"refit:{'+'.join(parts)}@{recorded or 'unrecorded'}"
        title = f"re-run the fit of {parts[0]} and {parts[1]} (recorded {recorded or 'without a time'})"
        if not snaps:
            out.append(Duty("refit", key, title, "it recorded no snapshot of the sources it measured, so it cannot "
                            "say whether it still holds", dict(subject, changed=[]), evidence))
            continue
        changed = sorted(f for f, digest in snaps.items() if _sha256(root / f) != digest)
        if changed:
            gone = [f for f in changed if not (root / f).is_file()]
            why = "a source it measured has changed since: " + ", ".join(changed)
            if gone:
                why += f" ({', '.join(gone)} no longer there)"
            out.append(Duty("refit", key, title, why, dict(subject, changed=changed), evidence))
    return out


def derive(records: Records, as_of: Optional[date] = None) -> List[Duty]:
    """Every duty the records say is owed as of ``as_of`` (default today), in a stable order: by kind,
    then by what it is about."""
    as_of = as_of or date.today()
    return _verdict_owed(records) + _plan_owed(records, as_of) + _refit_owed(records)


def to_dict(duties: List[Duty], records: Records, as_of: date) -> Dict[str, Any]:
    return {"schema": SCHEMA, "root": records.root, "as_of": as_of.isoformat(),
            "record_errors": len(records.errors()), "duties": [asdict(d) for d in duties]}


def summary(duties: List[Duty], records: Records, as_of: date) -> List[str]:
    """The duties as lines of text, with what each was read from."""
    if not duties:
        return [f"Nothing owed under {records.root} as of {as_of.isoformat()} "
                f"({len(records.jobs)} job(s), {len(records.fits)} fit record(s) read)."]
    lines = [f"{len(duties)} duty(ies) owed under {records.root} as of {as_of.isoformat()}:"]
    for d in duties:
        lines.append(f"  {d.line()}")
        lines.extend(f"      from {e}" for e in d.evidence)
    return lines
