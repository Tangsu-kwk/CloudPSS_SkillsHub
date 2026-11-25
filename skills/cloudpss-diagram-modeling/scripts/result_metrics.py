"""Read an existing job and extract peak/RMS metrics for named channels.

Read-only: never creates a revision or a job. Messages come from a live output
stream when the server still exposes one, otherwise from an archived SDK record
supplied with --records; the chosen source is recorded in result.json. An
incomplete stream is reported as such and never promoted to success. Values are
computed only from sampled points inside the requested window, and no threshold
is invented when the caller omits a criterion.
"""
import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
import sys

from sdk_bootstrap import activate
activate()

from auto_modeling.job_results import JobResults, fetch_job_info, fetch_job_record_info
from auto_modeling.plot_results import plot_figure

COLUMNS = ['指标名', '测点或通道', '配置时间窗', '实际采样起止', '样点数',
           '数值', '单位', '判据', '结论']
SUCCESS_STATUS = ('COMPLETED', 'completed', 'SUCCEEDED', 'succeeded')


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True,
                               indent=2, allow_nan=False) + '\n', encoding='utf-8')


def safe_name(channel):
    return ''.join(char if char.isalnum() or char in '-_.' else '_' for char in channel)


def unit_of(figure, trace):
    """Unit basis from the owning plot's axis title; never from a guessed abbreviation."""
    layout = figure.get('layout') or {}
    axis = trace.get('yaxis') or 'y'

    def axis_text(name):
        node = layout.get(name)
        if isinstance(node, dict):
            title = node.get('title')
            if isinstance(title, dict):
                return title.get('text') or ''
            if isinstance(title, str):
                return title
        return layout.get(f'{name}.title.text') or ''

    axis_key = 'yaxis' + axis[1:] if axis.startswith('y') else axis
    text = axis_text(axis_key) or axis_text(axis)
    if not text:
        # The SDK plot data can carry the axis label as a flat layout key.
        text = layout.get(f'{axis_key}.title.text') or ''
    if '(' in text and text.endswith(')'):
        return text[text.rindex('(') + 1:-1], 'yaxis.title.text'
    return None, 'yaxis.title.text 未给出括号单位，保留原始量纲'


def sampling(points):
    if len(points) < 2:
        return None
    step = points[1] - points[0]
    return round(1.0 / step, 6) if step > 0 else None


def in_window(xs, ys, window):
    if len(xs) != len(ys):
        raise ValueError(f'轴长不一致（x={len(xs)}, y={len(ys)}）；该通道不参与计算')
    window = window or {}
    if not isinstance(window, dict):
        raise ValueError('window must be an object or null')
    start, end = window.get('start'), window.get('end')
    return [(x, y) for x, y in zip(xs, ys)
            if (start is None or x >= start) and (end is None or x <= end)]


def compute(pairs, quantity):
    if quantity == 'peak_abs':
        return max(abs(y) for _, y in pairs)
    if quantity == 'peak':
        return max(y for _, y in pairs)
    if quantity == 'valley':
        return min(y for _, y in pairs)
    if quantity == 'rms':
        return math.sqrt(sum(y * y for _, y in pairs) / len(pairs))
    if quantity == 'mean':
        return sum(y for _, y in pairs) / len(pairs)
    raise ValueError(f'Unsupported quantity: {quantity}')


def judge(value, criterion):
    if criterion is None or value is None:
        return '未判定'
    if not isinstance(criterion, dict):
        raise ValueError('criterion must be an object or null')
    if 'max' in criterion and value > criterion['max']:
        return f"越上限(>{criterion['max']})"
    if 'min' in criterion and value < criterion['min']:
        return f"越下限(<{criterion['min']})"
    return '满足'


def messages_of(record):
    return record.get('receiver_messages') or record.get('messages') or []


def figures_from(record):
    grouped = defaultdict(list)
    for message in messages_of(record):
        if message.get('type') == 'plot' and message.get('sender') != 'local':
            grouped[message.get('key')].append(message)
    return {key: plot_figure(batch) for key, batch in sorted(grouped.items()) if key}


def channel_index(figures):
    index = defaultdict(list)
    for key, figure in figures.items():
        for trace in figure.get('data') or []:
            name = (trace or {}).get('name')
            if not name:
                continue
            xs, ys = trace.get('x') or [], trace.get('y') or []
            unit, basis = unit_of(figure, trace)
            index[name].append({'plot': key, 'x': xs, 'y': ys, 'unit': unit,
                                'unit_basis': basis, 'sampling_hz': sampling(xs),
                                'usable': len(xs) == len(ys)})
    return index


