"""Offline connection/schema contracts with real SDK objects; no cloud writes."""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import cloudpss
from mylib import PSAToolbox, edit_model_from_context as edit
from mylib.sdk_adapter import SDKAdapter


def model(edges=False):
    cells = {}
    for key, pins in {'a': {'0': 'bus', '1': ''}, 'b': {'0': 'bus'},
                      'c': {'0': ''}, 'd': {'0': 'other'}}.items():
        cells[key] = dict(id=key, shape='diagram-component', label=key.upper(),
                          definition='model/CloudPSS/_newBus_3p', canvas='canvas_0',
                          args={'Name': key, 'VBase': {'source': '500'}}, pins=pins)
    if edges:
        cells['e'] = dict(id='e', shape='diagram-edge', source={'cell': 'a', 'port': '0'},
                          target={'cell': 'b', 'port': '0'})
    return cloudpss.Model(dict(rid='model/example/source', configs=[{'name': 'Default', 'args': {}}],
        context={'currentConfig': 0}, jobs=[], revision={'version': 5, 'hash': 'fixture',
        'parameters': {}, 'pins': {}, 'implements': {'diagram': {
        'canvas': [{'key': 'canvas_0', 'name': 'Main'}], 'cells': cells}}}))


def topology():
    return {'revision_hash': 'fixture', 'component_count': 4, 'topology': {'components': {
        '/a': {'pins': {'0': '7', '1': None}}, '/b': {'pins': {'0': '7'}},
        '/c': {'pins': {'0': None}}, '/d': {'pins': {'0': '7'}}}}}


def full_edit(request, state):
    result = edit(request, state)
    if 'read_request' not in result:
        return result
    parts = []
    request = result['read_request']
    while True:
        page = edit(request, state)
        parts.append(page['text'])
        if page['next_offset'] is None:
            return json.loads(''.join(parts))
        request['options']['offset'] = page['next_offset']


