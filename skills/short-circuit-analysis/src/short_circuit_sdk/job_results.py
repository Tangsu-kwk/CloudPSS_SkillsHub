"""Read-only functions from the bundled automodeling 0.1.0 SDK."""
from copy import deepcopy
import re

from .remote_reads import _request, RemoteReadError


JOB_RECORD_QUERY = '''query JobRecordMetadata($input:JobInput!){job(input:$input){
 id args createTime startTime endTime status context user priority input output position
}}'''


def _job_id(value):
    if not isinstance(value,str) or not re.fullmatch(
        r'(?:[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}|00000000-0000-0000-0000-000000000000)',value):
        raise TypeError('任务 ID 格式不正确')
    return value


def fetch_job_record_info(jobId, *, requester=None):
    """Read the standard browser-record metadata projection from the service.

    This imports current server state, not a past browser snapshot. Existing
    session records remain authoritative until explicitly refreshed.
    """
    _job_id(jobId)
    try:
        job=_request(JOB_RECORD_QUERY,{'input':{'id':jobId}},requester).get('job')
    except RemoteReadError as exc:
        # Observed NIL/unknown-ID query returns this exact job-level 404.
        # Authentication/other paths/statuses retain their original failure.
        errors=exc.graphql_errors
        if errors and all(e.get('path')==['job'] and e.get('message')=='Not Found'
                          and e.get('status')=='404' for e in errors):
            raise LookupError(f'任务 {jobId} 不存在') from None
        raise
    if job is None:raise LookupError(f'任务 {jobId} 不存在')
    if not isinstance(job,dict) or job.get('id')!=jobId:
        raise ValueError(f'任务 {jobId} 信息不一致')
    return deepcopy(job)
