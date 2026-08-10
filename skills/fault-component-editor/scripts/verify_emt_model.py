"""Command-line wrapper for verify_emt_from_context."""
from __future__ import annotations

import json
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from mylib import verify_emt_from_context  # noqa: E402


def main() -> None:
    rid = sys.argv[1] if len(sys.argv) > 1 else ""
    result = verify_emt_from_context({"original_rid": rid})
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
