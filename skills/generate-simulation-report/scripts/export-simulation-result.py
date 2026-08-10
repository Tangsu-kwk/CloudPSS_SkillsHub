#!/usr/bin/env python3
import argparse
import csv
import json
import re
import sys
from pathlib import Path

import cloudpss
from cloudpss.job.job import Job


RESULT_RID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
OUTPUT_ROOT = "simulation-results"
WAIT_TIMEOUT_SECONDS = 120


def output_directory(workspace: Path, result_rid: str) -> Path:
    """根据结果 RID 生成导出目录，并防止路径穿越到工作区之外。"""
    if not RESULT_RID_PATTERN.fullmatch(result_rid):
        raise ValueError("result_rid 格式无效")

    workspace = workspace.resolve()
    output = (workspace / OUTPUT_ROOT / result_rid).resolve()
    # result_rid 会参与路径拼接，必须确认最终目录仍在当前工作区内。
    if workspace not in output.parents:
        raise ValueError("输出目录必须位于当前工作区")
    return output


def write_csv(path: Path, headers: list[str], columns: list[list]) -> None:
    """按列写入 CSV，自动用空字符串补齐长度较短的列。"""
    row_count = max((len(column) for column in columns), default=0)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        for index in range(row_count):
            writer.writerow([
                column[index] if index < len(column) else ""
                for column in columns
            ])


def export_table(path: Path, tables: list[dict]) -> int:
    """导出 CloudPSS 表格结果，并返回写出的数据行数。"""
    if not tables:
        write_csv(path, [], [])
        return 0

    columns = tables[0].get("data", {}).get("columns", [])
    write_csv(
        path,
        [str(column.get("name", "")) for column in columns],
        [list(column.get("data", [])) for column in columns],
    )
    return max((len(column.get("data", [])) for column in columns), default=0)


def export_powerflow(result, output: Path, result_rid: str) -> dict:
    """导出潮流计算结果，生成母线和支路 CSV 以及 manifest 元数据。"""
    buses_file = "buses.csv"
    branches_file = "branches.csv"
    bus_rows = export_table(output / buses_file, result.getBuses())
    branch_rows = export_table(output / branches_file, result.getBranches())
    return {
        "result_rid": result_rid,
        "simulation_type": "powerflow",
        "files": [
            {"path": buses_file, "kind": "buses", "rows": bus_rows},
            {"path": branches_file, "kind": "branches", "rows": branch_rows},
        ],
    }


def export_emt(result, output: Path, result_rid: str) -> dict:
    """导出 EMT 波形结果，每个 plot 输出一个按时间对齐的 CSV。"""
    files = []
    for index, plot in enumerate(result.getPlots()):
        names = list(result.getPlotChannelNames(index) or [])
        traces = [result.getPlotChannelData(index, name) for name in names]
        traces = [trace for trace in traces if trace is not None]

        # 同一个 plot 下的所有通道必须共享同一条时间轴，报告图表才能正确叠加。
        x_values = list(traces[0].get("x", [])) if traces else []
        if any(list(trace.get("x", [])) != x_values for trace in traces[1:]):
            raise ValueError(f"plot {index} 的通道时间轴不一致")
        if any(len(trace.get("y", [])) != len(x_values) for trace in traces):
            raise ValueError(f"plot {index} 的通道数据长度与时间轴不一致")

        filename = f"plot_{index:03d}.csv"
        write_csv(
            output / filename,
            ["time", *names],
            [x_values, *[list(trace.get("y", [])) for trace in traces]],
        )
        files.append({
            "path": filename,
            "kind": "waveform",
            "plot_index": index,
            "title": plot.get("data", {}).get("title"),
            "channels": names,
            "points": len(x_values),
        })

    return {
        "result_rid": result_rid,
        "simulation_type": "emt",
        "files": files,
    }


def export_result(result_rid: str, token: str, workspace: Path) -> dict:
    """拉取指定 CloudPSS 结果，按结果类型导出文件并写入 manifest。"""
    output = output_directory(workspace, result_rid)
    output.mkdir(parents=True, exist_ok=True)

    cloudpss.setToken(token)
    job = Job.fetch(result_rid)
    result = job.result
    result.waitFor(WAIT_TIMEOUT_SECONDS)

    # CloudPSS 不同仿真类型暴露的方法不同，这里用能力检测选择导出器。
    if hasattr(result, "getPlots"):
        manifest = export_emt(result, output, result_rid)
    elif hasattr(result, "getBuses") and hasattr(result, "getBranches"):
        manifest = export_powerflow(result, output, result_rid)
    else:
        raise TypeError(f"不支持的仿真结果类型: {type(result).__name__}")

    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "simulation_type": manifest["simulation_type"],
        "output_directory": str(output),
        "manifest": str(manifest_path),
        "file_count": len(manifest["files"]) + 1,
    }


def parse_args() -> argparse.Namespace:
    """解析命令行参数；token 只作为入参使用，不在帮助文本中展示。"""
    parser = argparse.ArgumentParser(description="导出 CloudPSS 仿真结果到当前工作区")
    parser.add_argument("--result-rid", required=True, help="CloudPSS 仿真结果 RID")
    parser.add_argument("--token", required=True, help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    """命令行入口：导出结果并以 JSON 输出摘要，失败时返回非零状态码。"""
    args = parse_args()
    try:
        summary = export_result(args.result_rid, args.token, Path.cwd())
    except Exception as error:
        print(f"错误: {error}", file=sys.stderr)
        return 1

    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
