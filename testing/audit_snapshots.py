"""Read recorded model snapshots; do not call runtime or CloudPSS."""
import json
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'runs'/'20260907-user-dialogue'
cases=json.loads((ROOT/'component_cases.json').read_text(encoding='utf-8'))
baseline=json.loads((OUT/'003-model.json').read_text(encoding='utf-8'))
def cells(d):return d['revision']['implements']['diagram']['cells']
base=cells(baseline)
report=[]
for i,c in enumerate(cases):
    n=100+i*10
    snapshots=[]
    for p in sorted(OUT.glob(f'{n//10:03d}*-model.json')):
        d=json.loads(p.read_text(encoding='utf-8'))
        current=cells(d)
        added={k:v for k,v in current.items() if k not in base}
        modified_existing=[k for k,v in current.items() if k in base and v!=base[k]]
        snapshots.append({'file':p.name,'added':added,'modified_existing':modified_existing})
    row={'template':c['template'],'name':c['name'],'snapshots':snapshots}
    report.append(row)
    if snapshots:
        last=snapshots[-1]
        print(c['template'],last['file'],'added',len(last['added']),'modified_existing',len(last['modified_existing']))
        for k,v in last['added'].items():
            print(k,v.get('label'),v.get('args'),v.get('pins'))
(OUT/'snapshot-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