class Connections(unittest.TestCase):
    def setUp(self):
        for name in ('configure',):
            p = patch.object(SDKAdapter, name)
            p.start(); self.addCleanup(p.stop)
        for name in ('fetch', 'create', 'save', 'update'):
            p = patch.object(cloudpss.Model, name, side_effect=AssertionError('Unexpected network'))
            p.start(); self.addCleanup(p.stop)
        p = patch.object(SDKAdapter, 'topology', side_effect=AssertionError('Unexpected topology'))
        p.start(); self.addCleanup(p.stop)
        self.sa = PSAToolbox()
        self.sa.setInitialConditions(project=model())
        self.state = {'toolbox': self.sa}

    def test_named_pins_empty_pins_paging_and_no_mutation(self):
        before = copy.deepcopy(self.sa.project.toJSON())
        query = lambda **target: edit({'operation': 'query_connections', 'target': target}, self.state)
        result = query(identifier='A', pin='0')
        self.assertEqual({r['key'] for r in result['items']}, {'a', 'b'})
        self.assertEqual(result['basis'], 'named_pins_only')
        self.assertEqual(query(identifier='a', pin='1')['total'], 1)
        self.assertEqual(query(node='missing')['total'], 0)
        page = self.sa.getConnections(node='bus', limit=1)
        self.assertEqual(page['next_offset'], 1)
        self.assertIsNone(self.sa.getConnections(node='bus', offset=1, limit=1)['next_offset'])
        result['items'][0]['node'] = 'tampered'
        self.assertEqual(before, self.sa.project.toJSON())

    def test_topology_alias_and_invalidation_after_confirmed_edit(self):
        self.sa.topo = topology()['topology']
        self.assertEqual(self.sa.getConnections(node='bus')['total'], 3)
        p = edit({'operation': 'update', 'target': {'identifier': 'a'},
                  'changes': {'pins': {'0': 'new'}, 'args': {'VBase': {'source': '2*Vbase'}}}}, self.state)
        self.assertIsNotNone(self.sa.topo)
        edit({'operation': 'update', 'preview_id': p['preview_id'], 'confirmation': 'execute'}, self.state)
        self.assertIsNone(self.sa.topo)
        self.assertEqual(self.sa.getConnections(node='bus')['total'], 1)
        self.assertEqual(self.sa.getComponentByKey('a').args['VBase']['source'], '2*Vbase')

    def test_reject_only_invalid_query_shapes(self):
        for target in ({}, {'identifier': 'a', 'node': 'bus'}, {'node': ''},
                       {'node': 'bus', 'pin': '0'}, {'identifier': 'a', 'pin': '999'}):
            with self.assertRaises((ValueError, KeyError, TypeError)):
                edit({'operation': 'query_connections', 'target': target}, self.state)
        for op in ('query_connections', 'query_edges'):
            with self.assertRaises(ValueError):
                edit({'operation': op, 'options': {'fields': ['Name']}}, self.state)
        for options in ({'limit': True}, {'offset': -1}, {'limit': 101}):
            with self.assertRaises(ValueError):
                self.sa.getConnections(node='bus', **options)

    def test_original_snapshot_survives_deletion_and_resets(self):
        normalized = topology()
        normalized['topology']['components']['/d']['pins']['0'] = '8'
        with patch.object(SDKAdapter, 'topology', return_value=normalized):
            self.sa.setInitialConditions(project=model(edges=True))
        original = self.sa.getDiagramEdges('A')
        self.assertEqual(original['total'], 1)
        self.assertEqual(self.sa.getDiagramEdges(view='current')['total'], 0)
        self.sa.deleteComponent('a')
        self.assertEqual(self.sa.getDiagramEdges('A'), original)
        original['items'][0]['source']['port'] = 'tampered'
        self.assertEqual(self.sa.getDiagramEdges('A')['items'][0]['source']['port'], '0')
        self.sa.setInitialConditions(project=model())
        self.assertFalse(self.sa.getDiagramEdges()['snapshot_available'])
        with patch.object(SDKAdapter, 'topology', side_effect=[normalized, RuntimeError('failed')]):
            with self.assertRaises(RuntimeError):
                self.sa.setInitialConditions(project=model(edges=True))
        self.assertFalse(self.sa.getDiagramEdges()['snapshot_available'])

    def test_edge_branches_cycles_and_component_boundary(self):
        self.sa.connection_snapshot_available = True
        self.sa.connection_components_before = {'a': {'label': 'A'}, 'b': {'label': 'B'}}
        edges = {'e1': ('a', 'b'), 'e2': ('e1', 'e3'), 'e3': ('e2', 'e1'), 'e4': ('b', 'elsewhere')}
        self.sa.connection_edges_before = {k: {'source': {'cell': a}, 'target': {'cell': b}}
                                            for k, (a, b) in edges.items()}
        self.assertEqual({r['key'] for r in self.sa.getDiagramEdges('A')['items']}, {'e1', 'e2', 'e3'})
        self.sa.loadRevision(revision=self.sa.getRevision())
        self.assertFalse(self.sa.getDiagramEdges()['snapshot_available'])

    def test_all_template_defaults_and_metadata_provenance(self):
        library = self.sa.compLib
        metadata = json.loads((ROOT/'references/component-pin-schema.json').read_text(encoding='utf-8'))['templates']
        for key, template in library.items():
            result = full_edit({'operation': 'get_template_schema', 'target': {'template_key': key}}, self.state)
            self.assertEqual({k: v['default'] for k, v in result['parameters'].items()}, template['args'])
            self.assertEqual({k: v['default'] for k, v in result['pins'].items()}, template['pins'])
            for pin, info in metadata[key]['pins'].items():
                for field in ('condition', 'visible', 'connection', 'dim'):
                    if field in info:
                        self.assertEqual(result['pins'][pin][field], info[field])
                if info.get('connection') == 'electrical':
                    self.assertIsNone(result['pins'][pin]['direction'])
            for name, info in metadata[key]['parameters'].items():
                for field, value in info.items():
                    self.assertEqual(result['parameters'][name][field], value)
            if metadata[key].get('status') == 'unavailable':
                self.assertEqual(result['metadata_status'], 'unavailable')
                self.assertIsNone(result['metadata_evidence'])
            else:
                self.assertEqual(result['metadata_evidence']['rid'], template['definition'])
        key = '_newBus_3p'
        self.sa.compLib[key]['definition'] = 'model/example/custom'
        result = full_edit({'operation': 'get_template_schema', 'target': {'template_key': key},
                           'options': {'fields': ['VBase']}}, self.state)
        self.assertEqual(result['metadata_status'], 'definition_mismatch')
        self.assertEqual(set(result['parameters']), {'VBase'})
        self.assertIsNone(result['parameters']['VBase']['unit'])

    def test_conditional_pins_and_expression_are_not_blocked_by_metadata(self):
        request = {'operation': 'create', 'target': {'template_key': '_newTransformer_3p2w',
                    'canvas': 'canvas_0'}, 'changes': {'pins': {'4': 'GND', '5': 'GND'},
                    'args': {'YD1': {'source': 'connection_mode'}}}}
        preview = full_edit(request, self.state)
        result = full_edit({'operation': 'create', 'preview_id': preview['preview_id'],
                            'confirmation': 'execute'}, self.state)
        self.assertEqual(result['changed']['pins']['4'], 'GND')
        self.assertEqual(result['changed']['args']['YD1']['source'], 'connection_mode')


if __name__ == '__main__':
    unittest.main(verbosity=2)
