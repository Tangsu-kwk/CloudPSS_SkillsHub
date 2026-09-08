"""Real Agent business acceptance. Harness observes; only Agent edits/saves.

Unique run-scoped RIDs, exact payload verification, create-only write guards,
events, previews, dialogues, snapshots and per-task failures are retained.
"""
import copy
import json
import os
import sys
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('OPENHANDS_SUPPRESS_BANNER', '1')
import cloudpss
import newagentv2 as host
from openhands.sdk import Conversation
from openhands.sdk.conversation.response_utils import get_agent_final_response

SOURCE = 'model/Makinohara_Shoko/IEEE39-test1'
SKILL = 'cloudpss-aux-modeling'


def cells(model):
    return model['revision']['implements']['diagram']['cells']


def val(x):
    return x.get('source') if isinstance(x, dict) else x


CASES = [
    dict(key='feeder', title='母线—线路—负荷支路',
         request='我想在 Bus16 引出一条新支路：新母线叫任务母线，节点名 qa_feeder，电压等级500 kV、60 Hz；一条三相传输线叫任务线路，连接 Bus16 和新母线，长10 km、基准500 kV、60 Hz，其他线路参数暂用模板值；新母线上接三相静态负荷任务负荷，有功5 MW、无功1 Mvar、额定500 kV、60 Hz。母线电压初值1标幺，其他参数用模板值。这轮验证接入结构，暂不评估线路参数的工程适用性。',
         expected={'任务母线':('_newBus_3p',{'Name':'qa_feeder','VBase':500,'Freq':60}), '任务线路':('TransmissionLine',{'Length':10,'Vbase':500,'Freq':60}), '任务负荷':('_newExpLoad_3p',{'p':5,'q':1,'v':500,'f':60})},
         nets=[('任务母线','0','qa_feeder'),('任务负荷','0','qa_feeder')],
         update='把任务负荷的有功改为8 MW、无功改为2 Mvar，并把任务线路长度改为12 km，接线保持不变。',
         updated={'任务负荷':{'p':8,'q':2},'任务线路':{'Length':12}}),
    dict(key='batch-load', title='批量负荷与参照参数修改',
         request='在 Bus16 接入三个三相静态负荷，标签叫批量负荷甲、批量负荷乙、参考负荷。有功分别为2、3、4 MW，无功分别为0.5、0.6、0.8 Mvar，额定电压500 kV、频率60 Hz，其余参数保持模板值。',
         expected={name:('_newExpLoad_3p',{'p':p,'q':q,'v':500,'f':60}) for name,p,q in [('批量负荷甲',2,.5),('批量负荷乙',3,.6),('参考负荷',4,.8)]},
         nets=[(name,'0','bus16') for name in ['批量负荷甲','批量负荷乙','参考负荷']],
         update='把批量负荷甲和批量负荷乙的有功、无功都设成和参考负荷一致，你先读取参考值。各自标签和接线不变。',
         updated={'批量负荷甲':{'p':4,'q':.8},'批量负荷乙':{'p':4,'q':.8}}),
    dict(key='transformer', title='变压器两侧母线接线',
         request='建立一个独立的变压器接线练习区：高压母线标签练习高压母线、节点 qa_hv，500 kV；低压母线标签练习低压母线、节点 qa_lv，110 kV。两母线都是60 Hz、1标幺。放置三相双绕组变压器练习变压器，容量100 MVA、一次侧500 kV、二次侧110 kV、60 Hz，其他参数采用模板值。请查询变压器端子含义后，把一次、二次三相端子分别接到两母线；需要的中性点连接应说明。暂不接入现有电网，也不仿真。',
         expected={'练习高压母线':('_newBus_3p',{'VBase':500,'Name':'qa_hv'}),'练习低压母线':('_newBus_3p',{'VBase':110,'Name':'qa_lv'}),'练习变压器':('_newTransformer_3p2w',{'Tmva':100,'V1':500,'V2':110,'f':60})},
         nets=[('练习高压母线','0','qa_hv'),('练习低压母线','0','qa_lv')],
         update='把练习变压器容量改为120 MVA，保持电压等级、接线和母线参数不变。', updated={'练习变压器':{'Tmva':120}}),
    dict(key='control', title='常量—增益—输出通道及取消修改',
         request='帮我做一个控制信号小练习：常量标签练习常量、输出值2，送入增益模块练习增益，增益3；增益输出送到输出通道练习通道，通道名称 qa_control、维度1、采样率1000 Hz。常量到增益的信号名 qa_input，增益到通道的信号名 qa_output。请查询各模块端子后接线，不增加电气设备。',
         expected={'练习常量':('_newConstant',{'Value':2}),'练习增益':('_newGain',{'G':3}),'练习通道':('_newChannel',{'Name':'qa_control','Dim':1,'Freq':1000})},
         nets=[('练习常量','0','qa_input'),('练习通道','0','qa_output')],
         update='把练习常量输出值改为4，练习增益改为2，其他设置和接线保持不变。', updated={'练习常量':{'Value':4},'练习增益':{'G':2}}),
    dict(key='fault', title='新增故障、缺失通道与短路分析衔接',
         request='在 Bus16 增加三相接地短路，标签和名称均为任务故障，3秒发生、3.1秒切除，初始电阻1000000000欧姆、故障电阻1欧姆。请查询故障类型和端子含义，正确接到母线与地。先只完成故障建模，电流记录通道等分析时检查需求再配。保留已有故障和原有接线。',
         expected={'任务故障':('_newFaultResistor_3p',{'Name':'任务故障','ft':7,'fs':3,'fe':3.1,'chg':1})}, nets=[],
         update='把任务故障切除时间改到3.2秒，其余参数不变。', updated={'任务故障':{'fe':3.2}}),
]


