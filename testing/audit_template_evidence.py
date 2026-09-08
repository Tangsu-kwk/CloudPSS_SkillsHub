"""Reassess legacy pass flags using snapshots, without another cloud write."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
cases=json.loads((ROOT/'component_cases.json').read_text(encoding='utf-8'))
creates=json.loads((ROOT/'expected_create.json').read_text(encoding='utf-8'))
updates=json.loads((ROOT/'expected_changes.json').read_text(encoding='utf-8'))
rows=[]
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def cells(d): return d['revision']['implements']['diagram']['cells']
def check(data,label,args):
    found=[c for c in cells(data).values() if c.get('label')==label]
    assert len(found)==1, f'{label}: not exactly one instance'
    for k,v in args.items():
        x=found[0]['args'].get(k)
        if isinstance(x,dict): x=x.get('source')
        if isinstance(v,(int,float)): assert x is not None and abs(float(x)-v)<1e-8, f'{k}: {x} != {v}'
        else: assert x==v, f'{k}: {x} != {v}'
for case in cases:
    dirs=sorted((ROOT/'runs').glob('template-'+case['template'].replace('_','')+'-*'))
    for out in dirs:
        row={'template':case['template'],'evidence':str(out),'status':'incomplete'}
        try:
            baseline=read(out/'source-before.json')
            check(read(out/'model-01.json'),case['name'],creates[case['template']])
            row['create_selected_args']='verified'
            check(read(out/'model-03.json'),case['name'],{**creates[case['template']],**updates[case['template']]})
            row['update_selected_args']='verified'
            last=read(out/'model-07.json')
            assert cells(last)==cells(baseline),'Deleted state differs from original cells'
            row['delete_cells']='verified'
            cloud=read(out/'target-cloud-readback.json')
            expected=read(out/'model-03.json')
            row['cloud_contains_modified_revision']=cloud['revision']['implements']==expected['revision']['implements']
            assert read(out/'source-after.json')==baseline,'Source changed'
            row['status']='selected_crud_cloud_verified' if row['cloud_contains_modified_revision'] else 'selected_crud_but_cloud_saved_deleted_baseline'
        except Exception as exc: row['audit_issue']=str(exc)
        rows.append(row)
(ROOT/'legacy-template-audit.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
for r in rows:
    if r.get('create_selected_args'): print(r['template'],r['status'],r.get('audit_issue',''))
