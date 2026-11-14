"""Owed work declared as duties on a role of the MacEff framework (https://github.com/cversek/MacEff).

``agentcad duties`` derives what a library's records say is owed. A harness that keeps standing roles can hold
each owed item as a duty on the role that keeps the library, so the item is seen where that agent already looks
instead of only when someone runs the command. This module is the adapter for MacEff's roles: it reads the
role's duties and declares the ones that are missing, through MacEff's own command (``macf_tools role``), never
by writing its store.

A declared duty carries the owed item's stable key on the last line of its body (``agentcad-duty: KEY``); that
line is how a later run knows the duty is already there. So declaring twice changes nothing. Two cases are
reported for the duty's holder and never acted on: a duty still open whose key the records no longer give (no
longer owed), and a duty closed (done or deferred) whose key the records give again (owed again). This adapter
never closes, reopens, edits or removes a duty.

Every duty is declared without a date. A due date needs a horizon, and a horizon is the declarer's own
reasoning about lead time, which a generator cannot supply; a planned day stays in the duty's text.
"""
import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from agentcad.duties import Duty

KEY_PREFIX = "agentcad-duty: "
TOOL = "macf_tools"
#: A duty in one of these states is on its holder's open list (MacEff roles: pending, active, done, deferred).
OPEN = ("pending", "active")


class RoleError(Exception):
    pass


@dataclass
class Plan:
    role: str                        # the role's id, as the roles command resolved the name given
    declare: List[Duty]              # owed, and no duty on the role carries its key
    present: List[Dict[str, str]]    # owed, declared and open: {"key", "id", "state"}
    reopened: List[Dict[str, str]]   # owed, but its duty is closed (done or deferred): in nobody's open list
    lapsed: List[Dict[str, str]]     # declared, still open, no longer owed by the records


def body(duty: Duty) -> str:
    """What must be true, where it was read from, and the key line a later run matches."""
    lines = [duty.why.strip()] if duty.why.strip() else []
    lines += [f"Read from: {e}" for e in duty.evidence]
    return "\n".join(lines + [KEY_PREFIX + duty.key])


def key_of(text: str) -> Optional[str]:
    """The key a duty's body carries, or None for a duty this adapter did not declare."""
    for line in reversed((text or "").strip().split("\n")):
        if line.startswith(KEY_PREFIX):
            return line[len(KEY_PREFIX):].strip() or None
    return None


def _run(argv: Sequence[str], tool: str) -> subprocess.CompletedProcess:
    exe = shutil.which(tool)
    if exe is None:
        raise RoleError(f"no {tool} command on PATH: duties can be declared only where MacEff is installed")
    try:
        return subprocess.run([exe, *argv], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RoleError(f"{tool} {' '.join(argv[:3])} did not run: {e}") from e


def existing(role: str, tool: str = TOOL) -> Tuple[str, List[Dict[str, str]]]:
    """The role's id as the tool resolved ``role`` (a name or prefix may be given), and its duties that carry a
    key: {"key", "id", "state"} each. A role the tool does not know, or an answer that is not the JSON it
    documents, is an error and never an empty list: an empty list would declare every duty again."""
    done = _run(["role", "show", role, "--all", "--json"], tool)
    if done.returncode != 0:
        raise RoleError(f"{tool} role show {role} failed (exit {done.returncode}): {done.stderr.strip()[:300]}")
    try:
        shown = json.loads(done.stdout)
        role_id, duties = str(shown["id"]), shown["duties"]
        found = [{"key": key_of(d.get("body", "")), "id": str(d["id"]), "state": str(d.get("state", ""))}
                 for d in duties]
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise RoleError(f"{tool} role show {role} --json did not give a role with duties ({type(e).__name__}: {e})")
    return role_id, [f for f in found if f["key"]]


def plan(role: str, owed: Sequence[Duty], declared: Sequence[Dict[str, str]]) -> Plan:
    by_key: Dict[str, List[Dict[str, str]]] = {}
    for d in declared:
        by_key.setdefault(d["key"], []).append(d)
    owed_keys = {d.key for d in owed}
    present, reopened = [], []
    for d in owed:
        held = by_key.get(d.key, [])
        open_ = [h for h in held if h["state"] in OPEN]
        if open_:
            present += open_
        elif held:
            reopened += held
    return Plan(role=role, declare=[d for d in owed if d.key not in by_key], present=present, reopened=reopened,
                lapsed=[d for d in declared if d["key"] not in owed_keys and d["state"] in OPEN])


def declare(role: str, duty: Duty, tool: str = TOOL) -> None:
    done = _run(["role", "duty", "add", role, duty.title, "--body", body(duty)], tool)
    if done.returncode != 0:
        raise RoleError(f"{tool} role duty add failed for {duty.key} (exit {done.returncode}): "
                        f"{(done.stderr or done.stdout).strip()[:300]}")


def apply(p: Plan, tool: str = TOOL) -> int:
    """Declare every missing duty; the number declared. Stops at the first refusal, so a partial run is
    finished by running again."""
    for duty in p.declare:
        declare(p.role, duty, tool)
    return len(p.declare)


def summary(p: Plan, applied: bool) -> List[str]:
    lines = [f"Role {p.role}: {len(p.declare)} to declare, {len(p.present)} already declared, "
             f"{len(p.reopened)} closed and owed again, {len(p.lapsed)} declared earlier and no longer owed."]
    verb = "declared" if applied else "would declare"
    lines += [f"  {verb}: {d.title}  [{d.key}]" for d in p.declare]
    lines += [f"  present:  duty {d['id']} ({d['state']})  [{d['key']}]" for d in p.present]
    lines += [f"  owed again, but its duty is {d['state']}: duty {d['id']}  [{d['key']}]; its holder decides whether "
              f"to reactivate it" for d in p.reopened]
    lines += [f"  no longer owed by the records: duty {d['id']} ({d['state']})  [{d['key']}]; its holder closes it "
              f"with the evidence" for d in p.lapsed]
    if p.declare and not applied:
        lines.append("Nothing was changed. Add --apply to declare them.")
    return lines
