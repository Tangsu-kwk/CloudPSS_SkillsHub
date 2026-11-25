"""Explicit checked save/submit/collect helpers; never retry cloud mutations."""
import argparse
from collections import defaultdict
from pathlib import Path
import json
import math

from sdk_bootstrap import activate
activate()
from configure_cloudpss import configure_cloudpss
from image_model_pipeline import read_json, write_json
from auto_modeling.diagram_aux import model_from_document
from auto_modeling.check_environment import load_check_environment
from auto_modeling.project_check import run_check
from auto_modeling.project_session import ProjectSession, open_project
from auto_modeling.project_persistence import project_exists
from auto_modeling.job_results import JobResults
from auto_modeling.job_runner import prepare_run_job
from auto_modeling.job_submission import submit_job_plan
from auto_modeling.plot_results import plot_figure
from official_model_check import check_official, require_official_check
from preflight_checks import check as check_preflight
from layout_audit import audit as audit_layout


def check(model, *, config_index=None, job_index=None):
    environment = load_check_environment(model)
    document = model.toJSON()
    report = run_check(model, **environment)
    report['official_check'] = check_official(model, config_index=config_index,
                                              job_index=job_index,
                                              definitions=environment['definitions'])
    report['preflight'] = check_preflight(document)
    report['layout'] = audit_layout(document, environment['definitions'])
    return report


def summarize(report):
    return {'complete': report['complete'], 'checked_groups': report['checked_groups'],
            'pending_groups': report['pending_groups'], 'limitations': report['limitations'],
            'official_check_status': report.get('official_check', {}).get('status'),
            'preflight_status': report.get('preflight', {}).get('status'),
            'layout_status': report.get('layout', {}).get('status'),
            'layout_overlaps': report.get('layout', {}).get('overlap_count'),
            'counts': {level: sum(p['level'] == level for p in report['problems'])
                       for level in ('error', 'warning', 'info')}}


def require_calculable(report, *, strict_layout=False):
    if report['pending_groups'] or any(p['level'] == 'error' for p in report['problems']):
        raise ValueError('Project check has errors or pending inputs; inspect check.json before proceeding')
    require_official_check(report['official_check'])
    if report['preflight']['status'] != 'clean':
        raise ValueError('Preflight checks found errors; inspect preflight.json before proceeding')
    if report['layout']['missing_positions']:
        raise ValueError('Layout audit found components without a position; inspect layout.json')
    if strict_layout and report['layout']['overlap_count']:
        raise ValueError('Layout audit found overlapping symbol boxes; inspect layout.json')


