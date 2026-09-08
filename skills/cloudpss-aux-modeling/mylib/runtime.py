"""Structured Agent boundary over the migrated modeling toolbox."""

from __future__ import annotations

import copy
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .PSAToolbox import PSAToolbox
from .CaseEditToolbox import merge_fields
from .sdk_adapter import json_value, validate_rid

SUPPORTED_OPERATIONS = {"initialize", "list_templates", "get_template_schema", "query",
                        "create", "update", "delete", "create_canvas", "delete_edges",
                        "refresh_topology", "saveProject", "cancel_preview", "read_result"}
CONFIRMATIONS = {"execute", "confirmed", "confirm", "确认执行", "确认"}
PREVIEW_TTL = 1800
OUTPUT_LIMIT = 12000


def validate_session_inputs(supplied, session, request):
    """Host configuration boundary; runtime objects are never Agent input."""
    if set(supplied) - {"original_rid", "api_url"}:
        raise ValueError("session_state only accepts original_rid and api_url; credentials come from environment")
    if any(not isinstance(v, str) or not v.strip() for v in supplied.values()):
        raise ValueError("Session configuration values must be nonempty strings")
    if "original_rid" in supplied:
        validate_rid(supplied["original_rid"])
    if "api_url" in supplied:
        from urllib.parse import urlsplit
        url = urlsplit(supplied["api_url"])
        if url.scheme not in {"http", "https"} or not url.netloc or url.username or url.password:
            raise ValueError("api_url must be an HTTP(S) URL without credentials")
    reset = request.get("operation") == "initialize" and request.get("options", {}).get("reset") is True
    if session.get("toolbox") is not None or session.get("memory_model") is not None:
        for key, value in supplied.items():
            if key == "original_rid":
                old = session.get(key) or getattr(session.get("memory_model"), "rid", None)
            else:
                sa = session.get("toolbox")
                old = session.get(key) or (sa.config.get("apiURL") if sa else None)
            if old != value and not reset:
                raise ValueError("Changing an initialized session requires initialize with options.reset=true")
    return dict(supplied)


def _select_args(args, fields):
    if fields is None:
        return copy.deepcopy(args)
    if not isinstance(fields, list) or not fields or any(not isinstance(f, str) for f in fields):
        raise ValueError("fields must be a nonempty list of exact parameter names")
    missing = set(fields) - set(args)
    if missing:
        raise ValueError(f"Unknown parameter fields: {sorted(missing)}")
    return {key: copy.deepcopy(args[key]) for key in fields}


def _bounded(result, state):
    serialized = json.dumps(result, ensure_ascii=False)
    if len(serialized) <= OUTPUT_LIMIT:
        return result
    now = time.time()
    cache = state.setdefault("result_pages", {})
    for key in list(cache):
        if now - cache[key]["created_at"] > PREVIEW_TTL:
            del cache[key]
    while len(cache) >= 8:
        del cache[next(iter(cache))]
    result_id = uuid.uuid4().hex
    cache[result_id] = {"text": serialized, "created_at": now}
    return {"status": result.get("status", "result_available"), "result_id": result_id,
            "preview_id": result.get("preview_id"), "characters": len(serialized),
            "message": "Full JSON retained in session for 30 minutes (last 8 results). Read all pages before approving a preview.",
            "read_request": {"operation": "read_result", "target": {"result_id": result_id},
                             "options": {"offset": 0, "limit": 4000}}}


@dataclass
class EditRequest:
    operation: str
    target: dict[str, Any] = field(default_factory=dict)
    changes: dict[str, Any] = field(default_factory=dict)
    confirmation: str | None = None
    options: dict[str, Any] = field(default_factory=dict)
    preview_id: str | None = None


