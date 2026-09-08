"""Real user-style Agent acceptance; no cloud project save or simulation.

CloudPSS fetch and temporary topology revision calls are real. The harness only
sends user messages and observes snapshots; it never edits the model for Agent.
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

RID = 'model/Makinohara_Shoko/IEEE39-test1'
SKILL = 'cloudpss-aux-modeling'


def main():
    out = ROOT / 'testing/runs' / ('step4-live-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True)
    secrets = [os.getenv(k, '') for k in ('LLM_API_KEY', 'SIMSTUDIO_TOKEN', 'CLOUDPSS_TOKEN')]
    def clean(value):
        text = json.dumps(value, ensure_ascii=False, default=str)
        for secret in secrets:
            if secret: text = text.replace(secret, '[REDACTED]')
        return text
    def save(name, value): (out / name).write_text(clean(value), encoding='utf-8')
    def event(e):
        with (out / 'events.jsonl').open('a', encoding='utf-8') as f:
            f.write(clean(e.model_dump(mode='json')) + '\n')
    messages = [
        f'帮我查看 {RID} 中的 Bus12，只列它的基准电压、频率和连接节点名，再检查当前模型拓扑是否能正常刷新。先不改模型，不保存、不运行仿真。',
        '帮我在主图上新增三个常量，标签分别是四步常量甲、四步常量乙、四步参考常量，值分别是1、2、42，暂时不接线。先给整体方案。',
        '确认按这个方案逐项新增，然后回读并检查拓扑；不要保存云端。',
        '把四步常量甲、四步常量乙的值分别改成10、20，名称和接线不动，先给方案。',
        '确认分别改成10、20，再查一下值。',
        '再把四步常量甲、四步常量乙的数值都改得和四步参考常量一致，你读取参考值，先给方案。',
        '确认按参考数值修改，保留各自的名称和接线。',
        '在 Bus12 上加一个三相电压表，标签叫四步电压表，输出叫 step4_bus12_voltage。先查清连接再给方案。',
        '确认按刚才的电压表方案执行，并检查修改后的拓扑。不要改变原有元件和连线；如果必须改动它们，先告诉我。',
        '把四步电压表改接到 Bus13，先查清连接并给我方案。',
        '确认改接到 Bus13，然后回读并检查拓扑；不要改变原有元件和连线。',
        '删掉本次新增的四步电压表、四步常量甲、四步常量乙、四步参考常量，先列出删除影响。',
        '确认只删除这四个新增元件，保持原模型其他内容不变，再检查拓扑。',
    ]
    turns = []; baseline = None
    host.WORKFLOW_STATE = host.WorkflowState()
    resume = '--resume' in sys.argv
    if resume:
        checkpoint = ROOT / 'testing/runs/step4-live-20260908-114831'
        baseline = json.loads((checkpoint/'model-00.json').read_text(encoding='utf-8'))
        restored = cloudpss.Model(json.loads((checkpoint/'model-08.json').read_text(encoding='utf-8')))
        host.WORKFLOW_STATE.skill_sessions[SKILL] = {'original_rid':RID, 'memory_model':restored}
        save('recovery.json', {'checkpoint':str(checkpoint/'model-08.json'),
                               'mode':'restore previous real-cloud memory revision; not a fresh cloud fetch'})
        messages = [
            f'继续处理 {RID} 当前工作区的四步电压表。只把它从 Bus12 改接到 Bus13，保留测量输出名 step4_bus12_voltage 和已有输出通道，不改其他参数。先查询并给预览。',
            '确认只改电压表接点到 Bus13，输出名保持原样；执行后回读并检查拓扑。',
            '删除本次新增的四步电压表、四步电压输出通道、四步常量甲、四步常量乙、四步参考常量，只删这五个对象，不动原模型内容。先给整体删除方案。',
            '确认删除刚才列出的五个测试对象，然后检查拓扑并核对原模型是否保持不变。不要保存云端。',
        ]
    def session(): return host.WORKFLOW_STATE.skill_sessions.get(SKILL, {})
    def component(label):
        sa = session()['toolbox']
        return sa.getComponentByKey(sa._resolve_comp_key(label))
    def value(label):
        val = component(label).args['Value']
        return float(val.get('source') if isinstance(val, dict) else val)
    with ExitStack() as stack:
        for cls, method in [(cloudpss.Model, n) for n in ('save', 'create', 'update')] + [(cloudpss.ModelRevision, 'run')]:
            stack.enter_context(patch.object(cls, method, side_effect=RuntimeError('This acceptance run does not authorize cloud save or simulation')))
        conv = Conversation(agent=host.create_agent(skills_dir=ROOT/'skills', prompt_path=ROOT/'new-system-promptv2.0.md'), workspace=ROOT, callbacks=[event], visualizer=None,
                            max_iteration_per_run=25)
        print('OUTPUT', out, flush=True)
        try:
            for i, msg in enumerate(messages):
                before = copy.deepcopy(session()['memory_model'].toJSON()) if session().get('memory_model') else None
                host.WORKFLOW_STATE.begin_turn(); conv.send_message(msg); conv.run()
                reply = get_agent_final_response(list(conv.state.events)) or ''
                turns.append({'user': msg, 'assistant': reply})
                save('turns.json', turns)
                model = session().get('memory_model')
                if model is None: raise AssertionError('Agent did not initialize a real model')
                data = model.toJSON(); save(f'model-{i:02}.json', data)
                sa = session()['toolbox']
                if sa.topo is not None: save(f'topology-{i:02}.json', sa.topo)
                if resume:
                    if i in (0,2): assert before==data, 'Preview modified the restored revision'
                    if i==1:
                        meter=component('四步电压表'); bus=component('Bus13')
                        assert meter.pins['0']==bus.pins['0']=='bus13'
                        assert meter.args['V']=='step4_bus12_voltage'
                        assert sa.topo is not None
                        top=sa.topo['components']
                        assert top['/'+meter.id]['pins']['0']==top['/'+bus.id]['pins']['0']
                    base_cells=baseline['revision']['implements']['diagram']['cells']
                    now_cells=data['revision']['implements']['diagram']['cells']
                    assert all(now_cells.get(k)==v for k,v in base_cells.items())
                    if i==3:
                        assert data==baseline, 'Cleanup did not restore baseline'
                        assert sa.topo is not None
                    print(f'RESUME TURN {i+1}/4 passed',flush=True)
                    continue
                if i == 0:
                    baseline = copy.deepcopy(data)
                    assert sa.topo is not None, 'Baseline real topology not obtained'
                    component('Bus12')
                if i in (1,3,5,7,9,11): assert before == data, f'Preview turn {i} modified model'
                if i in (2,4,6):
                    expected = {2:[1,2,42],4:[10,20,42],6:[42,42,42]}[i]
                    assert [value(x) for x in ('四步常量甲','四步常量乙','四步参考常量')] == expected
                if i in (8,10):
                    meter = component('四步电压表'); bus = component('Bus12' if i == 8 else 'Bus13')
                    assert bus.pins['0'] and meter.pins['0'] == bus.pins['0'], 'Named connection did not match bus'
                    assert sa.topo is not None, 'Edited real topology not obtained'
                    top = sa.topo.get('components', {})
                    assert '/' + meter.id in top and '/' + bus.id in top, 'Target absent from platform topology'
                    assert top['/'+meter.id]['pins']['0'] == top['/'+bus.id]['pins']['0'], 'Platform connectivity mismatch'
                original_cells = baseline['revision']['implements']['diagram']['cells']
                current = data['revision']['implements']['diagram']['cells']
                assert all(current.get(k) == v for k,v in original_cells.items()), 'An original model cell changed'
                if i == 12:
                    assert data == baseline, 'Cleanup did not restore baseline model'
                    assert sa.topo is not None
                print(f'TURN {i+1}/{len(messages)} passed', flush=True)
            # Independent read only evidence: persistent source was not overwritten.
            cloud = cloudpss.Model.fetch(RID).toJSON()
            save('source-cloud-after.json', cloud)
            assert cloud['revision'] == baseline['revision'], 'Cloud revision changed during run'
            save('result.json', {'passed':True, 'real_cloud':True, 'turns':len(turns),
                                'source_unchanged':True, 'saved_to_cloud':False, 'simulation_run':False})
        except Exception as exc:
            save('result.json', {'passed':False, 'error':str(exc), 'completed_turns':len(turns),
                                'saved_to_cloud':False, 'simulation_run':False})
            print('TEST_STOP', type(exc).__name__, str(exc), flush=True)
        finally: conv.close()


if __name__ == '__main__': main()
