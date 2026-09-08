"""Host integration and optional real-LLM dialogue against an offline SDK model.

No CloudPSS fetch/create/update/run is permitted. --dialogue requires LLM_API_KEY.
The LLM receives ordinary user requests; fixture/model data enter via host state.
"""
import argparse
import copy
import json
import os
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")
import cloudpss
import newagentv2 as host

OUT = ROOT / "testing/runs/20260908-agent-integration"
OUT.mkdir(parents=True, exist_ok=True)
SKILL = "cloudpss-aux-modeling"


def fixture():
    library = json.loads((ROOT / "skills" / SKILL / "saSource.json").read_text(encoding="utf-8"))
    cells = {}
    for i in (12, 13):
        bus = copy.deepcopy(library["_newBus_3p"])
        bus.update(id=f"bus{i}", label=f"Bus{i}", canvas="canvas_0", pins={"0": f"bus{i}"})
        bus["args"]["Name"] = f"Bus{i}"
        cells[bus["id"]] = bus
    return cloudpss.Model({"rid": "model/example/offline", "name": "Offline fixture", "description": "",
                          "tags": [], "context": {"currentConfig": 0}, "configs": [{"name": "Default", "args": {}}],
                          "jobs": [], "revision": {"version": 5, "hash": "offline", "parameters": {}, "pins": {},
                          "implements": {"diagram": {"canvas": [{"key": "canvas_0", "name": "Main"}], "cells": cells}}}})


def json_model():
    session = host.WORKFLOW_STATE.skill_sessions[SKILL]
    return session["memory_model"].toJSON()


