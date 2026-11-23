"""Read and edit a local short-circuit preparation workspace."""

import argparse
from hashlib import sha256
from copy import deepcopy
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from uuid import uuid4

from sdk_bootstrap import activate
from configure_cloudpss import configure_cloudpss

activate()
from auto_modeling.component_args import get_diagram_components, update_diagram_components_args
from auto_modeling.component_model import get_component_model
from auto_modeling.diagram_aux import model_from_document
from auto_modeling.diagram_batch import find_diagram_components, find_diagram_edges
from auto_modeling.diagram_edit import add_diagram_component, add_dynamic_diagram_edge, delete_diagram_cells, get_diagram_edges
from auto_modeling.dynamic_pins import instance_pin_definitions
from auto_modeling.job_functions import get_job_function
from auto_modeling.job_schemes import update_job
from auto_modeling.parameter_checks import check_parameter_constraints
from auto_modeling.project_session import open_project
from connection_preview import check_connection

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mylib.sdk_adapter import SDKAdapter, validate_rid


EMT = {"function/CloudPSS/emtp", "function/CloudPSS/emtps"}
RECORDER = "model/CloudPSS/_newChannel"
ROW_ID = "ɵid"
LITERAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def read(path):
    return json.loads(path.read_bytes())


def encode(data):
    return json.dumps(data, ensure_ascii=False, allow_nan=False)


def atomic_write(path, data):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     delete=False) as stream:
        tmp = Path(stream.name)
        try:
            stream.write(encode(data))
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            stream.close()
            tmp.unlink(missing_ok=True)
            raise
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


@contextmanager
def writer(root):
    lock = root / ".write-lock"
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise ValueError("Workspace has an active or interrupted writer; inspect it before clearing its lock") from exc
    try:
        yield
    finally:
        lock.rmdir()


def open_workspace(root, *, source=None, document=None):
    if (source is None) == (document is None):
        raise ValueError("Provide exactly one source RID or local document")
    root.mkdir(parents=True, exist_ok=True)
    with writer(root):
        state = root / "state.json"
        if state.exists():
            raise ValueError("Workspace already exists; select another directory to open a new model")
        model = open_project(source) if source else model_from_document(read(document))
        snapshot = model.toJSON()
        result = {
            "source_rid": source or snapshot.get("rid"),
            "baseline_revision": snapshot["revision"].get("hash"),
            "version": uuid4().hex,
            "document": snapshot,
        }
        atomic_write(state, result)
        return {key: value for key, value in result.items() if key != "document"}


def resolve_from(path, lookup):
    if path is None:
        return lookup
    cache = read(path)

    def resolve(rid):
        entry = cache[rid]
        if entry.get("rid", rid) != rid:
            raise ValueError(f"Definition identity mismatch: {rid}")
        return {**entry, **entry.get("revision", {}), "rid": rid}

    return resolve


def field_for(resolve, rid, key):
    definition = resolve(rid)
    if not definition:
        raise ValueError(f"Missing definition: {rid}")
    matches = [(group, item) for group in definition["parameters"] for item in group["items"]
               if item.get("key") == key]
    if len(matches) != 1:
        raise ValueError(f"Expected one definition for {rid}.{key}")
    group, field = matches[0]
    if any(part.get("condition") not in (None, "", True, "true") for part in (group, field)):
        raise ValueError(f"Field {key} requires conditional evaluation")
    return field


