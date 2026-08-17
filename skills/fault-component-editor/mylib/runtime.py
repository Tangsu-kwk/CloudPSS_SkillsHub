"""Local-first runtime for CloudPSS fault-component editing.

The runtime deliberately has no dependency on short-circuit-analysis.  It
edits the current in-memory CloudPSS Model, owns its snapshots/rollback, and
uses ``Model.runEMT`` only as a model-runnability verification.
"""
from __future__ import annotations

import copy
import json
import math
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .component_metadata import try_resolve_current_parameter_metadata

FAULT_DEFINITION = "model/CloudPSS/_newFaultResistor_3p"
GND_DEFINITION = "model/CloudPSS/GND"
CHANNEL_DEFINITION = "model/CloudPSS/_newChannel"
FAULT_FIELDS = ("fs", "fe", "ft", "Init", "chg", "I", "V")
SUPPORTED_OPERATIONS = {"query", "update", "create", "delete", "configure_channel", "save_copy"}


@dataclass
class EditRequest:
    operation: str
    target: dict[str, Any] = field(default_factory=dict)
    changes: dict[str, Any] = field(default_factory=dict)
    confirmation: str | None = None
    options: dict[str, Any] = field(default_factory=dict)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    to_json = getattr(value, "toJSON", None)
    if callable(to_json):
        return _json_safe(to_json())
    return str(value)


def _source(value: Any) -> Any:
    return value.get("source") if isinstance(value, dict) and "source" in value else value


def _number(value: Any) -> float | None:
    value = _source(value)
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _component_json(component: Any) -> dict[str, Any]:
    value = _json_safe(component)
    return value if isinstance(value, dict) else {}


def _components_from_model(model: Any) -> dict[str, Any]:
    getter = getattr(model, "getAllComponents", None)
    value = getter() if callable(getter) else {}
    return {str(key): item for key, item in value.items()} if isinstance(value, dict) else {}


def _cells(model_json: dict[str, Any]) -> dict[str, dict[str, Any]]:
    revision = model_json.get("revision", {})
    implements = revision.get("implements", {}) if isinstance(revision, dict) else {}
    diagram = implements.get("diagram", {}) if isinstance(implements, dict) else {}
    cells = diagram.get("cells", {}) if isinstance(diagram, dict) else {}
    if isinstance(cells, list):
        return {str(item.get("id")): item for item in cells if isinstance(item, dict) and item.get("id")}
    return {str(key): item for key, item in cells.items() if isinstance(item, dict)} if isinstance(cells, dict) else {}


def _live_cells(model: Any) -> dict[str, Any]:
    """Return the SDK diagram cell mapping without assuming a wrapper shape."""
    revision = getattr(model, "revision", None)
    implements = getattr(revision, "implements", None) if revision is not None else None
    diagram = getattr(implements, "diagram", None) if implements is not None else None
    cells = getattr(diagram, "cells", None) if diagram is not None else None
    return cells if isinstance(cells, dict) else {}


def _remove_diagram_edges(model: Any, edge_ids: set[str]) -> list[str]:
    cells = _live_cells(model)
    removed: list[str] = []
    for edge_id in edge_ids:
        if edge_id in cells and str(getattr(cells[edge_id], "shape", "") or cells[edge_id].get("shape", "")) == "diagram-edge":
            del cells[edge_id]
            removed.append(edge_id)
    return removed


def _add_diagram_edge(
    model: Any,
    *,
    source_id: str,
    source_port: str,
    target_id: str,
    target_port: str,
    canvas: str | None,
) -> str:
    """Add one explicit topology edge while preserving all existing edges."""
    try:
        from cloudpss.model.implements.component import Component
    except ImportError as exc:
        raise RuntimeError("CloudPSS dependency is unavailable") from exc

    cells = _live_cells(model)
    if not isinstance(cells, dict):
        raise RuntimeError("CloudPSS diagram cells are unavailable; cannot create diagram-edge")
    edge_id = f"fault-edge-{uuid.uuid4().hex}"
    edge = {
        "id": edge_id,
        "shape": "diagram-edge",
        "source": {"cell": str(source_id), "port": str(source_port)},
        "target": {"cell": str(target_id), "port": str(target_port)},
    }
    if canvas:
        edge["canvas"] = str(canvas)
    # DiagramImplement.toJSON() serializes every cell through cell.toJSON().
    # Keep new edges in the same SDK wrapper type as fetched diagram cells.
    cells[edge_id] = Component(edge)
    return edge_id


def _display_name(component_id: str, component: dict[str, Any]) -> str:
    args = component.get("args") if isinstance(component.get("args"), dict) else {}
    return str(_source(args.get("Name")) or component.get("label") or component_id)


def _resolve_target_component(model: Any, model_json: dict[str, Any], identifier: str) -> tuple[str, Any, dict[str, Any]]:
    """Resolve a component id or display name to one real diagram component id."""
    identifier = str(identifier or "").strip()
    if not identifier:
        raise ValueError("create requires target.component_id or target.name")
    components = _components_from_model(model) or _cells(model_json)
    exact = components.get(identifier)
    if exact is not None:
        component = _component_json(exact)
        if component.get("shape") != "diagram-edge":
            return identifier, exact, component
    matches: list[tuple[str, Any, dict[str, Any]]] = []
    for component_id, raw in components.items():
        component = _component_json(raw)
        if component.get("shape") == "diagram-edge":
            continue
        args = component.get("args") if isinstance(component.get("args"), dict) else {}
        names = {_display_name(component_id, component), str(_source(args.get("Name")) or "")}
        if identifier in names:
            matches.append((component_id, raw, component))
    if not matches:
        raise ValueError(f"Target component does not exist: {identifier!r}")
    if len(matches) > 1:
        ids = ", ".join(sorted(component_id for component_id, _, _ in matches))
        raise ValueError(f"Target component name is ambiguous: {identifier!r}; matching ids: {ids}")
    return matches[0]


def _resolve_target_pin(model: Any, model_json: dict[str, Any], request: EditRequest) -> tuple[str, str, dict[str, Any]]:
    identifier = str(request.target.get("component_id") or request.target.get("name") or "").strip()
    target_port = str(request.target.get("port") or "").strip()
    if not target_port:
        raise ValueError("create requires target.port")
    target_id, _, target = _resolve_target_component(model, model_json, identifier)
    pins = target.get("pins") if isinstance(target.get("pins"), dict) else None
    if pins is None or target_port not in {str(port) for port in pins}:
        raise ValueError(f"Target pin does not exist or cannot be confirmed: {target_id}:{target_port}")
    return target_id, target_port, target


