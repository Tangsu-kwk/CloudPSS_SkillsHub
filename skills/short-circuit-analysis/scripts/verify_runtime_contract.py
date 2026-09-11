"""Offline contract checks for the short-circuit-analysis bundled runtime."""

from __future__ import annotations

import csv
import importlib
import json
import os
import py_compile
import sys
import tempfile
import types
from pathlib import Path


RUNTIME_PATH = Path(__file__).resolve().parents[1] / "mylib" / "runtime.py"


def load_runtime():
    skill_dir = RUNTIME_PATH.parents[1]
    if str(skill_dir) not in sys.path:
        sys.path.insert(0, str(skill_dir))
    return importlib.import_module("mylib.runtime")


class FailedEmtModel:
    def runEMT(self):
        raise RuntimeError("synthetic EMT failure")


class EmptyResult:
    def getPlots(self):
        return []


class NoChannelModel:
    name = "NoChannel"
    rid = "model/NoChannel"

    def runEMT(self):
        return types.SimpleNamespace(
            id="synthetic-job",
            status=lambda: 1,
            result=EmptyResult(),
        )


class SyntheticResult:
    """Small EMTResult-shaped fixture with three fault-current channels."""

    def __init__(self):
        self.x_values = [index * 0.05 for index in range(201)]
        self.channels = {
            "#Ifault_bus5:0": [1.0 if 2.0 <= x <= 7.0 else 0.1 for x in self.x_values],
            "#Ifault_bus5:1": [2.0 if 2.0 <= x <= 7.0 else 0.2 for x in self.x_values],
            "#Ifault_bus5:2": [3.0 if 2.0 <= x <= 7.0 else 0.3 for x in self.x_values],
            "vac:0": [1.0 for _ in self.x_values],
            "#P1:0": [10.0 for _ in self.x_values],
        }

    def getPlots(self):
        return [{"key": "fault-currents"}]

    def getPlotChannelNames(self, index):
        assert index == 0
        return list(self.channels)

    def getPlotChannelData(self, index, channel_name):
        assert index == 0
        return {"x": self.x_values, "y": self.channels[channel_name]}


class SyntheticEmtModel:
    name = "SyntheticFaultModel"
    rid = "model/Synthetic/FaultModel"

    def __init__(self):
        self.run_count = 0

    def runEMT(self):
        self.run_count += 1
        return types.SimpleNamespace(
            id="synthetic-success-job",
            status=lambda: 1,
            result=SyntheticResult(),
        )


class SyntheticComponent:
    def __init__(self, payload):
        self.payload = payload

    def toJSON(self):
        return self.payload


class FaultCandidateModel:
    name = "FaultCandidateModel"
    rid = "model/Synthetic/FaultCandidates"

    def __init__(self, faults):
        self.faults = faults
        self.run_count = 0

    def getAllComponents(self):
        return {
            fault["id"]: SyntheticComponent(
                {
                    "definition": "model/CloudPSS/_newFaultResistor_3p",
                    "args": {
                        "Name": fault["name"],
                        "I": fault.get("current_channel"),
                        "fs": fault.get("start_time_s", 2.0),
                        "fe": fault.get("end_time_s", 2.1),
                    },
                }
            )
            for fault in self.faults
        }

    def runEMT(self):
        self.run_count += 1
        raise AssertionError("fault candidate inspection must not start EMT")


def assert_raises(exc_type, callback, message: str) -> None:
    try:
        callback()
    except exc_type:
        return
    raise AssertionError(message)