def _toolbox(session_state):
    sa = session_state.get("toolbox")
    rid = session_state.get("original_rid")
    if sa is not None:
        if rid and rid != sa.original_rid:
            raise ValueError("Session RID changed; use initialize with options.reset=true")
        return sa
    sa = PSAToolbox()
    injected = session_state.get("memory_model")
    if injected is not None:
        # Reuse the host-owned model; normalize before publishing the toolbox.
        sa.config["comLibName"] = session_state.get("component_library", "saSource.json")
        sa.config["deleteEdges"] = True
        # setInitialConditions performs the same edge-to-pin normalization as
        # the reference code while retaining the host-owned project object.
        sa.setInitialConditions(project=injected)
        sa.original_rid = rid or sa.original_rid
        session_state.update(toolbox=sa, original_rid=sa.original_rid)
        session_state["connection_audit"] = copy.deepcopy(getattr(sa, "connection_audit", {}))
        return sa
    if rid:
        validate_rid(rid)
        _, owner, key = rid.split("/")
        sa.setConfig(username=owner, model=key, token=session_state.get("token"),
                     apiURL=session_state.get("api_url"), comLibName=session_state.get("component_library"))
    elif session_state.get("memory_model") is None:
        raise ValueError("Provide session_state.original_rid")
    # Agent modeling follows reference edge-to-pin normalization in memory.
    sa.config["deleteEdges"] = True
    sa.setInitialConditions(project=session_state.get("memory_model"))
    sa.original_rid = rid or sa.original_rid
    session_state.update(toolbox=sa, memory_model=sa.project, original_rid=sa.original_rid)
    session_state["connection_audit"] = copy.deepcopy(getattr(sa, "connection_audit", {}))
    return sa


def _summary(key, comp, details=True):
    data = json_value(comp)
    fields = ["label", "definition", "canvas"]
    if details:
        fields += ["args", "pins", "position"]
    result = {"key": key, **{field: data.get(field) for field in fields}}
    if not details:
        name = data.get("args", {}).get("Name")
        result["name"] = name.get("source") if isinstance(name, dict) else name
    return result


def _inspect_model(session_state, identifier=None, *, offset=0, limit=20, definition=None, fields=None):
    if definition is not None and (not isinstance(definition, str) or not definition.startswith("model/")):
        raise ValueError("definition is a component type RID (model/owner/key), not a shape or instance name")
    sa = _toolbox(session_state)
    if identifier:
        key = sa._resolve_comp_key(identifier)
        component = _summary(key, sa.getComponentByKey(key))
        component["args"] = _select_args(component.get("args") or {}, fields)
        return {"original_rid": sa.original_rid, "component": component,
                "connection_audit": copy.deepcopy(getattr(sa, "connection_audit", {}))}
    if fields is not None:
        raise ValueError("fields requires a single component identifier")
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("offset >= 0 and 1 <= limit <= 100 are required")
    items = [(k, c) for k, c in sa.getAllComponents().items()
             if getattr(c, "shape", None) == "diagram-component"
             and (not definition or getattr(c, "definition", None) == definition)]
    return {"original_rid": sa.original_rid, "component_count": len(items),
            "connection_audit": copy.deepcopy(getattr(sa, "connection_audit", {})),
            "diagram_edge_count": sum(getattr(c, "shape", None) == "diagram-edge"
                                      for c in sa.getAllComponents().values()),
            "components": [_summary(k, c, False) for k, c in items[offset:offset + limit]],
            "offset": offset, "next_offset": offset + limit if offset + limit < len(items) else None,
            "canvases": json_value(sa.project.revision.implements.diagram.canvas)}


def inspect_model_from_context(session_state, identifier=None, *, offset=0, limit=20, definition=None, fields=None):
    return _bounded(_inspect_model(session_state, identifier, offset=offset, limit=limit,
                                  definition=definition, fields=fields), session_state)