def bind_channel(index, name, plot):
    items = index.get(name, [])
    candidates = [item for item in items if plot is None or item['plot'] == plot]
    if not candidates:
        location = f'图组 {plot} 中' if plot else '结果中'
        return None, f'缺通道绑定：{location}不存在 {name}'
    if len(candidates) > 1:
        plots = '、'.join(sorted({item['plot'] for item in candidates}))
        detail = f'同时出现在 {plots}，需在指标定义中指定 plot' if len({item['plot'] for item in candidates}) > 1 else f'在 {plots} 中有多个匹配'
        return None, f'通道绑定不唯一：{name} {detail}'
    item = candidates[0]
    if not item['usable']:
        return None, f"轴长不一致（x={len(item['x'])}, y={len(item['y'])}）；该通道不参与计算"
    return item, None


def metric_units(definition, item):
    requested, source = definition.get('unit'), item['unit']
    if definition.get('unit_basis') == '声明换算':
        scale = definition.get('scale')
        if source and requested and type(scale) in (int, float) and math.isfinite(scale) and scale > 0:
            return requested, scale, None
        return source, 1, '单位冲突：声明换算需要已知来源单位、目标单位和有限正比例'
    if requested and requested != source:
        return source, 1, f'单位冲突：定义 {requested}，来源 {source or "未知"}；无换算依据，不出值'
    return source, 1, None


def load_record(job_id, archived_record, timeout):
    """Return (record, source, read_error). Never invent an empty success."""
    if archived_record is not None:
        return archived_record, 'archived_sdk_record', None
    results = JobResults()
    error = None
    try:
        results.listen(job_id, timeout=timeout + 5, startup_timeout=min(timeout, 30))
        results.get_job_logs(job_id, True, timeout=timeout)
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
    finally:
        record = results.records.get(job_id) or {}
        results.close()
    return record, 'live_output_stream', error


def diagnose(record):
    logs = [(m.get('data') or {}).get('content') for m in messages_of(record)
            if m.get('type') == 'log' and (m.get('data') or {}).get('content')]
    completeness = record.get('stream_completeness')
    incomplete = bool(record) and completeness not in (None, 'normal_close')
    if not record:
        statement = '未取得该任务的结果流或归档记录；不把该次读取计为成功'
    elif incomplete:
        statement = f'结果不完整：结果流未正常结束（{completeness}）；不把该次读取计为成功'
    elif logs:
        statement = '任务未成功，未计算指标；下列日志为可用依据'
    else:
        statement = '任务未成功且未取得日志；仅保留任务状态与身份供核对'
    return {
        'incomplete': incomplete,
        'error_logs': logs[-20:],
        'terminate': record.get('stream_termination'),
        'statement': statement,
    }


