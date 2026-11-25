"""Read task-bound short-circuit report evidence and verify the original analysis metrics."""

import argparse
import csv
from html import escape
import json
import math
from pathlib import Path
import sys


METRICS = (
    ("peak_current", "全分析窗采样峰值", "Peak over analysis window"),
    ("fault_peak_current", "故障窗采样峰值", "Peak over fault window"),
    ("fault_rms_current", "故障窗总 RMS", "Total RMS over fault window"),
)


def load(path):
    return json.loads(path.read_bytes())


def require_agreement(first, second, key):
    if first.get(key) is not None and second.get(key) is not None and first[key] != second[key]:
        raise ValueError(f"Submission records disagree on {key}")


def read_submission(result, analysis_path, task_id, receipt_path):
    records = [result[key] for key in ("workspace_submission", "submission") if result.get(key)]
    if receipt_path is None:
        candidates = (analysis_path.parent / "submission.json", analysis_path.parent.parent / "submission.json")
        receipt_path = next((path for path in candidates if path.is_file()), None)
    if receipt_path is not None:
        records.append(load(receipt_path))
    if any(record.get("task_id") != task_id for record in records):
        raise ValueError("The submission record identifies a different task")

    combined = {}
    for record in records:
        for key in ("revision_hash", "analysis_context_sha256"):
            require_agreement(combined, record, key)
        for field, keys in (
            ("selection", ("job_index", "config_index")),
            ("workspace", ("source_rid", "baseline_revision", "version", "sha256")),
        ):
            incoming = record.get(field) or {}
            existing = combined.setdefault(field, {})
            for key in keys:
                require_agreement(existing, incoming, key)
            existing.update({key: value for key, value in incoming.items() if value is not None})
        for key in ("revision_hash", "analysis_context_sha256"):
            if record.get(key) is not None:
                combined[key] = record[key]

    workspace = combined.get("workspace", {})
    selection = combined.get("selection", {})
    binding = workspace.get("binding") or {}
    for key in ("job_index", "config_index"):
        require_agreement(selection, binding, key)
    return {
        "receipt": str(receipt_path) if receipt_path is not None else None,
        "runtime_revision": combined.get("revision_hash"),
        "baseline_revision": workspace.get("baseline_revision"),
        "source_rid": workspace.get("source_rid") or result.get("model_rid"),
        "selection": selection,
        "job_name": binding.get("job_name"),
        "config_name": binding.get("config_name"),
    }


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def verify_waveform(path, name, scale, windows, metrics, indexed_count, analysis_count):
    start, end = windows["analysis"]
    fault_start, fault_end = windows["fault"]
    if not start <= fault_start <= fault_end <= end:
        raise ValueError(f"{name}: sampled fault window is outside the analysis window")

    all_values, fault_values = [], []
    previous = -math.inf
    count = 0
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = csv.DictReader(stream)
        if not rows.fieldnames or any(rows.fieldnames.count(key) != 1 for key in ("time", name)):
            raise ValueError(f"{name}: invalid original waveform headers in {path.name}")
        for row in rows:
            time, value = float(row["time"]), float(row[name]) * scale
            if not math.isfinite(time) or not math.isfinite(value) or time <= previous:
                raise ValueError(f"{name}: invalid waveform sample in {path.name}")
            count += 1
            previous = time
            if start <= time <= end:
                all_values.append((time, value))
            if fault_start <= time <= fault_end:
                fault_values.append((time, value))

    for key, points in (("analysis", all_values), ("fault", fault_values)):
        if not points or [points[0][0], points[-1][0]] != windows[key]:
            raise ValueError(f"{name}: recorded {key} boundaries are missing from {path.name}")
    if indexed_count is not None and count != indexed_count:
        raise ValueError(f"{name}: original waveform sample count differs from index")
    if analysis_count is not None and len(all_values) != analysis_count:
        raise ValueError(f"{name}: analysis-window sample count differs from analysis record")
    calculated = (
        max(abs(value) for _, value in all_values),
        max(abs(value) for _, value in fault_values),
        math.sqrt(math.fsum(value * value for _, value in fault_values) / len(fault_values)),
    )
    for (key, _, _), value in zip(METRICS, calculated):
        if not math.isclose(value, metrics[key], rel_tol=1e-10, abs_tol=1e-12):
            raise ValueError(f"{name}: recomputed {key} differs from the task analysis")
    return {"analysis": len(all_values), "fault": len(fault_values)}


