"""Offline layout audit for a built model diagram.

Checks that every component has a numeric position, that symbol bounding boxes
(from the library graphic definitions) do not overlap, and reports the canvas
extent so a delivery figure can be reviewed before submission. Reads only local
JSON: no credentials, no network.
"""
import argparse
import json
from pathlib import Path
import sys


def load_cells(document):
    """Return (components, edges) lists from a model document or toJSON dump."""
    doc = document.get('revision', document)
    implements = doc.get('implements') or {}
    diagram = implements.get('diagram') or {}
    cells = diagram.get('cells') or []
    if isinstance(cells, dict):
        cells = list(cells.values())
    components = [c for c in cells if isinstance(c, dict) and c.get('shape') == 'diagram-component']
    edges = [c for c in cells if isinstance(c, dict) and c.get('shape') == 'diagram-edge']
    return components, edges


def symbol_sizes(definitions):
    """definition rid -> (width, height) in px, from the library graphic block."""
    sizes = {}
    for rid, item in (definitions or {}).items():
        revision = item.get('revision', item) if isinstance(item, dict) else {}
        graphic = (revision or {}).get('graphic') or {}
        width, height = graphic.get('width'), graphic.get('height')
        if isinstance(width, (int, float)) and isinstance(height, (int, float)) and width > 0 and height > 0:
            sizes[rid] = (float(width), float(height))
    return sizes


def _box(cell, sizes, clearance=0.0):
    position = cell.get('position') or {}
    x, y = position.get('x'), position.get('y')
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return None
    size = sizes.get(cell.get('definition'))
    if size is None:
        return None
    width, height = size
    rotate = cell.get('rotate') or 0
    if isinstance(rotate, (int, float)) and int(rotate) % 180 == 90:
        width, height = height, width
    pad = float(clearance)
    return (x - pad, y - pad, x + width + pad, y + height + pad)


def _overlap(first, second):
    dx = min(first[2], second[2]) - max(first[0], second[0])
    dy = min(first[3], second[3]) - max(first[1], second[1])
    if dx > 0 and dy > 0:
        return round(dx * dy, 1)
    return 0.0


def audit(document, definitions=None, *, clearance=0.0, max_overlaps=200, label_limit=40):
    components, edges = load_cells(document)
    sizes = symbol_sizes(definitions)
    boxes, missing, unknown = {}, [], {}
    for cell in components:
        box = _box(cell, sizes, clearance)
        if box is None:
            position = cell.get('position') or {}
            if not isinstance(position.get('x'), (int, float)) or not isinstance(position.get('y'), (int, float)):
                missing.append({'id': cell.get('id'), 'label': cell.get('label')})
            else:
                unknown[cell['definition']] = unknown.get(cell['definition'], 0) + 1
            continue
        boxes[cell['id']] = box

    overlaps = []
    ids = list(boxes)
    for i, first in enumerate(ids):
        for second in ids[i + 1:]:
            area = _overlap(boxes[first], boxes[second])
            if area:
                overlaps.append({'a': first, 'b': second, 'area_px': area})
    labels = {c['id']: c.get('label') for c in components}
    for item in overlaps:
        item['label_a'] = labels.get(item['a'])
        item['label_b'] = labels.get(item['b'])
    overlaps.sort(key=lambda item: -item['area_px'])

    outside = [{'id': c['id'], 'label': c.get('label'), 'position': c['position']}
               for c in components
               if isinstance((c.get('position') or {}).get('x'), (int, float))
               and ((c['position']['x'] < 0) or (c['position'].get('y', 0) < 0))]
    extent = {'x': max((c['position']['x'] + sizes.get(c['definition'], (0, 0))[0]
                        for c in components if isinstance((c.get('position') or {}).get('x'), (int, float))),
                       default=0),
              'y': max((c['position']['y'] + sizes.get(c['definition'], (0, 0))[1]
                        for c in components if isinstance((c.get('position') or {}).get('y'), (int, float))),
                       default=0)}
    status = 'issues' if missing or overlaps else 'clean'
    return {
        'status': status,
        'components': len(components),
        'edges': len(edges),
        'missing_positions': missing,
        'unknown_symbol_sizes': [{'definition': rid, 'count': n} for rid, n in sorted(unknown.items())],
        'overlap_count': len(overlaps),
        'overlaps': overlaps[:max_overlaps],
        'clearance_px': float(clearance),
        'out_of_canvas': outside,
        'canvas_extent': extent,
        'notes': [
            'Bounding boxes use the library graphic width/height from the supplied definitions.',
            'Straight or polyline edges crossing unrelated symbols are not detected offline; check the rendered canvas.',
        ],
    }


def require_layout(report, *, strict_overlap=True):
    if report['missing_positions']:
        raise ValueError('Layout audit found components without a position; see layout.json')
    if strict_overlap and report['overlap_count']:
        raise ValueError('Layout audit found overlapping symbol boxes; see layout.json')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--definitions', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--clearance', type=float, default=0.0)
    parser.add_argument('--allow-overlap', action='store_true', help='Report overlaps without failing')
    args = parser.parse_args(argv)
    model = json.loads(args.model.read_bytes())
    definitions = json.loads(args.definitions.read_bytes()) if args.definitions else None
    report = audit(model, definitions, clearance=args.clearance)
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('status', 'components', 'overlap_count',
                                             'canvas_extent')}))
    if report['missing_positions']:
        return 2
    if report['overlap_count'] and not args.allow_overlap:
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
