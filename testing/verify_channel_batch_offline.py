import sys
from types import SimpleNamespace
sys.path.insert(0, 'skills/cloudpss-aux-modeling')
from mylib.runtime import EditRequest, _configure_channels_batch, _delete_channel

class C:
    def __init__(self, **kw): self.__dict__.update(kw)

class SA:
    def __init__(self):
        self.project=C(jobs=[{'rid':'function/CloudPSS/emtps','args':{'output_channels':[{'0':'old','1':2000,'2':'compressed','4':['shared']},{'0':'shared','1':2000,'2':'compressed','4':['shared']}]}}])
        self.cells={'bus':C(id='bus',definition='model/CloudPSS/_newBus_3p',canvas='c',args={'I':'','V':'','P':'','Name':'Bus'},pins={'0':'n'}), 'shared':C(id='shared',definition='model/CloudPSS/_newChannel',canvas='c',args={'Name':'shared'},pins={'0':'shared'})}
        self.compLib={'_newChannel':{'definition':'model/CloudPSS/_newChannel','args':{'Name':'x'},'pins':{'0':''},'canvas':'c'}}
    def getAllComponents(self): return self.cells
    def _resolve_comp_key(self,x): return x
    def getComponentByKey(self,x): return self.cells[x]
    def addComp(self,t,k,canvas,pos,args,pins,label): self.cells[k]=C(id=k,definition=t['definition'],canvas=canvas,args=args,pins=pins,label=label)
    def deleteComponent(self,k): self.cells.pop(k)
    def setCompLabelDict(self): pass
    def setChannelPinDict(self): pass

sa=SA(); r=_configure_channels_batch(sa, EditRequest('configure_channels_batch',{'job_index':0},{'channels':[{'component':'bus','signal_type':'current','signal_arg':'I','name':'#a'},{'component':'bus','signal_type':'voltage','signal_arg':'V','name':'#b'}]})); assert len(r['succeeded'])==2 and not r['failed']
assert len(sa.project.jobs[0]['args']['output_channels'])==4
d=_delete_channel(sa, EditRequest('delete_channel',{'channel':'shared'},{})); assert len(sa.project.jobs[0]['args']['output_channels'])==2 and 'shared' not in sa.cells
print('batch/reuse/shared-delete offline checks passed')
