import json
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
root = Path(__file__).resolve().parent / 'runs' / '20260907-user-dialogue'
for p in sorted(root.glob('*-result.json')):
    d=json.loads(p.read_text(encoding='utf-8'))
    print(p.name, d.get('elapsed_s'), str(d.get('response', d.get('error','')))[:7000])
paths=sorted(root.glob('*-events.jsonl'), key=lambda p:p.stat().st_mtime)
if paths:
    print('LATEST EVENTS', paths[-1].name)
    rows=[json.loads(x)['event'] for x in paths[-1].read_text(encoding='utf-8').splitlines()]
    for e in rows[-7:]:
        if e.get('kind')=='ActionEvent':
            print('ACTION',json.dumps(e.get('action'),ensure_ascii=False)[:1500])
        elif e.get('kind')=='ObservationEvent':
            ob=e.get('observation',{})
            print('OBS',str(ob)[:400])
        else:
            print(e.get('kind'),str(e.get('llm_message', e.get('content','')))[:600])