def _set_component_pin(raw: Any, port: str, value: Any) -> None:
    pins = getattr(raw, "pins", None)
    if isinstance(pins, dict):
        pins[str(port)] = copy.deepcopy(value)
    elif isinstance(raw, dict):
        raw.setdefault("pins", {})[str(port)] = copy.deepcopy(value)
    else:
        raise TypeError("CloudPSS component pins are not writable")


def _fetch_topology(model: Any) -> dict[str, Any] | None:
    """Fetch the EMT topology exactly as CaseEditToolbox.refreshTopology does."""
    try:
        from cloudpss import ModelRevision, ModelTopology
    except ImportError:
        return None
    configs = getattr(model, "configs", None)
    context = getattr(model, "context", None)
    if not isinstance(configs, dict) or not isinstance(context, dict):
        return None
    current_config = context.get("currentConfig")
    if current_config not in configs:
        return None
    revision = ModelRevision.create(model.revision)
    revision_hash = revision.get("hash") if isinstance(revision, dict) else revision["hash"]
    return _json_safe(ModelTopology.fetch(revision_hash, "emtp", configs[current_config], maximumDepth=0).toJSON())


def _edge_groups(cells: dict[str, dict[str, Any]]) -> list[list[tuple[str, str]]]:
    """Offline equivalent of topology groups for verification and SDK fallback."""
    adjacency: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for edge in _edges(cells).values():
        left, right = _edge_endpoints(edge)
        if None in left or None in right:
            continue
        a = (str(left[0]), str(left[1]))
        b = (str(right[0]), str(right[1]))
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)
    groups: list[list[tuple[str, str]]] = []
    unseen = set(adjacency)
    while unseen:
        root = unseen.pop()
        group = {root}
        stack = [root]
        while stack:
            for neighbour in adjacency.get(stack.pop(), set()):
                if neighbour not in group:
                    group.add(neighbour)
                    unseen.discard(neighbour)
                    stack.append(neighbour)
        groups.append(sorted(group))
    return groups


def _pin_normalization_plan(model: Any, generated_names: dict[str, str] | None = None) -> dict[str, Any]:
    """Plan CaseEditToolbox.deleteEdges: shared pin names replace all diagram edges."""
    model_json = _json_safe(model.toJSON())
    cells = _cells(model_json)
    components = _components_from_model(model) or cells
    topology = _fetch_topology(model)
    node_endpoints: dict[str, list[tuple[str, str]]] = {}
    if isinstance(topology, dict) and isinstance(topology.get("components"), dict):
        for topo_id, component in topology["components"].items():
            component_id = str(topo_id).lstrip("/")
            pins = component.get("pins") if isinstance(component, dict) else None
            if not isinstance(pins, dict):
                continue
            for port, node in pins.items():
                if str(node) != "":
                    node_endpoints.setdefault(str(node), []).append((component_id, str(port)))
    else:
        for index, group in enumerate(_edge_groups(cells)):
            node_endpoints[str(index)] = group

    supplied = {str(key): str(value) for key, value in (generated_names or {}).items()}
    prefix = "AutoAddPin" + time.strftime("%Y%m%d%H%M%S", time.localtime()) + "_"
    generated_count = 0
    nodes: dict[str, dict[str, Any]] = {}
    endpoint_node: dict[tuple[str, str], str] = {}
    for node, endpoints in node_endpoints.items():
        existing: list[str] = []
        for component_id, port in endpoints:
            data = _component_json(components.get(component_id))
            value = str(_source((data.get("pins") or {}).get(port)) or "").strip()
            if value and value not in existing:
                existing.append(value)
            endpoint_node[(component_id, port)] = node
        pin_name = existing[0] if existing else supplied.get(node)
        if not pin_name:
            pin_name = prefix + str(generated_count)
            generated_count += 1
        nodes[node] = {"pin_name": pin_name, "endpoints": endpoints, "existing_names": existing}
    return {
        "nodes": nodes,
        "endpoint_node": endpoint_node,
        "edge_ids": sorted(_edges(cells)),
        "generated_names": {node: item["pin_name"] for node, item in nodes.items() if not item["existing_names"]},
        "source": "ModelTopology.fetch" if topology is not None else "diagram-edge fallback",
    }


def _apply_pin_normalization(model: Any, plan: dict[str, Any]) -> list[str]:
    """Apply the reference deleteEdges behavior to the in-memory model."""
    components = _components_from_model(model)
    for item in plan["nodes"].values():
        for component_id, port in item["endpoints"]:
            raw = components.get(component_id)
            if raw is None:
                continue
            current = str(_source((_component_json(raw).get("pins") or {}).get(port)) or "").strip()
            if not current:
                _set_component_pin(raw, port, item["pin_name"])
    return _remove_diagram_edges(model, set(plan["edge_ids"]))


def _target_pin_name(plan: dict[str, Any], target_id: str, target_port: str, target: dict[str, Any]) -> str:
    existing = str(_source((target.get("pins") or {}).get(target_port)) or "").strip()
    if existing:
        return existing
    node = plan["endpoint_node"].get((target_id, target_port))
    if node is None:
        raise ValueError(f"Target pin is not connected in EMT topology: {target_id}:{target_port}")
    return str(plan["nodes"][node]["pin_name"])


def _is_fault(component: dict[str, Any]) -> bool:
    definition = str(component.get("definition") or "").lower()
    props = component.get("props") if isinstance(component.get("props"), dict) else {}
    return "faultresistor" in definition and props.get("enabled", True) is not False


def _is_channel(component: dict[str, Any]) -> bool:
    return str(component.get("definition") or "") == CHANNEL_DEFINITION


def _is_gnd(component: dict[str, Any]) -> bool:
    return str(component.get("definition") or "") == GND_DEFINITION


def _faults(model: Any, model_json: dict[str, Any]) -> list[dict[str, Any]]:
    objects = _components_from_model(model) or _cells(model_json)
    faults: list[dict[str, Any]] = []
    for component_id, raw in objects.items():
        component = _component_json(raw)
        if not _is_fault(component):
            continue
        args = component.get("args") if isinstance(component.get("args"), dict) else {}
        faults.append(
            {
                "id": component_id,
                "name": _display_name(component_id, component),
                "definition": component.get("definition"),
                "args": {key: copy.deepcopy(args.get(key)) for key in FAULT_FIELDS if key in args},
                "props": copy.deepcopy(component.get("props", {})),
                "pins": copy.deepcopy(component.get("pins", {})),
            }
        )
    return faults


