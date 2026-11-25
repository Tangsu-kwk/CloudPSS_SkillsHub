"""Resolve a requested scheme name to an actual index, or refuse before submitting.

No mutation happens here. Exact names win; otherwise a unique prefix/substring
match is accepted. Multiple candidates or no candidate are returned as a
refusal with the candidate list, so a caller never guesses an index.
"""
import argparse
import json
from pathlib import Path
import sys

from sdk_bootstrap import activate
activate()

from auto_modeling.configs import list_configs
from auto_modeling.diagram_aux import model_from_document
from auto_modeling.project_reads import list_jobs
from auto_modeling.project_session import open_project


def resolve(items, wanted, kind):
    if not isinstance(wanted, str) or not wanted.strip():
        return None, {'refusal': f'{kind} 选择为空', 'candidates': []}
    exact = [item for item in items if item['name'] == wanted]
    if len(exact) == 1:
        return exact[0], None
    needle = wanted.strip()
    partial = [item for item in items if needle in item['name'] or item['name'] in needle]
    if len(partial) == 1:
        return partial[0], None
    if len(partial) > 1:
        return None, {'refusal': f'{kind} "{wanted}" 有 {len(partial)} 个候选，需指定其一',
                      'candidates': partial}
    return None, {'refusal': f'{kind} "{wanted}" 不存在', 'candidates': items}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--rid')
    source.add_argument('--document', type=Path, help='Local working model JSON')
    parser.add_argument('--config')
    parser.add_argument('--job')
    parser.add_argument('--list', action='store_true')
    args = parser.parse_args(argv)

    model = open_project(args.rid) if args.rid else model_from_document(json.loads(args.document.read_bytes()))
    configs, jobs = list_configs(model), list_jobs(model)
    out = {'rid': args.rid, 'configs': configs, 'jobs': jobs}
    if args.list:
        print(json.dumps(out, ensure_ascii=False))
        return 0
    failures = []
    if args.config:
        item, refusal = resolve(configs, args.config, '参数方案')
        if refusal:
            failures.append(refusal)
        else:
            out['config_selection'] = item
    if args.job:
        item, refusal = resolve(jobs, args.job, '计算方案')
        if refusal:
            failures.append(refusal)
        else:
            out['job_selection'] = item
    out['refusals'] = failures
    print(json.dumps(out, ensure_ascii=False))
    return 2 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