def main() -> None:
    runtime = load_runtime()

    original_auth = {
        name: os.environ.get(name)
        for name in ("CLOUDPSS_TOKEN", "CLOUDPSS_LOGIN_TOKEN", "SIMSTUDIO_TOKEN")
    }
    original_set_token = runtime.setToken
    captured_tokens: list[str] = []
    try:
        for name in original_auth:
            os.environ.pop(name, None)
        os.environ["CLOUDPSS_LOGIN_TOKEN"] = "synthetic-login-token"
        runtime.setToken = captured_tokens.append
        runtime._configure_cloudpss_auth()
        assert captured_tokens == ["synthetic-login-token"]

        os.environ["CLOUDPSS_TOKEN"] = "synthetic-sdk-token"
        runtime._configure_cloudpss_auth()
        assert captured_tokens[-1] == "synthetic-sdk-token"

        for name in original_auth:
            os.environ.pop(name, None)
        try:
            runtime._configure_cloudpss_auth()
        except RuntimeError as exc:
            assert str(exc) == "CloudPSS authentication is not configured by the host"
            assert "synthetic" not in str(exc)
        else:
            raise AssertionError("missing host authentication must fail before SDK access")
    finally:
        runtime.setToken = original_set_token
        for name, value in original_auth.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    # Entrypoint fixtures use a dummy token; no credential value is written to artifacts.
    os.environ.setdefault("CLOUDPSS_TOKEN", "runtime-contract-token")

    assert runtime._looks_like_current_channel("#Ifault_bus5:0")
    assert runtime._looks_like_current_channel("#Iabc_line:1")
    assert not runtime._looks_like_current_channel("#P1:0")
    assert not runtime._looks_like_current_channel("vac:0")
    assert not runtime._looks_like_current_channel("frequency:0")

    pairs = runtime._pair_named_channels(
        ["#P1:0", "#P2:0"],
        ["vac:0", "vac:1"],
        3,
    )
    assert pairs == [
        {"power": "#P1:0", "voltage": "vac:0"},
        {"power": "#P2:0", "voltage": "vac:1"},
    ]
    assert runtime._pair_named_channels(["#P1:0"], ["voltage_bus_a", "voltage_bus_b"], 3) == []

    assert_raises(
        ValueError,
        lambda: runtime._resolve_config({"channels": {"voltage": ["vac:0"]}}),
        "voltage channels must not be treated as current",
    )
    assert_raises(
        ValueError,
        lambda: runtime._resolve_config({"output": {"generate_report": True}}),
        "production output files must not be enabled through config",
    )
    assert_raises(
        ValueError,
        lambda: runtime._select_explicit_traces(
            SyntheticResult(), {"current": ["vac:0"]}
        ),
        "explicit voltage channels must not bypass current-channel validation",
    )

    snapshot = {
        "voltage_resolution": {
            "value_kv": 525.0,
            "source": "model.Bus_5_Vbase",
            "fault_bus": "Bus5",
        },
        "jobs": [],
        "faults": {"active": [{"start_time_s": 2.0, "end_time_s": 2.2}]},
    }
    merged = runtime._merge_analysis_config(
        {"analysis": {"base_voltage_kv": 230.0}},
        snapshot,
    )
    assert merged["analysis"]["base_voltage_kv"] == 525.0
    assert merged["analysis"]["requested_base_voltage_kv"] == 230.0
    assert merged["analysis"]["base_voltage_conflict"]["resolution"] == "model_value_used"
    assert_raises(
        ValueError,
        lambda: runtime._merge_analysis_config(
            {"analysis": {"current_scale": 1.0}}, snapshot
        ),
        "legacy current_scale must not bypass component-unit resolution",
    )

    topology_model = {
        "revision": {
            "implements": {
                "diagram": {
                    "cells": {
                        "fault-cell": {
                            "shape": "diagram-component",
                            "definition": "model/CloudPSS/_newFaultResistor_3p",
                        },
                        "bus-cell": {
                            "shape": "diagram-component",
                            "definition": "model/CloudPSS/_newBus_3p",
                            "args": {"Name": "Bus8"},
                        },
                        "fault-edge": {
                            "shape": "diagram-edge",
                            "source": {"cell": "fault-cell"},
                            "target": {"cell": "bus-cell"},
                        },
                    },
                    "variables": [
                        {"key": "Bus_8_Vbase", "value": {"source": "525"}},
                    ],
                }
            }
        }
    }
    topology_components = {
        "fault-cell": {
            "definition": "model/CloudPSS/_newFaultResistor_3p",
            "args": {"I": "#I", "V": "#V", "fs": "3", "fe": "3.2", "ft": "7"},
        },
        "bus-cell": {
            "definition": "model/CloudPSS/_newBus_3p",
            "args": {"Name": "Bus8"},
        },
    }
    topology_faults = runtime._fault_context(topology_components)
    assert topology_faults["active"][0]["start_time_s"] == 3.0
    assert topology_faults["active"][0]["end_time_s"] == 3.2
    topology_resolution = runtime._resolve_base_voltage(
        topology_model,
        topology_components,
        topology_faults,
    )
    assert topology_resolution["fault_bus"] == "Bus8"
    assert topology_resolution["value_kv"] == 525.0
    assert topology_resolution["source"].endswith("Bus_8_Vbase")

    multi_faults = {
        "active": [
            {"id": "fault-a", "name": "Bus5 fault", "current_channel": "#Ifault_bus5"},
            {"id": "fault-b", "name": "Bus8 fault", "current_channel": "#Ifault_bus8"},
        ]
    }
    assert_raises(
        ValueError,
        lambda: runtime._resolve_target_fault(multi_faults),
        "multiple active faults must require an explicit analysis target",
    )
    selected_fault = runtime._resolve_target_fault(multi_faults, "fault-b")
    assert selected_fault["id"] == "fault-b"
    selected_fault_by_name = runtime._resolve_target_fault(multi_faults, "Bus5 fault")
    assert selected_fault_by_name["id"] == "fault-a"
    assert_raises(
        ValueError,
        lambda: runtime._resolve_target_fault(multi_faults, "missing-fault"),
        "unknown target fault must fail",
    )
    selected_sources = runtime._declared_current_channel_sources(
        multi_faults,
        {"bus_current_channel": "#Ibus8", "fault_bus_component_id": "bus-cell"},
        selected_fault,
    )
    assert [source["channel"] for source in selected_sources] == [
        "#Ifault_bus8",
        "#Ibus8",
    ]

    multi_topology_model = {
        "revision": {
            "implements": {
                "diagram": {
                    "cells": {
                        "fault-a": {"definition": "model/CloudPSS/_newFaultResistor_3p"},
                        "fault-b": {"definition": "model/CloudPSS/_newFaultResistor_3p"},
                        "bus-5": {
                            "definition": "model/CloudPSS/_newBus_3p",
                            "args": {"Name": "Bus5", "VBase": "220", "I": "#Ibus5"},
                        },
                        "bus-8": {
                            "definition": "model/CloudPSS/_newBus_3p",
                            "args": {"Name": "Bus8", "VBase": "525", "I": "#Ibus8"},
                        },
                        "edge-a": {
                            "shape": "diagram-edge",
                            "source": {"cell": "fault-a"},
                            "target": {"cell": "bus-5"},
                        },
                        "edge-b": {
                            "shape": "diagram-edge",
                            "source": {"cell": "fault-b"},
                            "target": {"cell": "bus-8"},
                        },
                    },
                    "variables": [],
                }
            }
        }
    }
    multi_components = multi_topology_model["revision"]["implements"]["diagram"]["cells"]
    selected_resolution = runtime._resolve_base_voltage(
        multi_topology_model, multi_components, multi_faults, selected_fault
    )
    assert selected_resolution["fault_bus"] == "Bus8"
    assert selected_resolution["value_kv"] == 525.0
    assert selected_resolution["bus_current_channel"] == "#Ibus8"

    original_load = runtime.load_model_from_source
    try:
        candidate_models = {
            "model/Synthetic/NoFault": FaultCandidateModel([]),
            "model/Synthetic/OneFault": FaultCandidateModel(
                [{"id": "fault-a", "name": "Bus5 fault", "current_channel": "#Ifault5"}]
            ),
            "model/Synthetic/TwoFaults": FaultCandidateModel(
                [
                    {"id": "fault-a", "name": "Bus5 fault", "current_channel": "#Ifault5"},
                    {"id": "fault-b", "name": "Bus8 fault", "current_channel": "#Ifault8"},
                ]
            ),
        }
        runtime.load_model_from_source = lambda source, **_kwargs: candidate_models[source]

        no_fault = runtime.inspect_fault_candidates_from_source("model/Synthetic/NoFault")
        assert no_fault["fault_count"] == 0
        assert no_fault["selection_required"] is False
        assert no_fault["target_fault_id"] is None
        assert no_fault["emt_started"] is False

        one_fault = runtime.inspect_fault_candidates_from_source("model/Synthetic/OneFault")
        assert one_fault["fault_count"] == 1
        assert one_fault["selection_required"] is False
        assert one_fault["target_fault_id"] == "fault-a"

        two_faults = runtime.inspect_fault_candidates_from_source("model/Synthetic/TwoFaults")
        assert two_faults["fault_count"] == 2
        assert two_faults["selection_required"] is True
        assert two_faults["target_fault_id"] is None
        assert [(item["id"], item["name"]) for item in two_faults["faults"]] == [
            ("fault-a", "Bus5 fault"),
            ("fault-b", "Bus8 fault"),
        ]
        assert all(model.run_count == 0 for model in candidate_models.values())
    finally:
        runtime.load_model_from_source = original_load

    assert_raises(
        ValueError,
        lambda: runtime.analyze_model_from_source(""),
        "empty RID must fail before model loading",
    )
    assert_raises(
        RuntimeError,
        lambda: runtime.run_emt(FailedEmtModel()),
        "EMT failure must be reported",
    )

    assert_raises(
        ValueError,
        lambda: runtime.run_short_circuit_analysis(
            object(),
            config={"analysis": {"base_voltage_kv": None}},
        ),
        "missing base voltage must fail",
    )
    assert_raises(
        RuntimeError,
        lambda: runtime.run_short_circuit_analysis(
            NoChannelModel(),
            config={"analysis": {"base_voltage_kv": 110.0}},
        ),
        "missing channels must fail instead of fabricating results",
    )

    original_run_emt = runtime.run_emt
    try:
        runtime.run_emt = lambda model, timeout=300: model.runEMT()
        result = runtime.run_short_circuit_analysis(
            SyntheticEmtModel(),
            config={
                "analysis": {
                    "base_voltage_kv": 525.0,
                    "base_voltage_source": "model.Bus_5_Vbase",
                    "fault_bus": "Bus5",
                    "fault_current_channel": "#Ifault_bus5",
                    "declared_current_sources": [
                        {
                            "kind": "fault_element",
                            "component_id": "fault-cell",
                            "definition": "model/CloudPSS/_newFaultResistor_3p",
                            "parameter_key": "I",
                            "channel": "#Ifault_bus5",
                            "current_unit": {
                                "definition_rid": "model/CloudPSS/_newFaultResistor_3p",
                                "parameter_key": "I",
                                "raw_unit": "kA",
                                "normalized_unit": "kA",
                                "unit_source": "parameter.name",
                                "unit_scale_to_ka": 1.0,
                            },
                        }
                    ],
                    "analysis_window": [0.0, 10.0],
                    "prefault_window": [0.0, 2.0],
                    "fault_window": [2.0, 7.0],
                    "postfault_window": [7.0, 10.0],
                    "min_samples": 2,
                },
                "channels": {"auto_max_channels": 3},
                "thevenin": {"enabled": False},
            },
        )
    finally:
        runtime.run_emt = original_run_emt

    expected_channels = ["#Ifault_bus5:0", "#Ifault_bus5:1", "#Ifault_bus5:2"]
    assert result["task_id"] == "synthetic-success-job"
    assert [row["channel"] for row in result["channels"]] == expected_channels
    assert result["analysis"]["steady_fault_window"] == [3.0, 6.0]
    assert result["analysis"]["steady_fault_window_explicit"] is False
    assert result["summary"]["max_steady_fault_rms_current"] == 3.0
    assert "artifacts" not in result

    with tempfile.TemporaryDirectory() as output_dir:
        original_load = runtime.load_model_from_source
        original_inspect = runtime.inspect_model
        try:
            runtime.load_model_from_source = lambda _source, **_kwargs: object()
            runtime.inspect_model = lambda _model, **_kwargs: {
                "model": {"name": "NoFault", "rid": "model/NoFault"},
                "revision": {},
                "context": {},
                "jobs": [],
                "configs": [],
                "component_count": 0,
                "component_summary": [],
                "voltage_candidates": [],
                "voltage_resolution": {
                    "value_kv": 110.0,
                    "source": "model.VBase",
                    "fault_bus": None,
                },
                "faults": {"active": []},
            }
            assert_raises(
                RuntimeError,
                lambda: runtime.analyze_model_from_source(
                    "model/NoFault",
                    output_dir=output_dir,
                ),
                "models without an active fault must fail",
            )
            error_files = list(Path(output_dir).glob("analysis_error_*.json"))
            assert error_files, "failed analysis must write analysis_error.json"
        finally:
            runtime.load_model_from_source = original_load
            runtime.inspect_model = original_inspect

    with tempfile.TemporaryDirectory() as output_dir:
        original_load = runtime.load_model_from_source
        original_inspect = runtime.inspect_model
        original_run_emt = runtime.run_emt
        synthetic_snapshot = {
            "model": {"name": "SyntheticFaultModel", "rid": "model/Synthetic/FaultModel"},
            "revision": {},
            "context": {},
            "jobs": [],
            "configs": [],
            "component_count": 1,
            "component_summary": [],
            "voltage_candidates": [],
            "voltage_resolution": {
                "value_kv": 525.0,
                "source": "model.Bus_5_Vbase",
                "fault_bus": "Bus5",
            },
            "faults": {
                "active": [
                    {
                        "id": "fault-cell",
                        "current_channel": "#Ifault_bus5",
                        "start_time_s": 2.0,
                        "end_time_s": 7.0,
                    }
                ]
            },
            "target_fault": {
                "id": "fault-cell",
                "current_channel": "#Ifault_bus5",
                "start_time_s": 2.0,
                "end_time_s": 7.0,
            },
            "declared_current_sources": [
                {
                    "kind": "fault_element",
                    "component_id": "fault-cell",
                    "channel": "#Ifault_bus5",
                    "source": "components.fault-cell.args.I",
                    "definition": "model/CloudPSS/_newFaultResistor_3p",
                    "parameter_key": "I",
                    "current_unit": {
                        "definition_rid": "model/CloudPSS/_newFaultResistor_3p",
                        "parameter_key": "I",
                        "raw_unit": "A",
                        "normalized_unit": "kA",
                        "unit_source": "parameter.unit",
                        "unit_scale_to_ka": 0.001,
                    },
                }
            ],
        }
        synthetic_model = SyntheticEmtModel()
        try:
            runtime.load_model_from_source = lambda _source, **_kwargs: synthetic_model
            runtime.inspect_model = lambda _model, **_kwargs: synthetic_snapshot
            runtime.run_emt = lambda model, timeout=300: model.runEMT()
            public_result = runtime.analyze_model_from_source(
                "model/Synthetic/FaultModel",
                config={
                    "analysis": {
                        "analysis_window": [0.0, 10.0],
                        "prefault_window": [0.0, 2.0],
                        "fault_window": [2.0, 7.0],
                        "postfault_window": [7.0, 10.0],
                        "min_samples": 2,
                    },
                    "thevenin": {"enabled": False},
                },
                output_dir=output_dir,
            )
        finally:
            runtime.load_model_from_source = original_load
            runtime.inspect_model = original_inspect
            runtime.run_emt = original_run_emt

        assert public_result == {"task_id": "synthetic-success-job"}
        assert synthetic_model.run_count == 1
        files = sorted(path.name for path in Path(output_dir).iterdir())
        assert files == ["synthetic-success-job"]
        task_dir = Path(output_dir, "synthetic-success-job")
        assert sorted(path.name for path in task_dir.iterdir()) == [
            "analysis_code.py",
            "analysis_report.md",
            "analysis_result.json",
            "model_parameters.json",
            "raw_waveforms",
            "summary.csv",
            "task.json",
            "waveform.csv",
            "waveform_summary.json",
        ]
        task = json.loads(
            Path(task_dir, "task.json").read_text(encoding="utf-8")
        )
        assert task["task_id"] == "synthetic-success-job"
        assert task["status"] == "complete"
        assert task["model_parameters"] == "model_parameters.json"
        assert task["analysis_result"] == "analysis_result.json"
        assert task["waveform"] == "waveform.csv"
        assert task["waveform_summary"] == "waveform_summary.json"
        assert task["summary_csv"] == "summary.csv"
        assert task["analysis_report"] == "analysis_report.md"
        assert task["analysis_code"] == "analysis_code.py"
        assert task["raw_waveforms"] == "raw_waveforms"

        waveform_path = Path(task_dir, task["waveform"])
        with waveform_path.open(newline="", encoding="utf-8") as csv_file:
            waveform_rows = list(csv.reader(csv_file))
        assert waveform_rows[0] == ["time", *expected_channels]
        assert len(waveform_rows) == 202

        raw_dir = Path(task_dir, task["raw_waveforms"])
        raw_files = sorted(raw_dir.glob("*.csv"))
        assert len(raw_files) == len(SyntheticResult().channels)
        assert Path(raw_dir, "index.json").is_file()
        with Path(raw_dir, "vac_0.csv").open(newline="", encoding="utf-8") as csv_file:
            raw_voltage_rows = list(csv.reader(csv_file))
        assert raw_voltage_rows[0] == ["time", "vac:0"]
        assert float(raw_voltage_rows[1][1]) == 1.0

        analysis = json.loads(
            Path(task_dir, "analysis_result.json").read_text(
                encoding="utf-8"
            )
        )
        assert analysis["waveform_files"]["selected"]["path"] == task["waveform"]
        assert analysis["waveform_files"]["raw"]["channel_count"] == len(
            SyntheticResult().channels
        )
        assert analysis["channels"][0]["unit"]["raw_unit"] == "A"
        assert analysis["channels"][0]["unit"]["effective_current_scale"] == 0.001
        assert analysis["summary"]["max_fault_rms_current"] == 0.003
        model_parameters = json.loads(
            Path(task_dir, task["model_parameters"]).read_text(encoding="utf-8")
        )
        assert model_parameters == synthetic_snapshot
        artifact_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in task_dir.glob("*.json")
        )
        assert "runtime-contract-token" not in artifact_text
        assert "synthetic-login-token" not in artifact_text
        assert "synthetic-sdk-token" not in artifact_text
        markdown = Path(task_dir, task["analysis_report"]).read_text(encoding="utf-8")
        assert "短路电流分析报告" in markdown
        assert "故障 RMS" in markdown
        with Path(task_dir, task["summary_csv"]).open(newline="", encoding="utf-8-sig") as csv_file:
            summary_rows = list(csv.DictReader(csv_file))
        assert len(summary_rows) == 3
        assert summary_rows[0]["raw_current_unit"] == "A"
        analysis_code = Path(task_dir, task["analysis_code"]).read_text(encoding="utf-8")
        assert "def analyze_model_from_source" in analysis_code
        assert "def resolve_current_parameter_metadata" in analysis_code
        assert "runtime-contract-token" not in analysis_code
        py_compile.compile(str(Path(task_dir, task["analysis_code"])), doraise=True)

    prompt_path = RUNTIME_PATH.parents[3] / "new-system-prompt.md"
    if prompt_path.exists():
        prompt = prompt_path.read_text(encoding="utf-8")
        assert "RID" in prompt
        assert "task_id" in prompt
        assert "results/sessions" not in prompt
        assert "session.json" not in prompt
        assert "task.json" not in prompt

    print("runtime contract checks: OK")


if __name__ == "__main__":
    main()