def _attach_fault_current_unit_metadata(faults: list[dict[str, Any]]) -> None:
    """Enrich query/snapshot data without blocking editing when GraphQL is unavailable."""
    cache: dict[str, dict[str, Any]] = {}
    for fault in faults:
        definition = str(fault.get("definition") or "").strip()
        args = fault.get("args") if isinstance(fault.get("args"), dict) else {}
        if not _source(args.get("I")):
            fault["current_unit"] = {
                "status": "not_applicable",
                "definition_rid": definition,
                "parameter_key": "I",
                "message": "The fault has no declared args.I current channel",
            }
            continue
        metadata = cache.get(definition)
        if metadata is None:
            metadata = try_resolve_current_parameter_metadata(definition, "I")
            cache[definition] = metadata
        fault["current_unit"] = copy.deepcopy(metadata)


def _resolve_fault(model: Any, model_json: dict[str, Any], identifier: str) -> tuple[str, Any, dict[str, Any]]:
    matches = []
    for component_id, raw in (_components_from_model(model) or _cells(model_json)).items():
        component = _component_json(raw)
        if not _is_fault(component):
            continue
        args = component.get("args") if isinstance(component.get("args"), dict) else {}
        names = {component_id, _display_name(component_id, component), str(_source(args.get("Name")) or "")}
        if identifier in names:
            matches.append((component_id, raw, component))
    if len(matches) != 1:
        raise ValueError(f"Fault component identifier is not unique: {identifier!r}")
    return matches[0]