def main():
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    root = ROOT/'testing/runs'/('business-'+stamp)
    root.mkdir(parents=True)
    print('OUTPUT',root,flush=True)
    cloudpss.setToken(os.environ['SIMSTUDIO_TOKEN'].strip())
    secrets = [os.getenv(k,'') for k in ['LLM_API_KEY','SIMSTUDIO_TOKEN','CLOUDPSS_TOKEN']]
    def serialize(v):
        text=json.dumps(v,ensure_ascii=False,default=str,indent=2)
        for secret in secrets:
            if secret: text=text.replace(secret,'[REDACTED]')
        return text
    rows=[]
    for case in CASES:
        out=root/case['key']; out.mkdir()
        def save(name,data): (out/name).write_text(serialize(data),encoding='utf-8')
        def event(e):
            with (out/'events.jsonl').open('a',encoding='utf-8') as f:
                f.write(serialize(e.model_dump(mode='json')).replace('\n','')+'\n')
        turns=[]; attempts=[]; allowed={}; current_phase='initialization'; conv=None
        row={'task':case['title'],'key':case['key'],'status':'running','evidence':str(out),'cloud_saves':[]}
        host.WORKFLOW_STATE=host.WorkflowState()
        def state(): return host.WORKFLOW_STATE.skill_sessions.get(SKILL,{})
        def snapshot(): return copy.deepcopy(state()['memory_model'].toJSON())
        def turn(msg):
            before=snapshot() if state().get('memory_model') else None
            host.WORKFLOW_STATE.begin_turn(); conv.send_message(msg); conv.run()
            reply=get_agent_final_response(list(conv.state.events)) or ''
            turns.append({'phase':current_phase,'user':msg,'assistant':reply})
            save('turns.json',turns)
            data=snapshot(); save(f'model-{len(turns):02}.json',data)
            sa=state().get('toolbox')
            if sa and sa.topo is not None: save(f'topology-{len(turns):02}.json',sa.topo)
            previews={k:{'operation':v['operation'],'plan':v['plan']} for k,v in state().get('previews',{}).items()}
            save(f'previews-{len(turns):02}.json',previews)
            print('TURN',case['key'],len(turns),current_phase,flush=True)
            assert reply, 'Agent returned no final response'
            # Baseline objects cannot be edited as a side effect of these tasks.
            assert all(cells(data).get(k)==v for k,v in cells(baseline).items()), 'Original component/edge changed'
            return before,data
        def by_label(data,label):
            found=[v for v in cells(data).values() if v.get('label')==label]
            assert len(found)==1, f'Expected exactly one {label}; found {len(found)}'
            return found[0]
        def check(data,updated=False):
            for label,(template,args) in case['expected'].items():
                obj=by_label(data,label)
                assert obj['definition']=='model/CloudPSS/'+template, f'{label}: wrong template'
                expected={**args,**(case['updated'].get(label,{}) if updated else {})}
                for k,v in expected.items():
                    actual=val(obj['args'].get(k))
                    if isinstance(v,(int,float)): assert actual is not None and abs(float(actual)-v)<1e-8, f'{label}.{k}: {actual} != {v}'
                    else: assert actual==v, f'{label}.{k}: {actual} != {v}'
            for label,pin,net in case['nets']:
                assert by_label(data,label)['pins'].get(pin)==net, f'{label}: pin {pin} does not connect {net}'
            if case['key']=='feeder':
                assert set(by_label(data,'任务线路')['pins'].values())=={'bus16','qa_feeder'}, 'Feeder endpoints wrong'
            if case['key']=='control':
                assert set(by_label(data,'练习增益')['pins'].values())=={'qa_input','qa_output'}, 'Gain input/output network wrong'
            if case['key']=='transformer':
                pins=by_label(data,'练习变压器')['pins']
                assert 'qa_hv' in pins.values() and 'qa_lv' in pins.values(), 'Transformer sides not connected'
        original_create=cloudpss.Model.create
        def create(model,**kwargs):
            assert model.rid in allowed, 'Create target has no audited preview'
            assert model.rid not in attempts, 'No automatic create retry'
            expected=allowed[model.rid]
            data=model.toJSON()
            for field in ['implements','parameters','pins']:
                assert data['revision'].get(field)==expected['revision'].get(field), 'Create revision differs from preview'
            assert data['configs']==expected['configs'] and data['jobs']==expected['jobs']
            attempts.append(model.rid); save('create-attempts.json',attempts)
            response=original_create(model,**kwargs); save(f'create-response-{len(attempts)}.json',response)
            return response
        def save_stage(suffix):
            nonlocal current_phase
            current_phase='save-'+suffix
            rid=f'model/Makinohara_Shoko/test1-autotest-{stamp}-{case["key"]}-{suffix}'
            expected=snapshot()
            before,after=turn(f'将当前版本另存到新 RID {rid}，名称为 {case["key"]}-{suffix}。只创建新副本，先给保存预览，不运行仿真。')
            assert before==after, 'Save preview mutated model'
            plans=[v for v in state().get('previews',{}).values() if v['operation']=='saveProject' and v['plan']['new_rid']==rid]
            assert len(plans)==1, 'Save preview missing'
            allowed[rid]=expected
            turn(f'确认按刚才的预览保存到 {rid}，请云端回读；继续保留当前工作内容，不覆盖已有模型。')
            assert rid in attempts, 'No create call'
            loaded=cloudpss.Model.fetch(rid).toJSON(); save(suffix+'-cloud.json',loaded)
            assert loaded['rid']==rid
            for field in ['implements','parameters','pins']:
                assert loaded['revision'].get(field)==expected['revision'].get(field), 'Cloud revision mismatch'
            assert loaded['configs']==expected['configs'] and loaded['jobs']==expected['jobs']
            row['cloud_saves'].append(rid)
            return rid
        try:
            baseline=cloudpss.Model.fetch(SOURCE).toJSON(); save('source-before.json',baseline)
            with ExitStack() as stack:
                stack.enter_context(patch.object(cloudpss.Model,'create',side_effect=create))
                for method in ['save','update']:
                    stack.enter_context(patch.object(cloudpss.Model,method,side_effect=RuntimeError('Test permits new RID create only')))
                # Structural cases do not request EMT; the fault case may call analysis.
                if case['key']!='fault':
                    stack.enter_context(patch.object(cloudpss.ModelRevision,'run',side_effect=RuntimeError('No simulation requested in this structural task')))
                conv=Conversation(agent=host.create_agent(skills_dir=ROOT/'skills',prompt_path=ROOT/'new-system-promptv2.0.md'),workspace=ROOT,callbacks=[event],visualizer=None,max_iteration_per_run=25)
                current_phase='create-preview'
                turn(f'请使用 {SOURCE}。'+case['request']+' 原有设备和图形连线不变。先给完整方案，暂不执行、不保存，也不调用报告生成。')
                assert snapshot()==baseline,'Create preview changed model'
                current_phase='create-confirm'
                turn('确认刚才符合上述要求的整体方案，逐项创建并接线，回读实际参数和连接节点，刷新拓扑；暂不保存。如果端子含义无法核实，请明确说明，不要猜接。')
                check(snapshot()); row['create']='verified'
                current_phase='update-preview'
                before,after=turn(case['update']+'先给修改方案，暂不执行。')
                assert before==after,'Update preview changed model'
                current_phase='update-confirm'; turn('确认修改，回读刚才指定的参数，刷新拓扑。')
                check(snapshot(),True); row['update']='verified'
                sa=state()['toolbox']; assert sa.topo is not None,'No topology result'
                row['topology']='refreshed_not_physical_validation'
                rid=save_stage('edited'); row['edited_cloud']='verified'
                if case['key']=='fault':
                    current_phase='short-circuit'
                    turn(f'请对 {rid} 中的任务故障进行短路电流分析，目标是3秒开始的这个新增故障。已有故障保留，我理解它仍影响整个场景。如果缺少记录电流的通道，请先告诉我需要补什么，不要选其他支路电流代替，也不要生成报告。')
                    save('analysis-public.json',host.WORKFLOW_STATE.__dict__)
                    row['analysis']='inspect_record_for_readiness_or_result'
                    # Analysis follow-ups are reviewed interactively, never assume a missing-channel plan.
                else:
                    current_phase='boundary-preview'
                    label=next(iter(case['expected']))
                    before,after=turn(f'把“{label}”的标签改成“临时取消标签”，先让我看看方案，暂不改。')
                    assert before==after
                    before,after=turn('这个改名先不要了，取消刚才的方案，查看确认标签仍然保持原来的。')
                    assert before==after; row['cancel']='verified'
                current_phase='delete-preview'
                added=[v.get('label') for k,v in cells(snapshot()).items() if k not in cells(baseline) and v.get('definition')]
                before,after=turn('删除本次新增的这些对象：'+ '、'.join(added)+'。只删除这次新增的对象和它们自己的连接，保留原模型。先给删除影响。')
                assert before==after
                current_phase='delete-confirm'; turn('确认按上述范围删除，检查已删除，并刷新拓扑。')
                assert cells(snapshot())==cells(baseline),'Deletion did not restore source cells'
                row['delete']='verified'; save_stage('deleted')
                row['status']='structural_pass' if case['key']!='fault' else 'structural_pass_analysis_pending_review'
        except Exception as exc:
            row.update(status='failed_or_blocked',phase=current_phase,error=str(exc))
            save('failure.json',row)
            if conv and 'Insufficient Balance' not in str(exc):
                try:
                    current_phase='developer-debug'
                    turn('现在以开发者身份排查：本轮外部核验未通过，原因是 '+str(exc)+ '。请根据已有工具结果解释实际完成到哪一步、缺少什么公开能力。只诊断，不修改模型、不保存、不仿真。')
                except Exception as debug_exc: row['debug_error']=str(debug_exc)
        finally:
            if conv: conv.close()
            try:
                after=cloudpss.Model.fetch(SOURCE).toJSON(); save('source-after.json',after)
                row['source_unchanged']=after==baseline
                if not row['source_unchanged']: row['status']='failed_source_changed'
            except Exception as exc: row['source_audit_error']=str(exc)
            save('result.json',row); rows.append(row)
            (root/'progress.json').write_text(serialize(rows),encoding='utf-8')
            print('CASE_DONE',case['key'],row['status'],flush=True)
        if 'Insufficient Balance' in row.get('error',''): break
    print('BUSINESS_RUN_FINISHED',root,flush=True)


if __name__=='__main__': main()
