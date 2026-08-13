from __future__ import annotations

import csv
import json
import math
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from cloudpss import Model, setToken


DEFAULT_MODEL_RID = "model/CloudPSS/IEEE3"
DEFAULT_MODEL_FETCH_TIMEOUT = 120.0
DEFAULT_RESULTS_DIR = Path("results") / "short_circuit_analysis_result"


def _default_output_dir() -> Path:
    return Path.cwd() / DEFAULT_RESULTS_DIR


def _safe_path_part(value: str, fallback: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "")).strip("._")
    return text or fallback


def _task_id_from_job(job: Any) -> str:
    task_id = str(getattr(job, "id", "") or "").strip()
    if not task_id:
        raise RuntimeError("CloudPSS EMT job did not return an id")
    return task_id


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_channel_filename(channel_name: str) -> str:
    """Return a cross-platform filename while preserving the channel in the CSV header."""
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(channel_name)).strip()
    filename = filename.rstrip(". ") or "channel"
    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
    if filename.upper().split(".", 1)[0] in reserved:
        filename = f"channel_{filename}"
    return f"{filename}.csv"


def _emit_stage(stage: str) -> None:
    print(f"SCA_STAGE={stage}", flush=True)


def _configure_cloudpss_auth() -> None:
    """Map host-provided credentials to the variable consumed by cloudpss SDK."""
    token = next(
        (
            value.strip()
            for name in (
                "CLOUDPSS_TOKEN",
                "CLOUDPSS_LOGIN_TOKEN",
                "SIMSTUDIO_TOKEN",
            )
            if (value := os.environ.get(name)) and value.strip()
        ),
        None,
    )
    if token is None:
        raise RuntimeError("CloudPSS authentication is not configured by the host")
    setToken(token)


def load_model_from_source(
    source: str,
    *,
    fetch_timeout: float = DEFAULT_MODEL_FETCH_TIMEOUT,
):
    candidate = Path(source).expanduser()
    if candidate.exists():
        return Model.load(str(candidate))
    # The SDK otherwise waits indefinitely on a stalled GraphQL request.
    return Model.fetch(source, timeout=(10.0, float(fetch_timeout)))