def validate_fault_window(model, cell, changes, resolve, job_index):
    bounds = []
    for key in ("fs", "fe"):
        field = field_for(resolve, cell["definition"], key)
        raw = changes.get(key, cell["args"].get(key, field.get("value")))
        bounds.append(time_literal(raw, f"Fault time {key}"))
    start, end = bounds
    if start >= end:
        raise ValueError(f"Fault start fs ({start:g} s) must be earlier than fault end fe ({end:g} s)")
    if job_index is not None:
        if type(job_index) is not int or not 0 <= job_index < len(model.jobs) or model.jobs[job_index]["rid"] not in EMT:
            raise ValueError("Select an actual EMT calculation scheme index")
        args = model.jobs[job_index]["args"]
        first = time_literal(args.get("begin_time"), "EMT begin_time")
        last = time_literal(args.get("end_time"), "EMT end_time")
        if not first <= start < end <= last:
            raise ValueError(f"Fault time must lie inside EMT scheme {job_index} time range [{first:g}, {last:g}] s")


def time_literal(raw, label):
    value = text_value(raw)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)) or not LITERAL.fullmatch(str(value).strip()):
        raise ValueError(f"{label} requires a numeric literal; resolve its expression in the selected scheme")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def update_args(model, cid, changes, units, resolve, *, job_index=None):
    if not isinstance(changes, dict) or not changes:
        raise ValueError("Provide at least one field to change")
    cell = get_diagram_components(model, [cid])[0]
    stored = cell["args"]
    args = {}
    for key, value in changes.items():
        field = field_for(resolve, cell["definition"], key)
        if (cell["definition"] == "model/CloudPSS/_newFaultResistor_3p"
                and key == "ft" and field.get("type") == "choice" and field.get("input") == "constant"):
            choices = {item["key"]: item.get("name") for item in field["choices"] if not item.get("condition")}
            if not isinstance(value, str) or value not in choices:
                raise ValueError(f"Select a fault type key from the definition: {choices}")
            previous = stored.get(key, field.get("value"))
            if isinstance(previous, dict) and str(text_value(previous)).strip() not in choices:
                raise ValueError("Fault type references an expression; resolve its scope before editing")
            if previous != value:
                args[key] = value
            continue
        if field.get("type") not in {"real", "integer"} or field.get("input") != "constant":
            raise ValueError(f"{key} is outside supported numeric instance edits")
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"{key} requires a finite number")
        if units.get(key) != field.get("unit"):
            raise ValueError(f"{key} requires unit {field.get('unit')!r}")
        if check_parameter_constraints(value, field, scope=None, data={}):
            raise ValueError(f"{key} violates constraints")
        previous = stored.get(key, field.get("value"))
        if isinstance(previous, dict):
            # Numeric-literal wrappers occur in existing browser documents.
            source = previous.get("source")
            if (not isinstance(previous.get("ɵexp"), str) or not isinstance(source, str)
                    or not LITERAL.fullmatch(source.strip())):
                raise ValueError(f"{key} references an expression; resolve its scope before editing")
            old_number = float(source)
            if not math.isfinite(old_number):
                raise ValueError(f"{key} has an unsupported current value")
            if old_number != value:
                args[key] = {"source": str(value), "ɵexp": ""}
        elif previous != value:
            args[key] = value
    if cell["definition"] in {"model/CloudPSS/_newFaultResistor", "model/CloudPSS/_newFaultResistor_3p"} and (
        "fs" in changes or "fe" in changes
    ):
        validate_fault_window(model, cell, changes, resolve, job_index)
    if not args:
        return {"component": cid, "before": {}, "after": {}}
    update_diagram_components_args(model, [cid], args, definition_resolver=resolve)
    updated = get_diagram_components(model, [cid])[0]["args"]
    if any(updated.get(k) != expected for k, expected in args.items()):
        raise ValueError("SDK write did not retain the requested values")
    # Preserve related fields exactly if the SDK normalizes their number representation.
    model.getAllComponents()[cid].args = {**stored, **{k: updated[k] for k in args}}
    result = {"component": cid, "before": {k: stored.get(k) for k in args},
              "after": {k: updated[k] for k in args}}
    if "ft" in args:
        result["fault_type"] = {"key": args["ft"], "name": choices[args["ft"]]}
    return result


def text_value(value):
    return value.get("source") if isinstance(value, dict) else value


