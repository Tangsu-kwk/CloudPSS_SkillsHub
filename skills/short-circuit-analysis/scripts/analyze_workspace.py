"""Compatibility entrypoint for auxiliary-modeling instructions already in use."""

import argparse
import sys

from analyze import main


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("handoff")
    parser.add_argument("--output-dir")
    parser.add_argument("--options")
    parser.add_argument("--timeout", default="300")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    command = ["verify" if args.check_only else "run", "--handoff", args.handoff]
    if not args.check_only:
        if args.output_dir is not None:
            command.extend(["--output-dir", args.output_dir])
        if args.options is not None:
            command.extend(["--options", args.options])
        command.extend(["--timeout", args.timeout])
    raise SystemExit(main(command))
