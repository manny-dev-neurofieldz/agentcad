"""Two sliced files side by side: what changed between one slice of a part and another.

Each file is read once (``agentcad.gcode.sliced``) and described by the numbers ``gcode summary`` already
reports, plus the contact bands of the support finder and the time the file states. The record (schema
``agentcad.gcode.compare/1``) holds the description of A, of B, their difference as B minus A, and the settings
that differ. Every difference is computed from the values the record shows, rounded to the precision they have,
so a reader who subtracts the two columns gets the third.

Nothing is dropped quietly. An object in only one file is a row of its own. Contact bands under ``min_area`` are
counted apart. A file without feature comments reports its support figures as unknown rather than zero.
Settings that hold credentials or local paths are never compared and never shown.

The record::

    schema    "agentcad.gcode.compare/1"
    a, b      file (as given), format ("gcode" or "bgcode"), features_known,
              estimated_time {seconds, text} | null, layers, top_z,
              filament {used_mm, stated_mm, stated_g, agrees}, support {share, filament_mm},
              contacts {count, area_mm2, min_area_mm2, smaller {count, area_mm2}, contact_distance_mm},
              objects {name: {filament_mm, support_share}}
    delta     B minus A: estimated_time {seconds, text} | null, layers, top_z, filament {used_mm, stated_mm,
              stated_g}, support {share, filament_mm}, contacts {count, area_mm2},
              objects [{name, present: "both" | "a_only" | "b_only", filament_mm}]
    settings  compared, same, in_a, in_b, differ [{key, a, b}], only_in_a [...], only_in_b [...], withheld

A value that is unknown (a time the file does not state, support in a file without feature comments) is null, and
so is every difference that needs it.
"""

from typing import Dict, List, Optional

from agentcad.gcode import check, supports
from agentcad.gcode.model import SUPPORT_FEATURES
from agentcad.gcode.sliced import (FILAMENT_KEY, MASS_KEY, Sliced, format_duration, is_setting_key, stated_total,
                                   summary_record)

SCHEMA = "agentcad.gcode.compare/1"
NO_OBJECT = "(no object)"                     # the name the summary gives extrusion that belongs to no object
DEFAULT_MIN_AREA = 1.0                        # mm2: the size below which `gcode supports` hides a band
SETTINGS_SHOWN = 20                           # settings the text lists before counting the rest
VALUE_WIDTH = 36                              # characters of a setting's value the text shows
WITHHELD = "credentials and local paths are never compared or shown"
#: A file's own filament total and the total it states agree when they differ by at most the larger of AGREE_MM
#: and AGREE_SHARE of the stated total.
AGREE_MM, AGREE_SHARE = 0.5, 0.001


def is_private(key: str) -> bool:
    """Whether a setting holds a credential or a local path: ``check.PRIVATE_KEYS`` and the rest of the
    print-host family (an address, a port, a certificate), which a comparison of two slices has no use for."""
    return key in check.PRIVATE_KEYS or key.startswith("printhost_") or key == "print_host"


def visible_settings(config: Dict[str, str]) -> Dict[str, str]:
    """The slicer settings of a configuration that a comparison may show: statistics and private keys left out."""
    return {k: v for k, v in config.items() if is_setting_key(k) and not is_private(k)}


# --- one file -----------------------------------------------------------------------------------------------

