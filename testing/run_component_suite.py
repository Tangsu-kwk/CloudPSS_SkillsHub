"""Sequential user-dialogue scenarios, using the running probe's file inbox."""
import json
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'runs'/'20260907-user-dialogue'
# This legacy driver is retained for historical evidence. New acceptance runs
# must use one cloud RID per template and the dedicated save-aware harness.
INBOX=OUT/'inbox'
CASES=json.loads((ROOT/'component_cases.json').read_text(encoding='utf-8'))

def turn(number, message, fresh=None):
    key=f'{number:04d}'
    result=OUT/(key+'-result.json')
    if not result.exists():
        command={'message':message}
        if fresh:command['fresh']=fresh
        tmp=INBOX/(key+'.tmp')
        tmp.write_text(json.dumps(command,ensure_ascii=False),encoding='utf-8')
        tmp.rename(INBOX/(key+'.json'))
        while not result.exists():
            time.sleep(2)
    data=json.loads(result.read_text(encoding='utf-8'))
    if data.get('error'):
        raise RuntimeError(f'Test stopped on error in {result.name}; inspect the recorded evidence before resuming.')
    return data

for i,c in enumerate(CASES):
    n=100+i*10
    label=c['name']
    context=(f"请在模型 model/Makinohara_Shoko/IEEE39-test1 的主图上，帮我新增一个{c['type']}，"
             f"库中型号为 {c['template']}，标签叫“{label}”。{c['create']}。"
             "先把新设备放好，暂时不接线，新设备自己的所有引脚留空。模型原有设备和连接都保持不变。"
             "其他参数保持该型号的默认设置。先给我看方案，不保存、不运行仿真。")
    if c['template']=='_newBus_3p':
        context=context.replace('暂时不接线，新设备自己的所有引脚留空','母线节点命名为 QA_Bus110')
    if i==0:
        r=json.loads((OUT/'0100-result.json').read_text(encoding='utf-8'))
    else:
        context=context.replace('请在模型 model/Makinohara_Shoko/IEEE39-test1 的主图上，','继续在当前模型主图上，')
        r=turn(n,context)
    if not r.get('error'):
        r=turn(n+1,'确认只按我的要求添加这个新设备，模型原有设备和连接保持不变。完成后，请检查刚加的设备，告诉我实际参数和接线情况；暂时不保存、不运行仿真。')
        if r.get('pending_preview'):
            r=turn(n+2,'确认执行刚才的新增方案，然后查看这个设备。')
        r=turn(n+3,f"请找到刚才的“{label}”，{c['update']}。先让我看看修改方案，暂时不要执行。")
        r=turn(n+4,'确认修改。改完请重新查看该设备，把实际参数告诉我。不要保存或运行仿真。')
        if r.get('pending_preview'):
            r=turn(n+5,'确认执行这次参数修改。完成后重新查看设备，告诉我现在的参数。')
        r=turn(n+6,f'再帮我查一下“{label}”，确认刚才添加的设备还在，列出它现在的主要参数和接线情况。只查看，不做任何修改。')
    (OUT/'suite-progress.json').write_text(json.dumps({'completed_cases':i+1,'total_cases':len(CASES),'last':c['template']},ensure_ascii=False),encoding='utf-8')
    print('CASE_DONE',i+1,c['template'],flush=True)
print('SUITE_DONE',flush=True)
