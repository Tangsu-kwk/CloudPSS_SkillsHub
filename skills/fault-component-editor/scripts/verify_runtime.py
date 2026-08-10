"""Offline verification for the runtime's preview/edit contract."""
from __future__ import annotations

import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from mylib import EditRequest, edit_model_from_context, inspect_model_from_context  # noqa: E402


class FakeComponent:
    def __init__(self, data):
        self.data = data
        self.args = data.setdefault("args", {})

    def toJSON(self):
        return self.data


class FakeModel:
    def __init__(self):
        self.components = {
            "fault-1": FakeComponent(
                {
                    "definition": "model/CloudPSS/_newFaultResistor_3p",
                    "label": "F1",
                    "args": {"Name": "F1", "fs": "0.1", "fe": "0.2", "ft": "1", "Init": "1", "chg": "0.01", "I": "#I", "V": "#V"},
                }
            )
        }

    def toJSON(self):
        return {"revision": {"implements": {"diagram": {"cells": {k: v.toJSON() for k, v in self.components.items()}}}}}

    def getAllComponents(self):
        return self.components


state = {"original_rid": "model/example/fake", "memory_model": FakeModel(), "snapshot_dir": str(Path.cwd() / "results" / "fault_component_editor_test")}
assert inspect_model_from_context(state)["faults"]
preview = edit_model_from_context(EditRequest("update", {"id": "fault-1"}, {"fs": "1", "fe": "2", "ft": "7"}), state)
assert preview["status"] == "preview_required"
changed = edit_model_from_context(EditRequest("update", confirmation="确认执行"), state)
assert changed["status"] == "changed"
assert state["memory_model"].components["fault-1"].args["ft"] == "7"
print("fault-component-editor runtime verification passed")