def describe(s: Sliced, min_area: float = DEFAULT_MIN_AREA) -> Dict:
    """One file's side of the comparison."""
    rec = summary_record(s)
    known = rec["features_known"]
    used = rec["filament_used"]
    stated_mm = stated_total(s.stated, FILAMENT_KEY)
    distance = supports.contact_distance_from(s.config)
    if known:
        bands = supports.find_contacts(s.model, contact_distance=distance)
        kept = [b for b in bands if b.area_mm2 >= min_area]
        rest = [b for b in bands if b.area_mm2 < min_area]
        contacts: Dict = {"count": len(kept), "area_mm2": round(sum(b.area_mm2 for b in kept), 1),
                          "min_area_mm2": min_area,
                          "smaller": {"count": len(rest), "area_mm2": round(sum(b.area_mm2 for b in rest), 1)}}
        support: Dict = {"share": rec["support"]["share"],
                         "filament_mm": round(sum(p.filament for p in s.model.paths if p.feature in SUPPORT_FEATURES), 2)}
    else:                                          # no feature comments: nothing to say about supports
        contacts = {"count": None, "area_mm2": None, "min_area_mm2": min_area, "smaller": None}
        support = {"share": None, "filament_mm": None}
    contacts["contact_distance_mm"] = distance
    return {
        "file": str(s.path),
        "format": s.kind,
        "features_known": known,
        "estimated_time": rec["estimated_time"],
        "layers": rec["layers"],
        "top_z": rec["top_z"],
        "filament": {
            "used_mm": used["filament_mm"],
            "stated_mm": stated_mm,
            "stated_g": stated_total(s.stated, MASS_KEY),
            "agrees": (None if stated_mm is None
                       else abs(used["filament_mm"] - stated_mm) <= max(AGREE_MM, AGREE_SHARE * stated_mm)),
        },
        "support": support,
        "contacts": contacts,
        "objects": {name: {"filament_mm": o["filament_mm"], "support_share": o["support_share"] if known else None}
                    for name, o in rec["by_object"].items()},
    }


# --- the difference -----------------------------------------------------------------------------------------

def _d(a: Optional[float], b: Optional[float], digits: int) -> Optional[float]:
    """B minus A to the precision of the two values; None when either is unknown."""
    return None if a is None or b is None else round(b - a, digits)


def _seconds(side: Dict) -> Optional[int]:
    t = side["estimated_time"]
    return t["seconds"] if t else None


def delta(a: Dict, b: Dict) -> Dict:
    """B minus A, field by field, from two ``describe`` records."""
    secs = _d(_seconds(a), _seconds(b), 0)
    rows = []
    for name in sorted(set(a["objects"]) | set(b["objects"]), key=lambda n: (n == NO_OBJECT, n)):
        in_a, in_b = name in a["objects"], name in b["objects"]
        # an object a file does not have takes no filament there
        before = a["objects"][name]["filament_mm"] if in_a else 0.0
        after = b["objects"][name]["filament_mm"] if in_b else 0.0
        rows.append({"name": name, "present": "both" if in_a and in_b else ("a_only" if in_a else "b_only"),
                     "filament_mm": round(after - before, 2)})
    return {
        "estimated_time": None if secs is None else {"seconds": int(secs), "text": format_duration(int(secs), True)},
        "layers": b["layers"] - a["layers"],
        "top_z": _d(a["top_z"], b["top_z"], 3),
        "filament": {
            "used_mm": _d(a["filament"]["used_mm"], b["filament"]["used_mm"], 2),
            "stated_mm": _d(a["filament"]["stated_mm"], b["filament"]["stated_mm"], 2),
            "stated_g": _d(a["filament"]["stated_g"], b["filament"]["stated_g"], 2),
        },
        "support": {"share": _d(a["support"]["share"], b["support"]["share"], 4),
                    "filament_mm": _d(a["support"]["filament_mm"], b["support"]["filament_mm"], 2)},
        "contacts": {"count": _d(a["contacts"]["count"], b["contacts"]["count"], 0),
                     "area_mm2": _d(a["contacts"]["area_mm2"], b["contacts"]["area_mm2"], 1)},
        "objects": rows,
    }


def settings_diff(a_config: Dict[str, str], b_config: Dict[str, str]) -> Dict:
    """The settings that differ between two embedded configurations: values that differ, and keys in one only."""
    a, b = visible_settings(a_config), visible_settings(b_config)
    keys = sorted(set(a) | set(b))
    differ = [{"key": k, "a": a[k], "b": b[k]} for k in keys if k in a and k in b and a[k] != b[k]]
    only_a = [{"key": k, "a": a[k], "b": None} for k in keys if k in a and k not in b]
    only_b = [{"key": k, "a": None, "b": b[k]} for k in keys if k in b and k not in a]
    return {"compared": len(keys), "same": len(keys) - len(differ) - len(only_a) - len(only_b),
            "in_a": len(a), "in_b": len(b), "differ": differ, "only_in_a": only_a, "only_in_b": only_b,
            "withheld": WITHHELD}


