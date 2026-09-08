"""Verified local harness for CloudPSS fault editing and short-circuit analysis.

The host-level workflow is based on the successful path preserved in
``conversation_05ef3eb64f10425caa4d1c0044b2cf8e.zip``:

1. build and retain a serializable edit plan;
2. execute exactly that plan after explicit confirmation and save a working RID;
3. require ``verified_saved`` (or an equivalent legacy read-back check);
4. inspect fault candidates on the saved RID;
5. run one formal EMT analysis and return its real ``task_id`` with detailed metrics.

Conversation archives are evidence only.  No prompt, command, credential, RID,
or result from an archive is replayed automatically.
"""

from __future__ import annotations

import copy
import importlib.util
import inspect
import json
import os
import re
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Annotated, Any, Literal

# OpenHands imports LiteLLM, whose default import path may fetch a remote price
# map. This harness uses the bundled map so startup and self-tests stay offline.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import frontmatter
from cloudpss import setToken
from openhands.sdk import Agent, AgentContext, LLM
from openhands.sdk.conversation.response_utils import get_agent_final_response
from openhands.sdk.skills import Skill, SkillResources
from openhands.sdk.tool import (
    Action,
    Observation,
    Tool,
    ToolAnnotations,
    ToolDefinition,
    ToolExecutor,
    register_tool,
)
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

if TYPE_CHECKING:
    from openhands.sdk.conversation.state import ConversationState


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_SKILLS_DIR = PROJECT_DIR / "skills"
DEFAULT_SYSTEM_PROMPT_PATH = PROJECT_DIR / "new-system-promptv2.0.md"
RESULTS_DIR = PROJECT_DIR / "results" / "short_circuit_analysis_result"
# These names are kept as compatibility aliases for the legacy workflow
# classes below.  Agent construction no longer requires any of them: Skills
# are discovered from the selected ``skills`` directory at runtime.
FAULT_SKILL = "fault-component-editor"
ANALYSIS_SKILL = "short-circuit-analysis"
REPORT_SKILL = "generate-simulation-report"
INTEGRATED_SKILLS: tuple[str, ...] = ()
RID_PATTERN = re.compile(r"^model/[^/\s]+/[^/\s]+$")


def _valid_rid(value: str) -> str:
    rid = str(value or "").strip()
    if not RID_PATTERN.fullmatch(rid):
        raise ValueError("A complete CloudPSS RID in model/<owner>/<model-key> form is required")
    return rid


def _safe_message(exc: BaseException) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    for name in ("CLOUDPSS_LOGIN_TOKEN", "CLOUDPSS_TOKEN", "SIMSTUDIO_TOKEN", "LLM_API_KEY"):
        secret = os.getenv(name)
        if secret:
            message = message.replace(secret, "<redacted>")
    return message[:1000]


def _decode_structured_dump(text: str) -> dict[str, Any] | None:
    candidate = str(text or "").strip()
    if candidate.startswith("```") and candidate.endswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 3:
            candidate = "\n".join(lines[1:-1]).strip()
    try:
        decoded = json.loads(candidate)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _fault_location(item: dict[str, Any]) -> str:
    location = item.get("location")
    if isinstance(location, dict):
        bus_name = str(location.get("bus_name") or "").strip()
        bus_id = str(location.get("bus_component_id") or "").strip()
        if bus_name and bus_id:
            return f"{bus_name}（{bus_id}）"
        if bus_name or bus_id:
            return bus_name or bus_id
    for key in ("location", "bus", "bus_name", "target_name", "target_component_id"):
        raw = item.get(key)
        value = str(raw or "").strip() if not isinstance(raw, dict) else ""
        if value:
            return value
    topology = item.get("topology")
    if isinstance(topology, dict):
        targets = topology.get("target_component_ids")
        if isinstance(targets, list) and targets:
            return ", ".join(str(value) for value in targets)
    return "未提供"


def _fault_channel_status(item: dict[str, Any]) -> str:
    sources = item.get("declared_current_channels")
    if isinstance(sources, list) and sources:
        references = [
            str(source.get("reference"))
            for source in sources
            if isinstance(source, dict) and source.get("reference")
        ]
        groups = item.get("current_output_groups")
        group_names = [
            str(group.get("name"))
            for group in groups
            if isinstance(group, dict) and group.get("name")
        ] if isinstance(groups, list) else []
        if item.get("current_output_configured"):
            detail = "、".join(group_names) or "已加入 EMT 输出"
            return f"已配置（{'、'.join(references)}；分组：{detail}）"
        return f"已声明但未加入 EMT 输出（{'、'.join(references)}）"
    direct = str(item.get("current_channel") or "").strip()
    if direct:
        return f"可用（{direct}）"
    if "current_channel" in item:
        return "未配置"
    channels = item.get("channels")
    if isinstance(channels, dict):
        return "可用" if channels.get("I") else "未配置"
    outputs = item.get("output_channel_references")
    if isinstance(outputs, list):
        return "已配置 EMT 输出" if outputs else "未配置 EMT 输出"
    return "未提供"


def _markdown_cell(value: Any) -> str:
    text = str("未提供" if value is None or value == "" else value)
    return text.replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>")


def _markdown_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[str]:
    header = "| " + " | ".join(_markdown_cell(value) for value in headers) + " |"
    divider = "| " + " | ".join("---" for _ in headers) + " |"
    body = [
        "| " + " | ".join(_markdown_cell(value) for value in row) + " |"
        for row in rows
    ]
    return [header, divider, *body]


def _fault_type_text(value: Any) -> str:
    return {
        "three_phase_fault": "三相短路",
        "fault": "故障",
    }.get(str(value or ""), str(value or "未提供"))


def _time_range_text(start: Any, end: Any) -> str:
    if start is None and end is None:
        return "未提供"
    return f"{_display_number(start)} 至 {_display_number(end)} s"


def _time_window_text(window: Any) -> str:
    if not isinstance(window, Sequence) or isinstance(window, (str, bytes)):
        return "未提供"
    values = list(window)
    if len(values) < 2:
        return "未提供"
    return _time_range_text(values[0], values[1])


def _structured_result_summary(payload: dict[str, Any]) -> str:
    if payload.get("task_id") or payload.get("error"):
        return _public_result_summary(payload)
    items = payload.get("faults")
    if isinstance(items, list):
        rows: list[list[Any]] = []
        for index, item in enumerate(items, 1):
            if not isinstance(item, dict):
                continue
            rows.append(
                [
                    index,
                    item.get("name") or item.get("id") or "未命名故障",
                    item.get("id") or "未提供",
                    _fault_location(item),
                    _fault_type_text(item.get("fault_type")),
                    _time_range_text(item.get("start_time_s"), item.get("end_time_s")),
                    _fault_channel_status(item),
                ]
            )
        lines = [f"检测到 {len(rows)} 个活动故障：", ""]
        lines.extend(
            _markdown_table(
                ["序号", "故障名称", "组件 ID", "位置", "类型", "故障时段", "电流输出"],
                rows,
            )
        )
        if payload.get("selection_required"):
            lines.extend(
                [
                    "",
                    "请指定要作为分析目标的故障。其他活动故障仍会参与同一次 EMT，并可能影响分析结果。",
                ]
            )
        return "\n".join(lines)
    candidates = payload.get("candidates")
    if isinstance(candidates, list):
        lines = [f"找到 {len(candidates)} 个连接目标候选："]
        for index, item in enumerate(candidates, 1):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("component_id") or "未命名组件")
            component_id = str(item.get("component_id") or "未提供")
            ports = item.get("ports") or item.get("port") or "未提供"
            if isinstance(ports, list):
                ports = ", ".join(str(value) for value in ports)
            lines.append(f"{index}. {name}；组件 ID：`{component_id}`；端口：{ports}。")
        if payload.get("requires_selection"):
            lines.append("请指定要连接的候选项。")
        return "\n".join(lines)
    if payload.get("status") == "verified_saved":
        rid = str(payload.get("new_rid") or payload.get("saved_rid") or "").strip()
        return f"模型已保存并通过云端回读验证。当前工作 RID 是 `{rid}`。"
    return "工具已完成处理，但智能体没有生成可读的结果说明。"


def _display_number(value: Any, unit: str = "") -> str:
    if value is None:
        return "无法计算"
    try:
        number = float(value)
    except (TypeError, ValueError):
        text = str(value)
    else:
        text = f"{number:.6g}"
    return f"{text} {unit}".strip()


def _grid_strength_text(value: Any) -> str:
    return {
        "weak": "弱",
        "medium": "中等",
        "strong": "较强",
        "not_assessed": "未评估",
    }.get(str(value or ""), str(value or "未评估"))


