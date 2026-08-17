"""CloudPSS component-definition metadata and engineering-unit helpers."""

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
    revision {
      parameters
    }
  }
}
"""

CURRENT_UNIT_SCALE_TO_KA = {
    "A": 1e-3,
    "kA": 1.0,
    "MA": 1e3,
    "mA": 1e-6,
}


def _parameter_items(parameters: Any) -> list[dict[str, Any]]:
    """Flatten CloudPSS parameter groups while preserving item dictionaries."""
    if not isinstance(parameters, list):
        return []
    flattened: list[dict[str, Any]] = []
    for entry in parameters:
        if not isinstance(entry, dict):
            continue
        items = entry.get("items")
        if isinstance(items, list):
            flattened.extend(item for item in items if isinstance(item, dict))
        elif entry.get("key"):
            flattened.append(entry)
    return flattened


def fetch_component_definition(
    definition_rid: str,
    *,
    request: Callable[..., Any] = graphql_request,
) -> dict[str, Any]:
    """Fetch one exact component definition through CloudPSS GraphQL."""
    rid = str(definition_rid or "").strip()
    if not rid.startswith("model/"):
        raise ValueError(f"Invalid CloudPSS component definition RID: {rid!r}")
    response = request(
        COMPONENT_DEFINITION_QUERY,
        {"rid": rid},
        timeout=(10.0, 30.0),
    )
    if not isinstance(response, dict):
        raise RuntimeError("CloudPSS GraphQL returned an unexpected response type")
    if response.get("errors"):
        raise RuntimeError("CloudPSS GraphQL could not read the component definition")
    data = response.get("data")
    model = data.get("model") if isinstance(data, dict) else None
    if not isinstance(model, dict):
        raise LookupError(f"Component definition was not found or is not accessible: {rid}")
    returned_rid = str(model.get("rid") or "").strip()
    if returned_rid != rid:
        raise LookupError(f"Component definition RID mismatch: requested {rid!r}")
    return model


def find_parameter_definition(
    component_definition: dict[str, Any], parameter_key: str
) -> dict[str, Any]:
    """Return one exact parameter item from a component definition."""
    revision = component_definition.get("revision")
    parameters = revision.get("parameters") if isinstance(revision, dict) else None
    key = str(parameter_key or "").strip()
    matches = [item for item in _parameter_items(parameters) if str(item.get("key") or "") == key]
    if not matches:
        rid = component_definition.get("rid")
        raise LookupError(f"Parameter {key!r} was not found in component definition {rid!r}")
    if len(matches) > 1:
        raise RuntimeError(f"Parameter {key!r} is ambiguous in the component definition")
    return matches[0]


def _supported_bracket_unit(value: Any) -> str | None:
    text = str(value or "")
    matches = re.findall(r"\[\s*(A|kA|MA|mA)\s*\]", text)
    unique = list(dict.fromkeys(matches))
    if len(unique) > 1:
        raise ValueError(f"Conflicting supported current units were declared in {text!r}")
    return unique[0] if unique else None


def resolve_current_parameter_metadata(
    definition_rid: str,
    parameter_key: str = "I",
    *,
    request: Callable[..., Any] = graphql_request,
) -> dict[str, Any]:
    """Resolve a current parameter unit and its deterministic scale to kA."""
    component = fetch_component_definition(definition_rid, request=request)
    parameter = find_parameter_definition(component, parameter_key)
    declared_unit = str(parameter.get("unit") or "").strip() or None
    if declared_unit is not None:
        if declared_unit not in CURRENT_UNIT_SCALE_TO_KA:
            raise ValueError(
                f"Unsupported current unit {declared_unit!r} for {definition_rid} parameter {parameter_key}"
            )
        raw_unit, unit_source = declared_unit, "parameter.unit"
    else:
        candidates: list[tuple[str, str]] = []
        for field in ("name", "description"):
            bracket_unit = _supported_bracket_unit(parameter.get(field))
            if bracket_unit is not None:
                candidates.append((bracket_unit, f"parameter.{field}"))
        distinct = {unit for unit, _ in candidates}
        if len(distinct) > 1:
            raise ValueError(
                f"Conflicting current units for {definition_rid} parameter {parameter_key}: "
                + ", ".join(sorted(distinct))
            )
        if candidates:
            raw_unit, unit_source = candidates[0]
        else:
            raise ValueError(
                f"Current unit is missing for {definition_rid} parameter {parameter_key}; "
                "expected parameter.unit or a supported [unit] in name/description"
            )

    return {
        "definition_rid": str(component["rid"]),
        "component_name": component.get("name"),
        "parameter_key": str(parameter_key),
        "parameter_name": parameter.get("name"),
        "parameter_description": parameter.get("description"),
        "raw_unit": raw_unit,
        "normalized_unit": "kA",
        "unit_source": unit_source,
        "unit_scale_to_ka": CURRENT_UNIT_SCALE_TO_KA[raw_unit],
    }