def bound_ids(rows, rid):
    result = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("4"), list):
            raise ValueError(f"Unrecognized output row in {rid}")
        result.extend(row["4"])
    return result


def add_current_channel(model, request, resolve, resolve_job):
    cid, job_index = request["component"], request["job_index"]
    signal_arg = request["signal_arg"]
    source = get_diagram_components(model, [cid])[0]
    if (source.get("props") or {}).get("enabled") not in (None, True):
        raise ValueError("The source is disabled or its enabled state requires evaluation")
    field = field_for(resolve, source["definition"], signal_arg)
    if field.get("type") != "pinLike" or field.get("connection") != "output":
        raise ValueError("Select a current-output pinLike field from the component definition")
    if "current" not in field.get("name", "").casefold() and "电流" not in field.get("description", ""):
        raise ValueError("The definition does not identify this field as a current output")
    width = field.get("dim")
    if (not isinstance(width, list) or len(width) != 2 or str(width[1]) != "1"
            or not str(width[0]).isdigit() or int(width[0]) < 1):
        raise ValueError("Resolve the source's current dimensions before configuring the recorder")
    dim = int(width[0])
    if type(job_index) is not int or not 0 <= job_index < len(model.jobs) or model.jobs[job_index]["rid"] not in EMT:
        raise ValueError("Select an actual EMT calculation scheme index")
    config_index = request["config_index"]
    if type(config_index) is not int or not 0 <= config_index < len(model.configs):
        raise ValueError("Select an actual parameter scheme index")
    job = model.jobs[job_index]
    if job["args"].get("sim_option") not in (None, 0, "0"):
        raise ValueError("Check whether this calculation mode enables waveform output")
    rate = request.get("sample_rate_hz", 1000)
    if type(rate) not in (int, float) or not math.isfinite(rate) or rate <= 0:
        raise ValueError("Sample rate must be positive")
    rows = deepcopy(job["args"].get("output_channels", []))
    registered = bound_ids(rows, job["rid"])
    signal = request["signal"]
    if not isinstance(signal, str) or not signal.strip() or signal != signal.strip():
        raise ValueError("Provide a nonempty current signal name")
    old = source["args"].get(signal_arg)
    if old not in (None, "", signal):
        raise ValueError("Reuse the existing current signal; a rename requires reviewing its consumers first")

    graph = model.toJSON()["revision"]["implements"]["diagram"]["cells"]
    same_canvas = [v for v in graph.values() if v and v.get("canvas") == source["canvas"]]
    candidates = [v for v in same_canvas if v.get("definition") == RECORDER
                  and text_value(v.get("args", {}).get("Name")) == signal]
    # Other producers using the same name need review before binding a recorder.
    if any(v.get("id") != cid and v.get("definition") != RECORDER
           and any(text_value(a) == signal for a in (v.get("args") or {}).values())
           for v in same_canvas):
        raise ValueError("Signal is already referenced by another component on the source canvas")
    if len(candidates) > 1:
        raise ValueError("Multiple same-name recorders on source canvas")
    if candidates:
        recorder = candidates[0]
        recorder_id = recorder["id"]
        if (recorder.get("pins", {}).get("0") != signal
                or (recorder.get("props") or {}).get("enabled") not in (None, True)
                or text_value(recorder["args"].get("Dim")) not in (dim, str(dim))
                or find_diagram_edges(model, terminals=[{"cell": recorder_id, "port": "0"}])):
            raise ValueError("Existing recorder input or dimension conflicts with the requested signal")
    else:
        position = source["position"]
        recorder_id = add_diagram_component(model, RECORDER,
            {"x": position["x"] + 120, "y": position["y"]}, source["canvas"],
            {"Name": signal, "Dim": dim}, {"0": signal}, label=signal, definition_resolver=resolve)
    if old != signal:
        update_diagram_components_args(model, [cid], {signal_arg: signal}, definition_resolver=resolve)
        cell = model.getAllComponents()[cid]
        cell.args = {**source["args"], signal_arg: cell.args[signal_arg]}
    if recorder_id not in registered:
        row = {"0": signal, "1": rate, "2": "compressed", "3": 0, "4": [recorder_id], "5": [],
               ROW_ID: max((v.get(ROW_ID, 0) for v in rows if type(v.get(ROW_ID)) is int), default=0) + 1}
        # Older archives omit the optional list in column 5. Validate its
        # normalized form, then retain the exact existing row representations.
        normalized = [{"5": [], **previous} for previous in rows]
        update_job(model, job_index, {"output_channels": [*normalized, row]}, definition_resolver=resolve_job)
        accepted = model.jobs[job_index]["args"]["output_channels"]
        if accepted != [*normalized, row]:
            raise ValueError("SDK normalized or did not preserve the requested output rows")
        model.jobs[job_index]["args"]["output_channels"] = [*rows, accepted[-1]]
    else:
        linked = [row for row in rows if recorder_id in row["4"]]
        if len(linked) != 1 or ("sample_rate_hz" in request and linked[0].get("1") != rate):
            raise ValueError("Existing output rows conflict; review their registration and sampling settings")
    readback = get_diagram_components(model, [cid, recorder_id])
    if readback[0]["args"][signal_arg] != signal or readback[1]["pins"]["0"] != signal:
        raise ValueError("Current signal or recorder binding did not survive the edit")
    registered_rows = [row for row in model.jobs[job_index]["args"]["output_channels"]
                       if recorder_id in row["4"]]
    return {"component": cid, "signal_arg": signal_arg, "signal": signal, "recorder": recorder_id,
            "reused": bool(candidates), "job_index": job_index, "config_index": config_index,
            "job_rid": job["rid"], "job_name": job["name"], "dimension": dim,
            "config_name": model.configs[config_index]["name"], "output_row": registered_rows[0]}