def collect(results, job_id, out, timeout):
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('timeout must be positive and finite')
    if job_id not in results.records:
        results.import_job_info(job_id)
    status = 'snapshot'
    try:
        results.listen(job_id, timeout=timeout + 5, startup_timeout=min(timeout, 30))
        results.get_job_logs(job_id, True, timeout=timeout)
    except TimeoutError:
        status = 'snapshot_timeout'  # Preserve partial messages and the same remote task.
    finally:
        results.close()
        records = results.export_records()
        write_json(out / 'records.json', records)
    record = results.records[job_id]
    raw = record.get('messages', [])
    write_json(out / 'logs.json', [m for m in raw if m.get('type') == 'log'])
    grouped = defaultdict(list)
    for message in raw:
        if message.get('type') == 'plot' and message.get('sender') != 'local':
            grouped[message['key']].append(message)
    figures = [{'key': key, 'figure': plot_figure(messages)} for key, messages in grouped.items()]
    write_json(out / 'figures.json', figures)
    complete = record.get('stream_completeness') == 'normal_close' and bool(record.get('status'))
    if complete:
        status = 'collected'
    receipt = {'job_id': job_id, 'status': status, 'task_status': record.get('status'),
               'server_status': record.get('job', {}).get('status'), 'stream_complete': complete,
               'plot_count': len(figures), 'business_acceptance': 'not_performed_by_collector'}
    write_json(out / 'receipt.json', receipt)
    return receipt, 0 if complete else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('check', 'save', 'run', 'collect'):
        item = sub.add_parser(name)
        item.add_argument('--out', type=Path, required=True)
        item.add_argument('--config', type=Path)
        if name != 'collect':
            item.add_argument('--model', type=Path, required=True)
        if name in ('check', 'save', 'run'):
            item.add_argument('--strict-layout', action='store_true',
                              help='Treat overlapping symbol boxes as a failure')
        if name == 'save':
            item.add_argument('--rid', required=True)
            item.add_argument('--overwrite', action='store_true', help='Only for an already authorized overwrite')
        if name == 'run':
            item.add_argument('--config-index', type=int, required=True)
            item.add_argument('--job-index', type=int, required=True)
        if name == 'collect':
            item.add_argument('--job-id', required=True)
            item.add_argument('--records', type=Path)
            item.add_argument('--timeout', type=float, default=30)
    args = parser.parse_args(argv)
    # Reserve artifact paths before contacting any mutation endpoint.
    if args.out.exists():
        raise ValueError('Use a new output path; preserve previous evidence')
    if args.command == 'check':
        args.out.parent.mkdir(parents=True, exist_ok=True)
    else:
        args.out.mkdir(parents=True)
    results = None
    try:
        configure_cloudpss(args.config)
        if args.command == 'collect':
            results = JobResults()
            if args.records:
                results.import_records(read_json(args.records))
            receipt, code = collect(results, args.job_id, args.out, args.timeout)
            print(json.dumps(receipt))
            return code
        model = model_from_document(read_json(args.model))
        if args.command == 'check':
            report = check(model)
            write_json(args.out, report)
            print(json.dumps(summarize(report)))
            if (report['pending_groups'] or any(p['level'] == 'error' for p in report['problems'])
                    or report['official_check']['status'] in {'failed', 'issues'}
                    or report['preflight']['status'] != 'clean'
                    or report['layout']['missing_positions']
                    or (args.strict_layout and report['layout']['overlap_count'])):
                return 2
            return 0
        if args.command == 'save':
            report = check(model)
            write_json(args.out / 'check.json', report)
            write_json(args.out / 'preflight.json', report['preflight'])
            write_json(args.out / 'layout.json', report['layout'])
            require_calculable(report, strict_layout=args.strict_layout)
            exists = project_exists(args.rid)
            if exists and not args.overwrite:
                raise ValueError('Target RID exists; choose a new RID or use --overwrite for an authorized replacement')
            session = ProjectSession(model)
            saved = session.save_project(args.rid)
            # Persist known identity before subsequent read-only verification.
            write_json(args.out / 'receipt.json', {'status': 'saved', 'rid': saved, 'readback_verified': False})
            write_json(args.out / 'submitted_model.json', model.toJSON())
            readback = open_project(saved)
            write_json(args.out / 'model.json', readback.toJSON())
            readback_check = check(readback)
            write_json(args.out / 'readback_check.json', readback_check)
            receipt = {'status': 'saved_and_read_back', 'rid': saved, 'readback_loaded': True,
                       'structural_diff': 'caller_must_review_submitted_model_vs_model',
                       'readback_check': summarize(readback_check)}
            write_json(args.out / 'receipt.json', receipt)
            print(json.dumps(receipt))
            if (readback_check['pending_groups'] or any(p['level'] == 'error' for p in readback_check['problems'])
                    or readback_check['official_check']['status'] in {'failed', 'issues'}
                    or readback_check['preflight']['status'] != 'clean'
                    or readback_check['layout']['missing_positions']
                    or (args.strict_layout and readback_check['layout']['overlap_count'])):
                return 2
            return 0
        # Preparing uses the same checked SDK path as ProjectSession.run_job.
        plan = prepare_run_job(model, args.config_index, args.job_index)
        report = check(model, config_index=args.config_index, job_index=args.job_index)
        write_json(args.out / 'check.json', report)
        write_json(args.out / 'official_check.json', report['official_check'])
        write_json(args.out / 'preflight.json', report['preflight'])
        write_json(args.out / 'layout.json', report['layout'])
        require_calculable(report, strict_layout=args.strict_layout)
        write_json(args.out / 'submission_plan.json', plan)
        results = JobResults()
        job_id = submit_job_plan(plan, session=results, start_receiver=False)
        write_json(args.out / 'receipt.json', {'status': 'submitted', 'job_id': job_id,
                   'config_index': args.config_index, 'job_index': args.job_index,
                   'full_mcp_checker_parity': False, 'project_saved': False})
        write_json(args.out / 'records.json', results.export_records())
        print(json.dumps({'status': 'submitted', 'job_id': job_id, 'next': 'collect the same task; do not resubmit'}))
        return 0
    except Exception as exc:
        # Raw transport exception strings may include headers; keep stable types/identities.
        failure = {'status': 'error', 'error_type': type(exc).__name__,
                   'stage': getattr(exc, 'stage', args.command),
                   'outcome': getattr(exc, 'outcome', None),
                   'revision_hash': getattr(exc, 'revision_hash', None),
                   'job_id': getattr(exc, 'job_id', getattr(args, 'job_id', None)),
                   'instruction': 'Inspect saved evidence and known identities before retrying any mutation'}
        # Local validation errors are useful and contain no transport internals.
        if isinstance(exc, (ValueError, FileNotFoundError, ImportError)):
            import os
            message = str(exc)
            token = os.environ.get('CLOUDPSS_TOKEN')
            failure['message'] = message.replace(token, '[REDACTED]') if token else message
        if results is not None and args.command != 'check':
            results.close()
            write_json(args.out / 'records.json', results.export_records())
        if args.command == 'check':
            write_json(args.out, failure)
        else:
            write_json(args.out / 'failure.json', failure)
        print(json.dumps(failure))
        return 1
    finally:
        if results is not None:
            results.close()


if __name__ == '__main__':
    raise SystemExit(main())