def read_channel(channel, raw_index, task_dir, default_unit):
    name = channel["channel"]
    original = channel["analysis"]
    unit = channel.get("unit") or {}
    metrics = {key: original.get(key) for key, _, _ in METRICS}
    for key, value in metrics.items():
        if value is not None and (not finite(value) or value < 0):
            raise ValueError(f"{name}: invalid original {key}")
    windows = {
        "analysis": [original.get("t_start"), original.get("t_end")],
        "fault": [original.get("fault_window_start"), original.get("fault_window_end")],
    }
    row = {
        "channel": name,
        "plot_index": channel.get("plot_index"),
        "kind": channel.get("kind"),
        "method": original.get("method"),
        "measurement": channel.get("source"),
        "source_channels": channel.get("source_channels"),
        "unit": unit,
        "metric_unit": unit.get("normalized_unit") or default_unit,
        "metrics": metrics,
        "sampled_windows": windows,
        "sample_counts": {"analysis": original.get("sample_count"), "fault": None},
        "raw_csv_path": None,
        "verification": "not_verified",
    }
    if row["kind"] != "current":
        return {**row, "verification": "not_direct_current"}

    matches = [
        entry for entry in raw_index
        if (entry["channel"], entry["plot_index"]) == (name, row["plot_index"])
    ]
    if len(matches) > 1:
        raise ValueError(f"{name}: multiple original waveform entries match the channel and plot")
    if not matches:
        return {**row, "verification": "no_raw_index_entry"}
    entry = matches[0]
    path = (task_dir / entry["csv_path"]).resolve()
    if not path.is_relative_to(task_dir):
        raise ValueError(f"{name}: waveform path is outside the analysis directory")
    if not path.is_file():
        return {**row, "verification": "raw_csv_missing", "expected_raw_csv_path": entry["csv_path"]}

    scale = unit.get("effective_current_scale")
    if not unit.get("raw_unit") or not row["metric_unit"] or not finite(scale) or scale <= 0:
        return {**row, "verification": "unconfirmed_unit_or_scale"}
    indexed_unit = (entry.get("unit") or {}).get("raw_unit")
    if indexed_unit and indexed_unit != unit["raw_unit"]:
        raise ValueError(f"{name}: raw waveform unit differs from the analysis record")
    if not all(finite(value) for window in windows.values() for value in window):
        return {**row, "verification": "missing_sampled_boundaries"}
    if any(value is None for value in metrics.values()):
        return {**row, "verification": "missing_analysis_metrics"}

    counts = verify_waveform(path, name, scale, windows, metrics, entry.get("sample_count"), original.get("sample_count"))
    return {**row, "raw_csv_path": entry["csv_path"], "sample_counts": counts, "verification": "verified"}


def read_evidence(analysis_path, task_id, receipt_path=None):
    result = load(analysis_path)
    if not task_id or result.get("task_id") != task_id:
        raise ValueError("The requested task ID does not match the analysis result")
    submission = read_submission(result, analysis_path, task_id, receipt_path)
    analysis = result["analysis"]
    raw_index = ((result.get("waveform_files") or {}).get("raw") or {}).get("channels") or []
    channels = [
        read_channel(channel, raw_index, analysis_path.parent, analysis.get("normalized_current_unit"))
        for channel in result["channels"]
    ]
    if not channels:
        raise ValueError("The task analysis contains no analyzed channels")
    return {
        "task_id": task_id,
        "analysis_json": str(analysis_path),
        "model": result.get("model"),
        "run": submission,
        "fault": {
            key: analysis.get(key)
            for key in ("target_fault_id", "fault_bus", "fault_type", "fault_phases",
                        "fault_connection_type", "terminal_connection")
        },
        "configured_windows": {key: analysis.get(f"{key}_window") for key in ("analysis", "fault")},
        "channels": channels,
    }