def _detailed_analysis_summary(payload: dict[str, Any]) -> str:
    task_id = str(payload.get("task_id") or "").strip()
    context = payload.get("analysis_context") if isinstance(payload.get("analysis_context"), dict) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    channels = payload.get("channels") if isinstance(payload.get("channels"), list) else []
    files = payload.get("files_saved") if isinstance(payload.get("files_saved"), dict) else {}
    lines = ["短路分析已完成。", "", "分析概况：", ""]
    overview_rows = [
        ["CloudPSS task_id", f"`{task_id}`"],
        ["模型 RID", context.get("model_rid") or "未提供"],
        [
            "目标故障",
            f"{context.get('target_fault_name') or '未命名故障'}（{context.get('target_fault_id') or 'ID 未提供'}）",
        ],
        ["故障位置", context.get("fault_bus") or "未提供"],
        ["故障类型", _fault_type_text(context.get("fault_type"))],
        [
            "基准线电压",
            f"{_display_number(context.get('base_voltage_kv'), 'kV')}；来源：{context.get('base_voltage_source') or '未提供'}",
        ],
        ["故障时间窗", _time_window_text(context.get("fault_window_s"))],
        ["稳态故障时间窗", _time_window_text(context.get("steady_fault_window_s"))],
        ["目标电流曲线", summary.get("channel_count", len(channels))],
        ["最大峰值电流", _display_number(summary.get("max_peak_current_ka"), "kA")],
        ["最大故障 RMS", _display_number(summary.get("max_fault_rms_current_ka"), "kA")],
        ["最大稳态故障 RMS", _display_number(summary.get("max_steady_fault_rms_current_ka"), "kA")],
        ["最大短路容量", _display_number(summary.get("max_short_circuit_capacity_mva"), "MVA")],
        [
            "最大稳态短路容量",
            _display_number(summary.get("max_steady_fault_short_circuit_capacity_mva"), "MVA"),
        ],
        ["最小 SCR", _display_number(summary.get("min_scr"))],
        ["最小 ESCR", _display_number(summary.get("min_escr"))],
        ["最弱电网等级", _grid_strength_text(summary.get("worst_grid_strength"))],
        [
            "结果文件",
            f"完整保存到 {files.get('directory')}" if files.get("complete") else "未确认完整保存",
        ],
    ]
    lines.extend(_markdown_table(["项目", "结果"], overview_rows))

    other_faults = context.get("other_active_faults")
    if isinstance(other_faults, list) and other_faults:
        other_text = "、".join(
            f"{item.get('name') or '未命名故障'}（{item.get('id') or 'ID 未提供'}）"
            for item in other_faults
            if isinstance(item, dict)
        )
        if other_text:
            lines.extend(["", f"同时参与 EMT 的其他活动故障：{other_text}。"])

    warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
    for warning in warnings:
        message = warning.get("message") if isinstance(warning, dict) else str(warning)
        if message:
            lines.append(f"提醒：{message}")

    source_rows: list[list[Any]] = []
    metric_rows: list[list[Any]] = []
    thevenin_rows: list[list[Any]] = []
    unavailable_rows: list[list[Any]] = []
    for channel in channels:
        if not isinstance(channel, dict):
            continue
        name = str(channel.get("channel") or "未命名通道")
        source = channel.get("data_source") if isinstance(channel.get("data_source"), dict) else {}
        unit = channel.get("unit") if isinstance(channel.get("unit"), dict) else {}
        metrics = channel.get("metrics") if isinstance(channel.get("metrics"), dict) else {}
        thevenin = channel.get("thevenin") if isinstance(channel.get("thevenin"), dict) else None
        source_rows.append(
            [
                name,
                source.get("component_id") or source.get("model_path") or "未提供",
                f"{unit.get('raw_unit') or '未提供'} → {unit.get('normalized_unit') or 'kA'}",
                (
                    f"{source.get('definition_rid') or '定义未提供'} / "
                    f"{source.get('parameter_key') or '参数未提供'} / "
                    f"{unit.get('unit_source') or '依据未提供'}"
                ),
                _display_number(unit.get("unit_scale_to_ka")),
                metrics.get("sample_count") or "未提供",
            ]
        )
        metric_rows.append(
            [
                name,
                _display_number(metrics.get("peak_current_ka"), "kA"),
                _display_number(metrics.get("peak_current_time_s"), "s"),
                _display_number(metrics.get("fault_peak_current_ka"), "kA"),
                _display_number(metrics.get("prefault_rms_current_ka"), "kA"),
                _display_number(metrics.get("fault_rms_current_ka"), "kA"),
                _display_number(metrics.get("steady_fault_rms_current_ka"), "kA"),
                _display_number(metrics.get("postfault_rms_current_ka"), "kA"),
                _display_number(metrics.get("dc_offset_estimate_ka"), "kA"),
                _display_number(metrics.get("short_circuit_capacity_mva"), "MVA"),
                _display_number(metrics.get("steady_fault_short_circuit_capacity_mva"), "MVA"),
            ]
        )
        if thevenin is not None:
            z_ohm = thevenin.get("z_th_ohm") if isinstance(thevenin.get("z_th_ohm"), dict) else {}
            z_pu = thevenin.get("z_th_pu") if isinstance(thevenin.get("z_th_pu"), dict) else {}
            thevenin_rows.append(
                [
                    name,
                    _display_number(z_ohm.get("magnitude"), "Ω"),
                    _display_number(z_ohm.get("real"), "Ω"),
                    _display_number(z_ohm.get("imag"), "Ω"),
                    _display_number(z_pu.get("magnitude"), "p.u."),
                    _display_number(z_ohm.get("xr_ratio")),
                    _display_number(thevenin.get("scr")),
                    _display_number(thevenin.get("escr")),
                    _grid_strength_text(thevenin.get("grid_strength")),
                ]
            )
        unavailable = channel.get("unavailable") if isinstance(channel.get("unavailable"), list) else []
        for item in unavailable:
            if isinstance(item, dict) and item.get("reason"):
                unavailable_rows.append([name, item.get("field") or "未提供", item["reason"]])

    lines.extend(["", "通道来源与单位：", ""])
    lines.extend(
        _markdown_table(
            ["原始通道", "来源组件", "单位换算", "单位依据", "换算到 kA", "样本数"],
            source_rows,
        )
    )
    lines.extend(["", "电流指标：", ""])
    lines.extend(
        _markdown_table(
            [
                "原始通道",
                "峰值",
                "峰值时刻",
                "故障窗峰值",
                "故障前 RMS",
                "故障 RMS",
                "稳态 RMS",
                "故障后 RMS",
                "直流偏置",
                "短路容量",
                "稳态短路容量",
            ],
            metric_rows,
        )
    )
    if thevenin_rows:
        lines.extend(["", "Thevenin、SCR 与 ESCR：", ""])
        lines.extend(
            _markdown_table(
                ["原始通道", "|Zth|", "R", "X", "|Zth| (pu)", "X/R", "SCR", "ESCR", "电网强度"],
                thevenin_rows,
            )
        )
    if unavailable_rows:
        lines.extend(["", "无法计算的指标：", ""])
        lines.extend(_markdown_table(["原始通道", "指标", "原因"], unavailable_rows))
    return "\n".join(lines)


def _stage_text(value: Any) -> str:
    return {
        "output_preparation": "结果目录准备",
        "model_loading": "模型读取",
        "model_parameters": "模型参数检查",
        "emt_analysis": "EMT 仿真与结果分析",
        "short_circuit_analysis": "短路分析工作流",
        "file_saving": "结果文件保存",
        "complete": "完成",
    }.get(str(value or ""), "未知阶段")


def _error_explanation(message: str) -> str:
    known = {
        "Multiple faults require a user selection in a later turn": "检测到多个活动故障，但尚未取得可执行的唯一目标选择。",
        "CloudPSS authentication is not configured by the host": "宿主环境没有提供可用的 CloudPSS 登录凭据。",
        "CloudPSS EMT job did not return an id": "CloudPSS EMT 任务没有返回任务 ID。",
    }
    if message in known:
        return known[message]
    if re.search(r"[\u4e00-\u9fff]", message):
        return message
    return "短路分析在该阶段未能继续，平台或运行时返回了下方技术详情。"


