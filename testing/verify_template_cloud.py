"""Run one user-style CRUD + create-only cloud save acceptance case."""
import argparse, ast, copy, json, os, sys
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
import cloudpss, newagentv2 as host
from openhands.sdk import Conversation
from openhands.sdk.conversation.response_utils import get_agent_final_response

def main():
 p=argparse.ArgumentParser(); p.add_argument('--template',default='_newConstant'); p.add_argument('--target',required=True); a=p.parse_args()
 cloudpss.setToken(os.environ['SIMSTUDIO_TOKEN'].strip())
 source='model/Makinohara_Shoko/IEEE39-test1'; out=ROOT/'testing/runs'/('template-'+a.template.replace('_','')+'-'+datetime.now().strftime('%Y%m%d-%H%M%S')); out.mkdir(parents=True)
 model=cloudpss.Model.fetch(source); baseline=model.toJSON();
 host.WORKFLOW_STATE=host.WorkflowState(); host.WORKFLOW_STATE.skill_sessions['cloudpss-aux-modeling']={'original_rid':source,'memory_model':model}
 def save(n,v): (out/n).write_text(json.dumps(v,ensure_ascii=False,default=str,indent=2),encoding='utf-8')
 save('source-before.json',baseline)
 conv=Conversation(agent=host.create_agent(skills_dir=ROOT/'skills',prompt_path=ROOT/'new-system-promptv2.0.md'),workspace=ROOT,visualizer=None,max_iteration_per_run=18)
 cases={c['template']:c for c in json.loads((ROOT/'testing/component_cases.json').read_text(encoding='utf-8'))}; c=cases[a.template]
 msgs=[f'请在模型 {source} 主图新增一个{c["type"]}，标签叫“{c["name"]}”。{c["create"]}。先查询模板并给新增预览，不保存。','确认新增，完成后回读实际参数。',f'把“{c["name"]}”的参数按这个要求修改：{c["update"]}，先给修改预览。','确认修改，完成后查询实际参数。',f'把当前修改后的模型保存到新RID {a.target}，名称叫“{a.template}-acceptance”。先给保存预览，不运行仿真。',f'确认保存到 {a.target}，只创建新模型，保存后云端回读核对，不运行仿真。',f'现在删除“{c["name"]}”，先给删除影响预览。','确认删除，查询确认已删除。']
 turns=[]
 try:
  for i,m in enumerate(msgs):
   host.WORKFLOW_STATE.begin_turn(); conv.send_message(m); conv.run(); turns.append({'user':m,'assistant':get_agent_final_response(list(conv.state.events)) or ''}); save('turns.json',turns)
   s=host.WORKFLOW_STATE.skill_sessions['cloudpss-aux-modeling']; save(f'model-{i:02}.json',s['memory_model'].toJSON())
  target=cloudpss.Model.fetch(a.target).toJSON(); save('target-cloud-readback.json',target); source_after=cloudpss.Model.fetch(source).toJSON(); save('source-after.json',source_after)
  assert target['rid']==a.target and source_after==baseline
  save('result.json',{'passed':True,'target_rid':a.target,'source_unchanged':True,'readback_verified':True,'simulation_run':False})
  print('TEMPLATE_SAVE_PASSED',a.template,a.target)
 except Exception as e:
  save('result.json',{'passed':False,'error':str(e),'target_rid':a.target,'simulation_run':False}); print('TEMPLATE_STOP',type(e).__name__,str(e))
 finally: conv.close()
if __name__=='__main__': main()
