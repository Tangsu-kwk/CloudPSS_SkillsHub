"""Compare requested vs applied values through retained event evidence."""
import json
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
root=Path(__file__).resolve().parent/'runs'/'20260907-user-dialogue'
events=[]
for p in root.glob('*-events.jsonl'):
    for line in p.read_text(encoding='utf-8').splitlines():
        row=json.loads(line)
        e=row['event']
        if e.get('kind')=='ActionEvent':
            a=e.get('action',{})
            if a.get('skill')=='cloudpss-aux-modeling':
                req=a.get('request',{})
                if req.get('confirmation'):
                    events.append({'file':p.name,'timestamp':e.get('timestamp'),'operation':req.get('operation'),'request':req})
(root/'confirmed-action-audit.json').write_text(json.dumps(events,ensure_ascii=False,indent=2),encoding='utf-8')
print('confirmed_actions',len(events))
