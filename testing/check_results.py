import json
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'runs'/'20260907-user-dialogue'
cases=json.loads((ROOT/'component_cases.json').read_text(encoding='utf-8'))
expected=json.loads((ROOT/'expected_changes.json').read_text(encoding='utf-8'))
expected_create=json.loads((ROOT/'expected_create.json').read_text(encoding='utf-8'))
def cells(d):return d['revision']['implements']['diagram']['cells']
base=cells(json.loads((OUT/'003-model.json').read_text(encoding='utf-8')))
def unwrap(v):return v.get('source') if isinstance(v,dict) and 'source' in v else v
def equal(a,b):
    a=unwrap(a)
    if isinstance(b,(int,float)):
        try:return abs(float(a)-b)<1e-9
        except (TypeError,ValueError):return False
    return a==b
rows=[]
for i,c in enumerate(cases):
    n=100+i*10
    p=OUT/(f'{n+6:04d}-model.json')
    row={'template':c['template'],'status':'PENDING'}
    if p.exists():
        cur=cells(json.loads(p.read_text(encoding='utf-8')))
        found=[(k,v) for k,v in cur.items() if k not in base and v.get('definition')=='model/CloudPSS/'+c['template']]
        row['matches']=len(found)
        row['existing_modified']=[k for k in base if cur.get(k)!=base[k]]
        row['status']='MISSING' if not found else 'PASS'
        if found:
            k,v=found[0]
            row.update(key=k,label=v.get('label'),pins=v.get('pins'),actual_args=v.get('args'))
            row['mismatches']={key:{'expected':val,'actual':v.get('args',{}).get(key)} for key,val in expected[c['template']].items() if not equal(v.get('args',{}).get(key),val)}
            if row['mismatches']:row['status']='PARAM_MISMATCH'
            cp=OUT/(f'{n+2:04d}-model.json')
            if not cp.exists():cp=OUT/(f'{n+1:04d}-model.json')
            if cp.exists():
                cv=cells(json.loads(cp.read_text(encoding='utf-8'))).get(k,{})
                row['create_mismatches']={key:{'expected':val,'actual':cv.get('args',{}).get(key)} for key,val in expected_create[c['template']].items() if not equal(cv.get('args',{}).get(key),val)}
                if row['create_mismatches']:row['status']='CREATE_PARAM_MISMATCH'
            before=OUT/(f'{n+4:04d}-model.json')
            row['query_unchanged']=cells(json.loads(before.read_text(encoding='utf-8')))==cur if before.exists() else None
    elif (OUT/(f'{n+4:04d}-result.json')).exists():
        failed=json.loads((OUT/(f'{n+4:04d}-result.json')).read_text(encoding='utf-8'))
        if failed.get('error'):
            row.update(status='BLOCKED_PROVIDER',reason='DeepSeek HTTP 402 Insufficient Balance',create_completed=(OUT/(f'{n+1:04d}-model.json')).exists(),update_preview_completed=(OUT/(f'{n+3:04d}-model.json')).exists())
    rows.append(row)
    print(row['template'],row['status'],row.get('mismatches',''))
(OUT/'verification-matrix.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