def read_archive(path):
    """Archived SDK records are stored as UTF-8 JSON or gzip-compressed JSON."""
    raw = Path(path).read_bytes()
    if raw[:2] == b'\x1f\x8b':
        import gzip
        raw = gzip.decompress(raw)
    return json.loads(raw.decode('utf-8-sig'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--metrics', type=Path,
                        help='JSON: {"metrics":[{name,channel,plot,quantity,window,unit,unit_basis,scale,criterion}]}')
    parser.add_argument('--records', type=Path, help='Archived SDK records JSON (read-only reuse)')
    parser.add_argument('--offline', action='store_true', help='Use task metadata from --records without connecting.')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=120)
    args = parser.parse_args(argv)
    if args.offline and not args.records:
        parser.error('--offline requires --records')

    if args.out.exists() and any(args.out.iterdir()):
        raise ValueError('Use a new output path; preserve previous evidence')
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'waveforms').mkdir(exist_ok=True)

    definitions = None
    if args.metrics:
        definitions = json.loads(args.metrics.read_text(encoding='utf-8-sig')).get('metrics')
        if not isinstance(definitions, list) or not definitions:
            raise ValueError('metrics file must contain a non-empty "metrics" list')

    archived = read_archive(args.records) if args.records else None
    if archived is not None and (
        not isinstance(archived, dict) or archived.get('key') != args.job_id
        or (archived.get('job') or {}).get('id') != args.job_id
    ):
        parser.error('归档任务标识与 jobId 不一致')
    info = archived['job'] if args.offline else fetch_job_info(args.job_id)
    names = info if args.offline else fetch_job_record_info(args.job_id)
    record, source, read_error = load_record(args.job_id, archived, args.timeout)
    if not isinstance(record, dict) or record.get('key') != args.job_id:
        record = {}

    status = (info or {}).get('status')
    complete = record.get('stream_completeness') == 'normal_close' and bool(record.get('status'))
    succeeded = status in SUCCESS_STATUS and complete

    result = {
        'job_id': args.job_id,
        'data_source': source,
        'task_metadata_source': 'archived_sdk_record' if args.offline else 'cloudpss',
        'read_error': read_error,
        'task_status': {'server': status, 'sdk': record.get('status'),
                        'stream_completeness': record.get('stream_completeness'),
                        'complete': complete},
        'identity': {
            'job_name': names.get('jobArgName') or record.get('jobArgName'),
            'config_name': names.get('configArgName') or record.get('configArgName'),
            'record_name': record.get('name'),
            'context': (info or {}).get('context'),
            'revision_hash': (info or {}).get('args', {}).get('_ModelRevision'),
            'create_time': (info or {}).get('createTime'),
            'end_time': (info or {}).get('endTime'),
        },
        'logs': {'count': sum(1 for m in messages_of(record) if m.get('type') == 'log'),
                 'tail': diagnose(record)['error_logs'][-5:]},
        'unconfirmed': {
            'scale': '元数据未提供缩放因子；波形按结果流原始采样值读取',
            'phase': '通道后缀 :0/:1/:2 为索引；元数据未声明相别，不推断 A/B/C',
            'scheme': '方案名取自任务记录投影；未回读方案定义，缺失时为 null',
        },
        'channels': [],
    }

    if succeeded:
        figures = figures_from(record)
        index = channel_index(figures)
        result['channels'] = [
            {'name': name, 'plots': sorted({item['plot'] for item in items}),
             'ambiguous': len(items) > 1,
             'bindings': [{key: item[key] for key in ('plot', 'unit', 'unit_basis', 'sampling_hz', 'usable')}
                          | {'samples': len(item['x']), 'value_count': len(item['y'])} for item in items]}
            for name, items in sorted(index.items())
        ]
        result['render'] = {'plot_count': len(figures)}
    else:
        result['diagnostics'] = diagnose(record)
        if not record:
            result['diagnostics']['statement'] = ('未取得该任务的结果流或归档记录；'
                                                  '不把该次读取计为成功')
        index = {}

    rows, metric_results, waveform_files = [], [], {}
    # A failed or unreadable task keeps a header-only table: no metric rows exist.
    for definition in (definitions if succeeded else []) or []:
        name = definition.get('name') or definition.get('channel')
        channel = definition.get('channel')
        window = definition.get('window') or {}
        criterion = definition.get('criterion')
        configured = '' if not window else f"{window.get('start')}~{window.get('end')} s"
        row = {'指标名': name, '测点或通道': channel, '配置时间窗': configured,
               '实际采样起止': '', '样点数': '', '数值': '', '单位': definition.get('unit') or '',
               '判据': '' if criterion is None else json.dumps(criterion, ensure_ascii=False),
               '结论': '未判定'}
        item, reason = bind_channel(index, channel, definition.get('plot'))
        metric = {'name': name, 'channel': channel, 'plot': item['plot'] if item else definition.get('plot'),
                  'window': window, 'value': None, 'unit': None}
        if not reason:
            unit, scale, reason = metric_units(definition, item)
            row['单位'] = unit or ''
            metric.update(unit=unit, source_unit=item['unit'], scale=scale, unit_basis=definition.get('unit_basis') or item['unit_basis'])
        if not reason:
            pairs = in_window(item['x'], item['y'], window)
            if not pairs:
                reason = '窗口内无采样点'
        if reason:
            row['结论'] = reason
            row['单位'] = metric['unit'] or ''
        else:
            pairs = [(time, value * scale) for time, value in pairs]
            value = compute(pairs, definition.get('quantity', 'peak_abs'))
            row['实际采样起止'] = f'{pairs[0][0]:.6g}~{pairs[-1][0]:.6g} s'
            row['样点数'] = len(pairs)
            row['数值'] = f'{value:.9g}'
            row['结论'] = judge(value, criterion)
            path = args.out / 'waveforms' / f"{safe_name(channel)}.csv"
            if path.exists():
                path = path.with_name(f'{len(rows)}-{path.name}')
            with path.open('w', encoding='utf-8-sig', newline='') as handle:
                writer = csv.writer(handle)
                writer.writerow(['time_s', 'value'])
                writer.writerows([(repr(x), repr(y)) for x, y in pairs])
            relative = path.relative_to(args.out).as_posix()
            waveform_files[str(len(rows))] = relative
            metric.update(value=row['数值'], sample_count=len(pairs), sampled_range=[pairs[0][0], pairs[-1][0]], waveform=relative)
        rows.append(row)
        metric_results.append({**metric, 'conclusion': row['结论']})

    with (args.out / 'metrics.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    result['waveforms'] = waveform_files
    result['metrics'] = metric_results
    write_json(args.out / 'result.json', result)
    print(json.dumps({'status': 'ok' if succeeded else 'not_succeeded',
                      'data_source': source, 'metrics': result['metrics'],
                      'channels': len(result['channels'])}, ensure_ascii=False))
    return 0 if succeeded else 2


if __name__ == '__main__':
    sys.exit(main())
