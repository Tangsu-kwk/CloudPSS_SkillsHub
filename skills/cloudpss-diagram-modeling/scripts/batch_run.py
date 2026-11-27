"""Submit one or several independent parameter scenarios, with a crash-safe manifest.

Each scenario is built from the same frozen baseline copy, so a patch never
leaks into another scenario. Every scenario's state is persisted before the
next one starts, and a resubmission is never attempted for a scenario that may
already own a remote task. Failures are isolated per scenario.
"""
import argparse
import hashlib
import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys

from sdk_bootstrap import activate
activate()

from auto_modeling.configs import list_configs
from auto_modeling.job_results import fetch_job_info
from auto_modeling.job_runner import prepare_run_job
from official_model_check import OfficialCheckError, check_official, require_official_check
from preflight_checks import check as check_preflight
from layout_audit import audit as audit_layout
from auto_modeling.job_submission import submit_job_plan, JobSubmissionError
from auto_modeling.project_reads import list_jobs
from auto_modeling.project_session import open_project
from auto_modeling.scenarios import ScenarioSet
from scenario_select import resolve

TERMINAL = {'COMPLETED', 'FAILED', 'TIMED_OUT', 'CANCELED', 'ABORTED', 'KILLED'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def write(path, value):
    candidate = path.with_suffix('.tmp')
    with candidate.open('w', encoding='utf-8') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    candidate.replace(path)


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rid', required=True)
    parser.add_argument('--config', required=True)
    parser.add_argument('--job', required=True)
    parser.add_argument('--spec', type=Path, required=True,
                        help='JSON: {"scenarios":[{"name","patches":{"<cell>":{"<param>":value}}}]}')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--coverage-review', metavar='TEXT',
                        help='Review conclusion for uncovered official model checks')
    args = parser.parse_args(argv)

    spec = load(args.spec)
    scenarios = spec.get('scenarios')
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError('spec must contain a non-empty "scenarios" list')

    args.out.mkdir(parents=True, exist_ok=True)
    manifest_path = args.out / 'batch_manifest.json'
    if manifest_path.exists() and not args.resume:
        raise ValueError('Manifest exists; use --resume to continue or a new output path')
    if manifest_path.exists():
        manifest = load(manifest_path)
    else:
        manifest = {'rid': args.rid, 'created_at': now(), 'scenarios': []}

    names = [item.get('name') for item in scenarios]
    if any(not isinstance(name, str) or not name.strip() for name in names) or len(set(names)) != len(names):
        raise ValueError('Each scenario requires a unique non-empty name')
    requested = {item['name']: item.get('patches') or {} for item in scenarios}
    if manifest['rid'] != args.rid or any(
        entry['name'] not in requested or entry['patches'] != requested[entry['name']]
        for entry in manifest['scenarios']
    ):
        raise ValueError('Resume requires the original model and scenario definitions')

    # Resolve both selections before any remote mutation.
    baseline = open_project(args.rid)
    baseline_digest = digest(baseline.toJSON())
    if manifest.get('baseline_digest', baseline_digest) != baseline_digest:
        raise ValueError('The baseline model changed; restore the original baseline to resume')
    manifest['baseline_digest'] = baseline_digest
    config_item, config_refusal = resolve(list_configs(baseline), args.config, '参数方案')
    job_item, job_refusal = resolve(list_jobs(baseline), args.job, '计算方案')
    if config_refusal or job_refusal:
        manifest['selection_refusals'] = [item for item in (config_refusal, job_refusal) if item]
        manifest['selection_resolved'] = False
        write(manifest_path, manifest)
        print(json.dumps({'status': 'refused_before_submit',
                          'refusals': manifest['selection_refusals']}, ensure_ascii=False))
        return 2
    selection = {'config': config_item, 'job': job_item}
    if manifest.get('selection', selection) != selection:
        raise ValueError('Resume requires the original calculation and parameter schemes')
    manifest['selection'] = selection
    manifest['selection_resolved'] = True
    write(manifest_path, manifest)

    factory = ScenarioSet(baseline)
    existing = {entry['name']: entry for entry in manifest['scenarios']}

    for scenario in scenarios:
        name = scenario['name']
        patches = scenario.get('patches') or {}
        entry = existing.get(name) or {'name': name, 'patches': patches,
                                       'params_digest': digest(patches),
                                       'status': 'pending', 'attempts': 0}
        if name not in existing:
            manifest['scenarios'].append(entry)
            existing[name] = entry

        # Never resubmit something that may already own a task.
        if entry.get('job_id'):
            entry['status'] = 'submitted'
            write(manifest_path, manifest)
            try:
                info = fetch_job_info(entry['job_id']) or {}
                entry['terminal_status'] = info.get('status')
                entry['revision_hash'] = (info.get('args') or {}).get('_ModelRevision') or entry.get('revision_hash')
                entry.pop('lookup_error', None)
            except Exception as exc:
                entry['lookup_error'] = type(exc).__name__
            entry['checked_at'] = now()
            write(manifest_path, manifest)
            continue
        if entry.get('status') in {'submitting', 'submitted'}:
            entry['status'] = 'unknown'
            entry['note'] = '进程在提交回执落盘前中断；按提交意图待核对，不自动重提'
            write(manifest_path, manifest)
            continue
        if entry.get('status') == 'unknown':
            entry['note'] = '提交结果不明，保留已知身份，停止自动重提'
            write(manifest_path, manifest)
            continue

        entry['attempts'] = entry.get('attempts', 0) + 1
        entry['started_at'] = now()
        try:
            model = factory.build(patches)
        except Exception as exc:
            entry['status'] = 'failed'
            entry['stage'] = 'build'
            entry['error'] = {'type': type(exc).__name__, 'message': str(exc)[:400],
                              'field': ', '.join(f'{cell}.{param}' for cell in patches
                                                 for param in patches[cell])}
            entry['finished_at'] = now()
            write(manifest_path, manifest)
            continue

        plan = None
        try:
            plan = prepare_run_job(model, config_item['index'], job_item['index'])
            document = model.toJSON()
            entry['preflight'] = check_preflight(document)
            entry['layout'] = audit_layout(document)
            entry['official_check'] = check_official(
                model, config_index=config_item['index'], job_index=job_item['index'])
            require_official_check(entry['official_check'], coverage_review=args.coverage_review)
            if entry['preflight']['status'] != 'clean':
                raise ValueError('Preflight checks found errors; inspect batch manifest')
            if entry['layout']['missing_positions']:
                raise ValueError('Layout audit found components without a position; inspect batch manifest')
        except Exception as exc:
            problems = getattr(exc, 'problems', None)
            entry['status'] = 'failed'
            entry['stage'] = 'preflight'
            message = str(exc)
            if (isinstance(exc, OfficialCheckError) and exc.report.get('status') in ('partial', 'not_applicable')
                    and not (args.coverage_review or '').strip()):
                message = '请复核未覆盖项后以 --coverage-review "<结论>" 重新执行；' + message
            entry['error'] = {'type': type(exc).__name__, 'message': message[:400],
                              'problems': problems}
            entry['finished_at'] = now()
            write(manifest_path, manifest)
            continue

        entry['submitted_params_digest'] = digest(plan['job_input_without_revision']['args'])
        entry['local_display'] = plan.get('local_display')
        entry['status'] = 'submitting'
        entry['intent_at'] = now()
        write(manifest_path, manifest)

        try:
            job_id = submit_job_plan(plan, start_receiver=False)
            entry['status'] = 'submitted'
            entry['job_id'] = job_id
            entry['submitted_at'] = now()
            write(manifest_path, manifest)
        except JobSubmissionError as exc:
            entry['stage'] = exc.stage
            entry['outcome'] = exc.outcome
            entry['revision_hash'] = exc.revision_hash
            entry['job_id'] = exc.job_id
            if exc.job_id:
                entry['status'] = 'submitted'
            else:
                entry['status'] = 'unknown'
                entry['note'] = ('提交阶段异常且未取得任务 ID；保留阶段与参数摘要，'
                                 '标记待核对，不自动重提')
            entry['error'] = {'type': 'JobSubmissionError', 'message': str(exc)[:400]}
        except Exception as exc:
            entry['status'] = 'unknown'
            entry['stage'] = getattr(exc, 'stage', 'submit')
            entry['error'] = {'type': type(exc).__name__, 'message': str(exc)[:400]}
            entry['note'] = '提交异常类型未知；保留参数摘要，标记待核对'
        entry['finished_at'] = now()
        write(manifest_path, manifest)
        if entry.get('job_id'):
            try:
                info = fetch_job_info(entry['job_id']) or {}
                entry['revision_hash'] = (info.get('args') or {}).get('_ModelRevision') or entry.get('revision_hash')
                entry['terminal_status'] = info.get('status')
                entry['checked_at'] = now()
            except Exception as exc:
                entry['lookup_error'] = type(exc).__name__
            write(manifest_path, manifest)

    selection = manifest['selection']
    summary = [{'name': e['name'], 'status': e['status'], 'job_id': e.get('job_id'),
                'terminal_status': e.get('terminal_status'),
                'config': (e.get('local_display') or {}).get('configArgName')
                          or selection.get('config', {}).get('name'),
                'job': (e.get('local_display') or {}).get('jobArgName')
                       or selection.get('job', {}).get('name'),
                'revision_hash': e.get('revision_hash'),
                'params_digest': e.get('params_digest'),
                'stage': e.get('stage'),
                'field': (e.get('error') or {}).get('field'),
                'note': e.get('note') or (e.get('error') or {}).get('message')}
               for e in manifest['scenarios']]
    write(args.out / 'batch_summary.json', {'selection': manifest['selection'],
                                           'scenarios': summary})
    print(json.dumps({'selection': manifest['selection'], 'scenarios': summary},
                     ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