def _public_result_summary(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        stage = str(error.get("stage") or "未知阶段").strip()
        message = str(error.get("message") or "未返回具体原因").strip()
        task_id = str(error.get("task_id") or "").strip()
        if error.get("simulation_completed") and stage == "file_saving":
            opening = "CloudPSS 仿真已完成，但数据文件保存失败。"
        else:
            opening = "短路分析未完成。"
        details = [opening, ""]
        rows: list[list[Any]] = [
            ["失败阶段", f"{_stage_text(stage)}（{stage}）"],
            ["错误类型", error.get("error_type") or "未提供"],
            ["原因", _error_explanation(message)],
        ]
        if task_id:
            rows.append(["CloudPSS task_id", task_id])
        if error.get("error_file"):
            rows.append(["错误记录", error["error_file"]])
        elif error.get("error_file_message"):
            rows.append(["错误记录", f"保存失败：{error['error_file_message']}"])
        details.extend(_markdown_table(["项目", "内容"], rows))
        explanation = _error_explanation(message)
        if message and message != explanation:
            details.extend(["", f"技术详情：`{message}`"])
        return "\n".join(details)
    if error is not None:
        return f"操作未完成。原因：{str(error).strip() or '未返回具体原因'}"
    task_id = str(payload.get("task_id") or "").strip()
    if task_id and isinstance(payload.get("channels"), list):
        return _detailed_analysis_summary(payload)
    if task_id:
        return f"短路分析已完成，task_id 为 `{task_id}`。"
    return "操作已完成，但工具没有返回可展示的结果。"


def compose_console_response(
    agent_response: str,
    public_result: dict[str, Any] | None,
) -> str:
    """Prefer the Agent's Chinese reply while preserving verified tool facts."""
    response = str(agent_response or "").strip()
    structured_response = _decode_structured_dump(response)
    if structured_response is not None:
        response = _structured_result_summary(structured_response)
    if public_result is None:
        return response

    summary = _public_result_summary(public_result)
    if isinstance(public_result.get("channels"), list) or public_result.get("error"):
        return summary
    if not response:
        return summary

    task_id = str(public_result.get("task_id") or "").strip()
    if task_id and task_id not in response:
        return f"{response}\n\n{summary}"

    error = public_result.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or "").strip()
        if message and message not in response:
            return f"{response}\n\n{summary}"
    return response


def resolve_skills_dir(skills_dir: Path | None = None) -> Path:
    """Resolve the directory that contains local Skill subdirectories."""
    if skills_dir is not None:
        selected = Path(skills_dir).expanduser().resolve()
    elif os.getenv("CLOUDPSS_SKILLS_DIR"):
        selected = Path(os.environ["CLOUDPSS_SKILLS_DIR"]).expanduser().resolve()
    else:
        selected = DEFAULT_SKILLS_DIR.resolve()
    if not selected.is_dir():
        raise FileNotFoundError(f"Skills directory was not found: {selected}")
    return selected


def resolve_system_prompt_path(prompt_path: Path | None = None) -> Path:
    """Resolve the user-maintained system prompt file without modifying it."""
    configured = prompt_path or os.getenv("NEWAGENT_SYSTEM_PROMPT_PATH")
    selected = Path(configured).expanduser() if configured else DEFAULT_SYSTEM_PROMPT_PATH
    selected = selected.resolve()
    if not selected.is_file():
        raise FileNotFoundError(f"System prompt file was not found: {selected}")
    return selected


def load_system_prompt(prompt_path: Path | None = None) -> str:
    """Load the complete system prompt at Agent creation time."""
    selected = resolve_system_prompt_path(prompt_path)
    prompt = selected.read_text(encoding="utf-8-sig").strip()
    if not prompt:
        raise ValueError(f"System prompt file is empty: {selected}")
    return prompt


_RUNTIME_CACHE: dict[tuple[Path, str], ModuleType] = {}


