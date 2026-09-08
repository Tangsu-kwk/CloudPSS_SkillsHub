import json
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'runs'/'20260907-user-dialogue'
INBOX=OUT/'inbox'
cases=json.loads((ROOT/'extended_cases.json').read_text(encoding='utf-8'))
def turn(number,message):
    key=f'{number:04d}'
    result=OUT/(key+'-result.json')
    if not result.exists():
        tmp=INBOX/(key+'.tmp')
        tmp.write_text(json.dumps({'message':message},ensure_ascii=False),encoding='utf-8')
        tmp.rename(INBOX/(key+'.json'))
        while not result.exists():time.sleep(2)
    data=json.loads(result.read_text(encoding='utf-8'))
    if data.get('error'):
        raise RuntimeError(f'Test stopped on error in {result.name}; inspect evidence before resuming.')
    return data
while True:
    p=OUT/'suite-progress.json'
    if p.exists() and json.loads(p.read_text(encoding='utf-8'))['completed_cases']==21:break
    time.sleep(2)
for i,c in enumerate(cases):
    n=500+i*10
    r=turn(n,c['message']+' 不保存云端，不运行仿真。')
    if c['name'] not in {'missing_query','ambiguous_query','invalid_parameter','cancel_preview','short_circuit'}:
        for j in range(1,5):
            if j>1 and not r.get('pending_preview'):break
            r=turn(n+j,'确认，只按刚才要求的方案执行；涉及多个新设备时请逐个完成，不要漏项，原有设备保持不变。完成后重新查看实际参数和连接。不保存，不运行仿真。')
        r=turn(n+6,'请再查看一下刚才这项操作涉及的设备，用实际查询结果确认有没有遗漏、参数和连接是否与我的要求一致。只查看。')
    (OUT/'extended-progress.json').write_text(json.dumps({'completed_cases':i+1,'total_cases':len(cases),'last':c['name']},ensure_ascii=False),encoding='utf-8')
    print('EXTENDED_DONE',c['name'],flush=True)
