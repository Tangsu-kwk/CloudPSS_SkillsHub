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

    def toJSON(self):
        # Match CloudPSS DiagramImplement: every live cell must be an SDK-like
        # object and must support toJSON().
        cells = {key: value.toJSON() for key, value in self.cells.items()}
        return {"revision": {"implements": {"diagram": {"cells": cells}}}, "jobs": self.jobs}

    def getAllComponents(self):
        return self.components

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


runtime.try_resolve_current_parameter_metadata = lambda definition, parameter_key="I": {
    "status": "resolved",
    "definition_rid": definition,
    "parameter_key": parameter_key,
    "raw_unit": "kA",
    "normalized_unit": "kA",
    "unit_source": "parameter.name",
    "unit_scale_to_ka": 1.0,
}


with tempfile.TemporaryDirectory() as snapshot_dir:
    state = {"original_rid": "model/example/fake", "memory_model": FakeModel(), "snapshot_dir": snapshot_dir}
    queried_faults = inspect_model_from_context(state)["faults"]
    assert queried_faults
    assert queried_faults[0]["current_unit"]["raw_unit"] == "kA"
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
print("fault-component-editor runtime verification passed")
