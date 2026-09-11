"""离线验证独立 Skill 的查询、预览、新增、修改契约。"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mylib import EditRequest, edit_model_from_context, inspect_model_from_context  # noqa: E402


class FakeComponent:
    def __init__(self, data):
        self.__dict__.update(data)

    def toJSON(self):
        return dict(self.__dict__)


class FakeModel:
    def __init__(self):
        bus = FakeComponent({
            "id": "bus_1", "label": "Bus1", "definition": "model/CloudPSS/_newBus_3p",
            "canvas": "canvas_0", "args": {"Name": "Bus1", "VBase": 500}, "pins": {"0": "bus1"},
            "shape": "diagram-component",
        })
        self.components = {"bus_1": bus}
        self.revision = SimpleNamespace(
            implements=SimpleNamespace(
                diagram=SimpleNamespace(cells=self.components, canvas=[{"key": "canvas_0", "name": "Main"}])
            )
        )

    def getAllComponents(self):
        return self.components


state = {"original_rid": "model/example/IEEE39-test1", "memory_model": FakeModel(), "component_library": str(ROOT / "saSource.json")}
assert inspect_model_from_context(state, "Bus1")["component"]["pins"]["0"] == "bus1"

request = EditRequest(
    operation="create",
    target={"template_key": "_newBus_3p", "canvas": "canvas_0", "key_prefix": "ValidationBus"},
    changes={"args": {"Name": "ValidationBus", "VBase": 20}, "pins": {"0": "bus1"}, "label": "ValidationBus"},
)
preview = edit_model_from_context(request, state)
assert preview["status"] == "preview_required"
changed = edit_model_from_context(EditRequest("create", confirmation="确认执行"), state)
assert changed["status"] == "changed"
created_id = changed["changed"]["key"]
assert state["memory_model"].components[created_id].args["Name"] == "ValidationBus"

update_preview = edit_model_from_context(EditRequest("update", {"label": "ValidationBus"}, {"args": {"VBase": 110}}), state)
assert update_preview["status"] == "preview_required"
updated = edit_model_from_context(EditRequest("update", confirmation="execute"), state)
assert updated["changed"]["args"]["VBase"] == 110
assert state.get("pending_preview") is None
print("cloudpss-aux-modeling offline runtime verification passed")
