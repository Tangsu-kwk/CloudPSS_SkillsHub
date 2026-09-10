"""Resolve fault-adjacent buses without walking through electrical devices.

Platform topology is fetched for the exact revision/config being analyzed.
Named pins are preferred; diagram edges remain supported and cross-checked.
No model fields or cloud models are edited by this module.
"""
import copy
import math


def current_topology(model):
    from cloudpss import ModelRevision, ModelTopology
    configs = model.configs
    selected = model.context.get('currentConfig')
    if isinstance(configs, list):
        if type(selected) is not int or not 0 <= selected < len(configs):
            raise ValueError('currentConfig must index configs for fault topology')
    elif not isinstance(configs, dict) or selected not in configs:
        raise ValueError('currentConfig must identify a config for fault topology')
    # Work on a copy even if the SDK later changes create's implementation.
    revision = ModelRevision.create(copy.deepcopy(model.revision))
    if hasattr(revision, 'toJSON'):
        revision = revision.toJSON()
    if not isinstance(revision, dict) or not revision.get('hash'):
        raise ValueError('Platform did not return a revision hash for fault topology')
    topo = ModelTopology.fetch(revision['hash'], 'emtp', copy.deepcopy(configs[selected]), maximumDepth=0)
    if hasattr(topo, 'toJSON'):
        topo = topo.toJSON()
    if not isinstance(topo, dict) or not isinstance(topo.get('components'), dict):
        raise ValueError('Platform did not return fault topology components')
    return topo, {'revision_hash': revision['hash'], 'config': selected,
                  'source': 'CloudPSS ModelTopology.fetch', 'saved_to_cloud': False}


def is_bus(comp):
    rid = str(comp.get('definition') or '').lower()
    return '_newbus' in rid or rid.endswith('/bus')


def number(value):
    if isinstance(value, dict):
        value = value.get('source')
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) and n > 0 else None
    except (TypeError, ValueError):
        return None


def resolve(cells, target, topology=None):
    fault_id = target.get('id') if target else None
    fault = cells.get(fault_id, {})
    buses = {k: v for k, v in cells.items() if isinstance(v, dict) and is_bus(v)}
    pins = fault.get('pins') or {}
    # Fault templates expose their electrical terminals in pins. args.I/V are
    # signal names and never participate in these connectivity searches.
    top = topology.get('components', {}) if topology is not None else {}
    def node(key, pin):
        n = (top.get('/'+key, {}).get('pins') or {}).get(pin)
        return str(n) if n not in (None, '') else None
    ground_nodes = {node(k, p) for k, c in cells.items()
                    if isinstance(c, dict) and str(c.get('definition', '')).lower().endswith('/gnd')
                    for p in (c.get('pins') or {})} - {None}
    fault_nodes = {node(fault_id, p) for p in pins} - {None} if fault_id else set()
    fault_nodes -= ground_nodes
    top_candidates = {(k, p) for k, b in buses.items() for p in (b.get('pins') or {})
                      if node(k, p) in fault_nodes}
    names = {v for v in pins.values() if isinstance(v, str) and v.strip()}
    named = {(k, p) for k, b in buses.items() for p, n in (b.get('pins') or {}).items()
             if n and n in names and b.get('canvas') == fault.get('canvas')}
    cross_canvas = any(n and n in names and b.get('canvas') != fault.get('canvas')
                       for b in buses.values() for n in (b.get('pins') or {}).values())

    # Follow edge-to-edge junctions, but never traverse a component interior.
    edges = {k: v for k, v in cells.items() if isinstance(v, dict) and v.get('shape') == 'diagram-edge'}
    adjacent = {}
    for key, edge in edges.items():
        for side in ('source', 'target'):
            endpoint = edge.get(side) or {}
            adjacent.setdefault(endpoint.get('cell'), set()).add(key)
    queue = list(adjacent.get(fault_id, set())) if fault_id else []
    visited, edge_buses = set(), set()
    while queue:
        key = queue.pop()
        if key in visited:
            continue
        visited.add(key)
        queue.extend(adjacent.get(key, set()) - visited)
        for side in ('source', 'target'):
            endpoint = edges[key].get(side) or {}
            other, port = endpoint.get('cell'), endpoint.get('port')
            if other in edges and other not in visited:
                queue.append(other)
            elif other in buses:
                edge_buses.add((other, str(port) if port is not None else None))

    if topology is not None:
        if not fault_nodes:
            raise ValueError('Target fault has no resolved non-ground electrical topology node')
        for key, pin in named | edge_buses:
            ns = ({node(key, pin)} if pin is not None else
                  {node(key, p) for p in (buses[key].get('pins') or {})}) - {None}
            if not ns or not ns <= fault_nodes:
                raise ValueError('Fault Pin/diagram-edge connectivity conflicts with current topology')
        selected = top_candidates
        networks = {node(k, p) for k, p in selected}
        basis = 'named_pin_topology' if named else ('diagram_edge_topology' if edge_buses else 'topology')
    else:
        if cross_canvas:
            raise ValueError('Cross-canvas named pins require current platform topology')
        named_ids, edge_ids = {k for k, _ in named}, {k for k, _ in edge_buses}
        if named_ids and edge_ids and not edge_ids <= named_ids:
            raise ValueError('Named Pin and diagram-edge bus candidates conflict; refresh topology')
        selected = named or edge_buses
        networks = {('named', buses[k]['pins'][p]) for k, p in selected} if named else {
            ('edge', k) for k, _ in selected}
        basis = 'named_pin' if named else 'diagram_edge'
    if len(networks) > 1:
        raise ValueError('Target fault connects to multiple bus networks; cannot choose a fault bus')
    ids = sorted({k for k, _ in selected})
    return {'component_ids': ids, 'connection_basis': basis if ids else None,
            'topology_nodes': sorted(n for n in networks if isinstance(n, str)),
            'edge_ids': sorted(visited), 'named_pin_candidates': sorted({k for k, _ in named}),
            'diagram_edge_candidates': sorted({k for k, _ in edge_buses})}
