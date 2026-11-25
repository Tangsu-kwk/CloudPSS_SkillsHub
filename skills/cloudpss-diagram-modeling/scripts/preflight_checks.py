"""Offline pre-submit checks for a built model document.

Covers the four classes that platform jobs used to report only after submission:
power-flow node binding and island references, limit validity, line unit mixing,
and declared-vs-actual capacity of aggregated units. Reads only local JSON.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import sys

from layout_audit import load_cells

NODE_KEYS = {'pf_P', 'pf_V', 'BusType', 'pf_Qmin', 'pf_Qmax', 'pf_Vmin', 'pf_Vmax'}
CAPACITY_KEYS = ('Sbase', 'AP', 'Pref_WF', 'Pbase')
OPERATING_KEYS = ('pf_P', 'P_cmd')
LINE_BANDS = {  # plausible per-unit-length magnitudes for overhead circuits
    'R1': (0.004, 0.3),
    'Xl1': (0.10, 1.0),
    'Xc1': (0.005, 5.0),
}
LABEL_MW = re.compile(r'(\d+(?:\.\d+)?)\s*MW')
LABEL_NXM = re.compile(r'(\d+)\s*[×xX]\s*(\d+(?:\.\d+)?)\s*MW')


def _num(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _declared_mw(label):
    nested = LABEL_NXM.search(label or '')
    if nested:
        return int(nested.group(1)) * float(nested.group(2))
    flat = LABEL_MW.search(label or '')
    if flat:
        return float(flat.group(1))
    return None


def _is_bus(cell):
    return str(cell.get('definition', '')).endswith('_newBus_3p')


def _issue(items, level, code, cell, detail):
    items.append({'level': level, 'code': code, 'component': cell.get('id'),
                  'label': cell.get('label'), 'detail': detail})


def check(document):
    components, edges = load_cells(document)
    by_id = {c['id']: c for c in components}
    adjacency = defaultdict(set)
    dangling = []
    for edge in edges:
        source, target = edge.get('source') or {}, edge.get('target') or {}
        first, second = source.get('cell'), target.get('cell')
        if first not in by_id or second not in by_id:
            dangling.append({'edge': edge.get('id'), 'source': first, 'target': second})
            continue
        adjacency[first].add(second)
        adjacency[second].add(first)

    nodes = [c for c in components if NODE_KEYS & set(c.get('args') or {})]
    problems = []

    for cell in nodes:
        buses = [n for n in adjacency[cell['id']] if _is_bus(by_id[n])]
        if not buses:
            _issue(problems, 'error', 'node_without_bus', cell,
                   'power-flow node model has no bus neighbour')
        elif len(buses) > 1:
            _issue(problems, 'warning', 'node_multiple_buses', cell,
                   f'attached to {len(buses)} buses: {buses}')

    seen, islands = set(), []
    for cell in components:
        if cell['id'] in seen:
            continue
        stack, members = [cell['id']], []
        seen.add(cell['id'])
        while stack:
            current = stack.pop()
            members.append(current)
            for neighbour in adjacency[current]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        islands.append(members)
    for members in islands:
        island_nodes = [by_id[m] for m in members if by_id[m]['id'] in {c['id'] for c in nodes}]
        if not island_nodes:
            continue
        if not any(m for m in members if _is_bus(by_id[m])):
            _issue(problems, 'error', 'island_without_bus', island_nodes[0],
                   f'{len(island_nodes)} node models but no bus in island')
        if not any('pf_V' in (c.get('args') or {}) for c in island_nodes):
            labels = [c.get('label') for c in island_nodes]
            _issue(problems, 'error', 'island_without_reference', island_nodes[0],
                   f'no voltage-referenced source among {labels}')

    per_bus = defaultdict(list)
    for cell in nodes:
        for neighbour in adjacency[cell['id']]:
            if _is_bus(by_id[neighbour]):
                per_bus[neighbour].append(cell)
    for bus, attached in per_bus.items():
        if len(attached) > 1:
            _issue(problems, 'warning', 'shared_bus_nodes', attached[0],
                   f'{len(attached)} node models on bus {by_id[bus].get("label")}')

    for cell in nodes:
        args = cell.get('args') or {}
        qmin, qmax = _num(args.get('pf_Qmin')), _num(args.get('pf_Qmax'))
        if args.get('pf_Qmin') is not None or args.get('pf_Qmax') is not None:
            if qmin is None or qmax is None:
                _issue(problems, 'error', 'non_numeric_q_limit', cell,
                       f'pf_Qmin={args.get("pf_Qmin")!r} pf_Qmax={args.get("pf_Qmax")!r}')
            elif qmax <= qmin:
                _issue(problems, 'error', 'invalid_q_limits', cell, f'{qmin} .. {qmax}')
            elif qmin == 0 and qmax == 0:
                _issue(problems, 'warning', 'zero_q_range', cell, 'reactive range is zero')
        bus_type = _num(args.get('BusType'))
        if bus_type == 1 and 'pf_V' not in args:
            _issue(problems, 'error', 'pv_without_voltage', cell, 'BusType=1 requires pf_V')
        if bus_type == 0:
            vmin, vmax = _num(args.get('pf_Vmin')), _num(args.get('pf_Vmax'))
            if vmin is None or vmax is None:
                _issue(problems, 'error', 'missing_v_bounds', cell,
                       f'pf_Vmin={args.get("pf_Vmin")!r} pf_Vmax={args.get("pf_Vmax")!r}')
            elif vmax <= vmin:
                _issue(problems, 'error', 'invalid_v_bounds', cell, f'{vmin} .. {vmax}')

    line_evidence = []
    for cell in components:
        if not str(cell.get('definition', '')).endswith('TransmissionLine'):
            continue
        args = cell.get('args') or {}
        length = _num(args.get('Length'))
        if length is None or length <= 0:
            _issue(problems, 'error', 'invalid_length', cell, f'Length={args.get("Length")!r}')
            continue
        for key, (low, high) in LINE_BANDS.items():
            value = _num(args.get(key))
            if value is None:
                _issue(problems, 'error', 'missing_line_parameter', cell, f'{key} is not numeric')
                continue
            if value != 0 and not low <= value <= high:
                _issue(problems, 'error', 'suspected_unit_mix', cell,
                       f'{key}={value} outside per-unit-length band {low}..{high}')
        line_evidence.append({'component': cell.get('id'), 'label': cell.get('label'),
                              'Length_km': length, 'R_total_ohm': round((_num(args.get('R1')) or 0) * length, 4),
                              'X_total_ohm': round((_num(args.get('Xl1')) or 0) * length, 4)})

    capacity = []
    for cell in components:
        declared = _declared_mw(cell.get('label'))
        if declared is None:
            continue
        args = cell.get('args') or {}
        record = {'component': cell.get('id'), 'label': cell.get('label'), 'declared_mw': declared}
        checked = False
        for key in CAPACITY_KEYS + OPERATING_KEYS:
            if key not in args:
                continue
            value = _num(args[key])
            if value is None:
                if isinstance(args[key], dict):
                    record['skipped_expression'] = key
                continue
            checked = True
            deviation = abs(abs(value) - declared) / declared if declared else 0.0
            record[key] = value
            record['deviation_pct'] = round(100 * deviation, 3)
            if deviation > 0.01:
                level = 'error' if key in CAPACITY_KEYS else 'warning'
                code = 'capacity_mismatch' if key in CAPACITY_KEYS else 'operating_point_differs'
                _issue(problems, level, code, cell,
                       f'label declares {declared:g} MW, {key}={value:g} MW')
        if not checked:
            record['status'] = 'skipped_no_power'
        capacity.append(record)

    errors = [p for p in problems if p['level'] == 'error']
    return {
        'status': 'issues' if errors else 'clean',
        'components': len(components),
        'edges': len(edges),
        'dangling_edges': dangling,
        'problems': problems,
        'counts': {'error': len(errors),
                   'warning': sum(1 for p in problems if p['level'] == 'warning')},
        'line_unit_evidence': line_evidence,
        'capacity_reconciliation': capacity,
        'notes': [
            'Line R1/Xl1 are per-unit-length (ohm/km) and Xc1 per km (Mohm*km); totals are derived, not written.',
            'Capacity reconciliation reads the declared MW from the label and compares it with the first available power argument.',
        ],
    }


def require_preflight(report):
    if report['status'] != 'clean':
        raise ValueError('Preflight checks found errors; inspect preflight.json')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args(argv)
    report = check(json.loads(args.model.read_bytes()))
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('status', 'counts')}))
    for problem in report['problems'][:20]:
        print(json.dumps(problem, ensure_ascii=False))
    return 0 if report['status'] == 'clean' else 2


if __name__ == '__main__':
    sys.exit(main())
