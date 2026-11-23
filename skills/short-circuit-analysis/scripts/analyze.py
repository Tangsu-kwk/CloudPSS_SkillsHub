"""Inspect a saved CloudPSS model, verify a workspace handoff, or run EMT."""

import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import re
import sys


def model_rid(value):
    if not re.fullmatch(r"model/[^/\s]+/[^/\s]+", value):
        raise argparse.ArgumentTypeError("Expected a model/<owner>/<key> RID")
    return value


def analyze(args):
    from short_circuit.runtime import analyze_model_from_source, load_prepared_workspace

    if args.timeout <= 0:
        raise ValueError("Timeout must be positive")
    if (args.output_dir / "submission.json").exists():
        raise ValueError("This output directory already has a submission receipt; inspect it before another run")

    config = json.loads(args.options.read_bytes()) if args.options else None
    if args.options and not isinstance(config, dict):
        raise ValueError("Analysis options must be a JSON object")
    if args.fault is not None:
        config = {} if config is None else config
        analysis = config.setdefault("analysis", {})
        if not isinstance(analysis, dict):
            raise ValueError("analysis options must be a JSON object")
        if analysis.get("target_fault_id", args.fault) != args.fault:
            raise ValueError("--fault conflicts with the target_fault_id in the options")
        analysis["target_fault_id"] = args.fault

    source = args.rid
    if args.handoff is not None:
        _, record = load_prepared_workspace(args.handoff)
        source = record["model_document"]
    selection = {name: getattr(args, name) for name in ("job_index", "config_index")
                 if getattr(args, name) is not None}
    return analyze_model_from_source(
        source, config=config, output_dir=args.output_dir,
        timeout=args.timeout, workspace_handoff=args.handoff, **selection,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="List active faults on a saved model without submitting EMT")
    inspect.add_argument("--rid", required=True, type=model_rid)
    verify = commands.add_parser("verify", help="Verify a local auxiliary-modeling handoff")
    verify.add_argument("--handoff", required=True, type=Path)
    run = commands.add_parser("run", help="Submit and analyze one EMT calculation")
    source = run.add_mutually_exclusive_group(required=True)
    source.add_argument("--rid", type=model_rid)
    source.add_argument("--handoff", type=Path)
    run.add_argument("--fault", help="Target fault ID for a saved model")
    run.add_argument("--job-index", type=int, help="EMT calculation scheme index for a saved model")
    run.add_argument("--config-index", type=int, help="Parameter scheme index for a saved model")
    run.add_argument("--output-dir", required=True, type=Path)
    run.add_argument("--options", type=Path, help="Optional analysis configuration JSON")
    run.add_argument("--timeout", type=int, default=300)
    for action, help_text in (
        ("status", "Read an existing task status"),
        ("fetch", "Export original waveforms from an existing EMT task"),
        ("resume", "Complete the saved short-circuit analysis from the original task"),
    ):
        command = commands.add_parser(action, help=help_text)
        command.add_argument("--task-id", required=True)
        command.add_argument("--timeout", type=int, default=30)
        if action != "status":
            command.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == "run" and args.handoff is not None and any(
        value is not None for value in (args.fault, args.job_index, args.config_index)
    ):
        parser.error("A handoff already specifies the target fault and both schemes")

    try:
        if args.command == "inspect":
            from short_circuit.runtime import inspect_fault_candidates_from_source

            result = inspect_fault_candidates_from_source(args.rid)
        elif args.command == "verify":
            from short_circuit.runtime import load_prepared_workspace

            _, record = load_prepared_workspace(args.handoff)
            result = {"status": "binding_verified", **record}
        elif args.command == "run":
            with redirect_stdout(sys.stderr):
                result = analyze(args)
        else:
            from short_circuit.task_recovery import read_task

            result = read_task(args.task_id, action=args.command,
                               output_dir=getattr(args, "output_dir", None), timeout=args.timeout)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        info = getattr(exc, "public_error", {"message": str(exc)})
        print(json.dumps({"status": "failed", **info}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
