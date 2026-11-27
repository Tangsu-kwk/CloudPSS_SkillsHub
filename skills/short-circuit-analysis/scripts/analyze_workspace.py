"""Compatibility entrypoint for auxiliary-modeling instructions already in use.

With --check-only, an explicit --options file is validated as JSON but is not
used to verify the workspace handoff.
"""

import argparse
import json
from pathlib import Path
import sys

from analyze import main


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("handoff")
    parser.add_argument("--output-dir")
    parser.add_argument("--options", help="Analysis JSON file; with --check-only it is validated but not used")
    parser.add_argument("--timeout", default="300")
    parser.add_argument("--check-only", action="store_true", help="Verify handoff without using analysis options")
    args = parser.parse_args()
    command = ["verify" if args.check_only else "run", "--handoff", args.handoff]
    if args.check_only:
        if args.options is not None:
            json.loads(Path(args.options).read_bytes())
            print("--options validated as JSON but not used for handoff verification.", file=sys.stderr)
    else:
        if args.output_dir is not None:
            command.extend(["--output-dir", args.output_dir])
        if args.options is not None:
            command.extend(["--options", args.options])
        command.extend(["--timeout", args.timeout])
    raise SystemExit(main(command))
