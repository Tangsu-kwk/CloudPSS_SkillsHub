"""Deterministic image-modeling helpers. Images remain the agent's design input.

Import/build are offline; only the explicit fetch-definitions command reads the
network. This module never saves projects or submits computation tasks.
"""
from copy import deepcopy
from pathlib import Path
import argparse
import hashlib
import json
import math
import posixpath
import sys
import time
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
from sdk_bootstrap import activate
activate()
from layout_audit import audit as audit_layout
from preflight_checks import check as check_preflight
NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
HEADERS = {
    'id': ['id', 'logical_id', '实例标识', '序号'],
    'definition': ['definition', '元件库 RID'],
    'key': ['key', '参数键'], 'value': ['value', '模型设置值'],
    'group': ['group', '字段类别'], 'form': ['form', '值形式'],
    'label': ['label', '元件标签'], 'canvas': ['canvas', '图纸'],
    'position': ['position', '位置 X,Y'],
}


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Complete files only, including on interrupted serialization.
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(payload, encoding='utf-8')
    temp.replace(path)


def workbook_rows(path):
    """Read stored scalars, not rendered formats or formula cached results."""
    with zipfile.ZipFile(path) as book:
        strings = []
        if 'xl/sharedStrings.xml' in book.namelist():
            for item in ET.fromstring(book.read('xl/sharedStrings.xml')):
                strings.append(''.join(t.text or '' for t in item.findall('.//s:t', NS)))
        rels = ET.fromstring(book.read('xl/_rels/workbook.xml.rels'))
        targets = {r.attrib['Id']: r.attrib['Target'] for r in rels}
        for sheet in ET.fromstring(book.read('xl/workbook.xml')).findall('s:sheets/s:sheet', NS):
            rid = sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']
            target = targets[rid]
            member = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/' + target)
            rows = []
            for row in ET.fromstring(book.read(member)).findall('s:sheetData/s:row', NS):
                values, formulas = {}, set()
                for cell in row:
                    ref = cell.attrib['r']
                    col = ''.join(c for c in ref if c.isalpha())
                    if cell.find('s:f', NS) is not None:
                        formulas.add(col)
                    value = cell.findtext('s:v', None, NS)
                    kind = cell.get('t')
                    if kind == 'inlineStr':
                        value = ''.join(t.text or '' for t in cell.findall('.//s:t', NS))
                    elif kind == 's':
                        value = strings[int(value)]
                    elif kind == 'b':
                        value = value == '1'
                    elif kind == 'e':
                        formulas.add(col)  # Excel errors are never usable inputs.
                    elif value is not None and kind not in ('str', 'd'):
                        value = float(value) if any(c in value.lower() for c in '.e') else int(value)
                    values[col] = value
                rows.append((int(row.attrib['r']), values, formulas))
            yield sheet.attrib['name'], rows


