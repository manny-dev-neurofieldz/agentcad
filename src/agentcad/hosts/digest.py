"""HTTP Digest authentication (RFC 7616, with RFC 2617's ``qop=auth``), as pure functions.

Nothing here touches the network: a challenge is parsed from the ``WWW-Authenticate`` values a
response carried, and the ``Authorization`` value for the next request is computed from it. The
request itself is sent by a host's one network function.

Supported: ``MD5``, ``SHA-256`` and ``SHA-512-256`` and their ``-sess`` variants, ``qop=auth`` and
the older form with no ``qop``. A challenge that only offers ``auth-int`` or an unknown algorithm
is refused with a message naming what it offered.
"""

import hashlib
import re
import secrets
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

#: challenge algorithm (upper-case) -> (hashlib name, session variant)
ALGORITHMS = {
    "MD5": ("md5", False), "MD5-SESS": ("md5", True),
    "SHA-256": ("sha256", False), "SHA-256-SESS": ("sha256", True),
    "SHA-512-256": ("sha512_256", False), "SHA-512-256-SESS": ("sha512_256", True),
}
_RANK = {"SHA-512-256": 0, "SHA-256": 1, "MD5": 2}          # strongest first; a -SESS variant ranks with its base

_SCHEME = re.compile(r"(?:^|,)\s*([A-Za-z][A-Za-z0-9._~+/-]*)\s+(?=[A-Za-z0-9_-]+\s*=)")
_PARAM = re.compile(r'([A-Za-z0-9_-]+)\s*=\s*("(?:[^"\\]|\\.)*"|[^\s,]*)')


class DigestError(ValueError):
    """A challenge that cannot be answered (no Digest offered, or only what is not implemented)."""


@dataclass
class Challenge:
    realm: str
    nonce: str
    opaque: Optional[str] = None
    algorithm: str = "MD5"                  # canonical upper-case
    algorithm_named: bool = False           # the challenge spelled it out (echoed back, as curl does)
    qop: List[str] = field(default_factory=list)
    stale: bool = False

    @property
    def usable(self) -> bool:
        return self.algorithm in ALGORITHMS and (not self.qop or "auth" in self.qop)


def split_challenges(value: str) -> List[tuple]:
    """``(scheme, parameter text)`` for each challenge a single header value carries."""
    marks = [(m.start(1), m.end(0), m.group(1)) for m in _SCHEME.finditer(value)]
    out = []
    for i, (_, body_start, scheme) in enumerate(marks):
        body_end = marks[i + 1][0] if i + 1 < len(marks) else len(value)
        out.append((scheme, value[body_start:body_end].rstrip(", \t")))
    return out


def _parameters(text: str) -> Dict[str, str]:
    params = {}
    for key, value in _PARAM.findall(text):
        if value.startswith('"'):
            value = re.sub(r"\\(.)", r"\1", value[1:-1])
        params[key.lower()] = value
    return params


def parse_challenges(header_values: Sequence[str]) -> List[Challenge]:
    """Every Digest challenge in the ``WWW-Authenticate`` values of a 401 response."""
    found = []
    for value in header_values:
        for scheme, text in split_challenges(value):
            if scheme.lower() != "digest":
                continue
            p = _parameters(text)
            if "nonce" not in p:
                continue
            qop = [q.strip().lower() for q in p.get("qop", "").split(",") if q.strip()]
            found.append(Challenge(
                realm=p.get("realm", ""), nonce=p["nonce"], opaque=p.get("opaque"),
                algorithm=p.get("algorithm", "MD5").upper(), algorithm_named="algorithm" in p,
                qop=qop, stale=p.get("stale", "").lower() == "true"))
    return found


def offered_schemes(header_values: Sequence[str]) -> List[str]:
    """The authentication schemes a 401 response offered, for a message when none can be used."""
    return sorted({scheme for value in header_values for scheme, _ in split_challenges(value)})


def choose(challenges: Sequence[Challenge]) -> Challenge:
    """The strongest challenge this module can answer."""
    usable = [c for c in challenges if c.usable]
    if not usable:
        named = sorted({f"{c.algorithm}{' qop=' + ','.join(c.qop) if c.qop else ''}" for c in challenges})
        raise DigestError("the host's Digest challenge is not one agentcad can answer (offered: "
                          + (", ".join(named) or "nothing usable") + ")")
    return min(usable, key=lambda c: _RANK.get(c.algorithm.replace("-SESS", ""), 9))


def _hash(name: str, text: str) -> str:
    return hashlib.new(name, text.encode("utf-8"), usedforsecurity=False).hexdigest()


def response_value(ch: Challenge, method: str, uri: str, user: str, password: str, nc: int, cnonce: str) -> str:
    """The ``response`` field: RFC 7616 section 3.4.1 with ``qop=auth``, or RFC 2069's form without a qop."""
    hash_name, session = ALGORITHMS[ch.algorithm]
    ha1 = _hash(hash_name, f"{user}:{ch.realm}:{password}")
    if session:
        ha1 = _hash(hash_name, f"{ha1}:{ch.nonce}:{cnonce}")
    ha2 = _hash(hash_name, f"{method}:{uri}")
    if ch.qop:
        return _hash(hash_name, f"{ha1}:{ch.nonce}:{nc:08x}:{cnonce}:auth:{ha2}")
    return _hash(hash_name, f"{ha1}:{ch.nonce}:{ha2}")


def _quoted(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def authorization(ch: Challenge, method: str, uri: str, user: str, password: str,
                  nc: int = 1, cnonce: Optional[str] = None) -> str:
    """The ``Authorization`` header value answering ``ch`` for one request (field order as curl sends it)."""
    cnonce = cnonce or secrets.token_hex(8)
    response = response_value(ch, method, uri, user, password, nc, cnonce)
    parts = [f"username={_quoted(user)}", f"realm={_quoted(ch.realm)}", f"nonce={_quoted(ch.nonce)}",
             f"uri={_quoted(uri)}"]
    if ch.qop:
        parts += [f"cnonce={_quoted(cnonce)}", f"nc={nc:08x}", "qop=auth"]
    elif ALGORITHMS[ch.algorithm][1]:             # a -sess algorithm hashes the cnonce even without a qop
        parts.append(f"cnonce={_quoted(cnonce)}")
    parts.append(f"response={_quoted(response)}")
    if ch.opaque is not None:
        parts.append(f"opaque={_quoted(ch.opaque)}")
    if ch.algorithm_named:
        parts.append(f"algorithm={ch.algorithm}")
    return "Digest " + ", ".join(parts)
