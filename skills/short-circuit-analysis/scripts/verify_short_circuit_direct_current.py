from __future__ import annotations

import json
from pathlib import Path
import sys


SKILL_DIR = Path(__file__).resolve().parents[1]
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from mylib.runtime import load_model_from_source, run_short_circuit_analysis  # noqa: E402


DEFAULT_DIRECT_CURRENT_MODEL_RID = "model/CloudPSS/SubstationCase"


def main() -> None:
    source = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DIRECT_CURRENT_MODEL_RID
    model = load_model_from_source(source)
    config = {
        "analysis": {
            "base_voltage_kv": 110.0,
            "current_scale": 1.0,
            "analysis_window": [0.0, 0.55],
            "prefault_window": [0.0, 0.05],
            "fault_window": [0.08, 0.18],
            "postfault_window": [0.45, 0.55],
            "min_samples": 32,
        },
        "thevenin": {
            "enabled": True,
            "system_base_mva": 100.0,
            "plant_rating_mva": 100.0,
            "reactive_compensation_mvar": 0.0,
            "xr_ratio": 10.0,
            "weak_scr_threshold": 2.0,
            "strong_scr_threshold": 3.0,
        },
        "channels": {
            "current": [
                "#IabcⅠ线送端2CT二次:0",
                "#IabcⅠ线送端2CT二次:1",
                "#IabcⅠ线送端2CT二次:2",
            ],
            "auto_max_channels": 3,
        },
    }
    result = run_short_circuit_analysis(model, config=config)
    if result["summary"]["channel_count"] != 3:
        raise RuntimeError(f"Expected 3 direct current channels, got {result['summary']['channel_count']}")
    if result["summary"]["methods"] != ["direct_current_channel"]:
        raise RuntimeError(f"Expected direct current method only, got {result['summary']['methods']}")
    if result["summary"]["max_fault_rms_current"] <= 0:
        raise RuntimeError(f"Expected positive fault RMS current, got {result['summary']}")
    if result["summary"]["max_short_circuit_mva"] <= 0:
        raise RuntimeError(f"Expected positive short-circuit capacity, got {result['summary']}")
    if result["summary"].get("min_scr") is None or result["summary"]["min_scr"] <= 0:
        raise RuntimeError(f"Expected positive SCR, got {result['summary']}")

    for row in result["channels"]:
        analysis = row["analysis"]
        if analysis["method"] != "direct_current_channel":
            raise RuntimeError(f"Unexpected method for {row['channel']}: {analysis['method']}")
        if analysis["sample_count"] < config["analysis"]["min_samples"]:
            raise RuntimeError(f"Insufficient samples for {row['channel']}: {analysis['sample_count']}")
        if analysis["fault_rms_current"] <= 0:
            raise RuntimeError(f"Non-positive direct current RMS for {row['channel']}")
        if not analysis.get("thevenin"):
            raise RuntimeError(f"Missing Thevenin/SCR result for {row['channel']}")

    print(json.dumps({"ok": True, "source": source, **result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
