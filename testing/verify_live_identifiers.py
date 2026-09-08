"""Regression from real naming conventions without CloudPSS requests."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/cloudpss-aux-modeling'))
import cloudpss
from mylib import edit_model_from_context as edit

def component(name, label, key):
    return {'id':key, 'label':label, 'args':{'Name':name}, 'pins':{'0':name},
            'shape':'diagram-component','definition':'model/CloudPSS/_newBus_3p','canvas':'canvas_0'}

model=cloudpss.Model({'rid':'model/example/regression','revision':{'version':5,'implements':{'diagram':{
    'canvas':[{'key':'canvas_0','name':'Main'}], 'cells':{'bus_key':component('bus12','newBus_3p-38','bus_key')}}}}})
state={'memory_model':model}
assert edit({'operation':'query','target':{'identifier':'Bus12'}},state)['component']['key']=='bus_key'
assert edit({'operation':'query'},state)['components'][0]['name']=='bus12'
model.getAllComponents()['second']=state['toolbox'].adapter.component(component('BUS12','other','second'))
assert edit({'operation':'query','target':{'identifier':'bus12'}},state)['component']['key']=='bus_key'
for request in ({'operation':'query','target':{'identifier':'bUs12'}},
                {'operation':'query','target':{'definition':'diagram-edge'}}):
    try: edit(request,state)
    except ValueError: pass
    else: raise AssertionError('Invalid/ambiguous query accepted')
print('Live identifier regression passed')