def html_table(evidence, language):
    zh = language == "zh-CN"
    labels = {
        "verified": ("原始波形已复算", "Verified from original waveform"),
        "not_direct_current": ("非直接量测，沿用原分析值", "Indirect current, original analysis value"),
        "no_raw_index_entry": ("缺少原始通道索引", "Missing original waveform index"),
        "raw_csv_missing": ("缺少原始波形文件", "Missing original waveform CSV"),
        "unconfirmed_unit_or_scale": ("单位或比例待确认", "Unconfirmed unit or scale"),
        "missing_sampled_boundaries": ("缺少实际采样边界", "Missing sampled boundaries"),
        "missing_analysis_metrics": ("原分析指标不完整", "Original metrics incomplete"),
    }

    def cell(value):
        return "—" if value is None else escape(f"{value:.8g}" if isinstance(value, float) else str(value))

    def window(bounds):
        return "—" if None in bounds else " – ".join(escape(str(value)) for value in bounds)

    headings = (
        ("通道", "Channel"), *((chinese, english) for _, chinese, english in METRICS),
        ("单位", "Unit"), ("全分析窗采样范围（s）", "Analysis sample range (s)"),
        ("故障窗采样范围（s）", "Fault sample range (s)"), ("故障窗样点数", "Fault samples"),
        ("证据", "Evidence"),
    )
    index = 0 if zh else 1
    columns = "".join(f'<th scope="col">{heading[index]}</th>' for heading in headings)
    rows = []
    for row in evidence["channels"]:
        name = f'{row["channel"]} (plot {row["plot_index"]})' if row["plot_index"] is not None else row["channel"]
        values = [cell(row["metrics"][key]) for key, _, _ in METRICS]
        values.extend((
            cell(row["metric_unit"]),
            window(row["sampled_windows"]["analysis"]),
            window(row["sampled_windows"]["fault"]),
            cell(row["sample_counts"]["fault"]),
            labels[row["verification"]][index],
        ))
        cells = "".join(f"<td>{value}</td>" for value in values)
        rows.append(f'<tr><th scope="row">{cell(name)}</th>{cells}</tr>')
    caption = "原任务分析指标" if zh else "Original task metrics"
    return (
        f'<div class="report-evidence-table" data-task-id="{cell(evidence["task_id"])}" style="overflow-x:auto">'
        f'<table><caption>{caption} · <code>{cell(evidence["task_id"])}</code></caption>'
        f'<thead><tr>{columns}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    )


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--html-table", choices=("zh-CN", "en"), help="Emit an HTML table instead of JSON.")
    parser.add_argument("--check-html", type=Path, help="Check that the final report contains the generated table.")
    args = parser.parse_args()
    if args.check_html and not args.html_table:
        parser.error("--check-html requires --html-table with the report table language")
    try:
        evidence = read_evidence(args.analysis.resolve(), args.task_id, args.receipt)
        if args.html_table:
            table = html_table(evidence, args.html_table)
            if args.check_html:
                if args.check_html.read_text(encoding="utf-8").count(table) != 1:
                    raise ValueError("The report must contain the original task metric table exactly once")
                print(f"Verified report metric table for task {evidence['task_id']}")
            else:
                print(table)
        else:
            print(json.dumps(evidence, ensure_ascii=False, allow_nan=False))
    except (OSError, ValueError, KeyError, TypeError, OverflowError, csv.Error) as error:
        parser.exit(1, f"Short-circuit evidence error: {error}\n")
