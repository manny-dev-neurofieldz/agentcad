"""Parameter overrides for engines whose sources are Python modules.

The CLI passes ``-D name=value`` pairs as strings. An OpenSCAD source takes
them verbatim on its own command line; a Python source has no such channel,
so the convention shared by every Python-based engine is:

* if the module defines ``build(**params)``, the engine calls it with the
  overrides coerced to the types of the function's default values;
* otherwise the engine harvests a module-level object by name and reports
  that any overrides were ignored.

This module holds the coercion so each engine does not grow its own copy.
"""

import ast
import inspect
from typing import Any, Callable, Dict, Mapping, Optional

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def parse_define_value(text: str) -> Any:
    """Best-effort typed value from a ``-D`` string: literal if it parses, else the string."""
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text


def coerce_to_type_of(value: str, exemplar: Any) -> Any:
    """Coerce ``value`` to the type of ``exemplar`` when that type is bool/int/float/str.

    Anything else falls back to ``parse_define_value``. Raises ValueError when
    the string cannot be read as the exemplar's type, so a typo in an override
    surfaces instead of silently becoming a string.
    """
    if isinstance(exemplar, bool):
        lowered = value.strip().lower()
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
        raise ValueError(f"expected a boolean, got {value!r}")
    if isinstance(exemplar, int):
        return int(value)
    if isinstance(exemplar, float):
        return float(value)
    if isinstance(exemplar, str):
        return value
    return parse_define_value(value)


def coerce_defines(defines: Optional[Mapping[str, str]], build: Callable[..., Any]) -> Dict[str, Any]:
    """Coerce string overrides against ``build``'s signature defaults.

    Parameters without a default (or with a non-scalar default) are parsed as
    Python literals. Unknown parameter names are passed through only when the
    function accepts ``**kwargs``; otherwise a ValueError names the parameter
    so the caller can report it.
    """
    if not defines:
        return {}
    sig = inspect.signature(build)
    accepts_kwargs = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    params: Dict[str, Any] = {}
    for key, raw in defines.items():
        if key in sig.parameters:
            default = sig.parameters[key].default
            exemplar = None if default is inspect.Parameter.empty else default
            params[key] = coerce_to_type_of(raw, exemplar)
        elif accepts_kwargs:
            params[key] = parse_define_value(raw)
        else:
            raise ValueError(
                f"build() has no parameter '{key}' "
                f"(accepts: {', '.join(sig.parameters) or 'none'})"
            )
    return params
