"""JSON CLI for persistent fault edit plans."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from mylib import execute_edit_plan_from_source, preview_edit_plan_from_source  # noqa: E402


def _json_argument(value: str) -> object:
    path = Path(value)
    try:
        is_file = path.is_file()
    except OSError:
        is_file = False
    text = path.read_text(encoding="utf-8") if is_file else value
    return json.loads(text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview or execute one CloudPSS fault edit plan")
    subparsers = parser.add_subparsers(dest="command", required=True)

    preview = subparsers.add_parser("preview")
    preview.add_argument("source")
    preview.add_argument("operations_json", help="JSON array or path to a JSON file")

    execute = subparsers.add_parser("execute")
    execute.add_argument("plan_json", help="plan JSON object or path to a JSON file")
    execute.add_argument("target_rid")

    args = parser.parse_args()
    if args.command == "preview":
        operations = _json_argument(args.operations_json)
        if not isinstance(operations, list):
            raise SystemExit("operations_json must contain a JSON array")
        result = preview_edit_plan_from_source(args.source, operations)
    else:
        plan = _json_argument(args.plan_json)
        if not isinstance(plan, dict):
            raise SystemExit("plan_json must contain a JSON object")
        result = execute_edit_plan_from_source(plan, args.target_rid)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str))


if __name__ == "__main__":
    main()