def compare(a: Sliced, b: Sliced, min_area: float = DEFAULT_MIN_AREA) -> Dict:
    """The comparison record of two sliced files (schema agentcad.gcode.compare/1)."""
    da, db = describe(a, min_area), describe(b, min_area)
    return {"schema": SCHEMA, "a": da, "b": db, "delta": delta(da, db), "settings": settings_diff(a.config, b.config)}


# --- text ---------------------------------------------------------------------------------------------------

def _num(x: Optional[float], digits: int = 2, signed: bool = False) -> str:
    """A number to ``digits`` decimals; '-' when there is none; a plus on a positive one if asked."""
    if x is None:
        return "-"
    s = f"{x:.{digits}f}"
    if float(s) == 0:
        s = s.lstrip("-")
    return "+" + s if signed and float(s) > 0 else s


def _trim(x: Optional[float], digits: int = 3, signed: bool = False) -> str:
    """A number with the zeros after its last digit dropped ('30.4'), for values that carry no fixed precision."""
    text = _num(x, digits, signed)
    return text.rstrip("0").rstrip(".") if "." in text else text


def _percent(share: Optional[float], signed: bool = False) -> str:
    """A share as a percentage to two decimals (shares are kept to four, so the columns subtract exactly); a
    difference of shares in percentage points ('pp')."""
    if share is None:
        return "-"
    return f"{_num(share * 100, 2, True)} pp" if signed else f"{_num(share * 100, 2)}%"


def _clip(value: Optional[str], width: int = VALUE_WIDTH) -> str:
    value = "" if value is None else value
    return value if len(value) <= width else value[:width - 3] + "..."


def _table(title: str, rows: List[tuple]) -> List[str]:
    """Rows of (label, A, B, B - A[, note]) aligned in columns under a header row whose first cell is ``title``."""
    heads = ("A", "B", "B - A")
    w0 = max([len(title)] + [len(r[0]) for r in rows])
    widths = [max([len(h)] + [len(r[i + 1]) for r in rows]) for i, h in enumerate(heads)]
    out = ["  ".join([title.ljust(w0)] + [h.rjust(w) for h, w in zip(heads, widths)]).rstrip()]
    for r in rows:
        line = "  ".join([r[0].ljust(w0)] + [c.rjust(w) for c, w in zip(r[1:4], widths)])
        out.append((line + "  " + r[4] if len(r) > 4 and r[4] else line).rstrip())
    return out


def _time_cell(side: Dict) -> str:
    t = side["estimated_time"]
    return "-" if not t else t["text"]


