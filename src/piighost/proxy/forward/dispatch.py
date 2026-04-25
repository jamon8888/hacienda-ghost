"""Coverage-matrix dispatcher: maps (method, path) → Handler."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from piighost.proxy.forward.handlers.base import Handler

CoverageMatrix = Mapping[tuple[str, str], Handler]

_PARAM_RE = re.compile(r"\{[^/]+\}")


@dataclass(frozen=True)
class _CompiledRoute:
    method: str
    pattern: re.Pattern[str]
    handler: Handler


class Dispatcher:
    """Routes requests to handlers from a (method, path) matrix.

    Path segments wrapped in `{...}` (e.g., `/v1/files/{id}`) match a
    single non-empty path segment. Query strings are stripped before
    matching. Method comparison is case-insensitive.
    """

    def __init__(self, *, matrix: CoverageMatrix, default: Handler) -> None:
        self._default = default
        self._routes = [
            _CompiledRoute(
                method=method.upper(),
                pattern=self._compile(path),
                handler=handler,
            )
            for (method, path), handler in matrix.items()
        ]

    @staticmethod
    def _compile(path: str) -> re.Pattern[str]:
        escaped = re.escape(path)
        # re.escape escapes the braces too, undo just for our params:
        with_params = _PARAM_RE.sub(
            r"[^/]+", escaped.replace(r"\{", "{").replace(r"\}", "}")
        )
        return re.compile(rf"^{with_params}$")

    def dispatch(self, *, method: str, path: str) -> Handler:
        bare_path = path.split("?", 1)[0]
        upper_method = method.upper()
        for route in self._routes:
            if route.method == upper_method and route.pattern.match(bare_path):
                return route.handler
        return self._default