def _edges(cells: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {key: value for key, value in cells.items() if value.get("shape") == "diagram-edge"}


def _edge_endpoints(edge: dict[str, Any]) -> tuple[tuple[str | None, str | None], tuple[str | None, str | None]]:
    source = edge.get("source") if isinstance(edge.get("source"), dict) else {}
    target = edge.get("target") if isinstance(edge.get("target"), dict) else {}
    return (
        (str(source.get("cell")) if source.get("cell") else None, str(source.get("port")) if source.get("port") is not None else None),
        (str(target.get("cell")) if target.get("cell") else None, str(target.get("port")) if target.get("port") is not None else None),
    )


def _incident_edges(cells: dict[str, dict[str, Any]], component_id: str) -> dict[str, dict[str, Any]]:
    result = {}
    for edge_id, edge in _edges(cells).items():
        (source_id, _), (target_id, _) = _edge_endpoints(edge)
        if component_id in {source_id, target_id}:
            result[edge_id] = edge
    return result


def _channel_reference(component: dict[str, Any]) -> str | None:
    pins = component.get("pins") if isinstance(component.get("pins"), dict) else {}
    return str(_source(pins.get("0")) or "").strip() or None


def _reference_variants(value: Any) -> set[str]:
    raw = str(_source(value) or "").strip().strip("'\"")
    if not raw:
        return set()
    return {raw, raw.lstrip("#"), f"#{raw.lstrip('#')}"}


def _fault_channel_links(model: Any, model_json: dict[str, Any], fault_component: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    args = fault_component.get("args") if isinstance(fault_component.get("args"), dict) else {}
    components = _components_from_model(model) or _cells(model_json)
    links: dict[str, list[dict[str, Any]]] = {"I": [], "V": []}
    for field in ("I", "V"):
        wanted = _reference_variants(args.get(field))
        if not wanted:
            continue
        for component_id, raw in components.items():
            component = _component_json(raw)
            if not _is_channel(component):
                continue
            reference = _channel_reference(component)
            if reference and _reference_variants(reference) & wanted:
                links[field].append({"id": component_id, "reference": reference, "component": component})
    return links


def _fault_ground_links(model: Any, model_json: dict[str, Any], fault_id: str) -> dict[str, Any]:
    cells = _cells(model_json)
    components = _components_from_model(model) or cells
    fault_edges = _incident_edges(cells, fault_id)
    gnds: list[dict[str, Any]] = []
    target_edges: list[dict[str, Any]] = []
    fault = _component_json(components.get(fault_id))
    pins = fault.get("pins") if isinstance(fault.get("pins"), dict) else {}
    network_pin = str(_source(pins.get("0")) or "").strip()
    ground_pin = str(_source(pins.get("1")) or "").strip()
    for component_id, raw in components.items():
        if component_id == fault_id:
            continue
        component = _component_json(raw)
        component_pins = component.get("pins") if isinstance(component.get("pins"), dict) else {}
        for port, value in component_pins.items():
            pin_name = str(_source(value) or "").strip()
            if network_pin and pin_name == network_pin and not _is_channel(component):
                target_edges.append({"component_id": component_id, "port": str(port), "pin_name": pin_name})
            elif ground_pin and pin_name == ground_pin and _is_gnd(component):
                gnds.append({"component_id": component_id, "port": str(port), "pin_name": pin_name})
    uncertain: list[dict[str, Any]] = []
    for edge_id, edge in fault_edges.items():
        (source_id, source_port), (target_id, target_port) = _edge_endpoints(edge)
        other_id = target_id if source_id == fault_id else source_id
        other_port = target_port if source_id == fault_id else source_port
        other_component = _component_json(components.get(other_id)) if other_id else {}
        item = {"edge_id": edge_id, "component_id": other_id, "port": other_port, "edge": edge}
        if _is_gnd(other_component):
            gnds.append(item)
        elif other_id:
            target_edges.append(item)
        else:
            uncertain.append(item)
    if not network_pin or ground_pin != "GND":
        uncertain.append({"component_id": fault_id, "pins": copy.deepcopy(pins), "reason": "fault pins do not match logical pin-name topology"})
    return {"fault_edges": fault_edges, "gnds": gnds, "targets": target_edges, "uncertain": uncertain, "network_pin": network_pin, "ground_pin": ground_pin}


def _output_channel_entries(model_json: dict[str, Any], component_ids: set[str] | None = None) -> list[dict[str, Any]]:
    entries = []
    for job_index, job in enumerate(model_json.get("jobs", [])):
        args = job.get("args") if isinstance(job, dict) and isinstance(job.get("args"), dict) else {}
        configured = args.get("output_channels")
        if not isinstance(configured, list):
            continue
        for entry_index, entry in enumerate(configured):
            selected = entry.get("4", []) if isinstance(entry, dict) else []
            selected_ids = {str(item) for item in selected} if isinstance(selected, list) else set()
            if component_ids is None or component_ids & selected_ids:
                entries.append({"job_index": job_index, "entry_index": entry_index, "entry": copy.deepcopy(entry), "component_ids": sorted(selected_ids)})
    return entries


def _normalize_update(changes: dict[str, Any]) -> dict[str, Any]:
    unknown = set(changes) - set(FAULT_FIELDS)
    if unknown:
        raise ValueError(f"Unsupported fault fields: {sorted(unknown)}")
    normalized = copy.deepcopy(changes)
    for key in ("fs", "fe", "Init", "chg"):
        if key in normalized and _number(normalized[key]) is None:
            raise ValueError(f"{key} must be a finite number")
    if "ft" in normalized:
        value = _number(normalized["ft"])
        if value is None or value != int(value) or not 0 <= int(value) <= 7:
            raise ValueError("ft must be an integer from 0 to 7")
        normalized["ft"] = str(int(value))
    for key in ("I", "V"):
        if key in normalized and not str(_source(normalized[key]) or "").strip():
            raise ValueError(f"{key} must be non-empty text")
    return normalized


def _normalized_create_changes(changes: dict[str, Any]) -> dict[str, Any]:
    """Validate and freeze all required create parameters during preview."""
    allowed = {"fs", "fe", "ft", "Init", "chg"}
    normalized = _normalize_update({key: value for key, value in changes.items() if key in allowed})
    missing = sorted(allowed - set(normalized))
    if missing:
        raise ValueError(f"Creating a fault requires: {', '.join(missing)}")
    if _number(normalized["fs"]) >= _number(normalized["fe"]):
        raise ValueError("fs must be less than fe")
    return normalized


def _storage_value(old_value: Any, new_value: Any) -> Any:
    if isinstance(old_value, dict) and "source" in old_value:
        result = copy.deepcopy(old_value)
        result["source"] = str(_source(new_value))
        return result
    raw = _source(new_value)
    if isinstance(old_value, str):
        return str(raw)
    if isinstance(old_value, bool):
        return bool(raw)
    if isinstance(old_value, int) and not isinstance(old_value, bool):
        number = _number(raw)
        return int(number) if number is not None and number.is_integer() else copy.deepcopy(raw)
    if isinstance(old_value, float):
        number = _number(raw)
        return float(number) if number is not None else copy.deepcopy(raw)
    return copy.deepcopy(raw)


def _new_numeric(value: Any) -> int | float:
    number = _number(value)
    if number is None:
        raise ValueError(f"Expected a finite numeric value, got {value!r}")
    return int(number) if number.is_integer() else number


def _preferred_arg_type(model: Any, field: str) -> type:
    """Infer a new component argument type from the current model, if possible."""
    model_json = _json_safe(model.toJSON())
    for item in _faults(model, model_json):
        value = item.get("args", {}).get(field)
        if value is not None:
            return type(_source(value))
    return str if field in {"ft", "I", "V"} else float


def _set_component_args(raw: Any, updates: dict[str, Any]) -> None:
    args = getattr(raw, "args", None)
    if isinstance(args, dict):
        args.update(copy.deepcopy(updates))
    elif isinstance(raw, dict):
        raw.setdefault("args", {}).update(copy.deepcopy(updates))
    else:
        raise TypeError("CloudPSS component args are not writable")


def _snapshot_payload(
    model: Any,
    source: str | None,
    version: str,
    cached_unit_metadata: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    model_json = _json_safe(model.toJSON()) if callable(getattr(model, "toJSON", None)) else _json_safe(model)
    faults = _faults(model, model_json)
    cached_by_definition = {
        str(item.get("definition") or ""): copy.deepcopy(item.get("current_unit"))
        for item in (cached_unit_metadata or [])
        if isinstance(item, dict) and item.get("definition")
    }
    for fault in faults:
        definition = str(fault.get("definition") or "")
        fault["current_unit"] = cached_by_definition.get(definition) or {
            "status": "not_queried",
            "definition_rid": definition,
            "parameter_key": "I",
            "message": "Run the query operation to refresh current-unit metadata",
        }
    return {
        "source": source,
        "version": version,
        "model": model_json,
        "components": {key: _component_json(value) for key, value in _components_from_model(model).items()},
        "fault_unit_metadata": [
            {
                "id": fault.get("id"),
                "definition": fault.get("definition"),
                "current_channel": _source((fault.get("args") or {}).get("I")),
                "current_unit": fault.get("current_unit"),
            }
            for fault in faults
        ],
    }


def _state(session_state: dict[str, Any]) -> dict[str, Any]:
    session_state.setdefault("current_version", "v000_original")
    session_state.setdefault("last_successful_emt_version", None)
    session_state.setdefault("saved_copy_rid", None)
    session_state.setdefault("recent_emt_failures", [])
    session_state.setdefault("version_snapshots", {})
    session_state.setdefault("version_models", {})
    session_state.setdefault("pending_preview", None)
    session_state.setdefault("fault_unit_metadata", [])
    return session_state


def _ensure_model(session_state: dict[str, Any]) -> Any:
    model = session_state.get("memory_model")
    if model is not None:
        # Tool/session serialization can turn the live SDK Model into its JSON
        # dictionary between preview and confirmation turns. Rehydrate it
        # before any runtime operation calls Model methods such as toJSON().
        if isinstance(model, dict):
            try:
                from cloudpss import Model
            except ImportError as exc:
                raise RuntimeError("CloudPSS dependency is unavailable") from exc
            model = Model(copy.deepcopy(model))
            session_state["memory_model"] = model
        return model
    rid = str(session_state.get("original_rid") or "").strip()
    if not rid:
        raise ValueError("original_rid is required")
    try:
        from cloudpss import Model
    except ImportError as exc:
        raise RuntimeError("CloudPSS dependency is unavailable") from exc
    model = Model.fetch(rid)
    session_state["memory_model"] = model
    return model


def _write_snapshot(state: dict[str, Any], model: Any, version: str, kind: str = "model_parameters") -> str:
    root = Path(state.get("snapshot_dir") or Path.cwd() / "results" / "fault_component_editor")
    root.mkdir(parents=True, exist_ok=True)
    payload = _snapshot_payload(
        model,
        state.get("original_rid"),
        version,
        state.get("fault_unit_metadata"),
    )
    path = root / f"{kind}_{version}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    state["version_snapshots"][version] = str(path.resolve())
    state["version_models"][version] = copy.deepcopy(payload["model"])
    return str(path.resolve())


def _restore_version(state: dict[str, Any], version: str) -> Any:
    model_json = state["version_models"].get(version)
    if model_json is None:
        snapshot = state["version_snapshots"].get(version)
        if not snapshot:
            raise RuntimeError(f"Rollback snapshot is unavailable: {version}")
        model_json = json.loads(Path(snapshot).read_text(encoding="utf-8"))["model"]
    try:
        from cloudpss import Model
    except ImportError as exc:
        raise RuntimeError("CloudPSS dependency is unavailable") from exc
    restored = Model(copy.deepcopy(model_json))
    state["memory_model"] = restored
    state["current_version"] = version
    return restored


def _new_version(state: dict[str, Any], component_name: str, suffix: str) -> str:
    index = len(state["version_snapshots"])
    safe_id = re.sub(r"[^A-Za-z0-9_-]+", "_", component_name).strip("_") or "fault"
    safe_suffix = re.sub(r"[^A-Za-z0-9_-]+", "_", suffix).strip("_") or "edit"
    return f"v{index:03d}_{safe_id}_{safe_suffix}"


def _internal_channel_name(fault_label: str, kind: str) -> str:
    return f"#{fault_label}.{'I' if kind == 'current' else 'V'}"


def _reference_for_fault(existing: Any, internal: str) -> str:
    text = str(_source(existing) or "")
    quoted = text.strip().startswith(("'", '"'))
    reference = internal
    return f"'{reference}'" if quoted else reference


def _channel_reference_value(existing: Any, internal: str) -> Any:
    """Build the channel's Name/pin value using the existing wrapper style."""
    reference = f"#{internal}"
    if isinstance(existing, dict) and "source" in existing:
        result = copy.deepcopy(existing)
        result["source"] = f"'{reference}'"
        return result
    return reference


def _new_signal_wrapper(internal: str) -> dict[str, str]:
    return {"source": f"'#{internal}'", "ɵexp": ""}


def _sync_fault_channel(model: Any, model_json: dict[str, Any], fault_id: str, raw_fault: Any, fault_component: dict[str, Any], kind: str, requested: Any = None) -> dict[str, Any]:
    field = "I" if kind == "current" else "V"
    links = _fault_channel_links(model, model_json, fault_component)[field]
    internal = _internal_channel_name(fault_id, kind)
    requested_text = str(_source(requested) or "").strip().strip("'\"")
    if requested_text and requested_text not in {"#", "default", "默认", "故障电流通道", "故障电压通道"}:
        safe = re.sub(r"[^A-Za-z0-9_]+", "_", requested_text.lstrip("#")).strip("_")
        if safe:
            internal = f"{re.sub(r'[^A-Za-z0-9_]+', '_', fault_id).strip('_')}_{safe}"
    reference = _reference_for_fault(fault_component.get("args", {}).get(field), internal)
    channel_id = None
    if links:
        channel_id = links[0]["id"]
        channel_raw = _components_from_model(model).get(channel_id)
        channel_data = links[0]["component"]
        old_name = channel_data.get("args", {}).get("Name")
        _set_component_args(channel_raw, {"Name": _channel_reference_value(old_name, internal)})
        pins = getattr(channel_raw, "pins", None)
        pin_value = _channel_reference_value(channel_data.get("pins", {}).get("0"), internal)
        if isinstance(pins, dict):
            pins["0"] = pin_value
        elif isinstance(channel_raw, dict):
            channel_raw.setdefault("pins", {})["0"] = pin_value
    else:
        created = _create_channel(model, fault_id, kind, getattr(raw_fault, "canvas", None) or fault_component.get("canvas"), "故障电流通道" if kind == "current" else "故障电压通道", 2000)
        channel_id = created["id"]
        internal = created["internal"]
        reference = _reference_for_fault(fault_component.get("args", {}).get(field), internal)
    _set_component_args(raw_fault, {field: _storage_value(fault_component.get("args", {}).get(field), reference)})
    return {"field": field, "channel_id": channel_id, "reference": reference, "internal": internal, "created": not bool(links)}


def _component_id(component: Any) -> str:
    value = getattr(component, "id", None)
    if value:
        return str(value)
    data = _component_json(component)
    return str(data.get("id") or "")


def _add_output_channel(model: Any, channel_id: str, display_name: str, sample_rate: int = 2000) -> None:
    jobs = getattr(model, "jobs", None)
    if not isinstance(jobs, list):
        raise RuntimeError("CloudPSS model jobs are unavailable for output channel configuration")
    emt_job = next((job for job in jobs if isinstance(job, dict) and str(job.get("rid")) in {"function/CloudPSS/emtp", "function/CloudPSS/emtps"}), None)
    if emt_job is None:
        raise RuntimeError("No EMT job is available for output channel configuration")
    args = emt_job.setdefault("args", {})
    configured = args.setdefault("output_channels", [])
    if not isinstance(configured, list):
        raise RuntimeError("EMT output_channels is not a list")
    for entry in configured:
        if isinstance(entry, dict) and channel_id in entry.get("4", []):
            return
    # Preserve the model's existing entry schema. Unknown metadata is not
    # invented; only the confirmed output-channel fields are written.
    configured.append({"0": display_name, "1": int(sample_rate), "2": "compressed", "3": 1, "4": [channel_id]})


def _remove_output_channels(model: Any, component_ids: set[str]) -> list[dict[str, Any]]:
    removed = []
    jobs = getattr(model, "jobs", None)
    if not isinstance(jobs, list):
        return removed
    for job_index, job in enumerate(jobs):
        args = job.get("args") if isinstance(job, dict) and isinstance(job.get("args"), dict) else {}
        configured = args.get("output_channels")
        if not isinstance(configured, list):
            continue
        kept = []
        for entry_index, entry in enumerate(configured):
            selected = set(str(item) for item in entry.get("4", [])) if isinstance(entry, dict) and isinstance(entry.get("4", []), list) else set()
            if selected and selected <= component_ids:
                removed.append({"job_index": job_index, "entry_index": entry_index, "entry": copy.deepcopy(entry)})
            else:
                kept.append(entry)
        args["output_channels"] = kept
    return removed


def _create_channel(model: Any, pin_name: str, dim: int, canvas: str | None, display_name: str, sample_rate: int) -> dict[str, Any]:
    internal = pin_name
    reference = pin_name
    channel = model.addComponent(
        CHANNEL_DEFINITION,
        display_name,
        {"Dim": {"source": "3", "ɵexp": ""}, "Name": reference},
        {"0": reference},
        canvas=canvas,
    )
    channel_id = _component_id(channel)
    if not channel_id:
        raise RuntimeError("CloudPSS did not return the new channel component id")
    _add_output_channel(model, channel_id, display_name, sample_rate)
    return {"id": channel_id, "internal": internal, "reference": reference, "display_name": display_name}


def _create_fault_bundle(model: Any, request: EditRequest) -> dict[str, Any]:
    changes = _normalized_create_changes(request.changes)
    model_json = _json_safe(model.toJSON())
    target_id, target_port, target_data = _resolve_target_pin(model, model_json, request)
    existing_pin = str(_source((target_data.get("pins") or {}).get(target_port)) or "").strip()
    target_pin_name = existing_pin or f"AutoAddPin{time.strftime('%Y%m%d%H%M%S', time.localtime())}_{uuid.uuid4().hex[:8]}"
    canvas = request.options.get("canvas")
    if not canvas:
        canvas = target_data.get("canvas")
    if not canvas:
        canvases = getattr(getattr(getattr(model, "revision", None), "implements", None), "diagram", None)
        canvas_list = getattr(canvases, "canvas", None) if canvases is not None else None
        if isinstance(canvas_list, list) and canvas_list:
            canvas = canvas_list[0].get("key") if isinstance(canvas_list[0], dict) else None
    if not canvas:
        raise RuntimeError("No valid CloudPSS canvas is available for the new fault bundle")
    display_name = str(request.options.get("name") or request.target.get("name") or "").strip()
    if not display_name:
        raise ValueError("create requires a fault display name")
    # addComponent pins follow the verified CloudPSS component schema.
    gnd = model.addComponent(GND_DEFINITION, f"{display_name}_GND", {"Name": display_name + "_GND"}, {"0": "GND"}, canvas=canvas)
    gnd_id = _component_id(gnd)
    ft_value: Any = str(_source(changes["ft"]))
    if _preferred_arg_type(model, "ft") is int:
        ft_value = int(float(ft_value))
    fault_args = {
        "Name": display_name,
        "fs": _new_numeric(changes["fs"]),
        "fe": _new_numeric(changes["fe"]),
        "ft": ft_value,
        "Init": _new_numeric(changes["Init"]),
        "chg": _new_numeric(changes["chg"]),
        "I": "",
        "V": "",
    }
    # Component pin values describe logical pin names; explicit diagram edges
    # are required by the SDK to materialize the topology.
    fault = model.addComponent(FAULT_DEFINITION, display_name, fault_args, {"0": target_pin_name, "1": "GND"}, canvas=canvas)
    fault_id = _component_id(fault)
    if not fault_id:
        raise RuntimeError("CloudPSS did not return the new fault component id")
    fault_edge = _add_diagram_edge(
        model,
        source_id=target_id,
        source_port=target_port,
        target_id=fault_id,
        target_port="0",
        canvas=canvas,
    )
    ground_edge = _add_diagram_edge(
        model,
        source_id=fault_id,
        source_port="1",
        target_id=gnd_id,
        target_port="0",
        canvas=canvas,
    )
    current = _create_channel(model, f"#{display_name}.I", 3, canvas, str(request.options.get("current_output_name") or "故障电流通道"), int(request.options.get("sample_rate", 2000)))
    _set_component_args(fault, {"I": f"#{display_name}.I"})
    voltage = None
    if request.options.get("create_voltage_channel"):
        voltage = _create_channel(model, f"#{display_name}.V", 3, canvas, str(request.options.get("voltage_output_name") or "故障电压通道"), int(request.options.get("sample_rate", 2000)))
        _set_component_args(fault, {"V": f"#{display_name}.V"})
    return {
        "fault_id": fault_id,
        "gnd_id": gnd_id,
        "diagram_edges_added": [fault_edge, ground_edge],
        "target_pin_name": target_pin_name,
        "current_channel": current,
        "voltage_channel": voltage,
    }


def inspect_model_from_context(
    session_state: dict[str, Any], *, include_cells: bool = True
) -> dict[str, Any]:
    state = _state(session_state)
    model = _ensure_model(state)
    model_json = _json_safe(model.toJSON())
    if not isinstance(model_json, dict):
        raise TypeError("CloudPSS model JSON must be an object")
    faults = _faults(model, model_json)
    _attach_fault_current_unit_metadata(faults)
    state["fault_unit_metadata"] = [
        {
            "id": fault.get("id"),
            "definition": fault.get("definition"),
            "current_channel": _source((fault.get("args") or {}).get("I")),
            "current_unit": copy.deepcopy(fault.get("current_unit")),
        }
        for fault in faults
    ]
    if "v000_original" not in state["version_snapshots"]:
        _write_snapshot(state, model, "v000_original")
    for fault in faults:
        _, _, component = _resolve_fault(model, model_json, fault["id"])
        fault["channels"] = _fault_channel_links(model, model_json, component)
        fault["topology"] = _fault_ground_links(model, model_json, fault["id"])
        component_ids = {item["id"] for items in fault["channels"].values() for item in items}
        fault["output_channels"] = _output_channel_entries(model_json, component_ids)
    result = {
        "status": "ok",
        "original_rid": state.get("original_rid"),
        "current_version": state["current_version"],
        "faults": faults,
        "output_channels": _output_channel_entries(model_json),
    }
    if include_cells:
        result["cells"] = _cells(model_json)
    return result


def _preview_update(model: Any, model_json: dict[str, Any], request: EditRequest) -> dict[str, Any]:
    identifier = str(request.target.get("id") or request.target.get("name") or "").strip()
    if not identifier:
        raise ValueError("target.id or target.name is required")
    component_id, _, component = _resolve_fault(model, model_json, identifier)
    normalized = _normalize_update(request.changes)
    args = component.get("args") if isinstance(component.get("args"), dict) else {}
    fs = _number(normalized.get("fs", args.get("fs")))
    fe = _number(normalized.get("fe", args.get("fe")))
    if fs is not None and fe is not None and fs >= fe:
        raise ValueError("fs must be less than fe")
    links = _fault_channel_links(model, model_json, component)
    return {"target": {"id": component_id, "name": _display_name(component_id, component)}, "changes": {key: {"old": copy.deepcopy(args.get(key)), "new": value} for key, value in normalized.items()}, "channels": links, "notes": ["仅修改故障参数时不强制检查通道完整性。"]}


def _preview_configure_channel(model: Any, model_json: dict[str, Any], request: EditRequest) -> dict[str, Any]:
    identifier = str(request.target.get("id") or request.target.get("name") or "").strip()
    if not identifier:
        raise ValueError("target.id or target.name is required")
    component_id, _, component = _resolve_fault(model, model_json, identifier)
    kind = str(request.options.get("kind") or "current").lower()
    if kind not in {"current", "voltage"}:
        raise ValueError("channel kind must be current or voltage")
    field = "I" if kind == "current" else "V"
    internal = _internal_channel_name(component_id, kind)
    links = _fault_channel_links(model, model_json, component)
    return {"target": {"id": component_id, "name": _display_name(component_id, component)}, "kind": kind, "field": field, "old_reference": component.get("args", {}).get(field), "new_reference": f"#{internal}", "existing_channels": links[field], "create_channel": not bool(links[field]), "output_name": request.options.get("output_name") or ("故障电流通道" if kind == "current" else "故障电压通道")}


def _preview_delete(model: Any, model_json: dict[str, Any], request: EditRequest) -> dict[str, Any]:
    identifier = str(request.target.get("id") or request.target.get("name") or "").strip()
    component_id, _, component = _resolve_fault(model, model_json, identifier)
    channels = _fault_channel_links(model, model_json, component)
    topology = _fault_ground_links(model, model_json, component_id)
    channel_ids = {item["id"] for items in channels.values() for item in items}
    return {"target": {"id": component_id, "name": _display_name(component_id, component)}, "fault_edges": list(topology["fault_edges"]), "ground_links": topology["gnds"], "target_links": topology["targets"], "uncertain_links": topology["uncertain"], "channels": channels, "output_channels": _output_channel_entries(model_json, channel_ids), "requires_only_fault_authorization": bool(topology["uncertain"])}


def _preview_create(model: Any, model_json: dict[str, Any], request: EditRequest) -> dict[str, Any]:
    changes = _normalized_create_changes(request.changes)
    target_id, target_port, target = _resolve_target_pin(model, model_json, request)
    pin_name = str(_source((target.get("pins") or {}).get(target_port)) or "").strip() or "generated-at-execution"
    used: list[str] = []
    for edge_id, edge in _edges(_cells(model_json)).items():
        endpoints = _edge_endpoints(edge)
        if (target_id, target_port) in endpoints:
            used.append(edge_id)
    notes = []
    if used:
        notes.append(f"目标为可共享母线/节点端口，将在 {target_id}:{target_port} 上追加故障支路；保留现有边: {', '.join(used)}")
    return {"definition": FAULT_DEFINITION, "name": request.options.get("name") or request.target.get("name"), "target": {"component_id": target_id, "name": _display_name(target_id, target), "port": target_port, "pin_name": pin_name}, "fault_parameters": copy.deepcopy(changes), "creates": ["faultresistor_3p", "GND", "fault current channel", "EMT output channel", "2 diagram-edge"] + (["fault voltage channel", "voltage EMT output channel"] if request.options.get("create_voltage_channel") else []), "preserves": {"existing_diagram_edges": used}, "existing_faults": _faults(model, model_json), "notes": notes}


def _make_preview(state: dict[str, Any], request: EditRequest) -> dict[str, Any]:
    if request.operation not in SUPPORTED_OPERATIONS:
        raise ValueError(f"Unsupported operation: {request.operation}")
    model = _ensure_model(state)
    model_json = _json_safe(model.toJSON())
    if request.operation == "update":
        details = _preview_update(model, model_json, request)
    elif request.operation == "configure_channel":
        details = _preview_configure_channel(model, model_json, request)
    elif request.operation == "delete":
        details = _preview_delete(model, model_json, request)
    elif request.operation == "create":
        details = _preview_create(model, model_json, request)
    elif request.operation == "save_copy":
        name = str(request.options.get("name") or "").strip()
        if not name:
            raise ValueError("save_copy requires options.name")
        details = {"new_model_name": name, "original_rid": state.get("original_rid")}
    else:
        raise ValueError("query does not require confirmation")
    preview = {"preview_id": uuid.uuid4().hex, "operation": request.operation, "current_version": state["current_version"], "details": details, "requires_confirmation": True}
    # Store a plain mapping so the pending preview can be serialized by the
    # host session layer.  Older callers/tests may still provide an
    # EditRequest instance; confirmation handling below accepts both forms.
    pending_changes = copy.deepcopy(request.changes)
    if request.operation == "create":
        pending_changes = _normalized_create_changes(request.changes)
    state["pending_preview"] = {
        "preview": preview,
        "request": {
            "operation": request.operation,
            "target": copy.deepcopy(request.target),
            "changes": pending_changes,
            "confirmation": None,
            "options": copy.deepcopy(request.options),
        },
    }
    return preview


def _execute_update(state: dict[str, Any], request: EditRequest) -> dict[str, Any]:
    model = _ensure_model(state)
    model_json = _json_safe(model.toJSON())
    component_id, raw, component = _resolve_fault(model, model_json, str(request.target.get("id") or request.target.get("name")))
    normalized = _normalize_update(request.changes)
    old_args = component.get("args", {}) if isinstance(component.get("args"), dict) else {}
    stored = {key: _storage_value(old_args.get(key), value) for key, value in normalized.items() if key not in {"I", "V"}}
    _set_component_args(raw, stored)
    channels = {}
    for field, kind in (("I", "current"), ("V", "voltage")):
        if field in normalized:
            channels[field] = _sync_fault_channel(model, _json_safe(model.toJSON()), component_id, raw, _component_json(raw), kind, normalized[field])
    for field in ("I", "V"):
        if field in normalized:
            stored[field] = _component_json(raw).get("args", {}).get(field)
    return {"component_id": component_id, "component_name": _display_name(component_id, _component_json(raw)), "changed": stored, "channels": channels}


def _execute_configure_channel(state: dict[str, Any], request: EditRequest) -> dict[str, Any]:
    model = _ensure_model(state)
    model_json = _json_safe(model.toJSON())
    component_id, raw, component = _resolve_fault(model, model_json, str(request.target.get("id") or request.target.get("name")))
    kind = str(request.options.get("kind") or "current").lower()
    field = "I" if kind == "current" else "V"
    result = _sync_fault_channel(model, model_json, component_id, raw, component, kind, request.options.get("channel_name"))
    return {"component_id": component_id, "component_name": _display_name(component_id, component), **result}


def _execute_delete(state: dict[str, Any], request: EditRequest) -> dict[str, Any]:
    model = _ensure_model(state)
    model_json = _json_safe(model.toJSON())
    component_id, _, component = _resolve_fault(model, model_json, str(request.target.get("id") or request.target.get("name")))
    topology = _fault_ground_links(model, model_json, component_id)
    only_fault = bool(request.options.get("only_fault"))
    if topology["uncertain"] and not only_fault:
        raise RuntimeError("Associated topology is uncertain; require only_fault authorization")
    channels = _fault_channel_links(model, model_json, component)
    component_ids = {item["id"] for values in channels.values() for item in values}
    edge_ids = set(topology["fault_edges"])
    removed_outputs = _remove_output_channels(model, component_ids)
    removed_edges = _remove_diagram_edges(model, edge_ids) if not only_fault else []
    remover = getattr(model, "removeComponent", None)
    if not callable(remover):
        raise RuntimeError("CloudPSS Model.removeComponent is unavailable")
    # Remove edges first: the SDK otherwise rewrites endpoints to component
    # coordinates when a component is removed, leaving stale topology cells.
    remover(component_id)
    removed = {"fault": component_id, "component_name": _display_name(component_id, component), "edges": removed_edges, "channels": [], "gnds": [], "output_channels": removed_outputs}
    if not only_fault:
        for channel_id in sorted(component_ids):
            remover(channel_id)
            removed["channels"].append(channel_id)
        for ground in topology["gnds"]:
            ground_id = ground.get("component_id")
            if ground_id:
                remover(ground_id)
                removed["gnds"].append(ground_id)
    return removed


def _execute_save_copy(state: dict[str, Any], request: EditRequest) -> dict[str, Any]:
    model = _ensure_model(state)
    key = str(request.options.get("name") or "").strip()
    original_key = str(state.get("original_rid") or "").rsplit("/", 1)[-1]
    if not key or key == original_key:
        raise ValueError("A new model name different from the original RID is required")
    try:
        from cloudpss import Model
        copy_model = Model(copy.deepcopy(model.toJSON()))
    except ImportError as exc:
        raise RuntimeError("CloudPSS dependency is unavailable") from exc
    result = copy_model.save(key)
    new_rid = str(getattr(copy_model, "rid", "") or "").strip()
    if not new_rid or new_rid == state.get("original_rid"):
        raise RuntimeError("CloudPSS save did not produce a new model RID")
    state["saved_copy_rid"] = new_rid
    return {"new_rid": new_rid, "save_result": _json_safe(result), "memory_version": state["current_version"]}


def edit_model_from_context(request: EditRequest | dict[str, Any], session_state: dict[str, Any]) -> dict[str, Any]:
    state = _state(session_state)
    if isinstance(request, dict):
        request = EditRequest(**request)
    if request.operation == "query":
        return inspect_model_from_context(
            state, include_cells=bool(request.options.get("include_cells", False))
        )
    if request.operation == "verify_emt":
        return verify_emt_from_context(state)
    if request.confirmation in {"cancel", "取消"}:
        state["pending_preview"] = None
        return {"status": "cancelled", "current_version": state["current_version"]}
    if request.confirmation not in {"execute", "确认", "确认执行"}:
        return {"status": "preview_required", "preview": _make_preview(state, request), "current_version": state["current_version"]}
    pending = state.get("pending_preview")
    if not pending:
        return {"status": "confirmation_required", "message": "当前没有待确认的变更预览。"}
    pending_request = pending.get("request") if isinstance(pending, dict) else None
    if isinstance(pending_request, EditRequest):
        request = pending_request
    elif isinstance(pending_request, dict):
        request = EditRequest(**pending_request)
    else:
        raise RuntimeError("Pending preview request is invalid")
    if request.operation == "update":
        changed = _execute_update(state, request)
        suffix = "_".join(request.changes) or "edit"
    elif request.operation == "configure_channel":
        changed = _execute_configure_channel(state, request)
        suffix = f"{changed['field']}_channel"
    elif request.operation == "create":
        changed = _create_fault_bundle(_ensure_model(state), request)
        suffix = "created"
    elif request.operation == "delete":
        changed = _execute_delete(state, request)
        suffix = "deleted"
    elif request.operation == "save_copy":
        changed = _execute_save_copy(state, request)
        state["pending_preview"] = None
        return {"status": "saved", "current_version": state["current_version"], **changed}
    else:
        raise ValueError(f"Unsupported confirmed operation: {request.operation}")
    target_id = str(changed.get("component_id") or changed.get("fault_id") or changed.get("fault") or "model")
    target_name = str(changed.get("component_name") or request.options.get("name") or request.target.get("name") or target_id)
    version = _new_version(state, target_name, suffix)
    snapshot_path = _write_snapshot(state, _ensure_model(state), version)
    state["current_version"] = version
    state["pending_preview"] = None
    return {"status": "changed", "operation": request.operation, "changed": changed, "current_version": version, "snapshot_path": snapshot_path}


def verify_emt_from_context(session_state: dict[str, Any], *, poll_seconds: float = 1.0, timeout_seconds: float = 600.0) -> dict[str, Any]:
    state = _state(session_state)
    model = _ensure_model(state)
    version = state["current_version"]
    try:
        job = model.runEMT()
        task_id = str(getattr(job, "id", "") or "").strip()
        if not task_id:
            raise RuntimeError("CloudPSS EMT job did not return an id")
        deadline = time.monotonic() + timeout_seconds
        status = job.status()
        while status == 0:
            if time.monotonic() >= deadline:
                raise TimeoutError("CloudPSS EMT verification timed out")
            time.sleep(poll_seconds)
            status = job.status()
        if status != 1:
            raise RuntimeError(f"CloudPSS EMT verification failed with status {status}")
        state["last_successful_emt_version"] = version
        return {"status": "verified", "version": version, "task_id": task_id}
    except Exception as exc:
        failure = {"version": version, "error": str(exc)}
        state["recent_emt_failures"] = (state["recent_emt_failures"] + [failure])[-3:]
        failure_path = _write_snapshot(state, model, version, "emt_failure")
        rollback_version = state.get("last_successful_emt_version") or "v000_original"
        _restore_version(state, rollback_version)
        return {"status": "rolled_back", "failed_version": version, "error": failure, "failure_snapshot": failure_path, "rollback_version": rollback_version}