def _json_safe(value: Any) -> Any:
    """Convert SDK objects into JSON-safe values without exposing credentials."""
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


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _find_voltage_candidates(value: Any, path: str = "") -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if isinstance(value, dict):
        lowered = {str(key).lower().replace("_", ""): key for key in value}
        unit = str(value.get("unit", value.get("units", ""))).lower()
        for normalized in (
            "basevoltagekv",
            "nominalvoltagekv",
            "ratedvoltagekv",
            "voltagebasekv",
        ):
            if normalized in lowered:
                number = _number(value[lowered[normalized]])
                if number is not None and number > 0:
                    candidates.append({"path": f"{path}.{lowered[normalized]}", "value_kv": number})
        if unit in {"kv", "kilovolt", "kilovolts"}:
            for key in ("value", "default", "val"):
                number = _number(value.get(key))
                if number is not None and number > 0:
                    candidates.append({"path": f"{path}.{key}", "value_kv": number})
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            candidates.extend(_find_voltage_candidates(item, child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            candidates.extend(_find_voltage_candidates(item, f"{path}[{index}]"))
    return candidates


def _source_number(value: Any) -> float | None:
    if isinstance(value, dict) and "source" in value:
        return _number(value["source"])
    return _number(value)


def _source_text(value: Any) -> str | None:
    if isinstance(value, dict) and "source" in value:
        value = value["source"]
    if value is None:
        return None
    text = str(value).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1]
    return text or None


def _diagram_variables(model_json: dict[str, Any]) -> dict[str, Any]:
    revision = model_json.get("revision", {})
    implements = revision.get("implements", {}) if isinstance(revision, dict) else {}
    diagram = implements.get("diagram", {}) if isinstance(implements, dict) else {}
    variables = diagram.get("variables", []) if isinstance(diagram, dict) else []
    return {
        item.get("key"): item.get("value")
        for item in variables
        if isinstance(item, dict) and item.get("key")
    }


def _fault_context(component_json: dict[str, Any]) -> dict[str, Any]:
    faults: list[dict[str, Any]] = []
    for component_id, component in component_json.items():
        if not isinstance(component, dict):
            continue
        definition = str(component.get("definition") or "")
        if "faultresistor" not in definition.lower():
            continue
        args = component.get("args") if isinstance(component.get("args"), dict) else {}
        props = component.get("props") if isinstance(component.get("props"), dict) else {}
        if props.get("enabled") is False:
            continue
        name = args.get("Name") or component.get("label") or component_id
        current_channel = _source_text(args.get("I"))
        voltage_channel = _source_text(args.get("V"))
        faults.append(
            {
                "id": component_id,
                "name": name,
                "definition": definition,
                "current_channel": current_channel,
                "voltage_channel": voltage_channel,
                "start_time_s": _source_number(args.get("fs")),
                # CloudPSS uses `fe` for fault end time; `ft` is the fault type code.
                "end_time_s": _source_number(args.get("fe")),
                "fault_type": "three_phase_fault" if "_3p" in definition else "fault",
            }
        )
    return {"count": len(faults), "active": faults}


def _resolve_target_fault(
    faults: dict[str, Any], target_fault_id: str | None = None
) -> dict[str, Any] | None:
    """Select one analysis target while retaining all faults in the EMT model."""
    active = [fault for fault in faults.get("active", []) if isinstance(fault, dict)]
    if not active:
        return None
    if len(active) == 1 and not target_fault_id:
        return active[0]
    if target_fault_id:
        wanted = str(target_fault_id).strip()
        matches = [
            fault
            for fault in active
            if str(fault.get("id") or "") == wanted
            or str(fault.get("name") or "") == wanted
        ]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise ValueError(
                f"No active fault matches analysis.target_fault_id {wanted!r}."
            )
        raise ValueError(
            f"analysis.target_fault_id {wanted!r} matches more than one active fault."
        )
    if len(active) > 1:
        choices = ", ".join(
            f"{fault.get('id')} ({fault.get('name')})" for fault in active
        )
        raise ValueError(
            "Multiple active faults were found. Specify analysis.target_fault_id "
            "using one fault component ID or name; other active faults remain in the EMT "
            f"scenario. Available faults: {choices}."
        )
    return active[0]


def _diagram_cells(model_json: dict[str, Any]) -> dict[str, Any]:
    revision = model_json.get("revision", {})
    implements = revision.get("implements", {}) if isinstance(revision, dict) else {}
    diagram = implements.get("diagram", {}) if isinstance(implements, dict) else {}
    cells = diagram.get("cells", {}) if isinstance(diagram, dict) else {}
    if isinstance(cells, dict):
        return cells
    if isinstance(cells, list):
        return {
            str(cell.get("id")): cell
            for cell in cells
            if isinstance(cell, dict) and cell.get("id")
        }
    return {}


def _is_bus_component(component: Any) -> bool:
    if not isinstance(component, dict):
        return False
    definition = str(component.get("definition") or "").lower()
    return "_newbus" in definition or definition.endswith("/bus")


def _component_name(component_id: str, component: Any) -> str:
    if isinstance(component, dict):
        args = component.get("args")
        if isinstance(args, dict):
            name = _source_text(args.get("Name"))
            if name:
                return name
        name = _source_text(component.get("label"))
        if name:
            return name
    return component_id


def _fault_bus_from_topology(
    model_json: dict[str, Any],
    component_json: dict[str, Any],
    faults: dict[str, Any] | None,
) -> dict[str, Any]:
    """Resolve the bus attached to an active fault from diagram connectivity."""
    cells = _diagram_cells(model_json)
    if isinstance(faults, dict) and "active" in faults:
        active_faults = faults.get("active", [])
    elif isinstance(faults, dict):
        active_faults = [faults]
    else:
        active_faults = []
    fault_ids = {str(fault.get("id")) for fault in active_faults if fault.get("id")}
    if not fault_ids:
        return {"bus": None, "component_id": None, "edge_id": None}

    bus_candidates: list[dict[str, Any]] = []
    for edge_id, edge in cells.items():
        if not isinstance(edge, dict) or edge.get("shape") != "diagram-edge":
            continue
        endpoints = (edge.get("source", {}), edge.get("target", {}))
        endpoint_ids = [
            str(endpoint.get("cell"))
            for endpoint in endpoints
            if isinstance(endpoint, dict) and endpoint.get("cell")
        ]
        fault_endpoint = next((item for item in endpoint_ids if item in fault_ids), None)
        if fault_endpoint is None:
            continue
        other_ids = [item for item in endpoint_ids if item != fault_endpoint]
        for other_id in other_ids:
            component = component_json.get(other_id) or cells.get(other_id)
            if _is_bus_component(component):
                bus_candidates.append(
                    {
                        "bus": _component_name(other_id, component),
                        "component_id": other_id,
                        "edge_id": str(edge_id),
                    }
                )

    unique = {
        (item["bus"], item["component_id"]): item
        for item in bus_candidates
        if item.get("bus")
    }
    if len(unique) == 1:
        return next(iter(unique.values()))
    return {"bus": None, "component_id": None, "edge_id": None}


def _fault_bus_name(faults: dict[str, Any] | None) -> str | None:
    active_faults = (
        faults.get("active", [])
        if isinstance(faults, dict) and "active" in faults
        else [faults] if isinstance(faults, dict) else []
    )
    for fault in active_faults:
        name = str(fault.get("name") or "")
        match = re.search(r"(?:fault|故障)[_ -]?(bus\d+|母线\d+)", name, re.IGNORECASE)
        if match:
            return match.group(1).replace("母线", "Bus").replace("bus", "Bus")
        channel = str(fault.get("current_channel") or "")
        match = re.search(r"(?:fault_)?(bus\d+)", channel, re.IGNORECASE)
        if match:
            return match.group(1).replace("bus", "Bus")
    return None


def _resolve_base_voltage(
    model_json: dict[str, Any],
    component_json: dict[str, Any],
    faults: dict[str, Any],
    target_fault: dict[str, Any] | None = None,
) -> dict[str, Any]:
    variables = _diagram_variables(model_json)
    target_fault = target_fault or _resolve_target_fault(faults)
    topology_fault = _fault_bus_from_topology(model_json, component_json, target_fault)
    fault_bus = topology_fault["bus"] or _fault_bus_name(target_fault)
    candidates: list[dict[str, Any]] = []
    fault_bus_candidate: dict[str, Any] | None = None
    bus_current_channel: str | None = None
    if fault_bus:
        # Prefer the VBase declared by the bus that is actually connected to
        # the active fault.  Diagram variables are a useful fallback, but a
        # model may only expose the bus base voltage on the bus component.
        fault_bus_component_id = topology_fault.get("component_id")
        fault_bus_component = (
            component_json.get(fault_bus_component_id)
            if fault_bus_component_id
            else None
        )
        if fault_bus_component is None and fault_bus_component_id:
            fault_bus_component = _diagram_cells(model_json).get(fault_bus_component_id)
        component_args = (
            fault_bus_component.get("args")
            if isinstance(fault_bus_component, dict)
            and isinstance(fault_bus_component.get("args"), dict)
            else {}
        )
        bus_current_channel = _source_text(component_args.get("I"))
        component_value = _source_number(component_args.get("VBase"))
        if component_value is not None and component_value > 0:
            fault_bus_candidate = {
                "path": f"components.{fault_bus_component_id}.args.VBase",
                "value_kv": component_value,
            }
            candidates.append(fault_bus_candidate)

        match = re.fullmatch(r"Bus(\d+)", fault_bus, re.IGNORECASE)
        key = f"Bus_{match.group(1)}_Vbase" if match else f"{fault_bus}_Vbase"
        value = _source_number(variables.get(key))
        if value is not None and value > 0 and fault_bus_candidate is None:
            fault_bus_candidate = {
                "path": f"revision.implements.diagram.variables.{key}",
                "value_kv": value,
            }
            candidates.append(fault_bus_candidate)
    for key, value in variables.items():
        if str(key).endswith("_Vbase"):
            number = _source_number(value)
            if number is not None and number > 0:
                candidates.append({"path": f"revision.implements.diagram.variables.{key}", "value_kv": number})
    candidates.extend(_find_voltage_candidates(model_json))
    candidates.extend(_find_voltage_candidates(component_json, "components"))
    # Do not select an arbitrary voltage level from a multi-voltage model.
    if fault_bus_candidate is not None:
        chosen = fault_bus_candidate
    else:
        distinct_values = {candidate["value_kv"] for candidate in candidates}
        chosen = candidates[0] if len(distinct_values) == 1 and candidates else None
    return {
        "value_kv": chosen["value_kv"] if chosen else None,
        "source": chosen["path"] if chosen else None,
        "fault_bus": fault_bus,
        "fault_bus_component_id": topology_fault["component_id"],
        "fault_bus_edge_id": topology_fault["edge_id"],
        "bus_current_channel": bus_current_channel,
        "ambiguous": bool(candidates) and chosen is None,
        "candidates": candidates,
    }


def _declared_current_channel_sources(
    faults: dict[str, Any],
    resolution: dict[str, Any],
    target_fault: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return only current channels explicitly declared by the fault or bus."""
    sources: list[dict[str, Any]] = []
    active_faults = [target_fault] if target_fault else faults.get("active", [])
    for fault in active_faults:
        channel = _source_text(fault.get("current_channel"))
        if channel:
            sources.append(
                {
                    "kind": "fault_element",
                    "component_id": fault.get("id"),
                    "channel": channel,
                    "source": f"components.{fault.get('id')}.args.I",
                }
            )
    bus_channel = _source_text(resolution.get("bus_current_channel"))
    bus_component_id = resolution.get("fault_bus_component_id")
    if bus_channel and bus_component_id:
        sources.append(
            {
                "kind": "fault_bus",
                "component_id": bus_component_id,
                "channel": bus_channel,
                "source": f"components.{bus_component_id}.args.I",
            }
        )
    return sources


def inspect_model(
    model,
    *,
    target_fault_id: str | None = None,
    max_component_summary: int = 200,
) -> dict[str, Any]:
    """Read the model JSON and diagram components into a safe analysis snapshot."""
    model_json = _json_safe(model.toJSON())
    components = model.getAllComponents()
    component_json = {
        str(component_id): _json_safe(component.toJSON())
        for component_id, component in components.items()
    }
    revision = model_json.get("revision", {}) if isinstance(model_json, dict) else {}
    faults = _fault_context(component_json)
    target_fault = _resolve_target_fault(faults, target_fault_id)
    voltage_resolution = _resolve_base_voltage(
        model_json, component_json, faults, target_fault
    )
    declared_current_sources = _declared_current_channel_sources(
        faults, voltage_resolution, target_fault
    )
    return {
        "model": {
            "name": getattr(model, "name", ""),
            "rid": getattr(model, "rid", ""),
        },
        "revision": {
            "version": revision.get("version") if isinstance(revision, dict) else None,
            "parameters": revision.get("parameters", []) if isinstance(revision, dict) else [],
        },
        "context": _json_safe(getattr(model, "context", {})),
        "jobs": _json_safe(getattr(model, "jobs", [])),
        "configs": _json_safe(getattr(model, "configs", [])),
        "component_count": len(component_json),
        "component_ids": list(component_json)[:max_component_summary],
        "component_summary": [
            {
                "id": component_id,
                "definition": data.get("definition") if isinstance(data, dict) else None,
                "label": data.get("label") if isinstance(data, dict) else None,
                "args": data.get("args") if isinstance(data, dict) else None,
            }
            for component_id, data in list(component_json.items())[:max_component_summary]
        ],
        "voltage_candidates": voltage_resolution["candidates"],
        "voltage_resolution": voltage_resolution,
        "declared_current_sources": declared_current_sources,
        "faults": faults,
        "target_fault": target_fault,
        "model_json": model_json,
        "components": component_json,
        "provenance": {
            "model": "CloudPSS SDK Model.toJSON()",
            "components": "CloudPSS SDK Model.getAllComponents()",
        },
    }


def _default_analysis_config(snapshot: dict[str, Any]) -> dict[str, Any]:
    resolution = snapshot.get("voltage_resolution", {})
    base_voltage = resolution.get("value_kv")
    if base_voltage is None and resolution.get("ambiguous"):
        raise ValueError(
            "The model has multiple possible base voltages and none is tied to the active fault; "
            "provide analysis.base_voltage_kv explicitly."
        )
    if base_voltage is None:
        raise ValueError(
            "No model-derived base voltage is available for the active fault; "
            "the active fault bus must expose VBase."
        )
    simulation_window = _simulation_window(snapshot)
    target_fault = snapshot.get("target_fault") or _resolve_target_fault(
        snapshot.get("faults", {})
    ) or {}
    fault_window = _active_fault_window(snapshot, target_fault)
    if fault_window is None:
        raise ValueError(
            "No valid fault start/end time is available for the active fault; "
            "the fault component must define fs and fe."
        )
    active_fault = (
        target_fault
        if _number(target_fault.get("start_time_s")) is not None
        and _number(target_fault.get("end_time_s")) is not None
        else None
    )
    analysis: dict[str, Any] = {
        "base_voltage_kv": base_voltage,
        "base_voltage_source": resolution.get("source"),
        "fault_bus": resolution.get("fault_bus"),
        "target_fault_id": target_fault.get("id"),
        "fault_type": active_fault.get("fault_type") if active_fault else None,
        "declared_current_sources": snapshot.get("declared_current_sources", []),
        "fault_current_channel": target_fault.get("current_channel"),
        "min_samples": 128,
        "steady_fault_trim_fraction": 0.2,
    }
    if simulation_window:
        analysis["analysis_window"] = simulation_window
    if fault_window:
        analysis["fault_window"] = fault_window
        if simulation_window:
            analysis["prefault_window"] = [simulation_window[0], fault_window[0]]
            analysis["postfault_window"] = [fault_window[1], simulation_window[1]]
    return {
        "analysis": analysis,
        "channels": {"auto_max_channels": 3},
        "thevenin": {"enabled": True},
    }


def _merge_analysis_config(
    config: dict[str, Any] | None,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Merge user options while protecting model-derived electrical parameters."""
    resolution = snapshot.get("voltage_resolution", {})
    model_voltage = _optional_float(resolution.get("value_kv"))
    defaults = _default_analysis_config(snapshot)
    if config is None:
        if model_voltage is None:
            _default_analysis_config(snapshot)
        return defaults
    if config.get("output"):
        raise ValueError(
            "config.output is not supported; PromptToApp retrieves CloudPSS results by task_id"
        )

    supplied_analysis = config.get("analysis", {})
    supplied_channels = config.get("channels", {})
    supplied_thevenin = config.get("thevenin", {})
    if not all(
        isinstance(value, dict)
        for value in (supplied_analysis, supplied_channels, supplied_thevenin)
    ):
        raise ValueError("analysis, channels, and thevenin options must be objects")
    if supplied_channels.get("current"):
        raise ValueError(
            "channels.current is not accepted as a substitute for model-declared "
            "fault or fault-bus current channels. Configure the CloudPSS model first."
        )
    if supplied_channels.get("voltage") or supplied_channels.get("generic"):
        raise ValueError(
            "channels.voltage and channels.generic cannot be analyzed as current; "
            "use channels.equivalent_pairs for power/voltage estimation."
        )

    merged = {
        "analysis": {**defaults.get("analysis", {}), **supplied_analysis},
        "channels": {**defaults.get("channels", {}), **supplied_channels},
        "thevenin": {**defaults.get("thevenin", {}), **supplied_thevenin},
    }
    if "fault_window" in supplied_analysis and "steady_fault_window" not in supplied_analysis:
        merged["analysis"]["steady_fault_window"] = list(
            _steady_fault_window(
                supplied_analysis["fault_window"],
                float(merged["analysis"].get("steady_fault_trim_fraction", 0.2)),
            )
        )
    merged["analysis"]["_steady_fault_window_explicit"] = (
        supplied_analysis.get("steady_fault_window") is not None
    )
    if snapshot.get("target_fault"):
        merged["analysis"]["target_fault_id"] = snapshot["target_fault"].get("id")
    supplied_voltage = _optional_float(
        supplied_analysis.get("base_voltage_kv", supplied_analysis.get("base_voltage"))
    )
    if model_voltage is not None:
        if supplied_voltage is not None and not math.isclose(
            supplied_voltage, model_voltage, rel_tol=1e-9, abs_tol=1e-9
        ):
            merged["analysis"]["requested_base_voltage_kv"] = supplied_voltage
            merged["analysis"]["base_voltage_conflict"] = {
                "requested_kv": supplied_voltage,
                "model_kv": model_voltage,
                "model_source": resolution.get("source"),
                "resolution": "model_value_used",
            }
        merged["analysis"]["base_voltage_kv"] = model_voltage
        merged["analysis"]["base_voltage_source"] = resolution.get("source")
        merged["analysis"]["fault_bus"] = resolution.get("fault_bus")
    elif supplied_voltage is None:
        raise ValueError(
            "No model-derived base voltage is available for the active fault; "
            "the active fault bus must expose VBase."
        )
    return merged


def _validate_analysis_channel_prerequisites(
    snapshot: dict[str, Any],
    resolved_config: dict[str, Any],
) -> None:
    """Require model-declared current channels unless equivalent mode is explicit."""
    declared_sources = snapshot.get("declared_current_sources", [])
    equivalent_pairs = resolved_config.get("channels", {}).get("equivalent_pairs", [])
    if declared_sources or equivalent_pairs:
        return
    fault_bus = snapshot.get("voltage_resolution", {}).get("fault_bus")
    raise RuntimeError(
        "The active fault element and fault bus have no declared current channel. "
        f"Fault bus {fault_bus!r}: configure the CloudPSS fault-element or fault-bus "
        "current channel, then decide whether to retry the analysis."
    )


def _simulation_window(snapshot: dict[str, Any]) -> list[float] | None:
    for job in snapshot.get("jobs", []):
        if not isinstance(job, dict) or "emt" not in str(job.get("rid", "")).lower():
            continue
        args = job.get("args", {})
        if not isinstance(args, dict):
            continue
        start = _number(args.get("begin_time"))
        end = _number(args.get("end_time"))
        if start is not None and end is not None and end > start:
            return [start, end]
    return None


def _active_fault_window(
    snapshot: dict[str, Any], target_fault: dict[str, Any] | None = None
) -> list[float] | None:
    active_faults = (
        [target_fault]
        if target_fault
        else snapshot.get("faults", {}).get("active", [])
    )
    for fault in active_faults:
        start = _number(fault.get("start_time_s"))
        end = _number(fault.get("end_time_s"))
        if start is not None and end is not None and end > start:
            return [start, end]
    return None


def _collect_all_waveform_traces(result) -> list[dict[str, Any]]:
    """Read every raw channel returned by CloudPSS without applying analysis scaling."""
    traces: list[dict[str, Any]] = []
    for plot_index, plot in enumerate(result.getPlots()):
        plot_name = _plot_name(plot, plot_index)
        for channel_name in result.getPlotChannelNames(plot_index):
            data = result.getPlotChannelData(plot_index, channel_name)
            if not data:
                continue
            x_values = [float(value) for value in data.get("x", [])]
            y_values = [float(value) for value in data.get("y", [])]
            if len(x_values) != len(y_values):
                raise ValueError(
                    f"Waveform channel has mismatched time/value lengths: {channel_name}"
                )
            if not x_values:
                continue
            traces.append(
                {
                    "channel": str(channel_name),
                    "plot_index": plot_index,
                    "plot": plot_name,
                    "source": "CloudPSS EMTResult.getPlotChannelData",
                    "trace": {"x": x_values, "y": y_values},
                }
            )
    return traces


def _analysis_waveform_traces(result, result_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Rebuild the exact current traces used by deterministic analysis for CSV export."""
    analysis_config = result_data["analysis"]
    traces: list[dict[str, Any]] = []
    for row in result_data["channels"]:
        if row["kind"] == "current":
            _, _, trace = _find_trace(result, row["channel"])
            traces.append(
                {
                    "channel": row["channel"],
                    "source": "CloudPSS EMTResult.getPlotChannelData",
                    "trace": {
                        "x": list(trace["x"]),
                        "y": [
                            value * analysis_config["current_scale"]
                            for value in trace["y"]
                        ],
                    },
                }
            )
            continue

        source_channels = row["source_channels"]
        _, _, power_trace = _find_trace(result, source_channels["power"])
        _, _, voltage_trace = _find_trace(result, source_channels["voltage"])
        equivalent_trace = _equivalent_current_trace(
            power_trace,
            voltage_trace,
            power_scale_mw=analysis_config["power_scale_mw"],
            voltage_scale_pu=analysis_config["voltage_scale_pu"],
            base_voltage_kv=analysis_config["base_voltage_kv"],
            nominal_voltage_pu=analysis_config["nominal_voltage_pu"],
        )
        traces.append(
            {
                "channel": row["channel"],
                "source": (
                    "derived from CloudPSS EMTResult.getPlotChannelData "
                    "(power/voltage equivalent current)"
                ),
                "trace": equivalent_trace,
            }
        )
    return traces


def _write_waveform_csv(path: Path, traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Write selected analysis channels to one CSV using their shared time axis."""
    if not traces:
        raise ValueError("No waveform traces are available for CSV export")
    channel_names = [str(item["channel"]) for item in traces]
    if len(set(channel_names)) != len(channel_names):
        raise ValueError("Waveform channel names must be unique")
    time_values = [float(value) for value in traces[0]["trace"]["x"]]
    if len(time_values) < 2:
        raise ValueError("Waveform must contain at least two samples")
    _validate_time_axis(time_values)

    value_columns: list[list[float]] = []
    for item in traces:
        x_values = [float(value) for value in item["trace"]["x"]]
        y_values = [float(value) for value in item["trace"]["y"]]
        if len(y_values) != len(time_values) or any(
            not math.isfinite(value) for value in y_values
        ):
            raise ValueError(f"Invalid waveform values for channel: {item['channel']}")
        if len(x_values) != len(time_values) or any(
            not math.isclose(left, right, rel_tol=0.0, abs_tol=1e-9)
            for left, right in zip(x_values, time_values)
        ):
            raise ValueError(
                "Selected waveform channels do not share the same time axis; "
                "refusing to interpolate silently"
            )
        value_columns.append(y_values)

    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["time", *channel_names])
        for index, time_value in enumerate(time_values):
            writer.writerow([time_value, *(values[index] for values in value_columns)])
    return {
        "path": path.name,
        "channels": channel_names,
        "sample_count": len(time_values),
        "time_start_s": time_values[0],
        "time_end_s": time_values[-1],
    }


def _write_raw_channel_csvs(
    output_dir: Path,
    directory_name: str,
    traces: list[dict[str, Any]],
) -> dict[str, Any]:
    """Write one unscaled CSV for every channel in the CloudPSS EMT result."""
    raw_dir = output_dir / directory_name
    raw_dir.mkdir(parents=True, exist_ok=True)
    used_names: set[str] = set()
    channel_files: list[dict[str, Any]] = []
    for item in traces:
        channel_name = str(item["channel"])
        filename = _safe_channel_filename(channel_name)
        if filename in used_names:
            stem, suffix = Path(filename).stem, Path(filename).suffix
            filename = f"{stem}__plot_{int(item['plot_index'])}{suffix}"
            duplicate_index = 2
            while filename in used_names:
                filename = (
                    f"{stem}__plot_{int(item['plot_index'])}_{duplicate_index}{suffix}"
                )
                duplicate_index += 1
        used_names.add(filename)

        time_values = [float(value) for value in item["trace"]["x"]]
        value_values = [float(value) for value in item["trace"]["y"]]
        if len(time_values) != len(value_values):
            raise ValueError(
                f"Waveform channel has mismatched time/value lengths: {channel_name}"
            )
        path = raw_dir / filename
        with path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(["time", channel_name])
            writer.writerows(zip(time_values, value_values))
        channel_files.append(
            {
                "channel": channel_name,
                "plot_index": int(item["plot_index"]),
                "plot": str(item["plot"]),
                "sample_count": len(time_values),
                "csv_path": f"{directory_name}/{filename}",
            }
        )
    return {
        "directory": directory_name,
        "channel_count": len(channel_files),
        "channels": channel_files,
    }


def analyze_model_from_source(
    source: str,
    config: dict[str, Any] | None = None,
    *,
    output_dir: str | Path | None = None,
    timeout: int = 300,
    fetch_timeout: float = DEFAULT_MODEL_FETCH_TIMEOUT,
) -> dict[str, Any]:
    """Run one analysis and return only its CloudPSS EMT task ID."""
    if not isinstance(source, str) or not source.strip():
        raise ValueError("A CloudPSS model RID or local model path is required")
    target_dir = Path(output_dir) if output_dir is not None else _default_output_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    stage = "model_loading"
    task_id: str | None = None
    try:
        _configure_cloudpss_auth()
        model = load_model_from_source(source, fetch_timeout=fetch_timeout)
        _emit_stage(stage)

        stage = "model_parameters"
        requested_analysis = config.get("analysis", {}) if isinstance(config, dict) else {}
        target_fault_id = (
            requested_analysis.get("target_fault_id")
            if isinstance(requested_analysis, dict)
            else None
        )
        snapshot = inspect_model(model, target_fault_id=target_fault_id)
        _emit_stage(stage)

        if not snapshot.get("faults", {}).get("active"):
            raise RuntimeError(
                "No active fault scenario was found in the model. Configure a fault in CloudPSS "
                "before requesting short-circuit analysis."
            )

        # Only advance the checkpoint after configuration resolution succeeds.
        resolved_config = _merge_analysis_config(config, snapshot)
        _validate_analysis_channel_prerequisites(snapshot, resolved_config)
        stage = "emt_analysis"
        job = run_emt(model, timeout=timeout)
        task_id = _task_id_from_job(job)
        result = run_short_circuit_analysis(
            model,
            config=resolved_config,
            job=job,
            timeout=timeout,
        )
        result["task_id"] = task_id
        result["provenance"] = {
            "model_parameters": "CloudPSS SDK Model.toJSON and Model.getAllComponents",
            "waveform": "CloudPSS SDK EMTResult.getPlotChannelData",
            "metrics": "short-circuit-analysis Skill runtime",
        }

        task_dir = target_dir / _safe_path_part(task_id, "task")
        task_dir.mkdir(parents=True, exist_ok=True)
        analysis_path = task_dir / "analysis_result.json"
        model_parameters_path = task_dir / "model_parameters.json"
        task_path = task_dir / "task.json"
        waveform_path = task_dir / "waveform.csv"
        raw_waveform_dir_name = "raw_waveforms"
        waveform_metadata = _write_waveform_csv(
            waveform_path,
            _analysis_waveform_traces(job.result, result),
        )
        raw_waveform_metadata = _write_raw_channel_csvs(
            task_dir,
            raw_waveform_dir_name,
            _collect_all_waveform_traces(job.result),
        )
        result["waveform_files"] = {
            "selected": waveform_metadata,
            "raw": raw_waveform_metadata,
        }
        _write_json(model_parameters_path, snapshot)
        _write_json(analysis_path, result)
        _write_json(
            task_path,
            {
                "task_id": task_id,
                "status": "complete",
                "model_rid": source,
                "model_parameters": model_parameters_path.name,
                "analysis_result": analysis_path.name,
                "waveform": waveform_path.name,
                "raw_waveforms": raw_waveform_dir_name,
            },
        )
        _emit_stage(stage)
        _emit_stage("complete")
        return {"task_id": task_id}
    except Exception as exc:
        error = {
            "status": "failed",
            "source": source,
            "stage": stage,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        if task_id is not None:
            error["task_id"] = task_id
            error_dir = target_dir / _safe_path_part(task_id, "task")
            error_dir.mkdir(parents=True, exist_ok=True)
            error_path = error_dir / "analysis_error.json"
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            error_path = target_dir / f"analysis_error_{timestamp}.json"
        _write_json(error_path, error)
        raise


def wait_for_completion(job, timeout: int = 300, interval: int = 3) -> int:
    start_time = time.time()
    while True:
        status = job.status()
        if status in {1, 2}:
            return status
        if time.time() - start_time > timeout:
            return -1
        time.sleep(interval)


def run_emt(model, *, timeout: int = 300):
    job = model.runEMT()
    final_status = wait_for_completion(job, timeout=timeout)
    if final_status == -1:
        raise TimeoutError("EMT job timed out")
    if final_status == 2:
        raise RuntimeError("EMT job failed")
    if job.result is None:
        raise RuntimeError("EMT result is empty")
    return job


def _plot_name(plot: dict[str, Any], index: int) -> str:
    return plot.get("key") or plot.get("name") or f"plot_{index}"


def _resolve_config(config: dict[str, Any] | None) -> dict[str, Any]:
    config = config or {}
    if config.get("output"):
        raise ValueError(
            "config.output is not supported; PromptToApp retrieves CloudPSS results by task_id"
        )
    analysis = config.get("analysis", {})
    thevenin = config.get("thevenin", analysis.get("thevenin", {}))
    channels = config.get("channels", {})
    if channels.get("current"):
        raise ValueError(
            "channels.current is not accepted as a substitute for model-declared "
            "fault or fault-bus current channels. Configure the CloudPSS model first."
        )
    if channels.get("voltage") or channels.get("generic"):
        raise ValueError(
            "channels.voltage and channels.generic cannot be analyzed as current; "
            "use channels.equivalent_pairs for power/voltage estimation."
        )
    steady_fault_window_explicit = bool(
        analysis.get("_steady_fault_window_explicit", "steady_fault_window" in analysis)
    )
    steady_fault_window = analysis.get("steady_fault_window")
    if steady_fault_window is None and analysis.get("fault_window") is not None:
        steady_fault_window = list(
            _steady_fault_window(
                analysis["fault_window"],
                float(analysis.get("steady_fault_trim_fraction", 0.2)),
            )
        )
    declared_current_sources = list(analysis.get("declared_current_sources", []))
    legacy_fault_channel = _source_text(analysis.get("fault_current_channel"))
    if not declared_current_sources and legacy_fault_channel:
        declared_current_sources = [
            {
                "kind": "fault_element",
                "component_id": analysis.get("target_fault_id"),
                "channel": legacy_fault_channel,
                "source": "analysis.fault_current_channel",
            }
        ]
    return {
        "base_voltage_kv": _optional_float(analysis.get("base_voltage_kv", analysis.get("base_voltage"))),
        "requested_base_voltage_kv": _optional_float(analysis.get("requested_base_voltage_kv")),
        "base_voltage_conflict": analysis.get("base_voltage_conflict"),
        "base_voltage_source": analysis.get("base_voltage_source"),
        "fault_bus": analysis.get("fault_bus"),
        "target_fault_id": analysis.get("target_fault_id"),
        "fault_type": analysis.get("fault_type"),
        "declared_current_sources": declared_current_sources,
        "fault_current_channel": analysis.get("fault_current_channel"),
        "current_scale": float(analysis.get("current_scale", 1.0)),
        "power_scale_mw": float(analysis.get("power_scale_mw", 1.0)),
        "voltage_scale_pu": float(analysis.get("voltage_scale_pu", 1.0)),
        "nominal_voltage_pu": float(analysis.get("nominal_voltage_pu", 1.0)),
        "analysis_window": analysis.get("analysis_window"),
        "prefault_window": analysis.get("prefault_window"),
        "fault_window": analysis.get("fault_window"),
        "postfault_window": analysis.get("postfault_window"),
        "steady_fault_window": steady_fault_window,
        "steady_fault_window_explicit": steady_fault_window_explicit,
        "steady_fault_trim_fraction": float(analysis.get("steady_fault_trim_fraction", 0.2)),
        "min_samples": int(analysis.get("min_samples", 128)),
        "auto_max_channels": int(channels.get("auto_max_channels", 3)),
        "thevenin": {
            "enabled": bool(thevenin.get("enabled", analysis.get("enable_thevenin", True))),
            "system_base_mva": float(thevenin.get("system_base_mva", analysis.get("system_base_mva", 100.0))),
            "plant_rating_mva": _optional_float(
                thevenin.get("plant_rating_mva", thevenin.get("rating_mva", analysis.get("plant_rating_mva")))
            ),
            "reactive_compensation_mvar": _optional_float(
                thevenin.get("reactive_compensation_mvar", thevenin.get("shunt_compensation_mvar", 0.0))
            ),
            "xr_ratio": _optional_float(thevenin.get("xr_ratio", analysis.get("xr_ratio"))),
            "weak_scr_threshold": float(thevenin.get("weak_scr_threshold", 2.0)),
            "strong_scr_threshold": float(thevenin.get("strong_scr_threshold", 3.0)),
        },
        "channels": {
            "current": list(channels.get("current", [])),
            "voltage": list(channels.get("voltage", [])),
            "power": list(channels.get("power", [])),
            "reactive_power": list(channels.get("reactive_power", [])),
            "generic": list(channels.get("generic", [])),
        },
        "equivalent_pairs": list(channels.get("equivalent_pairs", [])),
    }


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _find_trace(result, channel_name: str) -> tuple[int, str, dict[str, list[float]]]:
    for plot_index, plot in enumerate(result.getPlots()):
        channel_names = list(result.getPlotChannelNames(plot_index))
        if channel_name not in channel_names:
            continue
        data = result.getPlotChannelData(plot_index, channel_name)
        if not data:
            continue
        x_values = [float(value) for value in data.get("x", [])]
        y_values = [float(value) for value in data.get("y", [])]
        if len(x_values) > 1 and len(x_values) == len(y_values):
            return plot_index, _plot_name(plot, plot_index), {"x": x_values, "y": y_values}
    raise KeyError(f"Trace not found: {channel_name}")


def _looks_like_current_channel(channel_name: str) -> bool:
    lower = channel_name.strip().lower()
    if not lower:
        return False
    stem = lower.split(":", 1)[0].strip()
    compact = re.sub(r"[^a-z0-9]+", "", stem)
    if not compact:
        return False
    excluded_tokens = ("power", "voltage", "vac", "vrms", "theta", "freq", "omega", "speed", "torque", "wr")
    if any(token in compact for token in excluded_tokens):
        return False
    if compact.startswith(("ifault", "iabc", "irms", "current")) or "current" in compact:
        return True
    if compact in {"i", "ia", "ib", "ic", "id", "iq", "it", "idc", "iac"}:
        return True
    return bool(re.search(r"(?:^|[^a-z0-9])i(?:a|b|c|abc|rms|t)?(?:$|[^a-z0-9])", stem))


def _looks_like_non_current_channel(channel_name: str) -> bool:
    """Reject explicit channels whose names identify voltage, power, or generic data."""
    compact = re.sub(r"[^a-z0-9]+", "", channel_name.strip().lower().split(":", 1)[0])
    if not compact:
        return False
    excluded_tokens = (
        "power",
        "voltage",
        "vac",
        "vrms",
        "generic",
        "theta",
        "freq",
        "omega",
        "speed",
        "torque",
        "wr",
    )
    if any(token in compact for token in excluded_tokens):
        return True
    return compact.startswith(("p", "q")) and not compact.startswith(("phase", "peak"))


def _channel_matches_fault(
    channel_name: str,
    *,
    fault_bus: str | None,
    preferred_channel: str | None,
    related_tokens: list[str],
) -> bool:
    """Check whether a current channel name identifies the active fault area."""
    channel_lower = str(channel_name).strip().lower()
    channel_stem = channel_lower.split(":", 1)[0]
    compact_channel = re.sub(r"[^a-z0-9]+", "", channel_stem)
    if preferred_channel:
        preferred = str(preferred_channel).strip().lower()
        if channel_lower == preferred or channel_lower.startswith(f"{preferred}:"):
            return True
    for token in related_tokens:
        preferred = str(token).strip().lower()
        if channel_lower == preferred or channel_lower.startswith(f"{preferred}:"):
            return True
    return False


def _auto_select_current_traces(
    result,
    max_channels: int,
    preferred_channel: str | None = None,
    fault_bus: str | None = None,
    related_tokens: list[str] | None = None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for plot_index, plot in enumerate(result.getPlots()):
        for channel_name in result.getPlotChannelNames(plot_index):
            if not _looks_like_current_channel(channel_name):
                continue
            if not _channel_matches_fault(
                channel_name,
                fault_bus=fault_bus,
                preferred_channel=preferred_channel,
                related_tokens=related_tokens or [],
            ):
                continue
            data = result.getPlotChannelData(plot_index, channel_name)
            if not data:
                continue
            x_values = [float(value) for value in data.get("x", [])]
            y_values = [float(value) for value in data.get("y", [])]
            if len(x_values) > 1 and len(x_values) == len(y_values):
                candidates.append(
                    {
                        "kind": "current",
                        "channel": channel_name,
                        "plot_index": plot_index,
                        "plot": _plot_name(plot, plot_index),
                        "trace": {"x": x_values, "y": y_values},
                    }
                )
    if preferred_channel:
        preferred = preferred_channel.strip().lower()
        preferred_candidates = [
            item
            for item in candidates
            if item["channel"].strip().lower() == preferred
            or item["channel"].strip().lower().startswith(f"{preferred}:")
        ]
        if preferred_candidates:
            # Once the model declares the fault-current stem, do not mix in
            # another current channel when one phase is missing.
            candidates = preferred_candidates
    return candidates[:max_channels]


def _select_declared_current_traces(
    result,
    max_channels: int,
    declared_sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Select traces only from model-declared fault or fault-bus channels."""
    for source in declared_sources:
        channel_stem = _source_text(source.get("channel"))
        if not channel_stem:
            continue
        candidates: list[dict[str, Any]] = []
        for plot_index, plot in enumerate(result.getPlots()):
            for channel_name in result.getPlotChannelNames(plot_index):
                channel_text = str(channel_name)
                if not (
                    channel_text == channel_stem
                    or channel_text.startswith(f"{channel_stem}:")
                ):
                    continue
                data = result.getPlotChannelData(plot_index, channel_text)
                if not data:
                    continue
                x_values = [float(value) for value in data.get("x", [])]
                y_values = [float(value) for value in data.get("y", [])]
                if len(x_values) > 1 and len(x_values) == len(y_values):
                    candidates.append(
                        {
                            "kind": "current",
                            "channel": channel_text,
                            "plot_index": plot_index,
                            "plot": _plot_name(plot, plot_index),
                            "trace": {"x": x_values, "y": y_values},
                        }
                    )
        if candidates:
            return candidates[:max_channels]
    return []


def _validate_fault_related_channels(
    selected: list[dict[str, Any]],
    *,
    fault_bus: str | None,
    preferred_channel: str | None,
    related_tokens: list[str],
) -> None:
    unrelated = [
        str(item["channel"])
        for item in selected
        if not _channel_matches_fault(
            str(item["channel"]),
            fault_bus=fault_bus,
            preferred_channel=preferred_channel,
            related_tokens=related_tokens,
        )
    ]
    if unrelated:
        raise ValueError(
            "Configured current channels are not associated with the active fault "
            f"or fault bus {fault_bus!r}: {', '.join(unrelated)}. "
            "Configure and output the fault-element or fault-bus current channels."
        )


def _select_explicit_traces(result, channel_config: dict[str, list[str]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for kind, names in channel_config.items():
        if kind not in {"current"}:
            continue
        for channel_name in names:
            if _looks_like_non_current_channel(str(channel_name)):
                raise ValueError(
                    f"Configured current channel is not a recognized current trace: {channel_name}. "
                    "Use channels.equivalent_pairs for power/voltage traces."
                )
            plot_index, plot, trace = _find_trace(result, channel_name)
            selected.append(
                {
                    "kind": "current",
                    "channel": channel_name,
                    "plot_index": plot_index,
                    "plot": plot,
                    "trace": trace,
                }
            )
    return selected


def _channel_match_keys(channel_name: str, kind: str) -> set[str]:
    """Return stable naming keys used to pair power and voltage channels."""
    lower = channel_name.strip().lower()
    stem, _, suffix = lower.partition(":")
    keys: set[str] = set()
    if kind == "power":
        match = re.search(r"(?:^|[^a-z0-9])(?:#?p|power)[_ -]?(\d+)", stem)
        if match:
            keys.add(f"ordinal:{int(match.group(1)) - 1}")
    else:
        match = re.search(r"(?:^|[^a-z0-9])(?:v|vac|voltage|vrms)[_ -]?(\d+)", stem)
        if match:
            keys.add(f"ordinal:{int(match.group(1)) - 1}")
        elif suffix.isdigit() and stem in {"v", "vac", "voltage", "vrms"}:
            keys.add(f"ordinal:{int(suffix)}")
    for token in re.findall(r"(?:bus|母线|phase|相)[a-z0-9]+", stem):
        keys.add(f"label:{token}")
    for token in re.findall(r"(?:^|[^a-z])(a|b|c)(?:$|[^a-z])", stem):
        keys.add(f"phase:{token}")
    return keys


def _pair_named_channels(
    power_names: list[str],
    voltage_names: list[str],
    max_channels: int,
) -> list[dict[str, str]]:
    """Pair channels only when names provide a non-ambiguous relationship."""
    pairs: list[dict[str, str]] = []
    unused_voltage = set(voltage_names)
    for power_name in power_names:
        candidates = [
            voltage_name
            for voltage_name in unused_voltage
            if _channel_match_keys(power_name, "power")
            & _channel_match_keys(voltage_name, "voltage")
        ]
        if len(candidates) != 1:
            continue
        voltage_name = candidates[0]
        pairs.append({"power": power_name, "voltage": voltage_name})
        unused_voltage.remove(voltage_name)
        if len(pairs) >= max_channels:
            break
    return pairs


def _window_values(
    x_values: list[float],
    y_values: list[float],
    window: list[float] | tuple[float, float] | None,
    *,
    default_start: float,
    default_end: float,
) -> tuple[list[float], list[float]]:
    if window:
        if len(window) != 2:
            raise ValueError("time window must be [start, end]")
        start = float(window[0])
        end = float(window[1])
    else:
        start = default_start
        end = default_end
    if not math.isfinite(start) or not math.isfinite(end) or end <= start:
        raise ValueError("time window must have finite start < end")
    tolerance = max(1e-9, abs(x_values[-1] - x_values[0]) * 1e-9)
    if start < x_values[0] and x_values[0] - start <= tolerance:
        start = x_values[0]
    if end > x_values[-1] and end - x_values[-1] <= tolerance:
        end = x_values[-1]
    if start < x_values[0] or end > x_values[-1]:
        raise ValueError(
            f"time window [{start:g}, {end:g}] is outside waveform range "
            f"[{x_values[0]:g}, {x_values[-1]:g}]"
        )
    out_x: list[float] = []
    out_y: list[float] = []
    for x_value, y_value in zip(x_values, y_values):
        if start <= x_value <= end:
            out_x.append(x_value)
            out_y.append(y_value)
    return out_x, out_y


def _rms(values: list[float]) -> float:
    if not values:
        raise ValueError("Cannot calculate RMS for empty values")
    return math.sqrt(sum(value * value for value in values) / len(values))


def _mean_abs(values: list[float]) -> float:
    if not values:
        raise ValueError("Cannot calculate mean for empty values")
    return sum(abs(value) for value in values) / len(values)


def _mean(values: list[float]) -> float:
    if not values:
        raise ValueError("Cannot calculate mean for empty values")
    return sum(values) / len(values)


def _peak(values: list[float]) -> float:
    if not values:
        raise ValueError("Cannot calculate peak for empty values")
    return max(abs(value) for value in values)


def _validate_time_axis(x_values: list[float]) -> None:
    if any(not math.isfinite(value) for value in x_values):
        raise ValueError("Waveform time axis contains non-finite values")
    if any(x_values[index] >= x_values[index + 1] for index in range(len(x_values) - 1)):
        raise ValueError("Waveform time axis is not strictly increasing")


def _default_windows(x_values: list[float]) -> dict[str, tuple[float, float]]:
    start = x_values[0]
    end = x_values[-1]
    duration = end - start
    if duration <= 0:
        raise ValueError("Invalid time axis duration")
    early_end = start + min(0.5, duration * 0.2)
    mid_start = start + duration * 0.2
    mid_end = start + duration * 0.8
    late_start = end - min(0.5, duration * 0.2)
    return {
        "prefault": (start, early_end),
        "fault": (mid_start, mid_end),
        "postfault": (late_start, end),
    }


def _short_circuit_mva(current_rms: float, base_voltage_kv: float) -> float:
    return math.sqrt(3.0) * base_voltage_kv * abs(current_rms)


def _grid_strength(scr: float | None, weak_threshold: float, strong_threshold: float) -> str:
    if scr is None:
        return "not_assessed"
    if scr < weak_threshold:
        return "weak"
    if scr < strong_threshold:
        return "medium"
    return "strong"


def _grid_strength_note(strength: str) -> str:
    notes = {
        "strong": "Short-circuit strength is above the configured strong-grid threshold.",
        "medium": "Short-circuit strength is in the intermediate range; voltage/reactive support and controls should be reviewed.",
        "weak": "Short-circuit strength is below the configured weak-grid threshold; detailed IBR/control interaction studies are recommended.",
        "not_assessed": "Plant rating was not provided, so SCR/ESCR was not assessed.",
    }
    return notes.get(strength, "Unknown grid-strength classification.")


def _thevenin_from_short_circuit(
    *,
    short_circuit_mva: float,
    base_voltage_kv: float,
    system_base_mva: float,
    plant_rating_mva: float | None,
    reactive_compensation_mvar: float | None,
    xr_ratio: float | None,
    weak_scr_threshold: float,
    strong_scr_threshold: float,
) -> dict[str, Any]:
    if short_circuit_mva <= 0:
        raise ValueError("short_circuit_mva must be positive to compute Thevenin equivalent")
    if base_voltage_kv <= 0:
        raise ValueError("base_voltage_kv must be positive to compute Thevenin equivalent")
    if system_base_mva <= 0:
        raise ValueError("system_base_mva must be positive to compute Thevenin equivalent")

    z_base_ohm = base_voltage_kv * base_voltage_kv / system_base_mva
    z_th_ohm_mag = base_voltage_kv * base_voltage_kv / short_circuit_mva
    z_th_pu_mag = system_base_mva / short_circuit_mva
    z_ohm: dict[str, Any] = {
        "magnitude": z_th_ohm_mag,
        "real": None,
        "imag": None,
        "xr_ratio": xr_ratio,
    }
    z_pu: dict[str, Any] = {
        "magnitude": z_th_pu_mag,
        "real": None,
        "imag": None,
        "xr_ratio": xr_ratio,
    }
    if xr_ratio is not None and xr_ratio > 0:
        r_ohm = z_th_ohm_mag / math.sqrt(1.0 + xr_ratio * xr_ratio)
        x_ohm = r_ohm * xr_ratio
        r_pu = z_th_pu_mag / math.sqrt(1.0 + xr_ratio * xr_ratio)
        x_pu = r_pu * xr_ratio
        z_ohm.update({"real": r_ohm, "imag": x_ohm})
        z_pu.update({"real": r_pu, "imag": x_pu})

    scr = None
    escr = None
    q_comp = reactive_compensation_mvar if reactive_compensation_mvar is not None else 0.0
    if plant_rating_mva is not None and plant_rating_mva > 0:
        scr = short_circuit_mva / plant_rating_mva
        escr = (short_circuit_mva - q_comp) / plant_rating_mva

    strength_basis = escr if escr is not None else scr
    strength = _grid_strength(strength_basis, weak_scr_threshold, strong_scr_threshold)
    return {
        "method": "derived_from_short_circuit_capacity",
        "formula": "Zth=Vll^2/Ssc; SCR=Ssc/Srated; ESCR=(Ssc-Qcomp)/Srated",
        "base_voltage_kv": base_voltage_kv,
        "system_base_mva": system_base_mva,
        "z_base_ohm": z_base_ohm,
        "z_th_ohm": z_ohm,
        "z_th_pu": z_pu,
        "short_circuit_capacity_mva": short_circuit_mva,
        "plant_rating_mva": plant_rating_mva,
        "reactive_compensation_mvar": q_comp,
        "scr": scr,
        "escr": escr,
        "weak_scr_threshold": weak_scr_threshold,
        "strong_scr_threshold": strong_scr_threshold,
        "grid_strength": strength,
        "assessment": _grid_strength_note(strength),
    }


def _steady_fault_window(
    fault_window: list[float] | tuple[float, float] | None,
    trim_fraction: float,
) -> tuple[float, float] | None:
    if not fault_window:
        return None
    if len(fault_window) != 2:
        raise ValueError("fault_window must be [start, end]")
    start = float(fault_window[0])
    end = float(fault_window[1])
    if not math.isfinite(start) or not math.isfinite(end) or end <= start:
        raise ValueError("fault_window must have finite start < end")
    if not 0 <= trim_fraction < 0.5:
        raise ValueError("steady_fault_trim_fraction must be in [0, 0.5)")
    trim = (end - start) * trim_fraction
    return start + trim, end - trim


def analyze_short_circuit_trace(
    trace: dict[str, list[float]],
    *,
    kind: str,
    base_voltage_kv: float,
    current_scale: float,
    analysis_window: list[float] | tuple[float, float] | None,
    prefault_window: list[float] | tuple[float, float] | None,
    fault_window: list[float] | tuple[float, float] | None,
    postfault_window: list[float] | tuple[float, float] | None,
    steady_fault_window: list[float] | tuple[float, float] | None = None,
    steady_fault_trim_fraction: float = 0.2,
    min_samples: int = 128,
) -> dict[str, Any]:
    x_raw = trace["x"]
    y_raw = [value * current_scale if kind == "current" else value for value in trace["y"]]
    _validate_time_axis(x_raw)

    total_start = x_raw[0]
    total_end = x_raw[-1]
    win_x, win_y = _window_values(x_raw, y_raw, analysis_window, default_start=total_start, default_end=total_end)
    if len(win_x) < min_samples:
        raise ValueError(f"Not enough samples in analysis window: {len(win_x)} < {min_samples}")

    defaults = _default_windows(win_x)
    _, prefault_values = _window_values(win_x, win_y, prefault_window, default_start=defaults["prefault"][0], default_end=defaults["prefault"][1])
    fault_x, fault_values = _window_values(win_x, win_y, fault_window, default_start=defaults["fault"][0], default_end=defaults["fault"][1])
    _, postfault_values = _window_values(win_x, win_y, postfault_window, default_start=defaults["postfault"][0], default_end=defaults["postfault"][1])
    selected_fault_window = [fault_x[0], fault_x[-1]]
    steady_window = _steady_fault_window(
        steady_fault_window or selected_fault_window,
        0.0 if steady_fault_window else steady_fault_trim_fraction,
    )
    fault_bounds = (
        [float(fault_window[0]), float(fault_window[1])]
        if fault_window
        else selected_fault_window
    )
    if steady_window and (
        steady_window[0] < fault_bounds[0]
        or steady_window[1] > fault_bounds[1]
    ):
        raise ValueError("steady_fault_window must be inside fault_window")
    steady_x, steady_values = _window_values(
        win_x,
        win_y,
        list(steady_window) if steady_window else None,
        default_start=selected_fault_window[0],
        default_end=selected_fault_window[1],
    )
    if not prefault_values or not fault_values or not postfault_values:
        raise ValueError("One or more analysis windows contain no data")
    if not steady_values:
        raise ValueError("Steady fault window contains no data")

    peak_current = _peak(win_y)
    fault_peak = _peak(fault_values)
    prefault_rms = _rms(prefault_values)
    fault_rms = _rms(fault_values)
    postfault_rms = _rms(postfault_values)
    steady_fault_peak = _peak(steady_values)
    steady_fault_rms = _rms(steady_values)
    # The signed mean is the DC component estimate over the selected fault window.
    dc_offset = _mean(fault_values)
    min_current = min(win_y)
    max_current = max(win_y)
    max_index = max(range(len(win_y)), key=lambda index: abs(win_y[index]))

    return {
        "method": "direct_current_channel" if kind == "current" else "generic_waveform",
        "sample_count": len(win_x),
        "t_start": win_x[0],
        "t_end": win_x[-1],
        "fault_window_start": fault_x[0],
        "fault_window_end": fault_x[-1],
        "steady_fault_window_start": steady_x[0],
        "steady_fault_window_end": steady_x[-1],
        "steady_fault_window_sample_count": len(steady_x),
        "steady_fault_window_policy": (
            "explicit" if steady_fault_window else f"trim_{steady_fault_trim_fraction:g}_each_side"
        ),
        "min_current": min_current,
        "max_current": max_current,
        "peak_current": peak_current,
        "peak_current_time_s": win_x[max_index],
        "fault_peak_current": fault_peak,
        "steady_fault_peak_current": steady_fault_peak,
        "prefault_rms_current": prefault_rms,
        "fault_rms_current": fault_rms,
        "steady_fault_rms_current": steady_fault_rms,
        "steady_to_fault_rms_ratio": steady_fault_rms / fault_rms if fault_rms > 1e-12 else None,
        "postfault_rms_current": postfault_rms,
        "fault_to_prefault_rms_ratio": fault_rms / prefault_rms if prefault_rms > 1e-12 else None,
        "postfault_to_prefault_rms_ratio": postfault_rms / prefault_rms if prefault_rms > 1e-12 else None,
        "dc_offset_estimate": dc_offset,
        "short_circuit_mva": _short_circuit_mva(fault_rms, base_voltage_kv),
        "steady_fault_short_circuit_mva": _short_circuit_mva(steady_fault_rms, base_voltage_kv),
    }


def _equivalent_current_trace(
    power_trace: dict[str, list[float]],
    voltage_trace: dict[str, list[float]],
    *,
    power_scale_mw: float,
    voltage_scale_pu: float,
    base_voltage_kv: float,
    nominal_voltage_pu: float,
) -> dict[str, list[float]]:
    p_x = power_trace["x"]
    p_y = power_trace["y"]
    v_x = voltage_trace["x"]
    v_y = voltage_trace["y"]
    if len(p_x) != len(v_x) or any(abs(a - b) > 1e-9 for a, b in zip(p_x, v_x)):
        raise ValueError("Power and voltage traces must share the same time axis")

    currents: list[float] = []
    for p_value, v_value in zip(p_y, v_y):
        voltage_pu = abs(v_value * voltage_scale_pu)
        if voltage_pu < 1e-6:
            voltage_pu = nominal_voltage_pu
        # S(MVA) = sqrt(3) * V(kV) * I(kA), so I(kA) = P(MW) / (sqrt(3) * V(kV)).
        current_ka = abs(p_value * power_scale_mw) / (math.sqrt(3.0) * base_voltage_kv * voltage_pu)
        currents.append(current_ka)
    return {"x": list(p_x), "y": currents}


def _select_equivalent_pairs(result, pairs: list[Any]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for pair in pairs:
        if not isinstance(pair, dict):
            raise ValueError("equivalent_pairs entries must be objects")
        power_channel = pair.get("power")
        voltage_channel = pair.get("voltage")
        if not power_channel or not voltage_channel:
            raise ValueError("equivalent_pairs requires power and voltage fields")
        p_plot_index, p_plot, p_trace = _find_trace(result, str(power_channel))
        _, _, v_trace = _find_trace(result, str(voltage_channel))
        selected.append(
            {
                "kind": "equivalent_current",
                "channel": f"{power_channel}|{voltage_channel}",
                "plot_index": p_plot_index,
                "plot": p_plot,
                "trace": p_trace,
                "voltage_trace": v_trace,
                "power_channel": str(power_channel),
                "voltage_channel": str(voltage_channel),
            }
        )
    return selected


def _auto_equivalent_pairs(result, max_channels: int) -> list[dict[str, Any]]:
    power_names: list[str] = []
    voltage_names: list[str] = []
    for plot_index, _plot in enumerate(result.getPlots()):
        for channel_name in result.getPlotChannelNames(plot_index):
            lower = channel_name.lower()
            if lower.startswith("#p"):
                power_names.append(channel_name)
            elif lower.startswith("v") or "vac" in lower or "vrms" in lower:
                voltage_names.append(channel_name)
    pairs = _pair_named_channels(power_names, voltage_names, max_channels)
    return _select_equivalent_pairs(result, pairs)


def _summarize_thevenin(rows: list[dict[str, Any]]) -> dict[str, Any]:
    thevenin_rows = [row["analysis"]["thevenin"] for row in rows if row["analysis"].get("thevenin")]
    if not thevenin_rows:
        return {
            "enabled": False,
            "channel_count": 0,
        }
    scr_values = [row["scr"] for row in thevenin_rows if row.get("scr") is not None]
    escr_values = [row["escr"] for row in thevenin_rows if row.get("escr") is not None]
    strength_rank = {"weak": 0, "medium": 1, "strong": 2, "not_assessed": 3}
    worst = min((row["grid_strength"] for row in thevenin_rows), key=lambda item: strength_rank.get(item, 99))
    return {
        "enabled": True,
        "channel_count": len(thevenin_rows),
        "min_z_th_pu_magnitude": min(row["z_th_pu"]["magnitude"] for row in thevenin_rows),
        "max_z_th_pu_magnitude": max(row["z_th_pu"]["magnitude"] for row in thevenin_rows),
        "min_z_th_ohm_magnitude": min(row["z_th_ohm"]["magnitude"] for row in thevenin_rows),
        "max_z_th_ohm_magnitude": max(row["z_th_ohm"]["magnitude"] for row in thevenin_rows),
        "min_scr": min(scr_values) if scr_values else None,
        "min_escr": min(escr_values) if escr_values else None,
        "worst_grid_strength": worst,
    }


def run_short_circuit_analysis(
    model,
    config: dict[str, Any] | None = None,
    *,
    job=None,
    timeout: int = 300,
) -> dict[str, Any]:
    """Analyze one existing or newly created EMT Job without exporting report files."""
    resolved = _resolve_config(config)
    if resolved["base_voltage_kv"] is None or resolved["base_voltage_kv"] <= 0:
        raise ValueError(
            "analysis.base_voltage_kv is required and must be positive; "
            "resolve it from the active fault bus or provide it explicitly."
        )
    if job is None:
        job = run_emt(model, timeout=timeout)
    task_id = _task_id_from_job(job)

    equivalent_selected = _select_equivalent_pairs(job.result, resolved["equivalent_pairs"]) if resolved["equivalent_pairs"] else []
    selected: list[dict[str, Any]] = []
    if not equivalent_selected:
        declared_sources = list(resolved.get("declared_current_sources", []))
        if not declared_sources:
            raise RuntimeError(
                "The active fault element and fault bus have no declared current channel. "
                f"Fault bus {resolved['fault_bus']!r}: configure the CloudPSS fault-element "
                "or fault-bus current channel before retrying the analysis."
            )
        selected = _select_declared_current_traces(
            job.result,
            resolved["auto_max_channels"],
            declared_sources,
        )
    if selected:
        declared_stems = [
            str(source.get("channel"))
            for source in resolved.get("declared_current_sources", [])
            if source.get("channel")
        ]
        _validate_fault_related_channels(
            selected,
            fault_bus=resolved["fault_bus"],
            preferred_channel=None,
            related_tokens=declared_stems,
        )
    if not selected and not equivalent_selected:
        raise RuntimeError(
            "No EMT current channel declared by the active fault element or fault bus was found. "
            f"Fault bus {resolved['fault_bus']!r}: configure the declared channel in the EMT "
            "output before retrying the analysis."
        )

    rows: list[dict[str, Any]] = []
    for item in selected:
        analysis = analyze_short_circuit_trace(
            item["trace"],
            kind=item["kind"],
            base_voltage_kv=resolved["base_voltage_kv"],
            current_scale=resolved["current_scale"],
            analysis_window=resolved["analysis_window"],
            prefault_window=resolved["prefault_window"],
            fault_window=resolved["fault_window"],
            postfault_window=resolved["postfault_window"],
            steady_fault_window=(
                resolved["steady_fault_window"]
                if resolved["steady_fault_window_explicit"]
                else None
            ),
            steady_fault_trim_fraction=resolved["steady_fault_trim_fraction"],
            min_samples=resolved["min_samples"],
        )
        rows.append(
            {
                "kind": item["kind"],
                "plot_index": item["plot_index"],
                "plot": item["plot"],
                "channel": item["channel"],
                "analysis": analysis,
            }
        )

    for item in equivalent_selected:
        eq_trace = _equivalent_current_trace(
            item["trace"],
            item["voltage_trace"],
            power_scale_mw=resolved["power_scale_mw"],
            voltage_scale_pu=resolved["voltage_scale_pu"],
            base_voltage_kv=resolved["base_voltage_kv"],
            nominal_voltage_pu=resolved["nominal_voltage_pu"],
        )
        analysis = analyze_short_circuit_trace(
            eq_trace,
            kind="current",
            base_voltage_kv=resolved["base_voltage_kv"],
            current_scale=1.0,
            analysis_window=resolved["analysis_window"],
            prefault_window=resolved["prefault_window"],
            fault_window=resolved["fault_window"],
            postfault_window=resolved["postfault_window"],
            steady_fault_window=(
                resolved["steady_fault_window"]
                if resolved["steady_fault_window_explicit"]
                else None
            ),
            steady_fault_trim_fraction=resolved["steady_fault_trim_fraction"],
            min_samples=resolved["min_samples"],
        )
        analysis["method"] = "estimated_from_power_voltage"
        rows.append(
            {
                "kind": "equivalent_current",
                "plot_index": item["plot_index"],
                "plot": item["plot"],
                "channel": item["channel"],
                "source_channels": {
                    "power": item["power_channel"],
                    "voltage": item["voltage_channel"],
                },
                "analysis": analysis,
            }
        )
    if not rows:
        raise RuntimeError(
            "No usable analysis channels were found. Configure a current channel on the active "
            "fault element or fault bus, or explicitly provide equivalent_pairs for estimation."
        )

    if resolved["thevenin"]["enabled"]:
        for row in rows:
            row["analysis"]["thevenin"] = _thevenin_from_short_circuit(
                short_circuit_mva=row["analysis"]["short_circuit_mva"],
                base_voltage_kv=resolved["base_voltage_kv"],
                system_base_mva=resolved["thevenin"]["system_base_mva"],
                plant_rating_mva=resolved["thevenin"]["plant_rating_mva"],
                reactive_compensation_mvar=resolved["thevenin"]["reactive_compensation_mvar"],
                xr_ratio=resolved["thevenin"]["xr_ratio"],
                weak_scr_threshold=resolved["thevenin"]["weak_scr_threshold"],
                strong_scr_threshold=resolved["thevenin"]["strong_scr_threshold"],
            )

    max_peak = max(row["analysis"]["peak_current"] for row in rows)
    max_fault_rms = max(row["analysis"]["fault_rms_current"] for row in rows)
    max_steady_fault_rms = max(row["analysis"]["steady_fault_rms_current"] for row in rows)
    max_steady_scc = max(row["analysis"]["steady_fault_short_circuit_mva"] for row in rows)
    max_scc = max(row["analysis"]["short_circuit_mva"] for row in rows)
    thevenin_summary = _summarize_thevenin(rows) if resolved["thevenin"]["enabled"] else {"enabled": False, "channel_count": 0}
    result_data = {
        "model": getattr(model, "name", ""),
        "model_rid": getattr(model, "rid", ""),
        "task_id": task_id,
        "analysis": {
            "base_voltage_kv": resolved["base_voltage_kv"],
            "base_voltage_source": resolved["base_voltage_source"],
            "requested_base_voltage_kv": resolved["requested_base_voltage_kv"],
            "base_voltage_conflict": resolved["base_voltage_conflict"],
            "fault_bus": resolved["fault_bus"],
            "target_fault_id": resolved["target_fault_id"],
            "fault_type": resolved["fault_type"],
            "current_scale": resolved["current_scale"],
            "power_scale_mw": resolved["power_scale_mw"],
            "voltage_scale_pu": resolved["voltage_scale_pu"],
            "nominal_voltage_pu": resolved["nominal_voltage_pu"],
            "analysis_window": resolved["analysis_window"],
            "prefault_window": resolved["prefault_window"],
            "fault_window": resolved["fault_window"],
            "postfault_window": resolved["postfault_window"],
            "steady_fault_window": resolved["steady_fault_window"],
            "steady_fault_window_explicit": resolved["steady_fault_window_explicit"],
            "steady_fault_trim_fraction": resolved["steady_fault_trim_fraction"],
            "min_samples": resolved["min_samples"],
        },
        "thevenin": {
            "enabled": resolved["thevenin"]["enabled"],
            "input": resolved["thevenin"],
            "summary": thevenin_summary,
        },
        "summary": {
            "channel_count": len(rows),
            "max_peak_current": max_peak,
            "max_fault_rms_current": max_fault_rms,
            "max_steady_fault_rms_current": max_steady_fault_rms,
            "max_short_circuit_mva": max_scc,
            "max_steady_fault_short_circuit_mva": max_steady_scc,
            "min_scr": thevenin_summary.get("min_scr"),
            "min_escr": thevenin_summary.get("min_escr"),
            "worst_grid_strength": thevenin_summary.get("worst_grid_strength"),
            "methods": sorted({row["analysis"]["method"] for row in rows}),
        },
        "channels": rows,
        "provenance": {
            "waveform": "CloudPSS EMTResult.getPlotChannelData",
            "metrics": "short-circuit-analysis Skill runtime",
        },
    }

    return result_data
