from __future__ import annotations

import json
from pathlib import Path
import sys


SKILL_DIR = Path(__file__).resolve().parents[1]
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from mylib.runtime import analyze_model_from_source  # noqa: E402


DEFAULT_DIRECT_CURRENT_MODEL_RID = "model/CloudPSS/SubstationCase"


def main() -> None:
    source = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DIRECT_CURRENT_MODEL_RID
    config = {
        "analysis": {
            "base_voltage_kv": 110.0,
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
        "channels": {"auto_max_channels": 3},
    }
    result = analyze_model_from_source(source, config=config)
    if not result.get("task_id"):
        raise RuntimeError("Expected a real CloudPSS EMT task_id")

    print(json.dumps({"ok": True, "source": source, **result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