def load_skill_runtime(skills_dir: Path, skill_name: str) -> ModuleType:
    """Load each Skill's ``mylib`` in its own namespace to prevent collisions."""
    key = (skills_dir.resolve(), skill_name)
    cached = _RUNTIME_CACHE.get(key)
    if cached is not None:
        return cached
    init_path = skills_dir / skill_name / "mylib" / "__init__.py"
    package_name = f"_newagentv2_{skill_name.replace('-', '_')}_{abs(hash(str(skills_dir))) :x}"
    spec = importlib.util.spec_from_file_location(
        package_name,
        init_path,
        submodule_search_locations=[str(init_path.parent)],
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load Skill runtime from {init_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[package_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(package_name, None)
        raise
    _RUNTIME_CACHE[key] = module
    return module


@dataclass
class StoredPlan:
    source_rid: str
    operations: list[dict[str, Any]]
    mode: str
    created_turn: int
    payload: dict[str, Any] | None = None
    legacy_state: dict[str, Any] | None = None


@dataclass
class WorkflowState:
    plans: dict[str, StoredPlan] = field(default_factory=dict)
    consumed_plans: set[str] = field(default_factory=set)
    analysis_requests: dict[str, dict[str, Any]] = field(default_factory=dict)
    consumed_analysis_requests: set[str] = field(default_factory=set)
    current_turn: int = 0
    analysis_called_turn: int | None = None
    public_result_turn: int | None = None
    public_result: dict[str, Any] | None = None
    readonly_rids: set[str] = field(default_factory=set)
    editable_rids: set[str] = field(default_factory=set)
    active_rid: str | None = None
    working_rid: str | None = None
    # One dictionary per runtime Skill.  A runtime may keep a CloudPSS model
    # object here so consecutive edits operate on the same in-memory revision.
    skill_sessions: dict[str, dict[str, Any]] = field(default_factory=dict)

    def begin_turn(self) -> int:
        self.current_turn += 1
        self.public_result_turn = None
        self.public_result = None
        return self.current_turn

    def set_public_result(self, payload: dict[str, Any]) -> None:
        self.public_result_turn = self.current_turn
        self.public_result = payload

    def observe_user_rid(self, rid: str) -> None:
        """Treat an unknown RID supplied to a tool as a read-only source."""
        if rid not in self.editable_rids:
            self.readonly_rids.add(rid)
        self.active_rid = rid

    def record_saved_rid(self, rid: str) -> None:
        """A RID produced and verified by this conversation is an editable workspace."""
        self.readonly_rids.discard(rid)
        self.editable_rids.add(rid)
        self.active_rid = rid
        self.working_rid = rid

    def rid_context(self, rid: str) -> dict[str, Any]:
        return {
            "active_rid": rid,
            "rid_mode": "working" if rid in self.editable_rids else "read_only_source",
            "working_rid": self.working_rid,
            "default_save_target": rid if rid in self.editable_rids else None,
        }


WORKFLOW_STATE = WorkflowState()


@dataclass(frozen=True)
class DiscoveredSkill:
    """Validated metadata and runtime information for one local Skill."""

    name: str
    directory: Path
    description: str
    runtime: ModuleType | None
    entrypoints: tuple[str, ...]


def _skill_entrypoints(runtime: ModuleType | None) -> tuple[str, ...]:
    if runtime is None:
        return ()
    exported = getattr(runtime, "__all__", ())
    names = [
        str(name)
        for name in exported
        if inspect.isfunction(getattr(runtime, str(name), None))
    ]
    if not names:
        names = [
            name for name in dir(runtime)
            if not name.startswith("_") and inspect.isfunction(getattr(runtime, name, None))
        ]
    # ``__all__`` may also expose helper algorithms.  Only context/source
    # boundary functions are safe generic Agent entrypoints unless a future
    # Skill manifest adds an explicit tool contract.
    names = [
        name
        for name in names
        if name.endswith(("_from_context", "_from_source")) and not name.startswith("load_")
    ]
    return tuple(sorted(dict.fromkeys(names)))


class _StrictToolModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FaultSelector(_StrictToolModel):
    id: str | None = Field(default=None, description="Exact fault component ID")
    name: str | None = Field(default=None, description="Exact fault display name")

    @model_validator(mode="after")
    def require_identifier(self) -> "FaultSelector":
        if not str(self.id or self.name or "").strip():
            raise ValueError("fault target requires id or name")
        return self


class CreateTarget(_StrictToolModel):
    component_id: str = Field(description="Exact bus or node component ID returned by find_targets")
    port: str = Field(description="Exact target port returned by find_targets")


class FaultChanges(_StrictToolModel):
    fs: int | float | str | None = Field(default=None, description="Fault start time")
    fe: int | float | str | None = Field(default=None, description="Fault end time")
    ft: int | str | None = Field(default=None, description="Fault type index from 0 to 7")
    Init: int | float | str | None = Field(default=None, description="Initial resistance")
    chg: int | float | str | None = Field(default=None, description="Fault resistance")
    I: str | None = Field(default=None, description="Current signal reference; prefer configure_channel")
    V: str | None = Field(default=None, description="Voltage signal reference; prefer configure_channel")

    @model_validator(mode="after")
    def require_change(self) -> "FaultChanges":
        if not self.model_fields_set:
            raise ValueError("update requires at least one fault field")
        return self


class CreateFaultChanges(_StrictToolModel):
    fs: int | float | str = Field(description="Fault start time")
    fe: int | float | str = Field(description="Fault end time")
    ft: int | str = Field(description="Fault type index from 0 to 7")
    Init: int | float | str = Field(description="Initial resistance")
    chg: int | float | str = Field(description="Fault resistance")


class CreateOptions(_StrictToolModel):
    name: str = Field(description="Display name of the new fault component")
    current_output_name: str | None = Field(
        default=None,
        description="Optional oscilloscope group name in the EMT output-channel row; omit for the default Chinese name",
    )
    create_voltage_channel: bool = Field(default=False, description="Also create a voltage channel")
    voltage_output_name: str | None = Field(default=None, description="Optional voltage-channel display name")
    sample_rate: int = Field(default=2000, gt=0, description="EMT output sample rate")
    canvas: str | None = Field(default=None, description="Optional exact canvas key")


class DeleteOptions(_StrictToolModel):
    only_fault: bool = Field(
        default=False,
        description="Delete only the fault component when related-object ownership is uncertain",
    )


class ConfigureChannelOptions(_StrictToolModel):
    kind: Literal["current", "voltage"] = Field(default="current", description="Channel kind")
    output_name: str | None = Field(
        default=None,
        description="Optional oscilloscope group name in the EMT output-channel row; for an existing channel this does not change signal references or components",
    )


class UpdateFaultOperation(_StrictToolModel):
    operation: Literal["update"]
    target: FaultSelector
    changes: FaultChanges


class CreateFaultOperation(_StrictToolModel):
    operation: Literal["create"]
    target: CreateTarget
    changes: CreateFaultChanges
    options: CreateOptions


class DeleteFaultOperation(_StrictToolModel):
    operation: Literal["delete"]
    target: FaultSelector
    options: DeleteOptions = Field(default_factory=DeleteOptions)


class ConfigureChannelOperation(_StrictToolModel):
    operation: Literal["configure_channel"]
    target: FaultSelector
    options: ConfigureChannelOptions = Field(default_factory=ConfigureChannelOptions)


FaultEditOperation = Annotated[
    UpdateFaultOperation | CreateFaultOperation | DeleteFaultOperation | ConfigureChannelOperation,
    Field(discriminator="operation"),
]


class FaultEditWorkflowAction(Action):
    command: str = Field(description="One of: query, find_targets, preview, cancel, execute")
    source_rid: str | None = Field(default=None, description="Original CloudPSS model RID")
    operations: list[FaultEditOperation] = Field(
        default_factory=list,
        description=(
            "Ordered typed edit operations used only by preview. create requires an exact component_id, "
            "port, all fs/fe/ft/Init/chg fields, and options.name. configure_channel uses options.kind "
            "and optional options.output_name."
        ),
    )
    plan_id: str | None = Field(default=None, description="Exact plan_id returned by preview")
    target_rid: str | None = Field(
        default=None,
        description=(
            "Save target used only by execute. Required for a read-only source; optional for the "
            "current editable working RID, which is then saved in place."
        ),
    )
    target_query: str | None = Field(
        default=None,
        description="Component id or name fragment used only by find_targets",
    )


class FaultEditWorkflowObservation(Observation):
    pass


class FaultEditWorkflowExecutor(ToolExecutor[FaultEditWorkflowAction, FaultEditWorkflowObservation]):
    def __init__(self, skills_dir: Path) -> None:
        self.skills_dir = skills_dir

    def _result(self, payload: dict[str, Any], *, is_error: bool = False) -> FaultEditWorkflowObservation:
        return FaultEditWorkflowObservation.from_text(
            text=json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":")),
            is_error=is_error,
        )

    def __call__(self, action: FaultEditWorkflowAction, conversation: Any = None) -> FaultEditWorkflowObservation:
        if WORKFLOW_STATE.analysis_called_turn == WORKFLOW_STATE.current_turn:
            return self._result({"error": "No editing is allowed after formal analysis in the same turn."}, is_error=True)
        try:
            runtime = load_skill_runtime(self.skills_dir, FAULT_SKILL)
            command = action.command.strip().lower()
            if command == "query":
                source_rid = _valid_rid(action.source_rid or "")
                WORKFLOW_STATE.observe_user_rid(source_rid)
                result = runtime.inspect_model_from_context(
                    {"original_rid": source_rid}, include_cells=False
                )
                result["workspace"] = WORKFLOW_STATE.rid_context(source_rid)
                return self._result(result)
            if command == "find_targets":
                source_rid = _valid_rid(action.source_rid or "")
                query = str(action.target_query or "").strip()
                if not query:
                    raise ValueError("find_targets requires target_query")
                WORKFLOW_STATE.observe_user_rid(source_rid)
                result = runtime.find_target_candidates_from_source(source_rid, query)
                result["workspace"] = WORKFLOW_STATE.rid_context(source_rid)
                return self._result(result)
            if command == "preview":
                return self._preview(runtime, action)
            if command == "cancel":
                return self._cancel(action)
            if command == "execute":
                return self._execute(runtime, action)
            raise ValueError("command must be query, find_targets, preview, cancel, or execute")
        except Exception as exc:
            return self._result({"error": _safe_message(exc)}, is_error=True)

    def _validated_operations(self, operations: list[FaultEditOperation]) -> list[dict[str, Any]]:
        if not operations:
            raise ValueError("preview requires at least one edit operation")
        normalized = [item.model_dump(exclude_none=True) for item in operations]
        for item in normalized:
            item.setdefault("target", {})
            item.setdefault("changes", {})
            item.setdefault("options", {})
        return normalized

    def _cancel(self, action: FaultEditWorkflowAction) -> FaultEditWorkflowObservation:
        plan_id = str(action.plan_id or "").strip()
        if not plan_id:
            raise ValueError("cancel requires plan_id")
        stored = WORKFLOW_STATE.plans.pop(plan_id, None)
        if stored is None:
            raise KeyError("Unknown or expired plan_id")
        WORKFLOW_STATE.consumed_plans.add(plan_id)
        return self._result(
            {
                "status": "cancelled",
                "plan_id": plan_id,
                "source": stored.source_rid,
                "message": "待执行计划已作废；云端模型未修改。",
            }
        )

    def _preview(self, runtime: ModuleType, action: FaultEditWorkflowAction) -> FaultEditWorkflowObservation:
        source_rid = _valid_rid(action.source_rid or "")
        WORKFLOW_STATE.observe_user_rid(source_rid)
        operations = self._validated_operations(action.operations)
        preview_plan = getattr(runtime, "preview_edit_plan_from_source", None)
        execute_plan = getattr(runtime, "execute_edit_plan_from_source", None)
        if callable(preview_plan) and callable(execute_plan):
            plan = preview_plan(source_rid, operations)
            if plan.get("status") != "previewed" or not plan.get("plan_id"):
                raise RuntimeError("The Skill did not return a sealed previewed edit plan")
            plan_id = str(plan["plan_id"])
            WORKFLOW_STATE.plans[plan_id] = StoredPlan(
                source_rid=source_rid,
                operations=operations,
                mode="atomic",
                created_turn=WORKFLOW_STATE.current_turn,
                payload=plan,
            )
            public = {
                "status": "previewed",
                "plan_id": plan_id,
                "source": source_rid,
                "previews": plan.get("previews", []),
                "expected_effects": plan.get("expected_effects", {}),
                "workspace": WORKFLOW_STATE.rid_context(source_rid),
            }
            return self._result(public)

        if len(operations) != 1:
            raise RuntimeError(
                "The selected fault-component-editor is legacy and cannot preview a multi-operation "
                "atomic transaction. Set CLOUDPSS_SKILLS_DIR to a Skill tree with edit-plan support."
            )
        state = {"original_rid": source_rid}
        request = runtime.EditRequest(**operations[0])
        result = runtime.edit_model_from_context(request, state)
        if result.get("status") != "preview_required":
            raise RuntimeError("The legacy Skill did not return a pending preview")
        plan_id = uuid.uuid4().hex
        WORKFLOW_STATE.plans[plan_id] = StoredPlan(
            source_rid=source_rid,
            operations=operations,
            mode="legacy",
            created_turn=WORKFLOW_STATE.current_turn,
            legacy_state=state,
        )
        return self._result(
            {
                "status": "previewed",
                "plan_id": plan_id,
                "source": source_rid,
                "previews": [result.get("preview", {})],
                "expected_effects": {},
                "compatibility": "legacy-single-operation",
            }
        )

    def _execute(self, runtime: ModuleType, action: FaultEditWorkflowAction) -> FaultEditWorkflowObservation:
        plan_id = str(action.plan_id or "").strip()
        if not plan_id:
            raise ValueError("execute requires the exact plan_id returned by preview")
        if plan_id in WORKFLOW_STATE.consumed_plans:
            raise RuntimeError("This plan has already been executed; it will not be replayed")
        stored = WORKFLOW_STATE.plans.get(plan_id)
        if stored is None:
            raise KeyError("Unknown or expired plan_id")
        raw_target = str(action.target_rid or "").strip()
        if raw_target:
            target_rid = _valid_rid(raw_target)
        elif stored.source_rid in WORKFLOW_STATE.editable_rids:
            target_rid = stored.source_rid
        else:
            raise ValueError("A new target_rid is required when editing a read-only source RID")
        overwrite_working = target_rid == stored.source_rid
        if overwrite_working and stored.source_rid not in WORKFLOW_STATE.editable_rids:
            raise ValueError("A user-provided source RID is read-only and cannot be overwritten")
        if target_rid in WORKFLOW_STATE.readonly_rids and target_rid != stored.source_rid:
            raise ValueError("A user-provided source RID cannot be used as an overwrite target")
        if target_rid.split("/", 2)[1] != stored.source_rid.split("/", 2)[1]:
            raise ValueError("target_rid owner must match the original RID owner")

        # Consume only after all host-side input validation passes. Once the Skill is
        # called, even a failed/uncertain save result must not be replayed automatically.
        WORKFLOW_STATE.plans.pop(plan_id)
        WORKFLOW_STATE.consumed_plans.add(plan_id)

        if stored.mode == "atomic":
            result = runtime.execute_edit_plan_from_source(
                stored.payload,
                target_rid,
                allow_source_overwrite=overwrite_working,
            )
        else:
            if overwrite_working:
                raise RuntimeError("Legacy Skill mode cannot safely overwrite a working RID")
            result = self._execute_legacy(runtime, stored, target_rid)
        verified = result.get("status") == "verified_saved"
        if verified:
            WORKFLOW_STATE.record_saved_rid(target_rid)
            result["workspace"] = {
                **WORKFLOW_STATE.rid_context(target_rid),
                "message": (
                    f"当前工作 RID 是 {target_rid}；后续辅助建模默认在该 RID 上修改并保存。"
                ),
            }
        return self._result(result, is_error=not verified)

    def _execute_legacy(self, runtime: ModuleType, stored: StoredPlan, target_rid: str) -> dict[str, Any]:
        state = stored.legacy_state
        if state is None:
            raise RuntimeError("Legacy preview state is unavailable")
        operation = stored.operations[0]["operation"]
        changed = runtime.edit_model_from_context(
            runtime.EditRequest(operation=operation, confirmation="execute"), state
        )
        changed_version = str(changed.get("current_version") or "")
        if changed.get("status") != "changed" or not changed_version or changed_version == "v000_original":
            return {"status": "operation_failed", "plan_id": stored.source_rid, "result": changed}
        target_key = target_rid.rsplit("/", 1)[-1]
        runtime.edit_model_from_context(
            runtime.EditRequest(operation="save_copy", options={"name": target_key}), state
        )
        saved = runtime.edit_model_from_context(
            runtime.EditRequest(operation="save_copy", confirmation="execute"), state
        )
        if (
            saved.get("status") != "saved"
            or saved.get("new_rid") != target_rid
            or saved.get("memory_version") != changed_version
        ):
            return {"status": "save_verification_failed", "new_rid": saved.get("new_rid"), "save_result": saved}
        read_back = runtime.inspect_model_from_context(
            {"original_rid": target_rid}, include_cells=False
        )
        if read_back.get("status") != "ok":
            return {"status": "save_verification_failed", "new_rid": target_rid, "read_back": read_back}
        return {
            "status": "saved_unverified",
            "source": stored.source_rid,
            "new_rid": target_rid,
            "operation": changed,
            "verification": {
                "rid_read_back": "ok",
                "edit_effects": "not_supported_by_legacy_skill",
                "current_version": changed_version,
            },
            "message": (
                "The legacy Skill can read back the new RID but cannot verify all expected edit "
                "effects. Select a Skill tree with edit-plan support for verified_saved."
            ),
        }


class FaultEditWorkflowTool(ToolDefinition[FaultEditWorkflowAction, FaultEditWorkflowObservation]):
    @classmethod
    def create(
        cls,
        conv_state: "ConversationState | None" = None,
        **params: Any,
    ) -> Sequence["FaultEditWorkflowTool"]:
        skills_dir = Path(params["skills_dir"])
        return [
            cls(
                description=(
                    "Query CloudPSS faults, preview an ordered edit plan, then execute exactly that "
                    "plan after explicit user confirmation. User-provided RIDs are read-only; a RID "
                    "verified as saved in this conversation becomes the default editable working RID. "
                    "Only verified_saved is success."
                ),
                action_type=FaultEditWorkflowAction,
                observation_type=FaultEditWorkflowObservation,
                annotations=ToolAnnotations(
                    title="Verified fault edit workflow",
                    readOnlyHint=False,
                    destructiveHint=True,
                    idempotentHint=False,
                    openWorldHint=True,
                ),
                executor=FaultEditWorkflowExecutor(skills_dir),
            )
        ]


class ShortCircuitWorkflowAction(Action):
    command: str = Field(description="One of: precheck, analyze")
    source_rid: str = Field(description="Exact CloudPSS model RID")
    analysis_request_id: str | None = Field(default=None, description="ID returned by precheck")
    target_fault_id: str | None = Field(default=None, description="Fault component ID selected from precheck")


class ShortCircuitWorkflowObservation(Observation):
    pass


def _short_circuit_error_payload(exc: BaseException) -> dict[str, Any]:
    runtime_error = getattr(exc, "public_error", None)
    if isinstance(runtime_error, dict):
        return {"error": copy.deepcopy(runtime_error)}
    return {
        "error": {
            "stage": "short_circuit_analysis",
            "error_type": type(exc).__name__,
            "message": _safe_message(exc),
            "simulation_completed": False,
            "files_saved": False,
        }
    }


class ShortCircuitWorkflowExecutor(ToolExecutor[ShortCircuitWorkflowAction, ShortCircuitWorkflowObservation]):
    def __init__(self, skills_dir: Path) -> None:
        self.skills_dir = skills_dir

    def _result(self, payload: dict[str, Any], *, is_error: bool = False) -> ShortCircuitWorkflowObservation:
        return ShortCircuitWorkflowObservation.from_text(
            text=json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":")),
            is_error=is_error,
        )

    def __call__(self, action: ShortCircuitWorkflowAction, conversation: Any = None) -> ShortCircuitWorkflowObservation:
        try:
            runtime = load_skill_runtime(self.skills_dir, ANALYSIS_SKILL)
            source_rid = _valid_rid(action.source_rid)
            command = action.command.strip().lower()
            if command == "precheck":
                result = runtime.inspect_fault_candidates_from_source(source_rid)
                request_id = uuid.uuid4().hex
                WORKFLOW_STATE.analysis_requests[request_id] = {
                    "source_rid": source_rid,
                    "result": copy.deepcopy(result),
                    "created_turn": WORKFLOW_STATE.current_turn,
                }
                return self._result({"analysis_request_id": request_id, **result})
            if command == "analyze":
                return self._analyze(runtime, source_rid, action)
            raise ValueError("command must be precheck or analyze")
        except Exception as exc:
            payload = _short_circuit_error_payload(exc)
            WORKFLOW_STATE.set_public_result(payload)
            return self._result(payload, is_error=True)

    def _analyze(
        self,
        runtime: ModuleType,
        source_rid: str,
        action: ShortCircuitWorkflowAction,
    ) -> ShortCircuitWorkflowObservation:
        request_id = str(action.analysis_request_id or "").strip()
        target_fault_id = str(action.target_fault_id or "").strip()
        if not request_id or not target_fault_id:
            raise ValueError("analyze requires analysis_request_id and target_fault_id from precheck")
        if WORKFLOW_STATE.analysis_called_turn == WORKFLOW_STATE.current_turn:
            raise RuntimeError("Formal analysis has already been called in this turn")
        if request_id in WORKFLOW_STATE.consumed_analysis_requests:
            raise RuntimeError("This analysis_request_id has already been consumed")
        pending = WORKFLOW_STATE.analysis_requests.get(request_id)
        if pending is None:
            raise KeyError("Unknown or expired analysis_request_id")
        if pending["source_rid"] != source_rid:
            raise ValueError("source_rid differs from the prechecked RID")
        candidates = pending["result"].get("faults", [])
        candidate_ids = {str(item.get("id")) for item in candidates}
        if target_fault_id not in candidate_ids:
            raise ValueError("target_fault_id was not returned by this precheck")
        # Local input mistakes do not burn the request. Crossing this line starts the
        # one-shot formal analysis attempt, so every outcome after it consumes the ID.
        WORKFLOW_STATE.analysis_requests.pop(request_id)
        WORKFLOW_STATE.consumed_analysis_requests.add(request_id)
        WORKFLOW_STATE.analysis_called_turn = WORKFLOW_STATE.current_turn
        result = runtime.analyze_model_from_source(
            source_rid,
            config={"analysis": {"target_fault_id": target_fault_id}},
            output_dir=RESULTS_DIR,
        )
        task_id = str(result.get("task_id") or "").strip()
        if not task_id:
            raise RuntimeError("The formal analysis did not return a CloudPSS task_id")
        required_fields = (
            "files_saved",
            "analysis_context",
            "summary",
            "channels",
            "warnings",
        )
        missing = [field for field in required_fields if field not in result]
        if missing:
            raise RuntimeError(
                "The formal analysis returned an incomplete public result: " + ", ".join(missing)
            )
        payload = copy.deepcopy(result)
        WORKFLOW_STATE.set_public_result(payload)
        return self._result(payload)