def _catalog(request, state):
    sa = state.get("toolbox") or PSAToolbox()
    if not sa.compLib:
        sa.config["comLibName"] = state.get("component_library", "saSource.json")
        sa.loadComponentLibrary()
    if request.operation == "list_templates":
        return {"templates": [{"template_key": k, "label": v.get("label"),
                               "definition": v.get("definition"), "pin_count": len(v.get("pins", {}))}
                              for k, v in sa.compLib.items()]}
    key = request.target.get("template_key")
    if key not in sa.compLib:
        raise ValueError("Unknown template_key; call list_templates first")
    template = sa.compLib[key]
    return {"template_key": key, "definition": template.get("definition"), "label": template.get("label"),
            "parameters": {k: {"default": copy.deepcopy(v), "storage_type": type(v).__name__,
                                "type": None, "unit": None, "description": None}
                           for k, v in _select_args(template.get("args", {}), request.options.get("fields")).items()},
            "pins": {k: {"default": v, "direction": None, "description": None}
                     for k, v in template.get("pins", {}).items()},
            "schema_source": "saSource.json template; engineering types/units not provided"}


def _fingerprint(sa):
    project = sa.project
    state = {"cells": json_value(sa.getAllComponents()),
             "canvas": json_value(project.revision.implements.diagram.canvas),
             "pos": sa.pos, "compCount": sa.compCount}
    for attr in ("rid", "name", "description", "configs", "jobs", "context", "tags", "permissions"):
        state[attr] = json_value(getattr(project, attr, None))
    if hasattr(project.revision, "toJSON"):
        state["revision"] = sa.getRevision()
    return hashlib.sha256(json.dumps(state, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _identifier(request):
    return request.target.get("identifier") or request.target.get("key") or request.target.get("label")


def _edit(sa, request):
    operation = request.operation
    allowed = {"create": {"args", "pins", "label"}, "update": {"args", "pins", "label"},
               "create_canvas": {"name"}, "delete": set(), "delete_edges": set()}
    unknown = set(request.changes) - allowed[operation]
    if unknown:
        raise ValueError(f"Unknown changes fields: {sorted(unknown)}; use changes.args/pins")
    for field in ("args", "pins"):
        if field in request.changes and not isinstance(request.changes[field], dict):
            raise TypeError(f"changes.{field} must be an object")
    if "label" in request.changes and (not isinstance(request.changes["label"], str) or not request.changes["label"]):
        raise ValueError("label must be a nonempty string")
    if operation == "create":
        template = request.target.get("template_key")
        if template not in sa.compLib:
            raise ValueError("Unknown template_key; query template catalog first")
        canvas = request.target.get("canvas")
        key, _ = sa.addCompInCanvas(sa.compLib[template], request.target.get("key_prefix") or template,
                                   canvas, **request.changes)
        return {"component": _summary(key, sa.getComponentByKey(key))}
    if operation == "create_canvas":
        canvas = request.target.get("canvas")
        sa.createCanvas(canvas, request.changes.get("name"))
        return {"canvas": canvas}
    if operation == "delete_edges":
        return {"removed_keys": sa.deleteEdges()}
    key = sa._resolve_comp_key(_identifier(request))
    comp = sa.getComponentByKey(key)
    if getattr(comp, "shape", None) != "diagram-component":
        raise ValueError("Target is not a diagram-component")
    before = _summary(key, comp)
    if operation == "delete":
        nets = set(getattr(comp, "pins", {}).values()) - {""}
        peers = [k for k, c in sa.getAllComponents().items() if k != key and
                 nets.intersection(getattr(c, "pins", {}).values())]
        return {"before": before, "removed_keys": sa.deleteComponent(key), "shared_net_peers": peers}
    if not request.changes:
        raise ValueError("update requires changes")
    pins = merge_fields(comp.pins, request.changes.get("pins", {}), pins=True)
    sa.updateCompArgs(request.changes.get("args", {}), key)
    comp.pins = pins
    if "label" in request.changes:
        comp.label = request.changes["label"]
    sa.setCompLabelDict()
    sa.setChannelPinDict()
    return {"before": before, "component": _summary(key, comp)}


def _save_plan(sa, request):
    rid = validate_rid(request.target.get("new_rid"))
    if rid in {sa.original_rid, getattr(sa.project, "rid", None)}:
        raise ValueError("Only a new RID may be saved")
    if set(request.changes) - {"name", "desc"}:
        raise ValueError("saveProject changes only accepts name and desc")
    if any(not isinstance(v, str) for v in request.changes.values()):
        raise TypeError("name and desc must be strings")
    return {"original_rid": sa.original_rid, "new_rid": rid, "mode": "create_only",
            **request.changes, "component_count": len(sa.getAllComponents())}


def _edit_model(request: EditRequest | dict[str, Any], session_state: dict[str, Any]):
    """Dispatch query/catalog or preview-confirm-execute against a host session."""
    if isinstance(request, dict):
        request = EditRequest(**request)
    if request.operation not in SUPPORTED_OPERATIONS:
        raise ValueError(f"Unsupported operation; choose from {sorted(SUPPORTED_OPERATIONS)}")
    targets = {
        "initialize": set(), "list_templates": set(), "get_template_schema": {"template_key"},
        "query": {"identifier", "key", "label", "definition"},
        "create": {"template_key", "canvas", "key_prefix"},
        "update": {"identifier", "key", "label"}, "delete": {"identifier", "key", "label"},
        "create_canvas": {"canvas"}, "delete_edges": set(), "refresh_topology": set(),
        "saveProject": {"new_rid"}, "cancel_preview": set(),
        "read_result": {"result_id"},
    }
    for field in ("target", "changes", "options"):
        if not isinstance(getattr(request, field), dict):
            raise TypeError(f"{field} must be an object")
    unknown = set(request.target) - targets[request.operation]
    if unknown:
        raise ValueError(f"Unsupported target fields for {request.operation}: {sorted(unknown)}")
    allowed_options = {"offset", "limit", "fields"} if request.operation == "query" else (
        {"reset", "offset", "limit"} if request.operation == "initialize" else (
        {"fields"} if request.operation == "get_template_schema" else (
        {"offset", "limit"} if request.operation == "read_result" else set())))
    if set(request.options) - allowed_options:
        raise ValueError(f"Unsupported options for {request.operation}")
    if request.operation in {"query", "initialize", "list_templates", "get_template_schema",
                             "refresh_topology", "cancel_preview", "read_result"} and request.changes:
        raise ValueError(f"{request.operation} does not accept changes")
    if request.operation in {"list_templates", "get_template_schema"}:
        return _catalog(request, session_state)
    if request.operation == "read_result":
        record = session_state.get("result_pages", {}).get(request.target.get("result_id"))
        if not record or time.time() - record["created_at"] > PREVIEW_TTL:
            raise ValueError("Unknown or expired result_id; repeat the original query")
        offset, limit = request.options.get("offset", 0), request.options.get("limit", 4000)
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 4000:
            raise ValueError("offset >= 0 and 1 <= limit <= 4000 required")
        data = record["text"]
        # Escaping a JSON text fragment can expand control characters. Bound
        # the serialized page too, without dropping any original characters.
        while len(json.dumps(data[offset:offset + limit], ensure_ascii=False)) > 8000:
            limit = max(1, limit // 2)
        return {"result_id": request.target["result_id"], "encoding": "JSON text; concatenate pages",
                "text": data[offset:offset + limit], "offset": offset,
                "next_offset": offset + limit if offset + limit < len(data) else None, "characters": len(data)}
    if request.operation == "initialize" and request.options.get("reset") is True:
        for key in ("toolbox", "memory_model", "previews", "current_version", "pending_preview", "result_pages", "connection_audit"):
            session_state.pop(key, None)
    sa = _toolbox(session_state)
    if request.operation in {"query", "initialize"}:
        return _inspect_model(session_state, _identifier(request),
                                          offset=request.options.get("offset", 0), limit=request.options.get("limit", 20),
                                          definition=request.target.get("definition"), fields=request.options.get("fields"))
    if request.operation == "refresh_topology":
        result = sa.refreshTopology()
        return {"status": "topology_refreshed", "revision_hash": result["revision_hash"],
                "component_count": result["component_count"], "saved_to_cloud": False}
    previews = session_state.setdefault("previews", {})
    now = time.time()
    for key in list(previews):
        if now - previews[key]["created_at"] > PREVIEW_TTL:
            del previews[key]
    if request.operation == "cancel_preview":
        if request.preview_id not in previews:
            raise ValueError("Unknown or expired preview_id")
        del previews[request.preview_id]
        return {"status": "cancelled", "preview_id": request.preview_id}
    if request.confirmation not in CONFIRMATIONS:
        if len(previews) >= 32:
            raise ValueError("Too many pending previews; cancel old previews")
        staged = copy.deepcopy(sa)
        plan = _save_plan(staged, request) if request.operation == "saveProject" else _edit(staged, request)
        preview_id = uuid.uuid4().hex
        previews[preview_id] = {"operation": request.operation, "request": copy.deepcopy(request),
                                "fingerprint": _fingerprint(sa), "created_at": now,
                                "plan": copy.deepcopy(plan)}
        public_plan = copy.deepcopy(plan)
        if request.operation == "update":
            for side in ("before", "component"):
                for field in ("args", "pins"):
                    public_plan[side][field] = {key: public_plan[side][field][key]
                                               for key in request.changes.get(field, {})}
            public_plan["scope"] = "Only requested args/pins shown; all omitted fields remain unchanged"
        return {"status": "preview_required", "preview_id": preview_id, "preview": public_plan,
                "expires_in_seconds": PREVIEW_TTL, "saved_to_cloud": False}
    preview_id = request.preview_id
    if not preview_id:
        matches = [k for k, v in previews.items() if v["operation"] == request.operation]
        if len(matches) != 1:
            raise ValueError("Provide exact preview_id; no unique matching preview")
        preview_id = matches[0]
    pending = previews.get(preview_id)
    if not pending or pending["operation"] != request.operation:
        raise ValueError("No matching preview")
    if pending["fingerprint"] != _fingerprint(sa):
        del previews[preview_id]
        raise ValueError("Model changed since preview; request a new preview")
    original = pending["request"]
    if (request.target and request.target != original.target or request.changes and request.changes != original.changes
            or request.options and request.options != original.options):
        raise ValueError("Confirmation cannot change preview contents")
    if original.operation == "saveProject":
        # Consume before the external call: a timeout must never auto-retry a write.
        del previews[preview_id]
        try:
            return sa.saveProject(original.target["new_rid"], confirmed=True, **original.changes)
        except Exception:
            return {"status": "save_outcome_unknown", "saved_to_cloud": None,
                    "target_rid": original.target["new_rid"],
                    "message": "Cloud create did not finish normally; inspect target RID before retry"}
    staged = copy.deepcopy(sa)
    result = _edit(staged, original)
    if result != pending["plan"]:
        raise ValueError("Preview no longer reproducible; request a new preview")
    # Commit the validated local revision in one swap; preserve host model identity.
    # Commit cells in place so host references (and Agent session state) remain valid.
    target_cells = sa.project.revision.implements.diagram.cells
    source_cells = staged.project.revision.implements.diagram.cells
    target_cells.clear()
    target_cells.update(source_cells)
    # Preserve the same revision object while replacing its diagram cells.
    sa.project.revision.implements.diagram.cells = target_cells
    sa.project.revision.implements.diagram.canvas[:] = staged.project.revision.implements.diagram.canvas
    sa.pos, sa.compCount = staged.pos, staged.compCount
    sa.topo = None
    sa.setCompLabelDict()
    sa.setChannelPinDict()
    del previews[preview_id]
    session_state["current_version"] = uuid.uuid4().hex
    changed = result.get("component", result)
    if "component" in result:
        changed = _summary(changed["key"], sa.getComponentByKey(changed["key"]))
    return {"status": "changed", "operation": original.operation, "changed": changed,
            "current_version": session_state["current_version"], "saved_to_cloud": False,
            "validation": {"structure": "read_back", "topology": "not_checked", "simulation": "not_run"}}


def edit_model_from_context(request: EditRequest | dict[str, Any], session_state: dict[str, Any]):
    return _bounded(_edit_model(request, session_state), session_state)
