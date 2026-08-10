from __future__ import annotations

import json
from pathlib import Path
import sys


SKILL_DIR = Path(__file__).resolve().parents[1]
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from mylib.runtime import DEFAULT_MODEL_RID, load_model_from_source, run_short_circuit_analysis  # noqa: E402


def main() -> None:
    source = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL_RID
    model = load_model_from_source(source)
    config = {
        "analysis": {
            "base_voltage_kv": 230.0,
            "power_scale_mw": 1.0,
            "voltage_scale_pu": 1.0,
            "analysis_window": [0.0, 10.0],
            "prefault_window": [0.0, 0.5],
            "fault_window": [2.0, 2.5],
            "postfault_window": [9.0, 10.0],
            "min_samples": 128,
        },
        "thevenin": {
            "enabled": True,
            "system_base_mva": 100.0,
            "plant_rating_mva": 1.0,
            "reactive_compensation_mvar": 0.0,
            "xr_ratio": 10.0,
            "weak_scr_threshold": 2.0,
            "strong_scr_threshold": 3.0,
        },
        "channels": {
            "equivalent_pairs": [
                {"power": "#P1:0", "voltage": "vac:0"},
                {"power": "#P2:0", "voltage": "vac:1"},
                {"power": "#P3:0", "voltage": "vac:2"},
            ],
            "auto_max_channels": 3,
        },
    }
    result = run_short_circuit_analysis(model, config=config)
    if result["summary"]["channel_count"] != 3:
        raise RuntimeError(f"Expected 3 channels, got {result['summary']['channel_count']}")
    if "estimated_from_power_voltage" not in result["summary"]["methods"]:
        raise RuntimeError(f"Expected estimated method, got {result['summary']['methods']}")
    for row in result["channels"]:
        analysis = row["analysis"]
        required = [
            "peak_current",
            "fault_rms_current",
            "prefault_rms_current",
            "postfault_rms_current",
            "short_circuit_mva",
        ]
        missing = [key for key in required if key not in analysis]
        if missing:
            raise RuntimeError(f"Missing fields for {row['channel']}: {missing}")
        if analysis["sample_count"] < config["analysis"]["min_samples"]:
            raise RuntimeError(f"Insufficient samples for {row['channel']}")
        if analysis["short_circuit_mva"] <= 0:
            raise RuntimeError(f"Non-positive short-circuit capacity for {row['channel']}")
        thevenin = analysis.get("thevenin")
        if not thevenin:
            raise RuntimeError(f"Missing Thevenin/SCR result for {row['channel']}")
        if thevenin["z_th_pu"]["magnitude"] <= 0 or thevenin["z_th_ohm"]["magnitude"] <= 0:
            raise RuntimeError(f"Invalid Thevenin impedance for {row['channel']}: {thevenin}")
        if thevenin.get("scr") is None or thevenin["scr"] <= 0:
            raise RuntimeError(f"Invalid SCR for {row['channel']}: {thevenin}")
        if thevenin.get("grid_strength") not in {"weak", "medium", "strong"}:
            raise RuntimeError(f"Unexpected grid strength for {row['channel']}: {thevenin}")
    if not result.get("thevenin", {}).get("summary", {}).get("enabled"):
        raise RuntimeError("Missing Thevenin summary")
    if result["summary"].get("min_scr") is None or result["summary"]["min_scr"] <= 0:
        raise RuntimeError(f"Missing min SCR summary: {result['summary']}")
    print(json.dumps({"ok": True, "source": source, **result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
