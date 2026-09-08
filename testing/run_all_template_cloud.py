"""Sequentially run independent cloud acceptance cases for all templates."""
import ast, json, os, runpy, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
cases=json.loads((ROOT/'testing/component_cases.json').read_text(encoding='utf-8'))
aliases={
 '_NewVoltageMeter':'voltage-meter','_newChannel':'channel','_newBreaker_3p':'breaker',
 '_newDropGen':'drop-generator','_newShuntLC_3p':'shunt-lc','_newConstant':'constant',
 '_newFaultResistor_3p':'fault-resistor','GND':'ground','_newACVoltageSource_3p':'ac-source',
 '_newBus_3p':'bus','_newExpLoad_3p':'load','_newStepGen':'step-generator',
 '_newTransformer_3p2w':'transformer','_PSASP_AVR_11to12':'avr','_newGain':'gain',
 'SyncGeneratorRouter':'sync-generator','TransmissionLine':'transmission-line',
 'Harmonic_continuous_injection':'harmonic-impedance','Harmonic_continuous_injection_I':'harmonic-current',
 'Harmonic_continuous_injection_V':'harmonic-voltage','_newSum':'sum'
}
done={'_newConstant','_newBus_3p'}
out=ROOT/'testing/runs'/'all-template-cloud'
out.mkdir(parents=True,exist_ok=True)
results=[]
for c in cases:
 t=c['template']; target='model/Makinohara_Shoko/test1-autotest-'+aliases.get(t,t.lower().replace('_','-'))
 if t in done:
  results.append({'template':t,'target_rid':target,'status':'already_completed'}); continue
 print('START',t,target,flush=True)
 os.environ['TEMPLATE_BATCH_DIR']=str(out)
 sys.argv=['verify_template_cloud.py','--template',t,'--target',target]
 try:
  runpy.run_path(str(ROOT/'testing/verify_template_cloud.py'),run_name='__main__')
 except Exception as e:
  results.append({'template':t,'target_rid':target,'status':'harness_error','error':str(e)})
  continue
 dirs=sorted((ROOT/'testing/runs').glob('template-'+t.replace('_','')+'-*'))
 result={}
 if dirs:
  p=dirs[-1]/'result.json'
  if p.exists(): result=json.loads(p.read_text(encoding='utf-8'))
 results.append({'template':t,'target_rid':target,**result,'status':'passed' if result.get('passed') else 'failed'})
 (out/'progress.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(results,ensure_ascii=False,indent=2),flush=True)
