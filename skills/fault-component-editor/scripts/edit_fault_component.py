"""Command-line wrapper for edit_model_from_context."""
from __future__ import annotations

import json
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from mylib import EditRequest, edit_model_from_context  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: edit_fault_component.py '<request-json>'")
    request = EditRequest(**json.loads(sys.argv[1]))
    result = edit_model_from_context(request, {"original_rid": ""})
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