def add_component(model, request, resolve):
    cid = add_diagram_component(
        model, request["definition"], request["position"], request["canvas"],
        request.get("args", {}), request.get("pins", {}), label=request.get("label"),
        definition_resolver=resolve,
    )
    return {"component": get_diagram_components(model, [cid])[0]}


def delete_component(model, cid):
    cell = get_diagram_components(model, [cid])[0]
    removed = delete_diagram_cells(model, [cid])
    ids = {entry["id"] for entry in removed}

    def references_removed(value):
        if isinstance(value, dict):
            return any(references_removed(item) for item in value.values())
        if isinstance(value, list):
            return any(references_removed(item) for item in value)
        return isinstance(value, str) and value in ids

    if references_removed(model.jobs) or references_removed(model.configs):
        raise ValueError("A calculation or parameter scheme still references the component or its edges")
    return {"component": cell, "removed": removed}


def connect(model, request, resolve):
    source, target = request["source"], request["target"]
    definitions = {}

    def cached_definition(rid):
        if rid not in definitions:
            definitions[rid] = resolve(rid)
        return definitions[rid]

    existing = find_diagram_edges(model, terminals=[source])
    endpoints = {(source["cell"], source["port"]), (target["cell"], target["port"])}
    for edge in existing:
        if {(edge[side].get("cell"), edge[side].get("port")) for side in ("source", "target")} == endpoints:
            raise ValueError(f"These terminals are already joined by {edge['id']}")
    cid = add_dynamic_diagram_edge(model, source, target, vertices=request.get("vertices"),
                                   definition_resolver=cached_definition)
    check_connection(model, source, target, cached_definition)
    return {"edge": get_diagram_edges(model, [cid])[0]}