def import_table(path, *, sheet=None, columns=None, blank='reject'):
    """Long-form rows: instance/definition/key/value; optional pin/form columns."""
    if blank not in ('reject', 'empty-string', 'null'):
        raise ValueError('Unknown blank policy')
    found = []
    for title, rows in workbook_rows(path):
        if sheet is not None and title != sheet:
            continue
        for offset, (number, cells, formulas) in enumerate(rows):
            mapped = {}
            for field, aliases in HEADERS.items():
                names = [columns[field]] if columns and field in columns else aliases
                matches = [col for col, val in cells.items() if val in names]
                if len(matches) > 1:
                    raise ValueError(f'{title}:{number}: ambiguous header {field}')
                if matches:
                    mapped[field] = matches[0]
            if {'id', 'definition', 'key', 'value'} <= mapped.keys():
                found.append((title, rows[offset + 1:], number, mapped))
                break
    if len(found) != 1:
        raise ValueError('Select exactly one long-form parameter sheet with --sheet / --columns')
    title, rows, header, mapped = found[0]
    components = {}
    for number, cells, formulas in rows:
        if not any(v is not None and v != '' for v in cells.values()):
            continue
        where = f'{title}:{number}'
        if formulas & set(mapped.values()):
            raise ValueError(f'{where}: formula/error cell; supply approved literal values')
        row = {k: cells.get(col) for k, col in mapped.items()}
        if row['id'] is None or not isinstance(row['definition'], str) or not isinstance(row['key'], str):
            raise ValueError(f'{where}: missing instance / definition / key')
        lid = str(row['id'])
        identity = {k: row[k] for k in ('definition', 'label', 'canvas', 'position') if k in row}
        comp = components.setdefault(lid, dict(logical_id=lid, **identity, args={}, pins={}, fields=[]))
        if any(comp[k] != v for k, v in identity.items()):
            raise ValueError(f'{where}: conflicting instance identity {lid}')
        value, form = row['value'], row.get('form')
        if value is None:
            if blank == 'reject':
                raise ValueError(f'{where}: blank value; choose a documented blank policy')
            value = '' if blank == 'empty-string' else None
        if form in ('expression', '表达式'):
            if not isinstance(value, str):
                raise ValueError(f'{where}: expression source must be text')
            value = {'source': value, 'ɵexp': ''}
        elif form in ('json', '结构值'):
            value = json.loads(value)
        group = row.get('group')
        if group in ('pins', '引脚信号绑定'):
            target = comp['pins']
        else:
            # Other values are parameter GROUP NAMES (e.g. a library's
            # Configuration / Initial Conditions), not parameter type names.
            target = comp['args']
        if row['key'] in target:
            raise ValueError(f'{where}: duplicate field {lid}.{row["key"]}')
        target[row['key']] = value
        comp['fields'].append({'key': row['key'], 'raw': row['value'], 'form': form,
                               'group': group, 'sheet': title, 'row': number,
                               'source_cells': deepcopy(cells)})
    if not components:
        raise ValueError('No component rows')
    return {'schema_version': 1, 'source': str(Path(path).resolve()),
            'source_sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            'sheet': title, 'header_row': header, 'blank_policy': blank,
            'components': list(components.values())}


def normalize_args(parameters, args, changes, location):
    """Use SDK converters, but reject values they would silently discard."""
    from auto_modeling.job_inputs import _fields, _convert, _expression
    fields = {f['key']: f for f in _fields(parameters)}
    result = {}
    sentinel = object()
    for key, value in args.items():
        if key not in fields:
            raise ValueError(f'{location}.{key}: undeclared field; resolve compatibility explicitly')
        if value is None:
            raise ValueError(f'{location}.{key}: explicit null needs an explicit design value or omission')
        converted = deepcopy(value) if _expression(value) else _convert(value, fields[key], sentinel)
        if converted is sentinel:
            raise ValueError(f'{location}.{key}: cannot convert supplied value')
        # Reject nonfinite values before SDK's JSON compatibility layer maps to null.
        json.dumps(converted, allow_nan=False)
        result[key] = converted
        if type(value) is not type(converted) or value != converted:
            changes.append({'path': location + '.' + key, 'from': value, 'to': converted})
    return result


def fetch_definitions(rids, cache, *, requester=None):
    from auto_modeling.check_environment import DEFINITION_QUERY
    from auto_modeling.remote_reads import _request
    result, stats = deepcopy(cache), {'hits': 0, 'requests': 0}
    for rid in sorted(set(rids)):
        if rid in result:
            _definition(rid, result[rid])
            stats['hits'] += 1
            continue
        stats['requests'] += 1
        item = _request(DEFINITION_QUERY, {'rid': rid}, requester).get('model')
        _definition(rid, item)
        result[rid] = item
    return result, stats


def _definition(rid, item):
    if (not isinstance(item, dict) or item.get('rid') != rid
            or not isinstance(item.get('revision'), dict)
            or item['revision'].get('version') != 5
            or not isinstance(item['revision'].get('parameters'), list)
            or not isinstance(item['revision'].get('pins'), list)):
        raise ValueError('Missing/invalid version 5 definition: ' + rid)
    return {'rid': rid, 'name': item.get('name', rid.rsplit('/', 1)[-1]), **item['revision']}