def main(dialogue=False, extended=False):
    global OUT
    if extended:
        OUT = OUT / "extended"
        OUT.mkdir(parents=True, exist_ok=True)
    discovered = host.discover_skills(ROOT / "skills")
    aux = next(item for item in discovered if item.name == SKILL)
    assert set(aux.entrypoints) == {"edit_model_from_context", "inspect_model_from_context"}
    host.WORKFLOW_STATE = host.WorkflowState()
    session = {"original_rid": "model/example/offline", "memory_model": fixture()}
    host.WORKFLOW_STATE.skill_sessions[SKILL] = session
    calls = []
    secrets = [os.getenv(k, "") for k in ("LLM_API_KEY", "SIMSTUDIO_TOKEN", "CLOUDPSS_TOKEN")]
    def clean(value):
        result = json.dumps(value, ensure_ascii=False, default=str)
        for secret in secrets:
            if secret:
                result = result.replace(secret, "[REDACTED]")
        return result
    def save(name, value):
        (OUT / name).write_text(clean(value), encoding="utf-8")
    executor = host.DynamicSkillExecutor(ROOT / "skills", discovered)
    def invoke(request, entry="edit_model_from_context"):
        observation = executor(host.DynamicSkillAction(skill=SKILL, entrypoint=entry, request=request))
        raw = observation.model_dump(mode="json")
        # Observation stores text in a content block in this OpenHands version.
        text = "".join(item.get("text", "") for item in raw.get("content", []))
        result = json.loads(text)
        calls.append({"request": request, "entrypoint": entry, "result": result})
        return result
    with ExitStack() as stack:
        for cls, name in ((cloudpss.Model, "fetch"), (cloudpss.Model, "create"), (cloudpss.Model, "update"),
                          (cloudpss.Model, "save"), (cloudpss.ModelRevision, "create"),
                          (cloudpss.ModelTopology, "fetch"), (cloudpss.ModelRevision, "run")):
            stack.enter_context(patch.object(cls, name, side_effect=RuntimeError("Offline fixture: CloudPSS network disabled")))
        if not dialogue:
            assert len(invoke({"operation": "list_templates"})["templates"]) == 21
            assert invoke({"offset": 1, "limit": 1}, "inspect_model_from_context")["components"][0]["key"] == "bus13"
            assert invoke({"operation": "query", "target": {"identifier": "Bus12"}})["component"]["key"] == "bus12"
            selected = invoke({"operation": "query", "target": {"identifier": "Bus12"},
                               "options": {"fields": ["VBase", "Name"]}})
            assert set(selected["component"]["args"]) == {"VBase", "Name"}
            assert invoke({"limit": 1}, "inspect_model_from_context")["diagram_edge_count"] == 0
            assert "error" in invoke({"operation": "query", "target": {"canvas": "canvas_0"}})
            assert "error" in invoke({"operation": "query", "options": {"fields": ["unknown"]}})
            assert "error" in invoke({"operation": "query", "session_state": {"toolbox": "forbidden"}})
            before = copy.deepcopy(json_model())
            preview = invoke({"operation": "create", "target": {"template_key": "_NewVoltageMeter", "canvas": "canvas_0"},
                              "changes": {"label": "Bus12电压表", "args": {"Dim": "3", "V": "#bus12_voltage"},
                                          "pins": {"0": "bus12"}}})
            assert json_model() == before
            created = invoke({"operation": "create", "preview_id": preview["preview_id"], "confirmation": "execute"})
            key = created["changed"]["key"]
            assert invoke({"identifier": key}, "inspect_model_from_context")["component"]["pins"]["0"] == "bus12"
            p = invoke({"operation": "update", "target": {"key": key}, "changes": {"args": {"V": "#updated"}}})
            invoke({"operation": "cancel_preview", "preview_id": p["preview_id"]})
            assert "error" in invoke({"operation": "update", "preview_id": p["preview_id"], "confirmation": "execute"})
            assert "error" in invoke({"operation": "saveProject", "target": {"new_rid": session["original_rid"]}})
            p = invoke({"operation": "delete", "target": {"key": key}})
            invoke({"operation": "delete", "preview_id": p["preview_id"], "confirmation": "execute"})
            assert key not in session["memory_model"].getAllComponents()
            # Reference-based update: read one component, apply only compatible args to another.
            ref = invoke({"operation": "query", "target": {"identifier": "Bus12"}})["component"]["args"]
            p = invoke({"operation": "update", "target": {"key": "bus13"},
                        "changes": {"args": {"VBase": ref["VBase"]}, "label": "Bus13_ref"}})
            invoke({"operation": "update", "preview_id": p["preview_id"], "confirmation": "execute"})
            assert invoke({"operation": "query", "target": {"identifier": "Bus13_ref"},
                           "options": {"fields": ["VBase"]}})["component"]["args"]["VBase"] == ref["VBase"]
            # Missing field and failed middle item do not silently apply later work.
            assert "error" in invoke({"operation": "update", "target": {"key": "bus13"},
                                       "changes": {"args": {"unknown": 1}}})
            # Independent entrypoint names with declared session_state work too.
            from types import SimpleNamespace
            def probe_from_context(session_state, *, value):
                session_state["n"] = session_state.get("n", 0) + value
                return {"n": session_state["n"]}
            probe = SimpleNamespace(name="session-probe", runtime=SimpleNamespace(probe_from_context=probe_from_context),
                                    entrypoints=("probe_from_context",))
            generic = host.DynamicSkillExecutor(ROOT / "skills", [probe])
            for value in (2, 3):
                generic(host.DynamicSkillAction(skill=probe.name, entrypoint="probe_from_context", request={"value": value}))
            assert host.WORKFLOW_STATE.skill_sessions[probe.name]["n"] == 5
            save("host-contract.json", {"mode": "offline_host_dispatch", "passed": True, "calls": calls,
                                         "llm_used": False, "cloud_saved": False, "simulation_run": False})
            print("Host discovery/session/pagination/preview/create/read/cancel/delete contract passed")
            return
        from openhands.sdk import Conversation
        from openhands.sdk.conversation.response_utils import get_agent_final_response
        os.environ.setdefault("SIMSTUDIO_TOKEN", "offline-fixture-no-cloud-access")
        os.environ.setdefault("CLOUDPSS_API_URL", "https://cloudpss.net/")
        events = OUT / "dialogue-events.jsonl"
        events.write_text("", encoding="utf-8")
        def on_event(event):
            with events.open("a", encoding="utf-8") as handle:
                handle.write(clean(event.model_dump(mode="json")) + "\n")
        turns = []
        messages = [
            "帮我看看 model/example/offline 这个模型里的 Bus12，电压等级和接线是什么样的？",
            "帮我在 Bus12 上加一个三相电压表，输出叫 bus12_voltage，标签叫 Bus12电压表，先给我看看方案。",
            "就按这个方案加。",
            "把刚才电压表的输出改成 bus12_voltage_new，其他保持原样，先给我看看。",
            "先不改了，取消这个修改。",
            "查一下刚才的电压表，确认输出名还是原来那个。",
            "把刚才加的 Bus12电压表删掉，先告诉我会影响什么。",
            "确认删除刚才的电压表。",
        ]
        if extended:
            messages = [
                "帮我看看 model/example/offline 里的 Bus12 接线和参数，单位不确定的就标出来。",
                "帮我加三个常量，分别叫常量甲、常量乙、常量丙，值分别是1、2、3，放到Main画布，先把整体方案给我。",
                "确认这三个常量的整体方案，按方案逐个加，遇到失败就停下来告诉我，不用保存云端。",
                "我想把改好的模型保存到 model/example/edited_copy，先给我看保存方案，不要执行。",
                "暂时不保存了，取消这个保存方案，再查一下刚才三个常量的值。",
            ]
        conversation = Conversation(agent=host.create_agent(skills_dir=ROOT / "skills"), workspace=ROOT,
                                    callbacks=[on_event], visualizer=None, max_iteration_per_run=12)
        try:
            for i, message in enumerate(messages):
                before = copy.deepcopy(json_model())
                host.WORKFLOW_STATE.begin_turn()
                conversation.send_message(message)
                conversation.run()
                final = get_agent_final_response(list(conversation.state.events))
                turns.append({"user": message, "assistant": str(final)})
                save("dialogue-turns.json", turns)
                save(f"dialogue-snapshot-{i}.json", json_model())
                cells = session["memory_model"].getAllComponents()
                meters = [c for c in cells.values() if getattr(c, "label", None) == "Bus12电压表"]
                if extended:
                    if i != 2:
                        assert json_model() == before, f"Unexpected mutation at turn {i}"
                    if i >= 2:
                        for label, value in (("常量甲", 1), ("常量乙", 2), ("常量丙", 3)):
                            matches = [c for c in cells.values() if getattr(c, "label", None) == label]
                            assert len(matches) == 1, f"Missing {label}"
                            arg = matches[0].args["Value"]
                            arg = arg.get("source") if isinstance(arg, dict) else arg
                            assert float(arg) == value
                    if i == 3:
                        assert any(p["operation"] == "saveProject" for p in session.get("previews", {}).values())
                    if i == 4:
                        assert not any(p["operation"] == "saveProject" for p in session.get("previews", {}).values())
                    print(f"Extended dialogue turn {i + 1}/{len(messages)} assertions passed", flush=True)
                    continue
                if i in (0, 1, 3, 4, 5, 6):
                    assert json_model() == before, f"Unexpected mutation at turn {i}"
                if i in (2, 4, 5, 6):
                    assert len(meters) == 1 and meters[0].pins["0"] == "bus12", f"Missing meter at turn {i}"
                    assert meters[0].args["V"].lstrip("#") == "bus12_voltage"
                if i == 7:
                    assert not meters, "Delete did not execute"
                print(f"Dialogue turn {i + 1}/{len(messages)} assertions passed", flush=True)
            save("dialogue-result.json", {"passed": True, "llm_used": True, "model_backend": "offline_fixture",
                                          "cloud_topology": "unavailable_by_design", "cloud_saved": False,
                                          "simulation_run": False})
        except Exception as exc:
            save("dialogue-result.json", {"passed": False, "error": str(exc), "completed_turns": len(turns),
                                          "llm_used": True, "model_backend": "offline_fixture"})
            raise
        finally:
            conversation.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dialogue", action="store_true")
    parser.add_argument("--extended", action="store_true")
    args = parser.parse_args()
    main(args.dialogue, args.extended)
