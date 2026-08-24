"""Offline verification for the runtime's preview/edit contract."""
from __future__ import annotations

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
