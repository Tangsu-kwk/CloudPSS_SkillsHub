"""Run the CloudPSS 5.0.10 Checker in an isolated process."""

import argparse
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys


class OfficialCheckError(ValueError):
    def __init__(self, report, reason='Official model check found errors or could not complete'):
        self.problems = report.get('problems') or []
        self.report = report
        super().__init__(f"{reason}; status={report.get('status')!r}; coverage={report.get('coverage')!r}; "
                         f"problems ({len(self.problems)})={self.problems[:3]!r}")


def check_official(model, *, config_index=None, job_index=None, definitions=None):
    payload = {'model': model.toJSON(), 'config_index': config_index,
               'job_index': job_index, 'definitions': definitions}
    try:
        result = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(Path(__file__).resolve())],
                                input=json.dumps(payload), encoding='utf8',
                                capture_output=True, timeout=120, check=True)
        return json.loads(result.stdout)
    except (subprocess.SubprocessError, OSError, ValueError) as exc:
        return {'status': 'failed', 'stage': 'worker', 'error_type': type(exc).__name__,
                'problems': []}


def require_official_check(report, *, coverage_review=None):
    """Reject unknown statuses and require an explicit review of uncovered items."""
    status = report.get('status')
    if status == 'checked':
        return
    if status in ('partial', 'not_applicable'):
        if not isinstance(coverage_review, str) or not coverage_review.strip():
            raise OfficialCheckError(report, 'uncovered items were not reviewed')
        report['coverage_review'] = coverage_review
        return
    raise OfficialCheckError(report)


def worker(payload):
    from cloudpss import Model
    from cloudpss.model.check import Checker
    from cloudpss.model.check.environments import env

    normalized = []
    unsupported_connections = []

    class IsolatedChecker(Checker):
        def updateEnvironment(self):
            definitions = payload.get('definitions')
            if definitions is None:
                super().updateEnvironment()
            else:
                for rid, definition in definitions.items():
                    env['models'][rid] = {**definition, 'revision': definition.get('revision', definition)}
            for rid, definition in env['models'].items():
                for pin in definition['revision']['pins']:
                    if 'condition' not in pin:
                        pin['condition'] = True
                        normalized.append({'definition': rid, 'pin': pin['key']})
                    if pin.get('connection') == 'true':
                        unsupported_connections.append({'definition': rid, 'pin': pin['key'],
                                                        'connection': 'true'})

    model = Model(payload['model'])
    config_index = payload['config_index']
    job_index = payload['job_index']
    config = model.configs[config_index] if config_index is not None else None
    if config is None and model.configs:
        config_index = model.context.get('currentConfig', 0)
        config = model.configs[config_index]
    job = model.jobs[job_index] if job_index is not None else None
    checker = IsolatedChecker(model, job, config)
    messages = io.StringIO()
    stage = 'definitions'
    problems = []
    try:
        with redirect_stdout(messages), redirect_stderr(messages):
            if model.revision.getImplements().getDiagram() is None:
                return {'status': 'not_applicable', 'problems': [], 'coverage': []}
            checker.updateEnvironment()
            stage = 'expressions'
            checker.diagramExpressionChecker()
            problems.extend({**p, 'stage': stage} for p in checker.problems)
            stage = 'connectivity'
            n = len(checker.problems)
            checker.diagramChecker()
            problems.extend({**p, 'stage': stage} for p in checker.problems[n:])
    except KeyError as exc:
        if stage == 'connectivity' and exc.args == ('true',) and unsupported_connections:
            incomplete = [{**p, 'stage': stage} for p in checker.problems[n:]]
            # The checker compares the evaluated value with int(value). Its
            # diagnostic can display an integer-form string as a non-integer.
            problems.extend(p for p in incomplete
                            if not re.fullmatch(r'引脚[XY]维度必须为整数: [0-9]+', p['problem']))
            return {'status': 'issues' if any(p['level'] == 'error' for p in problems) else 'partial',
                    'stage': stage, 'coverage': ['expressions'], 'problems': problems,
                    'incomplete_connectivity_diagnostics': incomplete,
                    'limitation': 'CloudPSS 5.0.10 cannot classify connection type true',
                    'unsupported_connections': unsupported_connections,
                    'normalized_pin_conditions': normalized,
                    'config_index': config_index, 'job_index': job_index}
        return {'status': 'failed', 'stage': stage, 'error_type': type(exc).__name__,
                'problems': problems, 'normalized_pin_conditions': normalized}
    except Exception as exc:
        return {'status': 'failed', 'stage': stage, 'error_type': type(exc).__name__,
                'problems': problems, 'normalized_pin_conditions': normalized}
    output = messages.getvalue()
    partial = 'Error evaluating condition:' in output or 'Traceback (most recent call last)' in output
    status = 'issues' if any(p['level'] == 'error' for p in problems) else ('partial' if partial else 'checked')
    return {'status': status, 'attempted_stages': ['expressions', 'connectivity'],
            'coverage': [] if partial else ['expressions', 'connectivity'], 'problems': problems,
            'condition_evaluation_incomplete': partial, 'normalized_pin_conditions': normalized,
            'config_index': config_index, 'job_index': job_index}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        report = worker(json.load(sys.stdin))
    except Exception as exc:
        report = {'status': 'failed', 'stage': 'setup', 'error_type': type(exc).__name__,
                  'problems': []}
    raw = json.dumps(report, ensure_ascii=True)
    token = os.environ.get('CLOUDPSS_TOKEN')
    print(raw.replace(json.dumps(token)[1:-1], '[REDACTED]') if token else raw)


if __name__ == '__main__':
    main()
