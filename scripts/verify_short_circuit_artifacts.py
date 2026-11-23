"""Independently recompute direct-current metrics from one CloudPSS task directory."""

import argparse
import csv
import json
import math
from pathlib import Path


def verify(directory: Path, task_id: str) -> dict:
    receipt = json.loads((directory / "submission.json").read_bytes())
    result = json.loads((directory / task_id / "analysis_result.json").read_bytes())
    submission = result.get("workspace_submission") or result["submission"]
    if any(record.get("task_id") != task_id for record in (receipt, result, submission)):
        raise ValueError("The analysis artifacts and receipt must identify the same task")
    if receipt["selection"] != submission["selection"] or receipt.get("revision_hash") != submission.get("revision_hash"):
        raise ValueError("The analysis and receipt identify different schemes or model revisions")
    analysis = result["analysis"]
    start, stop = analysis["analysis_window"]
    fault_start, fault_stop = analysis["fault_window"]
    if not start <= fault_start < fault_stop <= stop:
        raise ValueError("The fault window is outside the analysis window")
    raw_index = result["waveform_files"]["raw"]["channels"]
    rows = []
    for channel in result["channels"]:
        if channel["kind"] != "current":
            raise ValueError("Independent verification requires a direct current waveform")
        name = channel["channel"]
        files = [item for item in raw_index if (item["channel"], item["plot_index"]) == (name, channel["plot_index"])]
        if len(files) != 1:
            raise ValueError(f"Cannot identify one original waveform for {name!r}")
        scale = channel["unit"]["effective_current_scale"]
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError(f"Invalid current scale for {name!r}")
        task_dir = (directory / task_id).resolve()
        raw_file = (task_dir / files[0]["csv_path"]).resolve()
        if not raw_file.is_relative_to(task_dir):
            raise ValueError(f"Waveform file is outside task directory for {name!r}")
        with raw_file.open(encoding="utf-8-sig", newline="") as stream:
            samples = [(float(row["time"]), float(row[name]) * scale) for row in csv.DictReader(stream)]
        all_values = [value for time, value in samples if start <= time <= stop]
        fault_values = [value for time, value in samples if fault_start <= time <= fault_stop]
        if not all_values or not fault_values:
            raise ValueError(f"No samples in a required window for {name!r}")
        metrics = {
            "peak_current": max(map(abs, all_values)),
            "fault_peak_current": max(map(abs, fault_values)),
            "fault_rms_current": math.sqrt(math.fsum(value * value for value in fault_values) / len(fault_values)),
        }
        for key, value in metrics.items():
            if not math.isclose(value, channel["analysis"][key], rel_tol=1e-10, abs_tol=1e-12):
                raise ValueError(f"Recomputed {key} differs for {name!r}")
        rows.append({"channel": name, "fault_samples": len(fault_values), **metrics})
    if not rows:
        raise ValueError("No direct current channels were analyzed")
    return {"task_id": task_id, "selection": receipt["selection"], "unit": "kA", "channels": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("task_id")
    args = parser.parse_args()
    print(json.dumps(verify(args.directory, args.task_id), ensure_ascii=False))
