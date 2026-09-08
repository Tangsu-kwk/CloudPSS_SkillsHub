"""Authorized real Agent save acceptance, using the retained Bus13 snapshot.

Explicit CLI target required. Only one create call is allowed; never update/save
or simulate. A failed/uncertain create is not retried by this harness.
"""
import argparse
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
SNAPSHOT = ROOT/'testing/runs/step4-live-20260908-115754/model-01.json'
BASELINE = ROOT/'testing/runs/step4-live-20260908-114831/model-00.json'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', required=True)
    args = parser.parse_args()
    target = args.target
    assert target.startswith('model/Makinohara_Shoko/test1-autotest')
    out = ROOT/'testing/runs'/('step4-save-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True)
    secrets = [os.getenv(k, '') for k in ('LLM_API_KEY', 'SIMSTUDIO_TOKEN', 'CLOUDPSS_TOKEN')]

    def clean(value):
        text = json.dumps(value, ensure_ascii=False, default=str)
        for secret in secrets:
            if secret:
                text = text.replace(secret, '[REDACTED]')
        return text

    def save(name, value):
        (out/name).write_text(clean(value), encoding='utf-8')

    def event(e):
        with (out/'events.jsonl').open('a', encoding='utf-8') as f:
            f.write(clean(e.model_dump(mode='json'))+'\n')

    expected = json.loads(SNAPSHOT.read_text(encoding='utf-8'))
    baseline = json.loads(BASELINE.read_text(encoding='utf-8'))
    cells = expected['revision']['implements']['diagram']['cells']
    base_cells = baseline['revision']['implements']['diagram']['cells']
    assert len(cells) == len(base_cells)+5
    assert all(cells.get(k) == v for k, v in base_cells.items())
    assert cells['_NewVoltageMeter_1']['pins']['0'] == 'bus13'
    cloudpss.setToken(os.environ['SIMSTUDIO_TOKEN'].strip())
    source_before = cloudpss.Model.fetch(SOURCE).toJSON()
    save('source-before.json', source_before)
    assert source_before['revision'] == baseline['revision'], 'Source changed since checkpoint'
    host.WORKFLOW_STATE = host.WorkflowState()
    host.WORKFLOW_STATE.skill_sessions[SKILL] = {
        'original_rid': SOURCE, 'memory_model': cloudpss.Model(copy.deepcopy(expected))}
    save('provenance.json', {'snapshot':str(SNAPSHOT), 'target_rid':target,
                            'authorization':'User chose target and current proposed Bus13 version',
                            'signal_name':'step4_bus12_voltage', 'restored_host_snapshot':True})
    save('expected-model.json', expected)
    created = []
    original_create = cloudpss.Model.create
    create_enabled = False

    def guarded_create(model, **kwargs):
        assert create_enabled, 'Preview phase may not save'
        assert not created, 'Only one create attempt; inspect outcome before retry'
        assert model.rid == target, 'Unauthorized target'
        data = model.toJSON()
        assert data['revision'] == expected['revision'], 'Unexpected revision to save'
        assert data['configs'] == expected['configs'] and data['jobs'] == expected['jobs']
        created.append(target)
        save('create-attempt.json', {'target_rid':target, 'attempt':1})
        response = original_create(model, **kwargs)
        save('create-response.json', response)
        return response

    turns = []
    print('OUTPUT', out, flush=True)
    with ExitStack() as stack:
        for cls, name in [(cloudpss.Model, 'save'), (cloudpss.Model, 'update'), (cloudpss.ModelRevision, 'run')]:
            stack.enter_context(patch.object(cls, name, side_effect=RuntimeError('Only creating the authorized new RID is allowed')))
        stack.enter_context(patch.object(cloudpss.Model, 'create', side_effect=guarded_create))
        conv = Conversation(agent=host.create_agent(skills_dir=ROOT/'skills', prompt_path=ROOT/'new-system-promptv2.0.md'),
                            workspace=ROOT, callbacks=[event], visualizer=None, max_iteration_per_run=15)
        try:
            messages = [
                f'把当前工作区的模型另存为 {target}，名称叫 test1-autotest-bus13。采用目前的方案：三个常量值都是42，四步电压表接Bus13，保留四步电压输出通道及现有信号名 step4_bus12_voltage。不要重新加载原模型或修改其他内容。先查一下这五个对象，然后给保存预览，不运行仿真。',
                f'确认按刚才的预览，把当前这份修改后的模型保存到新RID {target}。只创建新模型，不能覆盖原模型；保存后从云端重新读取核对，不运行仿真。',
            ]
            for i, msg in enumerate(messages):
                create_enabled = i == 1
                host.WORKFLOW_STATE.begin_turn()
                conv.send_message(msg)
                conv.run()
                reply = get_agent_final_response(list(conv.state.events)) or ''
                turns.append({'user':msg, 'assistant':reply})
                save('turns.json', turns)
                session = host.WORKFLOW_STATE.skill_sessions[SKILL]
                # Before saving the source revision must remain byte-for-byte
                # identical. After the Agent performs the requested readback,
                # it may legitimately rebind the session to the new RID; in
                # that case compare the saved model payload instead of rid.
                current = session['memory_model'].toJSON()
                if i == 0:
                    assert current == expected, 'Preview changed working revision'
                else:
                    assert session.get('original_rid') == target, 'Save readback did not switch to target RID'
                    for field in ('revision', 'configs', 'jobs', 'context'):
                        assert current[field] == expected[field], f'Save readback changed {field}'
                if i == 0:
                    previews = [p for p in session.get('previews', {}).values()
                                if p['operation']=='saveProject' and p['plan']['new_rid']==target]
                    assert len(previews)==1, 'Expected exactly one target save preview'
                    save('save-preview.json', previews[0]['plan'])
                print(f'TURN {i+1}/2 complete', flush=True)
            assert created == [target], 'Agent did not attempt authorized create'
            loaded = cloudpss.Model.fetch(target).toJSON()
            save('target-cloud-readback.json', loaded)
            assert loaded['rid'] == target
            for key in ('implements',):
                assert loaded['revision'][key] == expected['revision'][key], 'Saved model differs'
            for key in ('configs', 'jobs', 'context'):
                assert loaded[key] == expected[key], f'Saved {key} differs'
            source_after = cloudpss.Model.fetch(SOURCE).toJSON()
            save('source-after.json', source_after)
            assert source_after == source_before, 'Source cloud model changed'
            save('result.json', {'passed':True, 'saved_rid':target, 'saved_to_cloud':True,
                                'readback_verified':True, 'source_unchanged':True,
                                'simulation_run':False, 'turns':len(turns)})
            print('SAVE_ACCEPTANCE_PASSED', flush=True)
        except Exception as exc:
            save('result.json', {'passed':False, 'target_rid':target, 'create_attempts':len(created),
                                'error':str(exc), 'simulation_run':False})
            print('TEST_STOP', type(exc).__name__, clean(str(exc)), flush=True)
        finally:
            conv.close()


if __name__ == '__main__':
    main()
