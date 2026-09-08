"""Offline regression with real SDK data types and mocked network boundaries."""
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import cloudpss
from mylib import PSAToolbox, edit_model_from_context as edit, inspect_model_from_context
from mylib.sdk_adapter import SDKAdapter, json_value


def model():
    return cloudpss.Model({
        "rid": "model/example/source", "name": "Source", "description": "", "tags": [],
        "configs": [{"name": "Default", "args": {}}], "context": {"currentConfig": 0}, "jobs": [],
        "revision": {"version": 5, "hash": "fixture", "parameters": {}, "pins": {},
                     "implements": {"diagram": {"canvas": [{"key": "canvas_0", "name": "Main"}], "cells": {}}}},
    })


def state():
    return {"original_rid": "model/example/source", "memory_model": model()}


def execute(state, request):
    preview = edit(request, state)
    return edit({"operation": request["operation"], "preview_id": preview["preview_id"], "confirmation": "execute"}, state)


def rejected(action):
    try:
        action()
    except (ValueError, KeyError, TypeError):
        return
    raise AssertionError("Expected rejection")


def verify():
    report = []
    library = json.loads((ROOT / "saSource.json").read_text(encoding="utf-8"))
    # Patching these makes accidental network calls fail immediately.
    with patch.object(cloudpss.Model, "fetch", side_effect=AssertionError("Unexpected fetch")), \
         patch.object(cloudpss.Model, "create", side_effect=AssertionError("Unexpected create")), \
         patch.object(cloudpss.Model, "update", side_effect=AssertionError("Never update")), \
         patch.object(cloudpss.Model, "save", side_effect=AssertionError("Never save")), \
         patch.object(cloudpss.ModelRevision, "create", side_effect=AssertionError("Unexpected topology")):
        s = state()
        assert len(edit({"operation": "list_templates"}, {})["templates"]) == len(library)
        for key, template in library.items():
            schema = edit({"operation": "get_template_schema", "target": {"template_key": key}}, {})
            assert set(schema["parameters"]) == set(template["args"])
            before = copy.deepcopy(json_value(s["memory_model"]))
            request = {"operation": "create", "target": {"template_key": key, "canvas": "canvas_0"}}
            p = edit(request, s)
            assert json_value(s["memory_model"]) == before
            result = edit({"operation": "create", "confirmation": "execute", "preview_id": p["preview_id"]}, s)
            created = result["changed"]["key"]
            assert result["changed"] == p["preview"]["component"]
            # Structural write/read for every template; selected parameter only.
            first = next(iter(template["args"]), None)
            changes = {"label": "verified_" + key}
            if first:
                changes["args"] = {first: {"source": "1+2"}}
            if template["pins"]:
                changes["pins"] = {next(iter(template["pins"])): "test_net"}
            updated = execute(s, {"operation": "update", "target": {"key": created}, "changes": changes})
            assert updated["changed"]["label"] == changes["label"]
            if first:
                assert updated["changed"]["args"][first]["source"] == "1+2"
            read = inspect_model_from_context(s, created)["component"]
            assert read == updated["changed"]
            execute(s, {"operation": "delete", "target": {"key": created}})
            assert created not in s["memory_model"].getAllComponents()
            report.append({"template": key, "catalog": "passed", "create_update_read_delete": "passed",
                           "scope": "selected parameter and pin, SDK structure only"})
        execute(s, {"operation": "create_canvas", "target": {"canvas": "extra"}, "changes": {"name": "Extra"}})
        assert s["memory_model"].revision.implements.diagram.canvas[-1]["key"] == "extra"
        req = {"operation": "create", "target": {"template_key": "_newChannel", "canvas": "extra"},
               "changes": {"args": {"Dim": 3}, "label": "Channel"}}
        p1, p2 = edit(req, s), edit(req, s)
        rejected(lambda: edit({"operation": "create", "confirmation": "execute"}, s))
        changed = edit({"operation": "create", "confirmation": "execute", "preview_id": p1["preview_id"]}, s)
        assert changed["changed"]["args"]["Dim"]["source"] == 3
        rejected(lambda: edit({"operation": "create", "confirmation": "execute", "preview_id": p2["preview_id"]}, s))
        rejected(lambda: edit({"operation": "create", "confirmation": "execute", "preview_id": p1["preview_id"]}, s))
        cid = changed["changed"]["key"]
        original = copy.deepcopy(json_value(s["memory_model"]))
        for changes in ({"args": {"does_not_exist": 1}}, {"pins": {"900": "x"}},
                        {"pins": {"0": 1}}, {"Dim": 3}, {"args": []}):
            rejected(lambda: edit({"operation": "update", "target": {"key": cid}, "changes": changes}, s))
            assert original == json_value(s["memory_model"])
        p = edit({"operation": "update", "target": {"key": cid}, "changes": {"label": "Expected"}}, s)
        rejected(lambda: edit({"operation": "update", "preview_id": p["preview_id"], "confirmation": "execute",
                               "changes": {"label": "Different"}}, s))
        edit({"operation": "cancel_preview", "preview_id": p["preview_id"]}, s)
        rejected(lambda: edit({"operation": "update", "preview_id": p["preview_id"], "confirmation": "execute"}, s))
        # Graphical references and shared named nets in delete previews.
        sa = s["toolbox"]
        cells = sa.getAllComponents()
        cells["edge"] = sa.adapter.component({"shape": "diagram-edge", "source": {"cell": cid, "port": "0"},
                                              "target": {}, "id": "edge"})
        deletion = execute(s, {"operation": "delete", "target": {"key": cid}})
        assert "edge" in deletion["changed"]["removed_keys"]
        rejected(lambda: edit({"operation": "saveProject", "target": {"new_rid": s["original_rid"]}}, s))
        rejected(lambda: sa.saveProject("model/example/new"))
        # SDK create/fetch mocked explicitly; update/save remain forbidden.
        project_before = copy.deepcopy(json_value(sa.project))
        saved = {}
        def create(candidate):
            if candidate.rid in saved:
                return {"errors": [{"message": "exists"}]}
            saved[candidate.rid] = copy.deepcopy(candidate)
            return {"data": {"createModel": {"rid": candidate.rid}}}
        with patch.object(cloudpss.Model, "create", side_effect=create) as create_mock, \
             patch.object(cloudpss.Model, "fetch", side_effect=lambda rid: saved[rid]):
            request = {"operation": "saveProject", "target": {"new_rid": "model/example/new"}}
            result = execute(s, request)
            assert result["status"] == "saved" and result["readback_verified"]
            assert json_value(sa.project) == project_before
            result = execute(s, request)
            assert result["status"] == "save_failed"
            assert create_mock.call_count == 2
        with patch.object(cloudpss.Model, "create", side_effect=create), \
             patch.object(cloudpss.Model, "fetch", side_effect=TimeoutError):
            result = execute(s, {"operation": "saveProject", "target": {"new_rid": "model/example/no_read"}})
            assert result["status"] == "saved_unverified" and result["saved_to_cloud"] is True
        with patch.object(cloudpss.Model, "create", side_effect=TimeoutError):
            p = edit({"operation": "saveProject", "target": {"new_rid": "model/example/timeout"}}, s)
            confirm = {"operation": "saveProject", "confirmation": "execute", "preview_id": p["preview_id"]}
            assert edit(confirm, s)["status"] == "save_outcome_unknown"
            rejected(lambda: edit(confirm, s))
        # Both real-model list/int and legacy dict/key config representations.
        with patch.object(cloudpss.ModelRevision, "create", return_value={"hash": "test_hash"}), \
             patch.object(cloudpss.ModelTopology, "fetch", return_value=SimpleNamespace(toJSON=lambda: {"components": {}})) as fetch:
            assert sa.refreshTopology()["revision_hash"] == "test_hash"
            assert fetch.call_args.args[2] == sa.project.configs[0]
            sa.project.configs = {"default": {"args": {}}}
            sa.project.context["currentConfig"] = "default"
            sa.refreshTopology()
            assert fetch.call_args.args[2] == sa.project.configs["default"]
            sa.project.context["currentConfig"] = "missing"
            rejected(sa.refreshTopology)
    print(json.dumps({"offline": True, "templates": report, "regressions": [
        "preview fidelity/isolation/staleness/replay/tamper/cancel", "invalid field rejection",
        "expression preservation", "canvas commit", "incident edge deletion",
        "source save refusal", "create-only persistence", "save/readback failure distinction",
        "list/int and dict/key topology configs"], "cloud_saved": False, "simulation_run": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    verify()
