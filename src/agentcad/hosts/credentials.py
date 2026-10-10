"""Where a host's address and credentials come from, and how they stay out of sight.

Two sources, never a project file:

* environment variables ``AGENTCAD_<HOST>_URL``, ``_USER``, ``_PASSWORD``, ``_TIMEOUT`` and
  ``_STORAGE`` (``<HOST>`` is the host's name in capitals: ``AGENTCAD_PRUSALINK_URL``);
* the table named after the host in ``hosts.toml`` in the agentcad user config folder
  (``$XDG_CONFIG_HOME/agentcad`` or ``~/.config/agentcad``).

Each value comes from the environment when it is set there, else from the file, else from the
host's defaults (``user`` is ``maker`` for PrusaLink). A file that other users can read or write is
refused, with the command that fixes its mode. A credential is never part of a message, a log
line, a repr or a JSON record: errors name where to put a value, never the value.
"""

import os
import re
import shlex
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlsplit, urlunsplit

from agentcad.hosts import HostConfigError

FILENAME = "hosts.toml"
FIELDS = ("url", "user", "password", "timeout", "storage")
REQUIRED = ("url", "user", "password")
DEFAULT_TIMEOUT = 10.0


@dataclass(frozen=True, repr=False)
class HostSettings:
    """A host's address and credentials. ``repr`` and ``str`` hide the user and the password."""
    url: str
    user: str
    password: str
    timeout: float = DEFAULT_TIMEOUT
    storage: Optional[str] = None
    source: str = ""

    def __repr__(self) -> str:
        return (f"HostSettings(url={self.url!r}, user='***', password='***', timeout={self.timeout!r}, "
                f"storage={self.storage!r}, source={self.source!r})")

    __str__ = __repr__

    def public(self) -> Dict[str, Any]:
        """What may be shown or written out: no user, no password."""
        return {"url": self.url, "timeout": self.timeout, "storage": self.storage, "source": self.source}


def env_name(host: str, field: str) -> str:
    """The environment variable for one setting of a host: ``AGENTCAD_PRUSALINK_PASSWORD``."""
    return "AGENTCAD_" + re.sub(r"[^A-Za-z0-9]+", "_", host).upper() + "_" + field.upper()


def config_path() -> Path:
    """The user file: ``hosts.toml`` beside ``printers.toml`` in the agentcad user config folder."""
    from agentcad.printers import user_config_dir
    return user_config_dir() / FILENAME


def normalize_url(raw: str) -> str:
    """The host's base URL: scheme (http by default), host and optional port and path prefix. A URL
    that carries a user name or a password is refused, and the refusal does not repeat it."""
    text = (raw or "").strip()
    if not text:
        raise HostConfigError("the host URL is empty")
    if "://" not in text:
        text = "http://" + text
    try:
        parts = urlsplit(text)
        parts.port                                    # a bad port raises here
    except ValueError:
        raise HostConfigError("the host URL is not valid (expected http://host[:port])") from None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise HostConfigError("the host URL must be http:// or https:// followed by a host name")
    if "@" in parts.netloc:
        raise HostConfigError("the host URL must not carry a user name or password; give them as the "
                              "user and password settings instead")
    if parts.query or parts.fragment:
        raise HostConfigError("the host URL must not have a query or a fragment")
    if not re.fullmatch(r"(/[!-~]*)?", parts.path):
        raise HostConfigError("the host URL path must be printable text without spaces")
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def check_private(path: Path, mode: Optional[int] = None) -> None:
    """Refuse a credentials file that group or others can reach, naming the command that fixes it.
    ``mode`` is the file's ``st_mode`` when the caller already has it from the open file."""
    if os.name == "nt":                               # POSIX permission bits do not describe access there
        return
    if mode is None:
        try:
            mode = os.stat(path).st_mode
        except OSError as e:
            raise HostConfigError(f"cannot read {path}: {e.strerror or e}") from None
    mode = stat.S_IMODE(mode)
    if mode & 0o077:
        raise HostConfigError(f"refusing to read {path}: other users can access it (mode {mode:04o}) and it "
                              f"holds a password; fix it with: chmod 600 {shlex.quote(str(path))}")


def read_table(host: str, path: Path) -> Dict[str, Any]:
    """The host's table from the user file ({} when the file is absent). The file must be private."""
    if not path.is_file():
        return {}
    from agentcad.config import tomllib
    try:
        with open(path, "rb") as f:
            check_private(path, os.fstat(f.fileno()).st_mode)          # the mode of the file actually opened
            if tomllib is None:
                raise HostConfigError(f"{path} exists but this Python has no TOML reader (use Python 3.11 or "
                                      f"install tomli), or set the {env_name(host, 'url')}, "
                                      f"{env_name(host, 'user')} and {env_name(host, 'password')} variables instead")
            data = tomllib.load(f)
    except OSError as e:
        raise HostConfigError(f"cannot read {path}: {e.strerror or e}") from None
    except ValueError as e:                           # tomllib.TOMLDecodeError; its message names a line, not a value
        raise HostConfigError(f"cannot parse {path}: {e}") from None
    table = data.get(host, {})
    if not isinstance(table, dict):
        raise HostConfigError(f"{path}: [{host}] must be a table")
    unknown = sorted(set(table) - set(FIELDS))
    if unknown:
        raise HostConfigError(f"{path}: unknown setting(s) in [{host}]: {', '.join(unknown)} "
                              f"(known: {', '.join(FIELDS)})")
    return table


def load_settings(host: str, defaults: Optional[Mapping[str, Any]] = None,
                  environ: Optional[Mapping[str, str]] = None, path: Optional[Path] = None) -> HostSettings:
    """A host's settings from the environment, then the user file, then ``defaults``."""
    environ = os.environ if environ is None else environ
    path = Path(path) if path is not None else config_path()
    values: Dict[str, Any] = {}
    origin: Dict[str, str] = {}
    table = read_table(host, path)
    for name in FIELDS:
        env_value = environ.get(env_name(host, name))
        if env_value not in (None, ""):
            values[name], origin[name] = env_value, "environment"
        elif table.get(name) not in (None, ""):
            values[name], origin[name] = table[name], str(path)
        elif name in (defaults or {}):
            values[name], origin[name] = defaults[name], "default"
    missing = [n for n in REQUIRED if n not in values]
    if missing:
        raise HostConfigError("; ".join(
            f"{host}: no {n}: set {env_name(host, n)} or add `{n} = ...` under [{host}] in {path}"
            + (" (mode 600)" if n == "password" else "") for n in missing))
    for name in ("user", "password", "storage"):
        if name in values and not isinstance(values[name], str):
            raise HostConfigError(f"{host}: {name} must be text (from {origin[name]})")
    try:
        timeout = float(values.get("timeout", DEFAULT_TIMEOUT))
        if timeout <= 0:
            raise ValueError
    except (TypeError, ValueError):
        raise HostConfigError(f"{host}: timeout must be a positive number of seconds (from "
                              f"{origin.get('timeout', 'default')})") from None
    sources = sorted({o for o in origin.values() if o != "default"})
    return HostSettings(url=normalize_url(str(values["url"])), user=values["user"], password=values["password"],
                        timeout=timeout, storage=values.get("storage") or None,
                        source=" and ".join(sources) or "defaults")