def save_request(state, request):
    rid = validate_rid(request["new_rid"])
    protected = (state["source_rid"], state["document"].get("rid"))
    if any(rid.casefold() == (value or "").casefold() for value in protected):
        raise ValueError("The source RID is read-only; choose a new RID")
    params = {key: request[key] for key in ("name", "desc") if key in request}
    if any(not isinstance(value, str) or not value.strip() for value in params.values()):
        raise ValueError("Provide nonempty text for name and description")
    return {"new_rid": rid, **params}


def preview(root, request, component_definitions=None, functions=None):
    with writer(root):
        state = read(root / "state.json")
        model = model_from_document(state["document"])
        resolve = resolve_from(component_definitions, get_component_model)
        action = request["operation"]
        if action == "update_parameters":
            job_index = request.get("job_index", (state.get("prepared_binding") or {}).get("job_index"))
            if job_index is None:
                current = model.context.get("currentJob")
                emt_indices = [index for index, job in enumerate(model.jobs) if job["rid"] in EMT]
                if type(current) is int and current in emt_indices:
                    job_index = current
                elif len(emt_indices) == 1:
                    job_index = emt_indices[0]
            result = update_args(model, request["component"], request["values"],
                                 request.get("units", {}), resolve, job_index=job_index)
        elif action == "configure_current":
            result = add_current_channel(model, request, resolve, resolve_from(functions, get_job_function))
        elif action == "add_component":
            result = add_component(model, request, resolve)
        elif action == "delete_component":
            result = delete_component(model, request["component"])
        elif action == "connect":
            result = connect(model, request, resolve)
        elif action == "save_new":
            result = save_request(state, request)
        else:
            raise ValueError("Unsupported workspace operation")
        preview_id = uuid4().hex
        pending = {"id": preview_id, "version": state["version"], "document": model.toJSON(),
                   "operation": action, "result": result}
        atomic_write(root / "preview.json", pending)
        return {"status": "preview_required", "preview_id": preview_id,
                "version": state["version"], "changes": result}


def save_new(root, state, pending, config_file):
    target = save_request(state, pending["result"])
    rid = target.pop("new_rid")
    receipt_file = root / f"save-{sha256(rid.casefold().encode()).hexdigest()}.json"
    if receipt_file.exists():
        raise ValueError("This RID has a save attempt; verify its outcome before any retry")
    model = model_from_document(pending["document"])
    # Deleted SDK cells are kept as null slots locally. The saved document omits them.
    cells = model.getAllComponents()
    for cid in [key for key, cell in cells.items() if cell.toJSON() is None]:
        del cells[cid]
    receipt = {"status": "save_started", "target_rid": rid, "version": state["version"]}
    configure_cloudpss(config_file)
    atomic_write(receipt_file, receipt)
    try:
        result = SDKAdapter().create_copy(model, rid, **target)
    except Exception:
        result = {"status": "save_outcome_unknown", "saved_to_cloud": None,
                  "message": "Check the destination RID and saved model before retrying"}
    receipt.update(result)
    atomic_write(receipt_file, receipt)
    return receipt


def apply(root, preview_id, config_file=None):
    with writer(root):
        state = read(root / "state.json")
        pending = read(root / "preview.json")
        if pending["id"] != preview_id or pending["version"] != state["version"]:
            raise ValueError("Preview is missing or stale; make a preview from the current work version")
        if pending["operation"] == "save_new":
            return save_new(root, state, pending, config_file)
        version = uuid4().hex
        state.update(version=version, document=pending["document"])
        if pending["operation"] == "configure_current":
            state["prepared_binding"] = pending["result"]
        else:
            state.pop("prepared_binding", None)
        atomic_write(root / "state.json", state)
        return {"status": "changed", "version": version, "readback": pending["result"]}


def inspect(root, component=None):
    state = read(root / "state.json")
    result = {key: value for key, value in state.items() if key != "document"}
    model = model_from_document(state["document"])
    result["emt_schemes"] = [{"index": i, "name": j["name"], "rid": j["rid"]}
                             for i, j in enumerate(model.jobs) if j["rid"] in EMT]
    result["parameter_schemes"] = [{"index": i, "name": c["name"]} for i, c in enumerate(model.configs)]
    if component:
        result["component"] = get_diagram_components(model, [component])[0]
    return result


