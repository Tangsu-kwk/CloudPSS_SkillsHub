"""User dialogue retest after automatic edge-to-pin initialization."""
import copy,json,os,sys
from pathlib import Path
from datetime import datetime
from unittest.mock import patch
from contextlib import ExitStack
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.setdefault('OPENHANDS_SUPPRESS_BANNER','1')
import cloudpss,newagentv2 as host
from openhands.sdk import Conversation
from openhands.sdk.conversation.response_utils import get_agent_final_response
out=ROOT/'testing/runs'/('pin-feeder-'+datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir(parents=True)
secrets=[os.getenv(k,'') for k in ['LLM_API_KEY','SIMSTUDIO_TOKEN','CLOUDPSS_TOKEN']]
def save(name,obj):
    s=json.dumps(obj,ensure_ascii=False,default=str)
    for secret in secrets:
        if secret:s=s.replace(secret,'[REDACTED]')
    (out/name).write_text(s,encoding='utf-8')
def event(e):
    s=json.dumps(e.model_dump(mode='json'),ensure_ascii=False,default=str)
    for secret in secrets:
        if secret:s=s.replace(secret,'[REDACTED]')
    with (out/'events.jsonl').open('a',encoding='utf-8') as f:f.write(s+'\n')
rid='model/Makinohara_Shoko/IEEE39-test1'
cloudpss.setToken(os.environ['SIMSTUDIO_TOKEN'])
source=cloudpss.Model.fetch(rid).toJSON();save('source-before.json',source)
host.WORKFLOW_STATE=host.WorkflowState();turns=[]
with ExitStack() as stack:
    for cls,name in [(cloudpss.Model,'save'),(cloudpss.Model,'update'),(cloudpss.Model,'create'),(cloudpss.ModelRevision,'run')]:
        stack.enter_context(patch.object(cls,name,side_effect=RuntimeError('This retest does not save or simulate')))
    conv=Conversation(agent=host.create_agent(skills_dir=ROOT/'skills',prompt_path=ROOT/'new-system-promptv2.0.md'),workspace=ROOT,callbacks=[event],visualizer=None,max_iteration_per_run=22)
    messages=[f'请打开 {rid}，按辅助建模的初始化方式处理，查看 Bus16 的电压等级、频率和连接节点。只看，不新增设备，不保存、不仿真。',
      '从 Bus16 引出一条支路：增加500 kV、60 Hz、1标幺母线，标签验收支路母线、名称 qa_pin_bus；一条三相传输线标签验收支路线路，连接 Bus16 和新母线，长10 km、基准500 kV、60 Hz；在新母线接入三相静态负荷验收支路负荷，有功5 MW、无功1 Mvar、额定500 kV、60 Hz。其他参数保持模板默认，名称未指定的留空。这轮只验收结构。先给方案，不执行。',
      '确认上述整体方案，逐项新增并接线，回读参数和连接节点，刷新拓扑检查支路确实连通。保持初始化后原有设备的参数和连接不变，不保存、不仿真。']
    try:
        for i,msg in enumerate(messages):
            host.WORKFLOW_STATE.begin_turn();conv.send_message(msg);conv.run()
            reply=get_agent_final_response(list(conv.state.events)) or ''
            turns.append({'user':msg,'assistant':reply});save('turns.json',turns)
            s=host.WORKFLOW_STATE.skill_sessions['cloudpss-aux-modeling'];sa=s['toolbox'];d=copy.deepcopy(sa.project.toJSON());save(f'model-{i}.json',d)
            if i==0:
                baseline=d;assert sa.connection_audit['status']=='topology_equivalent'
            if i==1:assert d==baseline,'Preview mutated initialized model'
            print('TURN',i+1,flush=True)
        cs=d['revision']['implements']['diagram']['cells'];base=baseline['revision']['implements']['diagram']['cells']
        assert all(cs.get(k)==v for k,v in base.items())
        def comp(label):return next((k,v) for k,v in cs.items() if v.get('label')==label)
        bk,b=comp('验收支路母线');lk,l=comp('验收支路线路');qk,q=comp('验收支路负荷')
        assert b['pins']['0']=='qa_pin_bus' and q['pins']['0']=='qa_pin_bus'
        assert set(l['pins'].values())=={'qa_pin_bus','bus16'}
        def num(obj,k):
            v=obj['args'][k];return float(v.get('source') if isinstance(v,dict) else v)
        assert num(b,'VBase')==500 and num(l,'Length')==10 and num(q,'p')==5 and num(q,'q')==1
        assert sa.topo is not None;save('topology.json',sa.topo)
        t=sa.topo['components'];assert t['/'+bk]['pins']['0']==t['/'+qk]['pins']['0']
        assert set(t['/'+lk]['pins'].values())=={t['/'+bk]['pins']['0'],t['/canvas_0_113']['pins']['0']}
        after=cloudpss.Model.fetch(rid).toJSON();save('source-after.json',after);assert source==after
        save('result.json',{'passed':True,'pin_connections_verified':True,'platform_topology_verified':True,'source_unchanged':True,'cloud_saved':False,'simulation_run':False})
        print('PIN_FEEDER_PASSED',out,flush=True)
    except Exception as exc:
        save('result.json',{'passed':False,'error':str(exc),'completed_turns':len(turns),'cloud_saved':False,'simulation_run':False});print('RETEST_STOP',str(exc),out,flush=True)
    finally:conv.close()
