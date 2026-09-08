"""Initialization rollback, no-edge fast path and real-cloud topology audit."""
import copy
import json
import sys
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/cloudpss-aux-modeling'))
import cloudpss
from mylib import PSAToolbox, edit_model_from_context
from mylib.sdk_adapter import SDKAdapter

fixture=json.loads((ROOT/'testing/runs/step4-live-20260908-114831/model-00.json').read_text(encoding='utf-8'))
def small():
    d=copy.deepcopy(fixture)
    d['revision']['implements']['diagram']['cells']={
        'a':{'id':'a','shape':'diagram-component','definition':'model/CloudPSS/_newBus_3p','label':'a','canvas':'canvas_0','args':{},'pins':{'0':'bus'}},
        'b':{'id':'b','shape':'diagram-component','definition':'model/CloudPSS/_newExpLoad_3p','label':'b','canvas':'canvas_0','args':{},'pins':{'0':''}},
        'e':{'id':'e','shape':'diagram-edge','source':{'cell':'a','port':'0'},'target':{'cell':'b','port':'0'}},
    }
    return cloudpss.Model(d)

def topo(a='1',b='1'):
    return {'revision_hash':'test','topology':{'components':{'/a':{'pins':{'0':a}},'/b':{'pins':{'0':b}}}},'component_count':2}

with patch.object(SDKAdapter,'configure'):
    for outcome in [RuntimeError('network down'),topo('1','2')]:
        model=small(); before=copy.deepcopy(model.toJSON()); s={'original_rid':model.rid,'memory_model':model}
        with patch.object(SDKAdapter,'topology',side_effect=[topo(),outcome]):
            try: edit_model_from_context({'operation':'initialize'},s)
            except (ValueError,RuntimeError): pass
            else: raise AssertionError('Failed conversion accepted')
        assert model.toJSON()==before and 'toolbox' not in s
    model=small()
    with patch.object(SDKAdapter,'topology',side_effect=[topo(),topo('98','98')]):
        s={'original_rid':model.rid,'memory_model':model}
        result=edit_model_from_context({'operation':'initialize'},s)
    assert result['connection_audit']['status']=='topology_equivalent'
    assert model.getAllComponents()['b'].pins['0']=='bus'
    assert 'e' not in model.getAllComponents()
    with patch.object(SDKAdapter,'topology',side_effect=AssertionError('No-edge model must not call topology')):
        edit_model_from_context({'operation':'initialize'},{'original_rid':model.rid,'memory_model':model})
print('Offline pin initialization rollback and equivalence passed')

if '--live' in sys.argv:
    import os
    from datetime import datetime
    cloudpss.setToken(os.environ['SIMSTUDIO_TOKEN'])
    out=ROOT/'testing/runs'/('pin-initialization-'+datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir(parents=True)
    rid='model/Makinohara_Shoko/IEEE39-test1'
    before=cloudpss.Model.fetch(rid).toJSON()
    s={'original_rid':rid}
    with patch.object(cloudpss.Model,'create',side_effect=AssertionError('No model save')), patch.object(cloudpss.Model,'save',side_effect=AssertionError('No model save')), patch.object(cloudpss.Model,'update',side_effect=AssertionError('No model update')):
        result=edit_model_from_context({'operation':'initialize'},s)
    sa=s['toolbox']; after=sa.project.toJSON()
    cloud_after=cloudpss.Model.fetch(rid).toJSON()
    assert cloud_after==before
    assert not any(c.get('shape')=='diagram-edge' for c in after['revision']['implements']['diagram']['cells'].values())
    for name,value in [('source.json',before),('converted.json',after),('audit.json',result['connection_audit']),('topology-after.json',sa.topo),('original-edges.json',sa.connection_edges_before),('result.json',{'passed':True,'source_unchanged':True,'cloud_saved':False,'simulation_run':False})]:
        (out/name).write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
    print('LIVE_PIN_INITIALIZATION_PASSED',out,json.dumps(result['connection_audit']))
