"""Step-three boundaries and real-LLM batch scenarios on an offline fixture."""
import copy
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from contextlib import ExitStack
from datetime import datetime

from verify_agent_modeling import host, fixture, ROOT, SKILL
import cloudpss


def main(dialogue=False, quality=False):
    out = ROOT / 'testing/runs' / ('step3-finish-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True)
    secrets = [os.getenv(k, '') for k in ('LLM_API_KEY','SIMSTUDIO_TOKEN','CLOUDPSS_TOKEN')]
    def clean(value):
        text = json.dumps(value, ensure_ascii=False, default=str)
        for value in secrets:
            if value: text = text.replace(value, '[REDACTED]')
        return text
    def save(name, value): (out / name).write_text(clean(value), encoding='utf-8')
    discovered = host.discover_skills(ROOT / 'skills')
    runtime = next(d.runtime for d in discovered if d.name == SKILL)
    host.WORKFLOW_STATE = host.WorkflowState()
    model = fixture()
    library = json.loads((ROOT/'skills'/SKILL/'saSource.json').read_text(encoding='utf-8'))
    for i, name in enumerate(['常量甲','常量乙','常量丙','参考常量']):
        comp = copy.deepcopy(library['_newConstant'])
        comp.update(id=f'constant{i}', label=name, canvas='canvas_0', pins={'0': f'signal{i}'})
        comp['args'].update(Name=name, Value=str([1,2,3,42][i]))
        model.getAllComponents()[comp['id']] = cloudpss.model.implements.component.Component(comp)
    state = {'original_rid': model.rid, 'memory_model': model}
    host.WORKFLOW_STATE.skill_sessions[SKILL] = state
    executor = host.DynamicSkillExecutor(ROOT/'skills', discovered)
    def invoke(request, entry='edit_model_from_context'):
        obs = executor(host.DynamicSkillAction(skill=SKILL, entrypoint=entry, request=request))
        return json.loads(''.join(x.get('text','') for x in obs.model_dump(mode='json')['content']))
    def values():
        return [float(model.getAllComponents()[f'constant{i}'].args['Value']) for i in range(4)]
    with ExitStack() as stack:
        for cls, method in [(cloudpss.Model,x) for x in ('fetch','create','update','save')] + [
            (cloudpss.ModelRevision,'create'), (cloudpss.ModelRevision,'run'), (cloudpss.ModelTopology,'fetch')]:
            stack.enter_context(patch.object(cls, method, side_effect=RuntimeError('Offline fixture: cloud unavailable')))
        if not dialogue:
            baseline = copy.deepcopy(model.toJSON())
            for bad in ({'toolbox': {}}, {'previews': {}}, {'memory_model': {}}, {'result_pages': {}}, {'token':'x'}, {'original_rid':'model/example/other'}):
                result=invoke({'operation':'query','session_state':bad})
                assert 'error' in result, result
                assert model.toJSON()==baseline and state['original_rid']==model.rid
            # Keyword-only and reversed-order signatures, generic Skill, no external configuration.
            def reversed_entry(session_state, *, request):
                session_state['v']=request['v']; return {'v':session_state['v']}
            item=SimpleNamespace(name='keyword-probe',runtime=SimpleNamespace(reversed_from_context=reversed_entry),
                                 entrypoints=('reversed_from_context',))
            other=host.DynamicSkillExecutor(ROOT/'skills',[item])
            obs=other(host.DynamicSkillAction(skill=item.name,entrypoint='reversed_from_context',request={'v':7}))
            assert not obs.is_error
            assert host.WORKFLOW_STATE.skill_sessions[item.name]['v']==7
            comp=model.getAllComponents()['constant0']
            comp.args['Value']='x'*50000
            short=invoke({'operation':'query','target':{'key':'constant0'},'options':{'fields':['Name']}})
            assert short['component']['args']=={'Name':'常量甲'}
            result=invoke({'operation':'query','target':{'key':'constant0'}})
            assert len(json.dumps(result))<12000 and result['result_id']
            text=''; offset=0
            while offset is not None:
                page=invoke({'operation':'read_result','target':{'result_id':result['result_id']},'options':{'offset':offset}})
                text+=page['text']; offset=page['next_offset']
            assert json.loads(text)['component']['args']['Value']=='x'*50000
            assert comp.args['Value']=='x'*50000
            comp.args['Value']='1'
            p=invoke({'operation':'update','target':{'key':'constant0'},'changes':{'args':{'Value':'9'}}})
            assert p['preview']['before']['args']=={'Value':'1'}
            assert p['preview']['component']['args']=={'Value':'9'}
            assert p['preview']['component']['pins']=={}
            invoke({'operation':'cancel_preview','preview_id':p['preview_id']})
            # Partial batch: first succeeds, middle fails, last is deliberately not dispatched.
            completed=[]
            for key in ['constant0','missing','constant2']:
                p=invoke({'operation':'update','target':{'key':key},'changes':{'args':{'Value':'9'}}})
                if 'error' in p: break
                result=invoke({'operation':'update','confirmation':'execute','preview_id':p['preview_id']})
                assert result['status']=='changed'; completed.append(key)
            assert completed==['constant0'] and values()==[9,2,3,42]
            save('result.json',{'passed':True,'checks':['session input rejection','keyword-only reversed signature',
                 'field selection','50000-character lossless retrieval','partial batch stop'], 'cloud_saved':False})
            print(out, 'offline checks passed'); return
        from openhands.sdk import Conversation
        from openhands.sdk.conversation.response_utils import get_agent_final_response
        os.environ.setdefault('SIMSTUDIO_TOKEN','offline-fixture')
        os.environ.setdefault('CLOUDPSS_API_URL','https://cloudpss.net/')
        messages=[
            '在 model/example/offline 里只查常量甲、乙、丙的值，不用展开全部参数。',
            '把常量甲、乙、丙的值都改成10，先给我整体方案。',
            '确认这三个都改成10，其他参数和接线不动。',
            '再把它们的值分别改成11、22、33，先看方案。',
            '确认按11、22、33分别修改。',
            '让这三个常量的数值和参考常量一致，你自己读取参考值，名称和接线保持各自原样，先给方案。',
            '确认照参考常量修改这三个的值。',
            '按顺序把常量甲、常量乙、常量丙的值改成7、8、9，先给我方案。',
            '确认按这个顺序修改，如果中途失败就停下，告诉我哪些完成、哪些没完成。',
        ]
        if quality:
            messages=[
                '在 model/example/offline 的Main画布上加一个常量，标签叫新常量，值设为5，先给方案。',
                '确认按方案新增。',
                '这次到底做了哪些验证？模型保存了吗？',
            ]
        turns=[]; inject_failure=False
        original=runtime.edit_model_from_context
        def failing(request, session_state):
            nonlocal inject_failure
            if inject_failure and isinstance(request,dict) and request.get('confirmation') in {'execute','确认执行','confirm','confirmed','确认'}:
                pending=session_state.get('previews',{}).get(request.get('preview_id'),{})
                req=pending.get('request')
                if req and req.operation=='update':
                    target=req.target.get('identifier') or req.target.get('key') or req.target.get('label')
                    if session_state['toolbox']._resolve_comp_key(target)=='constant1':
                        raise RuntimeError('第二项修改失败：测试夹具模拟执行服务异常，请停止后续项并报告已提交项')
            return original(request,session_state)
        stack.enter_context(patch.object(runtime,'edit_model_from_context',new=failing))
        # Preserve introspection, since dispatcher injects sessions by declared signature.
        import inspect
        runtime.edit_model_from_context.__signature__=inspect.signature(original)
        def event(e):
            with (out/'events.jsonl').open('a',encoding='utf-8') as f: f.write(clean(e.model_dump(mode='json'))+'\n')
        conv=Conversation(agent=host.create_agent(skills_dir=ROOT/'skills'),workspace=ROOT,callbacks=[event],
                          visualizer=None,max_iteration_per_run=25)
        try:
            for i,msg in enumerate(messages):
                before=copy.deepcopy(model.toJSON()); inject_failure=i==8 and not quality
                host.WORKFLOW_STATE.begin_turn(); conv.send_message(msg); conv.run()
                reply=get_agent_final_response(list(conv.state.events)) or ''
                turns.append({'user':msg,'assistant':reply,'characters':len(reply)})
                save('turns.json',turns); save(f'snapshot-{i}.json',model.toJSON())
                if quality:
                    if i != 1: assert before==model.toJSON()
                    if i >= 1:
                        matches=[c for c in model.getAllComponents().values() if getattr(c,'label',None)=='新常量']
                        assert len(matches)==1 and float(matches[0].args['Value'])==5
                    print(f'Quality turn {i+1}/3 passed ({len(reply)} characters)',flush=True)
                    continue
                if i in (0,1,3,5,7): assert before==model.toJSON(), f'Unexpected mutation turn {i}'
                expected={2:[10,10,10,42],4:[11,22,33,42],6:[42,42,42,42],8:[7,42,42,42]}
                if i in expected: assert values()==expected[i], (i,values())
                for j,name in enumerate(['常量甲','常量乙','常量丙','参考常量']):
                    c=model.getAllComponents()[f'constant{j}']; assert c.label==name and c.args['Name']==name and c.pins=={'0':f'signal{j}'}
                print(f'Turn {i+1}/{len(messages)} passed ({len(reply)} characters)',flush=True)
            save('result.json',{'passed':True,'model_backend':'offline SDK fixture','llm':os.getenv('LLM_MODEL'),
                               'max_reply_characters':max(t['characters'] for t in turns),'cloud_saved':False})
        except Exception as exc:
            save('result.json',{'passed':False,'error':str(exc),'completed_turns':len(turns)})
            raise
        finally: conv.close()
        print(out)


if __name__=='__main__': main('--dialogue' in sys.argv, '--quality' in sys.argv)