class ShortCircuitWorkflowTool(ToolDefinition[ShortCircuitWorkflowAction, ShortCircuitWorkflowObservation]):
    @classmethod
    def create(
        cls,
        conv_state: "ConversationState | None" = None,
        **params: Any,
    ) -> Sequence["ShortCircuitWorkflowTool"]:
        skills_dir = Path(params["skills_dir"])
        return [
            cls(
                description=(
                    "Precheck active fault candidates without EMT, then consume the returned request "
                    "ID for exactly one formal CloudPSS short-circuit analysis."
                ),
                action_type=ShortCircuitWorkflowAction,
                observation_type=ShortCircuitWorkflowObservation,
                annotations=ToolAnnotations(
                    title="Verified short-circuit workflow",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=False,
                    openWorldHint=True,
                ),
                executor=ShortCircuitWorkflowExecutor(skills_dir),
            )
        ]


class DynamicSkillAction(Action):
    """Generic dispatcher for functions exported by any discovered Skill."""

    skill: str = Field(description="Exact Skill name discovered from skills/<name>/SKILL.md")
    entrypoint: str = Field(description="Exact exported runtime function name")
    request: dict[str, Any] = Field(default_factory=dict, description="Entrypoint request payload")


class DynamicSkillObservation(Observation):
    pass