def build_plan(plan, definitions, materials=None, functions=None, *, strict_layout=False):
    """Fresh local model, no network; return model + traceable static report."""
    from auto_modeling.project_session import build_project_model
    from auto_modeling.canvas_edit import add_diagram_canvas, update_diagram_canvas
    from auto_modeling.diagram_edit import add_diagram_component, add_dynamic_diagram_edge
    from auto_modeling.component_checks import prepare_component_checks
    from auto_modeling.diagram_connections import check_diagram_connections, _DiagramScope, _condition
    from auto_modeling.dynamic_pins import check_pin_definitions, pinlike_pins
    from auto_modeling.job_inputs import evaluate_args
    from auto_modeling.parameter_defs import add_parameter_group, add_parameter
    from auto_modeling.configs import update_config, add_config
    from auto_modeling.job_schemes import add_job
    start = time.perf_counter()
    if plan.get('schema_version') != 1 or plan.get('unresolved'):
        raise ValueError('Plan version must be 1 and unresolved must be empty')
    allowed = {'schema_version', 'name', 'description', 'canvases', 'components', 'networks',
               'signals', 'parameter_groups', 'configs', 'jobs', 'current_config', 'unresolved'}
    if set(plan) - allowed:
        raise ValueError('Unknown plan fields: ' + str(sorted(set(plan) - allowed)))
    flat = {rid: _definition(rid, item) for rid, item in definitions.items()}
    material_components = (materials or {}).get('components', [])
    source = {c['logical_id']: c for c in material_components}
    if len(source) != len(material_components):
        raise ValueError('Duplicate material logical_id')
    m = build_project_model()
    m.name, m.description = plan.get('name', ''), plan.get('description', '')
    changes, overrides, ids, canvases = [], [], {}, {}
    milestones = {}
    for i, canvas in enumerate(plan['canvases']):
        if canvas['id'] in canvases:
            raise ValueError('Duplicate canvas id')
        if i == 0:
            key = 'canvas_0'
            update_diagram_canvas(m, key, name=canvas['name'])
        else:
            key = add_diagram_canvas(m, canvas['name'])
        canvases[canvas['id']] = key
    if not canvases:
        raise ValueError('At least one canvas required')
    for group in plan.get('parameter_groups', []):
        gi = add_parameter_group(m, group['name'])
        for p in group['items']:
            add_parameter(m, gi, p['key'], type=p['type'],
                          options={k: v for k, v in p.items() if k not in ('key', 'type')})
    for i, config in enumerate(plan.get('configs', [])):
        args = normalize_args(m.revision.parameters, config['args'], changes, f'configs.{i}')
        if i == 0:
            update_config(m, 0, args, name=config['name'])
        else:
            add_config(m, config['name'], args)
    selected = plan.get('current_config', 0)
    if type(selected) is not int or not 0 <= selected < len(m.configs):
        raise ValueError('Invalid current_config')
    m.context['currentConfig'] = selected
    milestones['project_setup_seconds'] = time.perf_counter() - start
    component_start = time.perf_counter()
    for spec in plan['components']:
        lid = spec['logical_id']
        if not isinstance(lid, str) or not lid or lid in ids:
            raise ValueError('Component logical_id must be unique nonempty text')
        if set(spec) - {'logical_id', 'definition', 'canvas', 'position', 'args', 'pins', 'label', 'size', 'angle', 'flip', 'evidence'}:
            raise ValueError(f'{lid}: unsupported component fields; no silent ignoring')
        base = source.get(lid, {})
        rid = spec.get('definition', base.get('definition'))
        if base and rid != base['definition']:
            raise ValueError(f'{lid}: material definition conflict; resolve source first')
        if rid not in flat:
            raise ValueError(f'{lid}: definition absent from cache: {rid}')
        for group in ('args', 'pins'):
            for key, value in spec.get(group, {}).items():
                if key in base.get(group, {}) and base[group][key] != value:
                    if not spec.get('evidence'):
                        raise ValueError(f'{lid}.{group}.{key}: material override needs evidence')
                    overrides.append({'path': f'{lid}.{group}.{key}', 'from': base[group][key],
                                      'to': value, 'evidence': spec['evidence']})
        args = normalize_args(flat[rid]['parameters'],
                              {**base.get('args', {}), **spec.get('args', {})}, changes, lid + '.args')
        pins = {**base.get('pins', {}), **spec.get('pins', {})}
        kwargs = {k: spec[k] for k in ('size',) if k in spec}
        cid = add_diagram_component(m, rid, spec['position'], canvases[spec['canvas']], args, {},
                                   label=spec.get('label', base.get('label')), definition_resolver=flat.get, **kwargs)
        ids[lid] = cid
        if 'angle' in spec:
            if type(spec['angle']) not in (int, float) or not math.isfinite(spec['angle']):
                raise ValueError(f'{lid}: angle must be finite degrees')
            m.getAllComponents()[cid].angle = spec['angle']
        if 'flip' in spec:
            if type(spec['flip']) is not bool:
                raise ValueError(f'{lid}: flip must be boolean')
            m.getAllComponents()[cid].flip = spec['flip']
        # Generated pins are validated below after evaluation, not dropped by defaultPins.
        m.getAllComponents()[cid].pins.update(deepcopy(pins))
    milestones['component_build_seconds'] = time.perf_counter() - component_start
    precheck_start = time.perf_counter()
    checked = prepare_component_checks(m, definitions=definitions)
    doc = checked['document']
    cells = doc['revision']['implements']['diagram']['cells']
    globals_ = evaluate_args(m.configs[selected]['args'], m.revision.parameters)
    effective = {}
    for lid, cid in ids.items():
        cell = cells[cid]
        pins = check_pin_definitions(definitions[cell['definition']], cell['args'])
        # pinLike parameters with a non-empty label are real terminals too.
        known0 = {p['key'] for p in pins}
        pins = pins + [p for p in pinlike_pins(definitions[cell['definition']], cell['args'])
                       if p['key'] not in known0]
        scope = _DiagramScope(cell['args'], cell, doc, globals_)
        effective[lid] = {p['key'] for p in pins if _condition(scope, p.get('condition'))}
        supplied = m.getAllComponents()[cid].pins
        known = {p['key'] for p in pins}
        for key, value in supplied.items():
            if key not in known:
                raise ValueError(f'{lid}.pins.{key}: unknown effective pin')
            if not isinstance(value, str) and not (isinstance(value, dict) and 'ɵexp' in value):
                raise ValueError(f'{lid}.pins.{key}: binding must be text or expression')
    milestones['effective_port_check_seconds'] = time.perf_counter() - precheck_start
    edges_start = time.perf_counter()
    edges = []
    def terminal(value):
        if not isinstance(value, list) or len(value) != 2 or any(not isinstance(v, str) for v in value):
            raise ValueError('Terminal must be [logical_id, string port_key]')
        lid, port = value
        if lid not in ids or port not in effective[lid]:
            raise ValueError(f'{lid}.{port}: unknown or inactive terminal')
        return {'cell': ids[lid], 'port': port}
    def edge(a, b, evidence, vertices=None):
        if not evidence:
            raise ValueError('Connection evidence required (image/region or approved assumption)')
        eid = add_dynamic_diagram_edge(m, terminal(a), terminal(b), vertices,
                                      definition_resolver=flat.get)
        edges.append({'id': eid, 'source': a, 'target': b, 'evidence': evidence})
    for network in plan.get('networks', []):
        if set(network) - {'name', 'members', 'evidence'}:
            raise ValueError('Unknown network fields')
        members = network['members']
        if len(members) < 2:
            raise ValueError('Network needs at least two terminals')
        for member in members[1:]:
            edge(members[0], member, network.get('evidence'))
    for signal in plan.get('signals', []):
        if set(signal) - {'source', 'target', 'vertices', 'evidence'}:
            raise ValueError('Unknown signal fields')
        edge(signal['source'], signal['target'], signal.get('evidence'), signal.get('vertices'))
    milestones['connection_build_seconds'] = time.perf_counter() - edges_start
    jobs_start = time.perf_counter()
    def references(value):
        if isinstance(value, dict):
            if set(value) == {'$cell'}:
                return ids[value['$cell']]
            return {k: references(v) for k, v in value.items()}
        if isinstance(value, list):
            return [references(v) for v in value]
        return value
    if plan.get('jobs'):
        m.jobs.clear()
        for job in plan['jobs']:
            rid = job['rid']
            definition = (functions or {}).get(rid)
            if definition is None or definition.get('rid') != rid:
                raise ValueError('Missing function definition: ' + rid)
            args = normalize_args(definition['parameters'], references(job['args']), changes, 'jobs.' + job['name'])
            from auto_modeling.scheme_args import default_args
            add_job(m, rid, job['name'], default_args(definition['parameters'], args),
                    definition_resolver=functions.get)
    milestones['job_build_seconds'] = time.perf_counter() - jobs_start
    final_check_start = time.perf_counter()
    m.context['diagram'].update(openedCanvas=[{'key': k} for k in canvases.values()], currentCanvas=0)
    checked = prepare_component_checks(m, definitions=definitions)
    problems = check_diagram_connections(checked['document'], definitions=definitions)
    document = m.toJSON()
    layout = audit_layout(document, definitions)
    preflight = check_preflight(document)
    milestones['final_static_check_seconds'] = time.perf_counter() - final_check_start
    blocking = bool(checked['problems'] or problems or preflight['status'] != 'clean'
                    or layout['missing_positions'] or (strict_layout and layout['overlap_count']))
    return m, {'status': 'issues' if blocking else 'static_clean',
               'scope': ('component parameters, diagram connections, preflight limits/units/capacity '
                         'and layout audit; not full platform run_check or physics'),
               'logical_to_sdk': ids, 'canvases': canvases, 'edges': edges,
               'conversions': changes, 'material_overrides': overrides, 'timing': milestones,
               'component_problems': checked['problems'],
               'connection_problems': problems, 'preflight': preflight, 'layout': layout,
               'elapsed_seconds': time.perf_counter() - start}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    doc = sub.add_parser('doctor', help='Offline dependencies and optional credential-presence check')
    doc.add_argument('--check-auth', action='store_true')
    doc.add_argument('--config', type=Path)
    imp = sub.add_parser('import-table')
    imp.add_argument('xlsx', type=Path)
    imp.add_argument('--sheet')
    imp.add_argument('--columns', type=Path, help='JSON semantic field -> literal header')
    imp.add_argument('--blank', choices=['reject', 'empty-string', 'null'], default='reject')
    imp.add_argument('--out', type=Path, required=True)
    fetch = sub.add_parser('fetch-definitions', help='Read public GraphQL definitions; no project writes')
    fetch.add_argument('materials', type=Path)
    fetch.add_argument('--cache', type=Path, required=True)
    fetch.add_argument('--config', type=Path)
    build = sub.add_parser('build', help='Offline build/check only')
    build.add_argument('plan', type=Path)
    build.add_argument('--materials', type=Path)
    build.add_argument('--definitions', type=Path, required=True)
    build.add_argument('--functions', type=Path)
    build.add_argument('--strict-layout', action='store_true',
                       help='Treat overlapping symbol boxes as a build failure')
    build.add_argument('--out', type=Path, required=True, help='New/empty artifact directory')
    args = parser.parse_args(argv)
    try:
        if args.command == 'doctor':
            from sdk_bootstrap import doctor
            report = doctor(check_auth=args.check_auth, config=args.config)
            print(json.dumps(report))
            return 0 if report['status'] == 'ok' else 1
        elif args.command == 'import-table':
            write_json(args.out, import_table(args.xlsx, sheet=args.sheet,
                       columns=read_json(args.columns) if args.columns else None, blank=args.blank))
            print(json.dumps({'status': 'imported', 'out': str(args.out)}))
        elif args.command == 'fetch-definitions':
            from configure_cloudpss import configure_cloudpss
            configure_cloudpss(args.config)
            materials = read_json(args.materials)
            cache, stats = fetch_definitions([c['definition'] for c in materials['components']],
                                            read_json(args.cache) if args.cache.exists() else {})
            write_json(args.cache, cache)
            print(json.dumps(stats))
        else:
            if args.out.exists() and any(args.out.iterdir()):
                raise ValueError('Use a new/empty output directory; preserve previous evidence')
            model, report = build_plan(read_json(args.plan), read_json(args.definitions),
                           read_json(args.materials) if args.materials else None,
                           read_json(args.functions) if args.functions else None,
                           strict_layout=args.strict_layout)
            report['input_sha256'] = {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (args.plan, args.definitions, args.materials, args.functions) if p}
            write_json(args.out / 'model.json', model.toJSON())
            write_json(args.out / 'build_report.json', report)
            print(json.dumps({k: report[k] for k in ('status', 'elapsed_seconds')}))
            return 0 if report['status'] == 'static_clean' else 2
        return 0
    except Exception as exc:
        # Do not print transport internals/configuration or credential values.
        print(json.dumps({'status': 'error', 'type': type(exc).__name__, 'message': str(exc)}, ensure_ascii=True))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
