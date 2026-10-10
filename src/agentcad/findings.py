"""Findings: one judgment, in one shape, wherever agentcad judges something.

A finding names what was judged (``key``) and how it came out (``severity``:
error, warning or ok), what was found against what was intended, why it
matters, and where the intent was stated (``source``). It can also say which
rule judged it, which layer set the limit (a default, the project, a
feature's annotation), the feature and the source location it is about, how
uncertain the measurement is, and the usual fix. Severities stay three: a
rule that needs to say more says it in these fields, not in a new severity.

``message`` holds a sentence a rule composed itself (the tray's warnings);
without one, ``sentence()`` composes the settings check's sentence from the
other fields.
"""

from dataclasses import asdict, dataclass, fields
from typing import Any, Dict, Optional

SEVERITIES = ("error", "warning", "ok")

#: The settings check's usual fixes, by what went wrong.
FIX_MISSING = "check the slicer version writes this setting, or drop it from the intent."
FIX_DIFFERS = ("re-load the project file in the slicer and re-slice; a preset selected afterwards can "
               "override a project's settings.")


@dataclass
class Finding:
    key: str
    severity: str            # "error" | "warning" | "ok"
    found: Optional[str]
    intended: str
    why: str
    source: str
    #: The rule that judged it, e.g. "slice_setting" or "solid_count".
    rule: str = ""
    #: The layer that set the limit: "default", a project table, a feature annotation.
    layer: str = ""
    #: The feature the finding is about, when one is named.
    feature: str = ""
    #: Where in the source, as "file:line", when known.
    location: str = ""
    #: How far the measurement may be off, in the unit of ``found``.
    uncertainty: Optional[float] = None
    #: The usual fix.
    fix: str = ""
    #: A sentence the rule composed; ``sentence()`` returns it (with the fix) when set.
    message: str = ""

    def __post_init__(self):
        if self.severity not in SEVERITIES:
            raise ValueError(f"finding {self.key}: severity must be one of {', '.join(SEVERITIES)}, "
                             f"not {self.severity!r}")

    def sentence(self) -> str:
        if self.message:
            return self.message + (f" Fix: {self.fix}" if self.fix and self.severity != "ok" else "")
        why = f" Why: {self.why}." if self.why else ""
        if self.severity == "ok":
            return f"{self.key} = {self.found}, as {self.source} asks."
        if self.found is None:
            return (f"{self.key} is not in the file's configuration; {self.source} asks for {self.intended}.{why} "
                    f"Fix: {self.fix or FIX_MISSING}")
        return f"{self.key} is {self.found} in the file; {self.source} asks for {self.intended}.{why} " \
               f"Fix: {self.fix or FIX_DIFFERS}"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self) | {"sentence": self.sentence()}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Finding":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})