def export(root, destination, handoff=None):
    state = read(root / "state.json")
    data = encode(state["document"])
    binding = state.get("prepared_binding")
    if handoff and not binding:
        raise ValueError("Prepare and confirm a current binding before exporting for analysis")
    payload = data.encode("utf-8")
    with destination.open("xb") as stream:
        stream.write(payload)
    result = {"version": state["version"], "model_document": str(destination.resolve()),
              "sha256": sha256(payload).hexdigest(), "source_rid": state["source_rid"],
              "baseline_revision": state["baseline_revision"], "binding": binding}
    if handoff:
        with handoff.open("x", encoding="utf-8") as stream:
            stream.write(encode(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--config-file", type=Path, help="Optional explicit CloudPSS credential configuration")
    subs = parser.add_subparsers(dest="command", required=True)
    start = subs.add_parser("open")
    inputs = start.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--source")
    inputs.add_argument("--document", type=Path)
    query = subs.add_parser("inspect")
    query.add_argument("--component")
    find = subs.add_parser("find")
    find.add_argument("--definition")
    find.add_argument("--label")
    find.add_argument("--canvas")
    ports = subs.add_parser("ports")
    ports.add_argument("component")
    ports.add_argument("--definitions", type=Path)
    edges = subs.add_parser("edges")
    edges.add_argument("--component", required=True)
    edges.add_argument("--port")
    stage = subs.add_parser("preview")
    stage.add_argument("request", type=Path)
    stage.add_argument("--definitions", type=Path)
    stage.add_argument("--functions", type=Path)
    subs.add_parser("apply").add_argument("preview_id")
    output = subs.add_parser("export")
    output.add_argument("destination", type=Path)
    output.add_argument("--handoff", type=Path)
    args = parser.parse_args()
    root = args.workspace
    try:
        request = read(args.request) if args.command == "preview" else None
        if (args.command == "open" and args.source) or (args.command == "ports" and args.definitions is None) or (
                request and request.get("operation") in {"update_parameters", "add_component", "configure_current", "connect"} and (
                args.definitions is None or (request.get("operation") == "configure_current"
                                             and args.functions is None))):
            configure_cloudpss(args.config_file)
        if args.command == "open":
            result = open_workspace(root, source=args.source, document=args.document)
        elif args.command == "inspect":
            result = inspect(root, args.component)
        elif args.command == "find":
            model = model_from_document(read(root / "state.json")["document"])
            result = find_diagram_components(model, definitions=[args.definition] if args.definition else None,
                       labels=[args.label] if args.label else None, canvases=[args.canvas] if args.canvas else None)
        elif args.command == "ports":
            model = model_from_document(read(root / "state.json")["document"])
            cell = get_diagram_components(model, [args.component])[0]
            resolve = resolve_from(args.definitions, get_component_model)
            definition = resolve(cell["definition"])
            if definition is None:
                raise ValueError(f"No definition found for {cell['definition']}")
            result = {"component": args.component, "canvas": cell["canvas"],
                      "ports": instance_pin_definitions(model, cell, definition)}
        elif args.command == "edges":
            model = model_from_document(read(root / "state.json")["document"])
            endpoint = {"cell": args.component}
            if args.port is not None:
                endpoint["port"] = args.port
            result = find_diagram_edges(model, terminals=[endpoint])
        elif args.command == "preview":
            result = preview(root, request, args.definitions, args.functions)
        elif args.command == "apply":
            result = apply(root, args.preview_id, args.config_file)
        else:
            result = export(root, args.destination, args.handoff)
        print(encode(result))
    except (KeyError, ValueError, TypeError, OSError, RuntimeError, OverflowError) as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