class DynamicSkillExecutor(ToolExecutor[DynamicSkillAction, DynamicSkillObservation]):
    def __init__(self, skills_dir: Path, discovered: Sequence[DiscoveredSkill]) -> None:
        self.skills_dir = skills_dir
        self.skills = {item.name: item for item in discovered}

    def __call__(self, action: DynamicSkillAction, conversation: Any = None) -> DynamicSkillObservation:
        try:
            item = self.skills.get(action.skill)
            if item is None or item.runtime is None:
                raise ValueError(f"Skill {action.skill!r} has no executable mylib runtime")
            if action.entrypoint not in item.entrypoints:
                raise ValueError(
                    f"Entrypoint {action.entrypoint!r} is not exported by Skill {action.skill!r}; "
                    f"available: {list(item.entrypoints)}"
                )
            function = getattr(item.runtime, action.entrypoint)
            request = copy.deepcopy(action.request)
            signature = inspect.signature(function)
            parameters = signature.parameters
            # Any Skill entrypoint declaring session_state receives a private,
            # persistent session. This keeps the host independent of Skill and
            # entrypoint names while preserving multi-turn in-memory workspaces.
            if "session_state" in parameters:
                session = WORKFLOW_STATE.skill_sessions.setdefault(action.skill, {})
                supplied = request.pop("session_state", {})
                if not isinstance(supplied, dict):
                    raise TypeError("session_state input must be an object")
                validator = getattr(item.runtime, "validate_session_inputs", None)
                if supplied:
                    if not callable(validator):
                        raise ValueError("This Skill does not accept external session configuration")
                    accepted = validator(supplied, session, request)
                else:
                    accepted = {}
                if "request" in parameters:
                    kwargs = {"request": request, "session_state": session}
                else:
                    kwargs = {"session_state": session, **request}
                signature.bind(**kwargs)
                session.update(accepted)
                result = function(**kwargs)
            else:
                result = function(**request)
            if not isinstance(result, dict):
                result = {"result": result}
            result.setdefault("skill", action.skill)
            result.setdefault("entrypoint", action.entrypoint)
            return DynamicSkillObservation.from_text(
                text=json.dumps(result, ensure_ascii=False, default=str, separators=(",", ":"))
            )
        except Exception as exc:
            return DynamicSkillObservation.from_text(
                text=json.dumps({"error": _safe_message(exc)}, ensure_ascii=False), is_error=True
            )


class DynamicSkillTool(ToolDefinition[DynamicSkillAction, DynamicSkillObservation]):
    @classmethod
    def create(cls, conv_state: "ConversationState | None" = None, **params: Any) -> Sequence["DynamicSkillTool"]:
        skills_dir = Path(params["skills_dir"])
        discovered = params.get("discovered") or discover_skills(skills_dir)
        executable = [item for item in discovered if item.runtime is not None and item.entrypoints]
        if not executable:
            return []
        catalog = "; ".join(f"{item.name}: {', '.join(item.entrypoints)}" for item in executable)
        return [
            cls(
                description=(
                    "Dispatch an explicitly selected exported function from a discovered local Skill. "
                    "Do not invent Skill or entrypoint names; use the catalog. " + catalog
                ),
                action_type=DynamicSkillAction,
                observation_type=DynamicSkillObservation,
                annotations=ToolAnnotations(
                    title="Dynamic Skill runtime",
                    readOnlyHint=False,
                    destructiveHint=True,
                    idempotentHint=False,
                    openWorldHint=True,
                ),
                executor=DynamicSkillExecutor(skills_dir, executable),
            )
        ]


def register_workflow_tools(
    skills_dir: Path | None = None,
    discovered: Sequence[DiscoveredSkill] | None = None,
) -> None:
    from openhands.sdk.tool.registry import list_registered_tools

    registered = set(list_registered_tools())
    root = resolve_skills_dir(skills_dir)
    items = list(discovered) if discovered is not None else discover_skills(root)
    names = {item.name for item in items}
    # Legacy workflow tools are optional compatibility adapters.  They are
    # registered only when their exact Skill exists; all other Skills use the
    # directory-driven DynamicSkillTool below.
    if FAULT_SKILL in names and FaultEditWorkflowTool.name not in registered:
        register_tool(FaultEditWorkflowTool.name, FaultEditWorkflowTool)
    if ANALYSIS_SKILL in names and ShortCircuitWorkflowTool.name not in registered:
        register_tool(ShortCircuitWorkflowTool.name, ShortCircuitWorkflowTool)
    if DynamicSkillTool.name not in registered:
        register_tool(DynamicSkillTool.name, DynamicSkillTool)


def _resource_files(skill_dir: Path, resource_type: str) -> list[str]:
    resource_dir = skill_dir / resource_type
    if not resource_dir.is_dir():
        return []
    return sorted(
        path.relative_to(resource_dir).as_posix()
        for path in resource_dir.rglob("*")
        if path.is_file()
    )


def _load_selected_skill(skills_dir: Path, name: str) -> Skill:
    """Load one selected Skill while tolerating newer structured metadata.

    OpenHands SDK 1.35 expects ``compatibility`` and metadata values to be
    strings, while the current SkillsHub uses structured YAML for those fields.
    Normalize only the in-memory SDK representation; never rewrite SKILL.md.
    """
    skill_dir = skills_dir / name
    skill_path = skill_dir / "SKILL.md"
    document = frontmatter.load(skill_path)
    metadata = document.metadata or {}
    declared_name = str(metadata.get("name") or name)
    if declared_name != name:
        raise ValueError(
            f"Skill directory {name!r} declares a different name: {declared_name!r}"
        )
    description = str(metadata.get("description") or "").strip()
    if not description:
        raise ValueError(f"Skill {name!r} has no description")

    compatibility_value = metadata.get("compatibility")
    compatibility = None
    if compatibility_value is not None:
        compatibility = (
            compatibility_value
            if isinstance(compatibility_value, str)
            else json.dumps(compatibility_value, ensure_ascii=False, sort_keys=True)
        )
    raw_custom_metadata = metadata.get("metadata")
    custom_metadata = None
    if isinstance(raw_custom_metadata, dict):
        custom_metadata = {
            str(key): (
                value
                if isinstance(value, str)
                else json.dumps(value, ensure_ascii=False, sort_keys=True)
            )
            for key, value in raw_custom_metadata.items()
        }

    resources = SkillResources(
        skill_root=skill_dir.resolve().as_posix(),
        scripts=_resource_files(skill_dir, "scripts"),
        references=_resource_files(skill_dir, "references"),
        assets=_resource_files(skill_dir, "assets"),
    )
    return Skill(
        name=name,
        content=document.content,
        source=skill_path.resolve().as_posix(),
        is_agentskills_format=True,
        description=description,
        license=(str(metadata["license"]) if metadata.get("license") else None),
        compatibility=compatibility,
        metadata=custom_metadata,
        resources=resources if resources.has_resources() else None,
    )


