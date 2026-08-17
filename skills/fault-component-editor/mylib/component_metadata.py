"""CloudPSS component current-unit metadata used by fault editing queries."""

from __future__ import annotations

from typing import Any, Callable

from ._component_metadata_core import resolve_current_parameter_metadata


def try_resolve_current_parameter_metadata(
    definition_rid: str,
    parameter_key: str = "I",
    *,
    request: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Return current-unit evidence without blocking unrelated model edits."""
    try:
        kwargs = {"request": request} if request is not None else {}
        metadata = resolve_current_parameter_metadata(
            definition_rid, parameter_key, **kwargs
        )
        return {"status": "resolved", **metadata}
    except Exception as exc:
        return {
            "status": "unavailable",
            "definition_rid": str(definition_rid or ""),
            "parameter_key": str(parameter_key or ""),
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
