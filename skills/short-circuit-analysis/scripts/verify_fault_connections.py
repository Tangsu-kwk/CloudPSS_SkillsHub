"""Connection resolver regression; SDK calls mocked, no cloud operations."""
import copy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mylib import runtime as r
from mylib.connection_resolution import current_topology


def fixture():
    cells = {
        'fault': {'definition': 'model/CloudPSS/_newFaultResistor_3p', 'canvas': 'c',
                  'pins': {'0': 'ground', '1': 'bus'}, 'args': {'I': '#I', 'fs': 3, 'fe': 3.2}},
        'bus': {'definition': 'model/CloudPSS/_newBus_3p', 'canvas': 'c',
                'pins': {'0': 'bus'}, 'args': {'Name': 'Bus16', 'VBase': 500}},
        'ground': {'definition': 'model/CloudPSS/GND', 'canvas': 'c', 'pins': {'0': 'ground'}},
    }
    topo = {'components': {'/fault': {'pins': {'0': 0, '1': 8}},
                          '/bus': {'pins': {'0': 8}, 'args': {'VBase': 500}},
                          '/ground': {'pins': {'0': 0}}}}
    return cells, topo


def voltage(cells, topo=None):
    return r._resolve_base_voltage({'revision': {'implements': {'diagram': {'cells': cells}}}},
        cells, {}, {'id': 'fault'}, topology=topo)


class Connections(unittest.TestCase):
    def test_pin_topology_and_voltage_provenance(self):
        c,t=fixture(); before=copy.deepcopy(c)
        v=voltage(c,t)
        self.assertEqual(v['value_kv'],500)
        self.assertEqual(v['connection_basis'],'named_pin_topology')
        self.assertEqual(v['fault_bus_component_ids'],['bus'])
        self.assertEqual(voltage(c)['connection_basis'],'named_pin')
        self.assertEqual(c,before)

    def test_edge_only_branch_and_cycle(self):
        c,t=fixture()
        c['fault']['pins']={'0':'','1':''};c['bus']['pins']={'0':''}
        c['e1']={'shape':'diagram-edge','source':{'cell':'fault','port':'1'},'target':{'cell':'e2'}}
        c['e2']={'shape':'diagram-edge','source':{'cell':'e1'},'target':{'cell':'bus','port':'0'}}
        self.assertEqual(voltage(c)['value_kv'],500)
        self.assertEqual(voltage(c,t)['connection_basis'],'diagram_edge_topology')

    def test_no_traversal_through_line(self):
        c,t=fixture();c['fault']['pins']={'0':'ground','1':'separate'}
        c['line']={'definition':'model/CloudPSS/TransmissionLine','pins':{'0':'separate','1':'bus'}}
        c['e1']={'shape':'diagram-edge','source':{'cell':'fault'},'target':{'cell':'line'}}
        c['e2']={'shape':'diagram-edge','source':{'cell':'line'},'target':{'cell':'bus'}}
        self.assertIsNone(voltage(c)['value_kv'])

    def test_same_name_different_canvas_requires_topology(self):
        c,t=fixture();c['bus']['canvas']='other'
        with self.assertRaises(ValueError):voltage(c)
        t['components']['/bus']['pins']['0']=9
        self.assertIsNone(voltage(c,t)['value_kv'])

    def test_mixed_conflict_and_equivalent_bus_alias(self):
        c,t=fixture();c['second']=copy.deepcopy(c['bus']);c['second']['pins']={'0':'alias'}
        c['e']={'shape':'diagram-edge','source':{'cell':'fault','port':'1'},'target':{'cell':'second','port':'0'}}
        t['components']['/second']={'pins':{'0':8},'args':{'VBase':500}}
        self.assertEqual(voltage(c,t)['fault_bus_component_ids'],['bus','second'])
        t['components']['/second']['pins']['0']=9
        with self.assertRaises(ValueError):voltage(c,t)

    def test_multiple_voltages_and_fault_networks(self):
        c,t=fixture();c['second']=copy.deepcopy(c['bus']);c['second']['args']['VBase']=110
        t['components']['/second']={'pins':{'0':8}}
        with self.assertRaises(ValueError):voltage(c,t)
        c['second']['args']['VBase']=500;c['second']['pins']['0']='second'
        c['fault']['pins']['0']='second';t['components']['/fault']['pins']['0']=9
        t['components']['/second']['pins']['0']=9
        with self.assertRaises(ValueError):voltage(c,t)

    def test_empty_pins_and_unrelated_voltage_not_used(self):
        c,t=fixture();c['fault']['pins']={'0':'','1':''}
        self.assertIsNone(voltage(c)['value_kv'])
        with self.assertRaises(ValueError):
            r._merge_analysis_config({'analysis':{'base_voltage_kv':500}},
                                      {'voltage_resolution':voltage(c)})

    def test_platform_expression_not_locally_evaluated(self):
        c,t=fixture();c['bus']['args']['VBase']={'source':'2*RatedV'}
        v=voltage(c,t)
        self.assertEqual(v['value_kv'],500)
        self.assertTrue(v['source'].startswith('topology.'))
        t['components']['/bus']['args']['VBase']='2*RatedV'
        with self.assertRaises(ValueError):voltage(c,t)

    def test_sdk_config_forms_and_failure_propagation(self):
        for configs,selected in [([{'args':{}}],0),({'main':{'args':{}}},'main')]:
            model=SimpleNamespace(configs=configs,context={'currentConfig':selected},revision={'hash':'original'})
            with patch('cloudpss.ModelRevision.create',return_value={'hash':'temp'}), \
                 patch('cloudpss.ModelTopology.fetch',return_value={'components':{}}) as fetch:
                _,evidence=current_topology(model)
                self.assertEqual(evidence['config'],selected)
                self.assertEqual(fetch.call_args.args[2],configs[selected])
            self.assertEqual(model.revision,{'hash':'original'})
            with patch('cloudpss.ModelRevision.create',side_effect=ValueError('invalid model')):
                with self.assertRaises(ValueError):current_topology(model)


if __name__=='__main__':unittest.main(verbosity=2)