def discover_skills(skills_dir: Path | None = None) -> list[DiscoveredSkill]:
    """Discover every valid direct-child Skill below ``skills_dir``.

    Discovery is deliberately directory driven.  A folder is a Skill only
    when it contains ``SKILL.md`` with a matching ``name`` and description.
    ``mylib`` is optional; when present its package is loaded in an isolated
    namespace and its exported callables are recorded for tool registration.
    """
    root = resolve_skills_dir(skills_dir)
    discovered: list[DiscoveredSkill] = []
    for skill_dir in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name):
        skill_path = skill_dir / "SKILL.md"
        if not skill_path.is_file():
            continue
        try:
            document = frontmatter.load(skill_path)
            metadata = document.metadata or {}
            name = str(metadata.get("name") or skill_dir.name).strip()
            description = str(metadata.get("description") or "").strip()
            if name != skill_dir.name:
                raise ValueError(f"declared name {name!r} does not match directory")
            if not description:
                raise ValueError("description is empty")
            runtime = None
            init_path = skill_dir / "mylib" / "__init__.py"
            if init_path.is_file():
                runtime = load_skill_runtime(root, name)
            discovered.append(
                DiscoveredSkill(
                    name=name,
                    directory=skill_dir.resolve(),
                    description=description,
                    runtime=runtime,
                    entrypoints=_skill_entrypoints(runtime),
                )
            )
        except Exception as exc:
            raise RuntimeError(f"Unable to load Skill {skill_dir.name!r}: {_safe_message(exc)}") from exc
    if not discovered:
        raise RuntimeError(f"No valid Skills were found below {root}")
    return discovered


def load_integrated_skills(skills_dir: Path) -> list[Skill]:
    """Backward-compatible name for loading all discovered Skills."""
    return [_load_selected_skill(skills_dir, item.name) for item in discover_skills(skills_dir)]


def create_agent(
    *,
    skills_dir: Path | None = None,
    prompt_path: Path | None = None,
) -> Agent:
    selected_skills = resolve_skills_dir(skills_dir)
    discovered = discover_skills(selected_skills)
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        raise RuntimeError("LLM_API_KEY environment variable is not set")
    cloudpss_token = (
        os.getenv("SIMSTUDIO_TOKEN")
        or os.getenv("CLOUDPSS_TOKEN")
        or os.getenv("CLOUDPSS_LOGIN_TOKEN")
    )
    if not cloudpss_token:
        raise RuntimeError("SIMSTUDIO_TOKEN, CLOUDPSS_TOKEN, or CLOUDPSS_LOGIN_TOKEN is required")
    if not os.getenv("CLOUDPSS_API_URL"):
        raise RuntimeError("CLOUDPSS_API_URL environment variable is not set")
    os.environ.setdefault("CLOUDPSS_TOKEN", cloudpss_token)
    setToken(cloudpss_token)

    llm = LLM(
        usage_id="cloudpss-verified-integrated-agent-v2",
        model=os.getenv("LLM_MODEL", "deepseek/deepseek-chat"),
        api_key=SecretStr(api_key),
        base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
    )
    register_workflow_tools(selected_skills, discovered)
    context = AgentContext(
        skills=[_load_selected_skill(selected_skills, item.name) for item in discovered],
        load_public_skills=False,
    )
    tool_params = {"skills_dir": str(selected_skills)}
    tools: list[Tool] = [Tool(name=DynamicSkillTool.name, params=tool_params)]
    # Keep the two mature workflow tools as optional compatibility adapters.
    names = {item.name for item in discovered}
    if FAULT_SKILL in names:
        tools.append(Tool(name=FaultEditWorkflowTool.name, params=tool_params))
    if ANALYSIS_SKILL in names:
        tools.append(Tool(name=ShortCircuitWorkflowTool.name, params=tool_params))
    return Agent(
        llm=llm,
        tools=tools,
        agent_context=context,
        system_prompt=load_system_prompt(prompt_path),
    )


