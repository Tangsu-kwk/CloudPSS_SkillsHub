"""Offline verification for the runtime's preview/edit contract."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from mylib import EditRequest, edit_model_from_context, inspect_model_from_context  # noqa: E402
from mylib import runtime  # noqa: E402


class FakeComponent:
    def __init__(self, data):
        self.data = data
        self.id = data.get("id")
        self.args = data.setdefault("args", {})
        self.pins = data.setdefault("pins", {})
        self.canvas = data.get("canvas")

    def toJSON(self):
        return self.data


class FakeDiagramCell:
    def __init__(self, data):
        self.__dict__.update(data)

    def toJSON(self):
        return dict(self.__dict__)


class FakeModel:
    def __init__(self):
        self.components = {
            "fault-1": FakeComponent(
                {
                    "id": "fault-1",
                    "definition": "model/CloudPSS/_newFaultResistor_3p",
                    "label": "F1",
                    "args": {"Name": "F1", "fs": "0.1", "fe": "0.2", "ft": "1", "Init": "1", "chg": "0.01", "I": "#I", "V": "#V"},
                    "pins": {"0": "", "1": ""},
                    "canvas": "canvas_0",
                }
            ),
            "canvas_0_1091": FakeComponent(
                {
                    "id": "canvas_0_1091",
                    "definition": "model/CloudPSS/_newBus_3p",
                    "args": {"Name": "Bus5"},
                    "pins": {"0": ""},
                    "canvas": "canvas_0",
                }
            ),
        }
        self.cells = dict(self.components)
        self.revision = SimpleNamespace(
            implements=SimpleNamespace(
                diagram=SimpleNamespace(cells=self.cells, canvas=[{"key": "canvas_0"}])
            )
        )
        self.jobs = [{"rid": "function/CloudPSS/emtp", "args": {"output_channels": []}}]
        self._next_component = 0
        self.fail_remove_id = None
        self.definition_queries = []

    def toJSON(self):
        # Match CloudPSS DiagramImplement: every live cell must be an SDK-like
        # object and must support toJSON().
        cells = {key: value.toJSON() for key, value in self.cells.items()}
        return {"revision": {"implements": {"diagram": {"cells": cells}}}, "jobs": self.jobs}

    def getAllComponents(self):
        return self.components

    def getComponentsByRid(self, definition):
        self.definition_queries.append(definition)
        return {
            component_id: component
            for component_id, component in self.components.items()
            if component.data.get("definition") == definition
        }

    def addComponent(self, definition, label, args, pins, canvas=None):
        self._next_component += 1
        component_id = f"created-{self._next_component}"
        component = FakeComponent(
            {
                "id": component_id,
                "definition": definition,
                "label": label,
                "args": args,
                "pins": pins,
                "canvas": canvas,
            }
        )
        self.components[component_id] = component
        self.cells[component_id] = component
        return component

    def removeComponent(self, component_id):
        if component_id == self.fail_remove_id:
            raise RuntimeError("injected remove failure")
        self.components.pop(component_id, None)
        self.cells.pop(component_id, None)


def add_component(model, data):
    component = FakeComponent(data)
    model.components[component.id] = component
    model.cells[component.id] = component
    return component


def add_edge(model, edge_id, source_id, source_port, target_id, target_port):
    model.cells[edge_id] = FakeDiagramCell(
        {
            "id": edge_id,
            "shape": "diagram-edge",
            "source": {"cell": source_id, "port": source_port},
            "target": {"cell": target_id, "port": target_port},
        }
    )


def fake_add_diagram_edge(model, *, source_id, source_port, target_id, target_port, canvas):
    edge_id = f"fault-edge-{len(model.cells)}"
    add_edge(model, edge_id, source_id, source_port, target_id, target_port)
    return edge_id


def deletion_model(*, shared_gnd=False, shared_channel=False, mixed_output=True):
    model = FakeModel()
    add_component(
        model,
        {
            "id": "gnd-1",
            "definition": runtime.GND_DEFINITION,
            "args": {"Name": "GND-1"},
            "pins": {"0": ""},
        },
    )
    add_component(
        model,
        {
            "id": "channel-1",
            "definition": runtime.CHANNEL_DEFINITION,
            "args": {"Name": "#I"},
            "pins": {"0": "#I"},
        },
    )
    model.components["fault-1"].pins.clear()
    model.components["fault-1"].args["V"] = ""
    add_edge(model, "fault-target", "canvas_0_1091", "0", "fault-1", "0")
    add_edge(model, "fault-ground", "fault-1", "1", "gnd-1", "0")
    add_component(
        model,
        {
            "id": "other-1",
            "definition": "model/CloudPSS/Load",
            "args": {"Name": "Other"},
            "pins": {"0": ""},
        },
    )
    if shared_gnd:
        add_edge(model, "other-ground", "other-1", "0", "gnd-1", "0")
    if shared_channel:
        add_component(
            model,
            {
                "id": "fault-2",
                "definition": runtime.FAULT_DEFINITION,
                "args": {"Name": "F2", "I": "#I"},
                "pins": {"0": "", "1": ""},
            },
        )
    selected = ["channel-1", "other-channel"] if mixed_output else ["channel-1"]
    model.jobs[0]["args"]["output_channels"] = [
        {"0": "fault current", "1": 2000, "2": "compressed", "3": 1, "4": selected, "unknown": "keep"}
    ]
    return model


runtime._add_diagram_edge = fake_add_diagram_edge


with tempfile.TemporaryDirectory() as snapshot_dir:
    state = {"original_rid": "model/example/fake", "memory_model": FakeModel(), "snapshot_dir": snapshot_dir}
    query = inspect_model_from_context(state)
    queried_faults = query["faults"]
    assert queried_faults
    assert "current_unit" not in queried_faults[0]
    assert "cells" not in query
    assert "output_channels" not in query
    assert runtime.FAULT_DEFINITION in state["memory_model"].definition_queries
    compact_query = edit_model_from_context(EditRequest("query"), state)
    assert compact_query["faults"]
    assert "cells" not in compact_query
    full_query = edit_model_from_context(
        EditRequest("query", options={"include_cells": True}), state
    )
    assert "cells" in full_query
    preview = edit_model_from_context(EditRequest("update", {"id": "fault-1"}, {"fs": "1", "fe": "2", "ft": "7"}), state)
    assert preview["status"] == "preview_required"
    changed = edit_model_from_context(EditRequest("update", confirmation="确认执行"), state)
    assert changed["status"] == "changed"
    assert state["memory_model"].components["fault-1"].args["ft"] == "7"

with tempfile.TemporaryDirectory() as snapshot_dir:
    model = FakeModel()
    state = {"original_rid": "model/example/fake", "memory_model": model, "snapshot_dir": snapshot_dir}
    model.cells["branch-1"] = FakeDiagramCell({"id": "branch-1", "shape": "diagram-edge", "source": {"cell": "canvas_0_1091", "port": "0"}, "target": {"cell": "line-1", "port": "0"}})
    request = EditRequest(
        "create",
        {"component_id": "Bus5", "port": "0"},
        {"fs": "1", "fe": "2", "ft": "7", "Init": "1", "chg": "0.01"},
        options={"name": "Bus5三相故障"},
    )
    preview = edit_model_from_context(request, state)
    assert preview["preview"]["details"]["target"]["component_id"] == "canvas_0_1091"
    assert state["pending_preview"]["request"]["changes"] == {"fs": "1", "fe": "2", "ft": "7", "Init": "1", "chg": "0.01"}
    changed = edit_model_from_context(EditRequest("create", confirmation="确认执行"), state)
    assert changed["status"] == "changed"
    fault_id = changed["changed"]["fault_id"]
    fault_component = model.components[fault_id]
    assert fault_component.pins["0"].startswith("AutoAddPin")
    assert fault_component.pins["1"] == "GND"
    assert str(fault_component.args["I"]).endswith(".I")
    serialized = model.toJSON()
    edge_cells = [cell for cell in serialized["revision"]["implements"]["diagram"]["cells"].values() if cell.get("shape") == "diagram-edge"]
    assert len(edge_cells) == 3
    assert any(edge.get("source", {}).get("cell") == "canvas_0_1091" and edge.get("target", {}).get("cell") == fault_id for edge in edge_cells)
    assert any(edge.get("source", {}).get("cell") == fault_id and edge.get("target", {}).get("cell") == changed["changed"]["gnd_id"] for edge in edge_cells)

    missing_state = {"original_rid": "model/example/fake", "memory_model": FakeModel(), "snapshot_dir": snapshot_dir}
    try:
        edit_model_from_context(
            EditRequest("create", {"component_id": "MissingBus", "port": "0"}, request.changes, options=request.options),
            missing_state,
        )
    except ValueError as exc:
        assert "does not exist" in str(exc)
    else:
        raise AssertionError("Missing target name must be rejected")

    ambiguous_model = FakeModel()
    duplicate = FakeComponent({"id": "canvas_0_2091", "definition": "model/CloudPSS/Bus", "args": {"Name": "Bus5"}, "pins": {"0": ""}, "canvas": "canvas_0"})
    ambiguous_model.components[duplicate.id] = duplicate
    ambiguous_model.cells[duplicate.id] = duplicate
    ambiguous_state = {"original_rid": "model/example/fake", "memory_model": ambiguous_model, "snapshot_dir": snapshot_dir}
    try:
        edit_model_from_context(request, ambiguous_state)
    except ValueError as exc:
        assert "ambiguous" in str(exc)
    else:
        raise AssertionError("Ambiguous target name must be rejected")

with tempfile.TemporaryDirectory() as snapshot_dir:
    model = deletion_model()
    state = {"original_rid": "model/example/fake", "memory_model": model, "snapshot_dir": snapshot_dir}
    preview = edit_model_from_context(EditRequest("delete", {"id": "fault-1"}), state)
    plan = preview["preview"]["details"]["delete_plan"]
    assert plan["uncertain"] == []
    assert set(plan["delete_component_ids"]) == {"fault-1", "gnd-1", "channel-1"}
    changed = edit_model_from_context(EditRequest("delete", confirmation="确认执行"), state)
    committed = state["memory_model"]
    assert changed["status"] == "changed"
    assert not ({"fault-1", "gnd-1", "channel-1"} & set(committed.components))
    assert "fault-target" not in committed.cells and "fault-ground" not in committed.cells
    output = committed.jobs[0]["args"]["output_channels"][0]
    assert output["4"] == ["other-channel"] and output["unknown"] == "keep"

with tempfile.TemporaryDirectory() as snapshot_dir:
    model = deletion_model(shared_gnd=True, shared_channel=True)
    state = {"original_rid": "model/example/fake", "memory_model": model, "snapshot_dir": snapshot_dir}
    preview = edit_model_from_context(EditRequest("delete", {"id": "fault-1"}), state)
    plan = preview["preview"]["details"]["delete_plan"]
    assert plan["delete_component_ids"] == ["fault-1"]
    assert {item["component_id"] for item in plan["preserved"]} == {"gnd-1", "channel-1"}
    edit_model_from_context(EditRequest("delete", confirmation="确认执行"), state)
    committed = state["memory_model"]
    assert {"gnd-1", "channel-1"} <= set(committed.components)
    assert committed.jobs[0]["args"]["output_channels"][0]["4"] == ["channel-1", "other-channel"]

with tempfile.TemporaryDirectory() as snapshot_dir:
    model = deletion_model(mixed_output=False)
    state = {"original_rid": "model/example/fake", "memory_model": model, "snapshot_dir": snapshot_dir}
    edit_model_from_context(EditRequest("delete", {"id": "fault-1"}), state)
    edit_model_from_context(EditRequest("delete", confirmation="确认执行"), state)
    assert state["memory_model"].jobs[0]["args"]["output_channels"] == []

with tempfile.TemporaryDirectory() as snapshot_dir:
    model = deletion_model()
    state = {"original_rid": "model/example/fake", "memory_model": model, "snapshot_dir": snapshot_dir}
    edit_model_from_context(EditRequest("delete", {"id": "fault-1"}, options={"only_fault": True}), state)
    edit_model_from_context(EditRequest("delete", confirmation="确认执行"), state)
    committed = state["memory_model"]
    assert "fault-1" not in committed.components
    assert {"gnd-1", "channel-1"} <= set(committed.components)
    assert "fault-target" not in committed.cells and "fault-ground" not in committed.cells

with tempfile.TemporaryDirectory() as snapshot_dir:
    model = deletion_model()
    model.fail_remove_id = "gnd-1"
    state = {"original_rid": "model/example/fake", "memory_model": model, "snapshot_dir": snapshot_dir}
    edit_model_from_context(EditRequest("delete", {"id": "fault-1"}), state)
    try:
        edit_model_from_context(EditRequest("delete", confirmation="确认执行"), state)
    except RuntimeError as exc:
        assert "injected remove failure" in str(exc)
    else:
        raise AssertionError("Injected delete failure must be raised")
    assert state["memory_model"] is model
    assert {"fault-1", "gnd-1", "channel-1"} <= set(model.components)
print("fault-component-editor runtime verification passed")


# A JSON edit plan must survive a process boundary.  These fakes model the
# boundary by serializing the plan and by fetching a fresh model for execute.
cloud_store = {"model/example/source": deletion_model()}
save_calls = []
corrupt_readback = False


def fake_fetch_model(source):
    if source not in cloud_store:
        raise ValueError(f"missing fake cloud model: {source}")
    model = copy.deepcopy(cloud_store[source])
    if corrupt_readback and source != "model/example/source" and "fault-1" in model.components:
        model.components["fault-1"].args["chg"] = "999"
    return model


def fake_save_model_copy(model, key):
    new_rid = f"model/example/{key}"
    cloud_store[new_rid] = copy.deepcopy(model)
    save_calls.append(new_rid)
    return copy.deepcopy(model), new_rid, {"fakeSave": {"rid": new_rid}}


runtime._fetch_model_from_source = fake_fetch_model
runtime._save_model_copy = fake_save_model_copy

try:
    runtime._execute_save_copy(
        {"original_rid": "model/example/source", "memory_model": None},
        EditRequest("save_copy", options={"name": "must-not-save"}),
    )
except RuntimeError as exc:
    assert "cannot recover" in str(exc)
else:
    raise AssertionError("legacy save_copy must reject a missing in-memory edited model")

update_operations = [
    {
        "operation": "update",
        "target": {"id": "fault-1"},
        "changes": {"fs": "3", "fe": "3.1", "Init": "100000000", "chg": "0.001"},
    }
]
plan = runtime.preview_edit_plan_from_source("model/example/source", update_operations)
serialized_plan = json.loads(json.dumps(plan, ensure_ascii=False))
assert "memory_model" not in json.dumps(serialized_plan)
assert serialized_plan["status"] == "previewed"
saved = runtime.execute_edit_plan_from_source(serialized_plan, "model/example/updated")
assert saved["status"] == "verified_saved"
assert saved["new_rid"] == "model/example/updated"
assert cloud_store["model/example/updated"].components["fault-1"].args["chg"] == "0.001"

# Replaying the same sealed plan overwrites the same target snapshot and does
# not compound edits or create duplicate components.
saved_again = runtime.execute_edit_plan_from_source(serialized_plan, "model/example/updated")
assert saved_again["status"] == "verified_saved"
assert len(cloud_store["model/example/updated"].components) == len(cloud_store["model/example/source"].components)

# Preview invalidation is checked before editing or saving.
stale_plan = runtime.preview_edit_plan_from_source("model/example/source", update_operations)
cloud_store["model/example/source"].components["fault-1"].args["fs"] = "0.15"
save_count = len(save_calls)
stale = runtime.execute_edit_plan_from_source(stale_plan, "model/example/stale")
assert stale["status"] == "preview_stale"
assert len(save_calls) == save_count
cloud_store["model/example/source"].components["fault-1"].args["fs"] = "0.1"

# A delete-and-create replacement is one transaction and is verified after a
# fresh readback of the target RID.
replace_operations = [
    {"operation": "delete", "target": {"id": "fault-1"}},
    {
        "operation": "create",
        "target": {"component_id": "canvas_0_1091", "port": "0"},
        "changes": {"fs": "0.1", "fe": "0.2", "ft": "1", "Init": "1", "chg": "0.01"},
        "options": {"name": "Bus5 replacement"},
    },
]
replace_plan = runtime.preview_edit_plan_from_source("model/example/source", replace_operations)
replaced = runtime.execute_edit_plan_from_source(
    json.loads(json.dumps(replace_plan)), "model/example/replaced"
)
assert replaced["status"] == "verified_saved", replaced
replaced_model = cloud_store["model/example/replaced"]
assert "fault-1" not in replaced_model.components
assert len(runtime._matching_faults_by_name(replaced_model, "Bus5 replacement")) == 1

# If one operation fails, the target is never saved.
failed_plan = runtime.preview_edit_plan_from_source("model/example/source", update_operations)
failed_plan["operations"].append(
    {"operation": "delete", "target": {"id": "missing-fault"}, "changes": {}, "options": {}}
)
failed_plan = runtime._seal_plan(runtime._plan_payload(failed_plan))
save_count = len(save_calls)
failed = runtime.execute_edit_plan_from_source(failed_plan, "model/example/partial")
assert failed["status"] == "operation_failed"
assert len(save_calls) == save_count
assert "model/example/partial" not in cloud_store

# A successful save API response is not success when readback facts differ.
corrupt_readback = True
bad_readback = runtime.execute_edit_plan_from_source(serialized_plan, "model/example/corrupt")
corrupt_readback = False
assert bad_readback["status"] == "save_verification_failed"
assert bad_readback["verification"]["critical"]

print("fault-component-editor persistent edit-plan verification passed")