def render_text(rec: Dict, all_settings: bool = False) -> List[str]:
    """The comparison as text: a table of A, B and B - A, the notes it needs, and the settings that differ."""
    a, b, d, st = rec["a"], rec["b"], rec["delta"], rec["settings"]
    af, bf, df = a["filament"], b["filament"], d["filament"]
    rows: List[tuple] = [
        ("estimated time", _time_cell(a), _time_cell(b), d["estimated_time"]["text"] if d["estimated_time"] else "-"),
        ("filament used (mm)", _num(af["used_mm"]), _num(bf["used_mm"]), _num(df["used_mm"], signed=True)),
        ("  stated by the file", _num(af["stated_mm"]), _num(bf["stated_mm"]), _num(df["stated_mm"], signed=True)),
    ]
    if af["stated_g"] is not None or bf["stated_g"] is not None:
        rows.append(("filament used (g), stated", _num(af["stated_g"]), _num(bf["stated_g"]),
                     _num(df["stated_g"], signed=True)))
    ac, bc, dc = a["contacts"], b["contacts"], d["contacts"]
    rows += [
        ("layers", str(a["layers"]), str(b["layers"]), _num(d["layers"], 0, True)),
        ("top height (mm)", _trim(a["top_z"]), _trim(b["top_z"]), _trim(d["top_z"], signed=True)),
        ("support share", _percent(a["support"]["share"]), _percent(b["support"]["share"]),
         _percent(d["support"]["share"], True)),
        ("support (mm)", _num(a["support"]["filament_mm"]), _num(b["support"]["filament_mm"]),
         _num(d["support"]["filament_mm"], signed=True)),
        (f"contact bands (>= {_trim(ac['min_area_mm2'], 2)} mm2)", _num(ac["count"], 0), _num(bc["count"], 0),
         _num(dc["count"], 0, True)),
        ("contact area (mm2)", _num(ac["area_mm2"], 1), _num(bc["area_mm2"], 1), _num(dc["area_mm2"], 1, True)),
    ]
    object_rows = [("  " + row["name"],
                    _num(a["objects"][row["name"]]["filament_mm"]) if row["name"] in a["objects"] else "-",
                    _num(b["objects"][row["name"]]["filament_mm"]) if row["name"] in b["objects"] else "-",
                    _num(row["filament_mm"], signed=True),
                    {"both": "", "a_only": "only in A", "b_only": "only in B"}[row["present"]])
                   for row in d["objects"]]
    lines = [f"A: {a['file']} ({a['format']})", f"B: {b['file']} ({b['format']})", ""] + _table("", rows)
    if object_rows:
        lines += [""] + _table("objects (filament, mm)", object_rows)

    notes = []
    for label, side in (("A", a), ("B", b)):
        if not side["features_known"]:
            notes.append(f"{label} carries no feature comments, so its support figures are unknown")
        if not side["estimated_time"]:
            notes.append(f"{label} states no estimated printing time")
        elif side["estimated_time"]["seconds"] is None:
            notes.append(f"{label} states a time this reader does not know ({side['estimated_time']['text']!r})")
        f = side["filament"]
        if f["agrees"] is False:
            notes.append(f"{label}'s own filament total ({_num(f['used_mm'])} mm) and the total the file states "
                         f"({_num(f['stated_mm'])} mm) disagree; find out which is wrong before trusting a number here")
    small = [(label, side["contacts"]["smaller"]) for label, side in (("A", a), ("B", b))
             if side["contacts"]["smaller"] and side["contacts"]["smaller"]["count"]]
    if small:
        notes.append("contact bands under " + _trim(a["contacts"]["min_area_mm2"], 2) + " mm2 are not counted above: "
                     + ", ".join(f"{s['count']} in {label} ({_num(s['area_mm2'], 1)} mm2)" for label, s in small)
                     + " (--min-area 0 counts them)")
    if notes:
        lines += [""] + [f"note: {n}" for n in notes]
    return lines + [""] + _settings_lines(st, all_settings)


def _settings_lines(st: Dict, all_settings: bool) -> List[str]:
    n_diff = len(st["differ"]) + len(st["only_in_a"]) + len(st["only_in_b"])
    if not st["in_a"] or not st["in_b"]:               # nothing on one side: a list of "only in" would say nothing
        bare = [label for label, n in (("A", st["in_a"]), ("B", st["in_b"])) if not n]
        return [f"settings: {' and '.join(bare)} {'carries' if len(bare) == 1 else 'carry'} no slicer configuration, "
                f"so there is nothing to compare ({st['in_a']} settings in A, {st['in_b']} in B)"]
    if not n_diff:
        return [f"settings: none differ ({st['compared']} compared; {st['withheld']})"]
    out = [f"settings that differ: {n_diff} of {st['compared']} compared ({st['withheld']})"]
    groups = (("", st["differ"], lambda r: f"{_clip(r['a'])} -> {_clip(r['b'])}"),
              ("only in A:", st["only_in_a"], lambda r: _clip(r["a"])),
              ("only in B:", st["only_in_b"], lambda r: _clip(r["b"])))
    budget = n_diff if all_settings else SETTINGS_SHOWN
    width = max(len(r["key"]) for _, rows, _ in groups for r in rows)
    shown = 0
    for title, rows, show in groups:
        take = rows[:max(0, budget - shown)]
        if take and title:
            out.append(title)
        out += [f"  {r['key'].ljust(width)}  {show(r)}" for r in take]
        shown += len(take)
    if shown < n_diff:
        out.append(f"... and {n_diff - shown} more (--all-settings lists every one; --json carries them all)")
    return out