def self_test() -> None:
    skills_dir = resolve_skills_dir()
    prompt_path = resolve_system_prompt_path() if DEFAULT_SYSTEM_PROMPT_PATH.is_file() else None
    prompt = load_system_prompt(prompt_path)
    discovered = discover_skills(skills_dir)
    integrated_skills = load_integrated_skills(skills_dir)
    assert prompt
    assert [skill.name for skill in integrated_skills] == [item.name for item in discovered]
    assert {item.name for item in discovered} >= {
        "cloudpss-aux-modeling", "short-circuit-analysis", "generate-simulation-report"
    }
    aux = next(item for item in discovered if item.name == "cloudpss-aux-modeling")
    analysis = next(item for item in discovered if item.name == "short-circuit-analysis")
    report = next(item for item in discovered if item.name == "generate-simulation-report")
    assert "edit_model_from_context" in aux.entrypoints
    assert "analyze_model_from_source" in analysis.entrypoints
    assert report.runtime is None
    register_workflow_tools(skills_dir, discovered)
    assert len(DynamicSkillTool.create(skills_dir=str(skills_dir), discovered=discovered)) == 1
    assert _time_window_text([2.0, 2.1]) == "2 至 2.1 s"
    assert _time_window_text([]) == "未提供"
    assert _time_window_text([2.0]) == "未提供"
    assert _time_window_text([2.0, 2.1, "ignored"]) == "2 至 2.1 s"
    assert _time_window_text("2.0,2.1") == "未提供"

    # Contract checks use fake runtimes only: no model fetch, save, or EMT call.
    test_state = WorkflowState(current_turn=1)
    original_state = globals()["WORKFLOW_STATE"]
    globals()["WORKFLOW_STATE"] = test_state
    try:
        class FakeEditRuntime:
            calls = 0

            @classmethod
            def execute_edit_plan_from_source(
                cls,
                plan: dict[str, Any],
                target_rid: str,
                *,
                allow_source_overwrite: bool = False,
            ) -> dict[str, Any]:
                cls.calls += 1
                assert not allow_source_overwrite
                return {
                    "status": "verified_saved",
                    "plan_id": plan["plan_id"],
                    "new_rid": target_rid,
                }

        test_state.plans["plan-1"] = StoredPlan(
            source_rid="model/owner/source",
            operations=[{"operation": "update"}],
            mode="atomic",
            created_turn=1,
            payload={"plan_id": "plan-1"},
        )
        edit_executor = FaultEditWorkflowExecutor(skills_dir)
        try:
            edit_executor._execute(
                FakeEditRuntime,
                FaultEditWorkflowAction(
                    command="execute",
                    plan_id="plan-1",
                    target_rid="model/other/target",
                ),
            )
            raise AssertionError("Owner mismatch must fail before execution")
        except ValueError:
            pass
        assert "plan-1" in test_state.plans and FakeEditRuntime.calls == 0
        saved = edit_executor._execute(
            FakeEditRuntime,
            FaultEditWorkflowAction(
                command="execute",
                plan_id="plan-1",
                target_rid="model/owner/target",
            ),
        )
        assert not saved.is_error and FakeEditRuntime.calls == 1
        assert "plan-1" in test_state.consumed_plans
        assert test_state.working_rid == "model/owner/target"

        typed_preview = FaultEditWorkflowAction(
            command="preview",
            source_rid="model/owner/source",
            operations=[
                {
                    "operation": "create",
                    "target": {"component_id": "bus-24", "port": "0"},
                    "changes": {"fs": 3, "fe": 3.1, "ft": 7, "Init": 1e8, "chg": 0.001},
                    "options": {"name": "Bus24三相故障"},
                }
            ],
        )
        normalized = edit_executor._validated_operations(typed_preview.operations)
        assert normalized[0]["target"] == {"component_id": "bus-24", "port": "0"}
        assert normalized[0]["options"]["name"] == "Bus24三相故障"

        test_state.plans["plan-2"] = StoredPlan(
            source_rid="model/owner/target",
            operations=[{"operation": "update"}],
            mode="atomic",
            created_turn=1,
            payload={"plan_id": "plan-2"},
        )

        class FakeOverwriteRuntime:
            calls = 0

            @classmethod
            def execute_edit_plan_from_source(
                cls,
                plan: dict[str, Any],
                target_rid: str,
                *,
                allow_source_overwrite: bool = False,
            ) -> dict[str, Any]:
                cls.calls += 1
                assert allow_source_overwrite
                assert target_rid == "model/owner/target"
                return {
                    "status": "verified_saved",
                    "plan_id": plan["plan_id"],
                    "new_rid": target_rid,
                }

        overwritten = edit_executor._execute(
            FakeOverwriteRuntime,
            FaultEditWorkflowAction(command="execute", plan_id="plan-2"),
        )
        assert not overwritten.is_error and FakeOverwriteRuntime.calls == 1
        assert test_state.working_rid == "model/owner/target"

        test_state.plans["plan-3"] = StoredPlan(
            source_rid="model/owner/read-only",
            operations=[{"operation": "update"}],
            mode="atomic",
            created_turn=1,
            payload={"plan_id": "plan-3"},
        )
        test_state.readonly_rids.add("model/owner/read-only")
        try:
            edit_executor._execute(
                FakeOverwriteRuntime,
                FaultEditWorkflowAction(
                    command="execute",
                    plan_id="plan-3",
                    target_rid="model/owner/read-only",
                ),
            )
            raise AssertionError("A read-only source RID must not be overwritten")
        except ValueError:
            pass
        assert "plan-3" in test_state.plans

        cancelled = edit_executor._cancel(
            FaultEditWorkflowAction(command="cancel", plan_id="plan-3")
        )
        assert not cancelled.is_error and "plan-3" not in test_state.plans

        class FakeAnalysisRuntime:
            calls = 0

            @classmethod
            def analyze_model_from_source(
                cls,
                source_rid: str,
                config: dict[str, Any],
                *,
                output_dir: Path,
            ) -> dict[str, Any]:
                cls.calls += 1
                assert config == {"analysis": {"target_fault_id": "fault-2"}}
                return {
                    "task_id": "offline-task-id",
                    "files_saved": {
                        "complete": True,
                        "directory": str(output_dir / "offline-task-id"),
                        "files": ["task.json"],
                    },
                    "analysis_context": {
                        "target_fault_id": "fault-2",
                        "target_fault_name": "Bus24三相故障",
                        "fault_bus": "bus24",
                        "base_voltage_kv": 345.0,
                    },
                    "summary": {
                        "channel_count": 1,
                        "max_peak_current_ka": 10.0,
                        "max_fault_rms_current_ka": 7.0,
                        "max_steady_fault_rms_current_ka": 6.5,
                        "max_short_circuit_capacity_mva": 4183.0,
                        "max_steady_fault_short_circuit_capacity_mva": 3885.0,
                        "worst_grid_strength": "not_assessed",
                    },
                    "channels": [
                        {
                            "channel": "#fault-2.I:0",
                            "data_source": {
                                "component_id": "fault-2",
                                "waveform_api": "CloudPSS EMTResult.getPlotChannelData",
                            },
                            "unit": {
                                "raw_unit": "A",
                                "normalized_unit": "kA",
                                "unit_source": "parameter.unit",
                                "unit_scale_to_ka": 0.001,
                            },
                            "metrics": {
                                "sample_count": 1000,
                                "peak_current_ka": 10.0,
                                "peak_current_time_s": 3.01,
                                "fault_peak_current_ka": 9.0,
                                "prefault_rms_current_ka": 0.1,
                                "fault_rms_current_ka": 7.0,
                                "steady_fault_rms_current_ka": 6.5,
                                "postfault_rms_current_ka": 0.2,
                                "dc_offset_estimate_ka": 0.3,
                                "short_circuit_capacity_mva": 4183.0,
                                "steady_fault_short_circuit_capacity_mva": 3885.0,
                            },
                            "thevenin": {
                                "z_th_ohm": {
                                    "magnitude": 28.45,
                                    "real": None,
                                    "imag": None,
                                    "xr_ratio": None,
                                },
                                "z_th_pu": {"magnitude": 0.0239},
                                "scr": None,
                                "escr": None,
                                "grid_strength": "not_assessed",
                            },
                            "unavailable": [
                                {"field": "scr", "reason": "未提供并网设备额定容量，无法计算 SCR。"}
                            ],
                        }
                    ],
                    "warnings": [],
                }

        test_state.analysis_requests["request-1"] = {
            "source_rid": "model/owner/target",
            "result": {"faults": [{"id": "fault-1"}, {"id": "fault-2"}]},
            "created_turn": 2,
        }
        analysis_executor = ShortCircuitWorkflowExecutor(skills_dir)
        try:
            analysis_executor._analyze(
                FakeAnalysisRuntime,
                "model/owner/target",
                ShortCircuitWorkflowAction(
                    command="analyze",
                    source_rid="model/owner/target",
                    analysis_request_id="request-1",
                    target_fault_id="unknown-fault",
                ),
            )
            raise AssertionError("Unknown fault must fail before formal analysis")
        except ValueError:
            pass
        assert "request-1" in test_state.analysis_requests and FakeAnalysisRuntime.calls == 0
        analyzed = analysis_executor._analyze(
            FakeAnalysisRuntime,
            "model/owner/target",
            ShortCircuitWorkflowAction(
                command="analyze",
                source_rid="model/owner/target",
                analysis_request_id="request-1",
                target_fault_id="fault-2",
            ),
        )
        assert not analyzed.is_error and FakeAnalysisRuntime.calls == 1
        assert test_state.public_result is not None
        assert test_state.public_result["task_id"] == "offline-task-id"
        assert len(test_state.public_result["channels"]) == 1
        assert "request-1" in test_state.consumed_analysis_requests

        detailed_response = compose_console_response(
            '{"task_id":"offline-task-id"}', test_state.public_result
        )
        assert "短路分析已完成" in detailed_response
        assert "| 项目 | 结果 |" in detailed_response
        assert "| 原始通道 | 峰值 | 峰值时刻 |" in detailed_response
        assert "Thevenin、SCR 与 ESCR" in detailed_response
        assert "无法计算的指标" in detailed_response
        assert "#fault-2.I:0" in detailed_response
        assert "10 kA" in detailed_response
        assert "参数缺失" in compose_console_response(
            "",
            {"error": {"stage": "model_parameters", "message": "参数缺失"}},
        )
        runtime_failure = RuntimeError("wrapped failure")
        runtime_failure.public_error = {
            "stage": "file_saving",
            "error_type": "PermissionError",
            "message": "工作区不可写",
            "task_id": "completed-cloud-task",
            "simulation_completed": True,
            "files_saved": False,
        }
        failure_payload = _short_circuit_error_payload(runtime_failure)
        assert failure_payload["error"]["task_id"] == "completed-cloud-task"
        failure_response = compose_console_response("", failure_payload)
        assert "仿真已完成，但数据文件保存失败" in failure_response
        assert "completed-cloud-task" in failure_response
        selection_failure = compose_console_response(
            "",
            {
                "error": {
                    "stage": "short_circuit_analysis",
                    "error_type": "RuntimeError",
                    "message": "Multiple faults require a user selection in a later turn",
                }
            },
        )
        assert "尚未取得可执行的唯一目标选择" in selection_failure
        assert "技术详情" in selection_failure
        candidate_reply = compose_console_response(
            json.dumps(
                {
                    "faults": [
                        {"id": "fault-1", "name": "原故障"},
                        {"id": "fault-2", "name": "Bus24三相故障", "current_channel": "#fault-2.I"},
                    ],
                    "selection_required": True,
                },
                ensure_ascii=False,
            ),
            None,
        )
        assert "检测到 2 个活动故障" in candidate_reply
        assert "| 序号 | 故障名称 | 组件 ID | 位置 |" in candidate_reply
        assert "Bus24三相故障" in candidate_reply
        assert not candidate_reply.lstrip().startswith("{")
    finally:
        globals()["WORKFLOW_STATE"] = original_state

    print(
        json.dumps(
            {
                "status": "ok",
                "skills_dir": str(skills_dir),
                "skills": [item.name for item in discovered],
                "system_prompt": str(prompt_path),
                "dynamic_runtime_entrypoints": {
                    item.name: list(item.entrypoints) for item in discovered if item.runtime is not None
                },
                "offline_contracts": "passed",
            },
            ensure_ascii=False,
        )
    )


def main() -> None:
    from openhands.sdk import Conversation

    agent = create_agent()
    conversation = Conversation(agent=agent, workspace=PROJECT_DIR)
    try:
        print("Verified CloudPSS Agent v2 ready. 输入问题，输入 exit 退出。")
        while True:
            try:
                message = input("用户> ").strip()
            except EOFError:
                break
            if message.lower() in {"exit", "quit", "退出"}:
                break
            if not message:
                continue
            turn = WORKFLOW_STATE.begin_turn()
            conversation.send_message(message)
            conversation.run()
            agent_response = get_agent_final_response(list(conversation.state.events)) or ""
            public_result = (
                WORKFLOW_STATE.public_result
                if WORKFLOW_STATE.public_result_turn == turn
                else None
            )
            response = compose_console_response(agent_response, public_result)
            if response:
                print(f"Agent> {response}")
    finally:
        conversation.close()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        main()
