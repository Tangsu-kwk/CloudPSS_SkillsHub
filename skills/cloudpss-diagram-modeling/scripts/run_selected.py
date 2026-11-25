"""Run exactly one task from a requested scheme pair, with a verifiable receipt.

Scheme names are resolved to indices before any mutation; an unknown or
ambiguous name is refused with candidates and zero mutations. The receipt keeps
both the user's wording and the resolved index/name, the server-returned
revision hash, a digest of the submitted arguments and the job ID, so the three
records (selection, interface arguments, run record) can be compared directly.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

from sdk_bootstrap import activate
activate()

import cloudpss.utils as cloud_utils
from auto_modeling.configs import add_config, list_configs
from auto_modeling.diagram_aux import model_from_document
from auto_modeling.job_results import fetch_job_info
from auto_modeling.job_runner import prepare_run_job
from auto_modeling.job_submission import JobSubmissionError, submit_job_plan
from auto_modeling.project_reads import list_jobs
from auto_modeling.project_session import open_project
from scenario_select import resolve
from official_model_check import check_official, require_official_check
from preflight_checks import check as check_preflight
from layout_audit import audit as audit_layout

MUTATIONS = []
_original = cloud_utils.graphql_request


def counting_request(query, variables=None, **kwargs):
    if isinstance(query, str) and 'mutation' in query:
        if 'createModelRevision' in query:
            MUTATIONS.append('revision')
        elif 'createJob' in query:
            MUTATIONS.append('job')
        else:
            MUTATIONS.append('other')
    return _original(query, variables, **kwargs)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--rid')
    source.add_argument('--document', type=Path, help='Local working model JSON')
    parser.add_argument('--config', required=True, help='User wording for the parameter scheme')
    parser.add_argument('--job', required=True, help='User wording for the calculation scheme')
    parser.add_argument('--add-config', help='Append this extra in-memory parameter scheme first')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    cloud_utils.graphql_request = counting_request

    model = open_project(args.rid) if args.rid else model_from_document(json.loads(args.document.read_bytes()))
    if args.add_config:
        add_config(model, args.add_config, {})

    configs, jobs = list_configs(model), list_jobs(model)
    config_item, config_refusal = resolve(configs, args.config, '参数方案')
    job_item, job_refusal = resolve(jobs, args.job, '计算方案')
    receipt = {
        'user_selection': {'config': args.config, 'job': args.job},
        'available': {'configs': configs, 'jobs': jobs},
    }
    if config_refusal or job_refusal:
        receipt.update({
            'status': 'refused_before_submit',
            'refusals': [item for item in (config_refusal, job_refusal) if item],
            'mutations_sent': list(MUTATIONS),
        })
        (args.out / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False,
                                                          indent=2) + '\n', encoding='utf-8')
        print(json.dumps(receipt, ensure_ascii=False))
        return 2

    receipt['resolved'] = {'config': config_item, 'job': job_item}
    try:
        plan = prepare_run_job(model, config_item['index'], job_item['index'])
        document = model.toJSON()
        receipt['preflight'] = check_preflight(document)
        receipt['layout'] = audit_layout(document)
        receipt['official_check'] = check_official(
            model, config_index=config_item['index'], job_index=job_item['index'])
        require_official_check(receipt['official_check'])
        if receipt['preflight']['status'] != 'clean':
            raise ValueError('Preflight checks found errors; inspect receipt')
        if receipt['layout']['missing_positions']:
            raise ValueError('Layout audit found components without a position; inspect receipt')
    except Exception as exc:
        receipt.update({'status': 'preflight_failed', 'stage': 'preflight',
                        'error': {'type': type(exc).__name__, 'message': str(exc)[:400],
                                  'problems': getattr(exc, 'problems', None)},
                        'mutations_sent': list(MUTATIONS)})
        (args.out / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False,
                                                          indent=2) + '\n', encoding='utf-8')
        print(json.dumps(receipt, ensure_ascii=False))
        return 2

    submitted_args = plan['job_input_without_revision']['args']
    receipt['submitted_params_digest'] = digest(submitted_args)
    receipt['submitted_params'] = {k: submitted_args[k] for k in
                                  ('Method', 'ShowRunLog', 'MaxIteration') if k in submitted_args}
    receipt['local_display'] = plan.get('local_display')
    try:
        job_id = submit_job_plan(plan, start_receiver=False)
        info = fetch_job_info(job_id) or {}
        receipt.update({
            'status': 'submitted',
            'job_id': job_id,
            'revision_hash': (info.get('args') or {}).get('_ModelRevision'),
            'terminal_status': info.get('status'),
            'server_context': info.get('context'),
        })
    except JobSubmissionError as exc:
        receipt.update({'status': 'unknown', 'stage': exc.stage, 'outcome': exc.outcome,
                        'revision_hash': exc.revision_hash, 'job_id': exc.job_id,
                        'error': {'type': 'JobSubmissionError', 'message': str(exc)[:400]}})
    receipt['mutations_sent'] = list(MUTATIONS)
    (args.out / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False,
                                                      indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False))
    return 0 if receipt.get('status') == 'submitted' else 2


if __name__ == '__main__':
    sys.exit(main())
