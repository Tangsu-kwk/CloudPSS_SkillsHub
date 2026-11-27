"""Read an existing CloudPSS task and, when context exists, finish its analysis."""

import hashlib
import json
import math
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from uuid import UUID

from cloudpss.job.result.EMTResult import EMTResult
from cloudpss.utils import graphql_request

from . import runtime

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from short_circuit_sdk.job_results import fetch_job_record_info
from short_circuit_sdk.result_stream import read_job_results, remaining


PENDING = {"WAITING", "RUNNING", "QUEUED", "PENDING", "CREATED"}


def _read_context(directory, task_id):
    receipt = json.loads((directory / "submission.json").read_bytes())
    if receipt.get("task_id") != task_id:
        raise ValueError("Task ID differs from the local submission receipt")
    if not receipt.get("analysis_context_sha256"):
        raise ValueError("This receipt has no saved analysis context; use fetch to export the original waveforms")
    path = directory / "analysis-context.json"
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != receipt["analysis_context_sha256"]:
        raise ValueError("Saved analysis context differs from the submission receipt")
    context = json.loads(payload)
    if context.get("schema") != 1:
        raise ValueError("Unsupported saved analysis context")
    return receipt, context


def read_task(task_id, *, action, output_dir=None, timeout=30):
    if (not isinstance(timeout, (int, float)) or isinstance(timeout, bool)
            or not math.isfinite(timeout) or timeout <= 0):
        raise ValueError(f"Timeout must be a finite positive number, got {timeout!r}")
    if str(UUID(task_id)) != task_id:
        raise ValueError("Provide the CloudPSS task UUID")
    if action == "resume":
        receipt, context = _read_context(output_dir, task_id)
    runtime._configure_cloudpss_auth()
    deadline = time.monotonic() + timeout

    def request(query, variables, **_):
        return graphql_request(query, variables, timeout=remaining(deadline))

    info = fetch_job_record_info(task_id, requester=request)
    status = {"task_id": task_id, "server_status": info.get("status"),
              "context": info.get("context"), "revision_hash": (info.get("args") or {}).get("_ModelRevision")}
    if action == "status":
        return status
    if action == "resume" and receipt.get("revision_hash") and status["revision_hash"] != receipt["revision_hash"]:
        raise ValueError("Remote task revision differs from the submission receipt")
    if status["server_status"] in PENDING:
        return {**status, "status": "pending"}
    if status["server_status"] != "COMPLETED":
        raise ValueError(f"Task {task_id} has status {status['server_status']!r}; completed EMT results are required")
    task_context = info.get("context")
    if not isinstance(task_context, list) or not task_context or task_context[0] not in runtime.EMT_FUNCTIONS:
        raise ValueError(f"Task {task_id} does not identify a supported EMT function")

    _, stream = read_job_results(task_id, block=True, deadline=deadline, kind="plot", info=info)
    if not stream.complete or (stream.termination or {}).get("succeeded") is False:
        raise ValueError(f"Task {task_id} did not return a completed result stream")
    job = SimpleNamespace(id=task_id)
    job.result = EMTResult(job, SimpleNamespace(messages=stream.messages))
    traces = runtime._collect_all_waveform_traces(job.result)
    if not traces:
        raise ValueError(f"Task {task_id} has no readable waveform channels")
    if action == "fetch":
        task_dir = output_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        metadata = runtime._write_raw_channel_csvs(task_dir, "fetched_waveforms", traces)
        return {**status, "status": "waveforms_exported",
                "index": str(task_dir / "fetched_waveforms" / "index.json"),
                "channel_count": metadata["channel_count"]}

    model = SimpleNamespace(rid=context["model_rid"], name=context["model_name"])
    runtime.write_analysis_artifacts(model, job, context["resolved_config"], context["snapshot"],
                                     output_dir, receipt, recovered=True)
    return {**status, "status": "analysis_recovered", "analysis": str(output_dir / task_id / "analysis_result.json")}
