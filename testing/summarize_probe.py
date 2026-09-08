import json
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
root=Path(__file__).resolve().parent/'runs'/'20260907-user-dialogue'
for p in sorted(root.glob('*-result.json'))[-3:]:
    d=json.loads(p.read_text(encoding='utf-8'))
    print(p.name,round(d.get('elapsed_s',0),1),d.get('response',d.get('error',''))[:5500])
paths=sorted(root.glob('*-events.jsonl'),key=lambda p:p.stat().st_mtime)
if paths:
    events=[json.loads(x)['event'] for x in paths[-1].read_text(encoding='utf-8').splitlines()]
    print('EVENTS',len(events))
    for e in events[-4:]:
        if e.get('kind')=='ActionEvent':print(json.dumps(e['action'],ensure_ascii=False)[:1000])
        elif e.get('kind')=='ObservationEvent':
            ob=e['observation']; texts=' '.join(c.get('text','') for c in ob.get('content',[]))
            print('RESULT',ob.get('is_error'),texts[:300])
