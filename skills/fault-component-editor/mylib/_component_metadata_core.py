"""Standalone copy of current-unit resolution; this Skill has no sibling dependency."""

from __future__ import annotations

import re
from typing import Any, Callable

from cloudpss.utils import graphql_request


COMPONENT_DEFINITION_QUERY = """
query ComponentDefinition($rid: ResourceId!) {
  model(input: {rid: $rid}) {
    rid
    name
    description
    revision { parameters }
  }
}
"""

CURRENT_UNIT_SCALE_TO_KA = {"A": 1e-3, "kA": 1.0, "MA": 1e3, "mA": 1e-6}


def _items(parameters: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for entry in parameters if isinstance(parameters, list) else []:
        if not isinstance(entry, dict):
            continue
        nested = entry.get("items")
        if isinstance(nested, list):
            result.extend(item for item in nested if isinstance(item, dict))
        elif entry.get("key"):
            result.append(entry)
    return result


def resolve_current_parameter_metadata(
    definition_rid: str,
    parameter_key: str = "I",
    *,
    request: Callable[..., Any] = graphql_request,
) -> dict[str, Any]:
    rid = str(definition_rid or "").strip()
    if not rid.startswith("model/"):
        raise ValueError(f"Invalid CloudPSS component definition RID: {rid!r}")
    response = request(
        COMPONENT_DEFINITION_QUERY,
        {"rid": rid},
        timeout=(10.0, 30.0),
    )
    if not isinstance(response, dict) or response.get("errors"):
        raise RuntimeError("CloudPSS GraphQL could not read the component definition")
    data = response.get("data")
    component = data.get("model") if isinstance(data, dict) else None
    if not isinstance(component, dict) or str(component.get("rid") or "") != rid:
        raise LookupError(f"Component definition was not found or is not accessible: {rid}")
    revision = component.get("revision")
    parameters = revision.get("parameters") if isinstance(revision, dict) else None
    matches = [item for item in _items(parameters) if str(item.get("key") or "") == parameter_key]
    if len(matches) != 1:
        raise LookupError(f"Parameter {parameter_key!r} was not found uniquely in {rid}")
    parameter = matches[0]
    declared = str(parameter.get("unit") or "").strip() or None
    if declared is not None:
        if declared not in CURRENT_UNIT_SCALE_TO_KA:
            raise ValueError(f"Unsupported current unit {declared!r}")
        unit, source = declared, "parameter.unit"
    else:
        candidates: list[tuple[str, str]] = []
        for field in ("name", "description"):
            found = list(dict.fromkeys(re.findall(r"\[\s*(A|kA|MA|mA)\s*\]", str(parameter.get(field) or ""))))
            if len(found) > 1:
                raise ValueError(f"Conflicting current units in parameter.{field}")
            if found:
                candidates.append((found[0], f"parameter.{field}"))
        if not candidates:
            raise ValueError("Current unit is missing")
        if len({candidate for candidate, _ in candidates}) != 1:
            raise ValueError("Conflicting current unit declarations")
        unit, source = candidates[0]
    return {
        "definition_rid": rid,
        "component_name": component.get("name"),
        "parameter_key": parameter_key,
        "parameter_name": parameter.get("name"),
        "raw_unit": unit,
        "normalized_unit": "kA",
        "unit_source": source,
        "unit_scale_to_ka": CURRENT_UNIT_SCALE_TO_KA[unit],
    }
