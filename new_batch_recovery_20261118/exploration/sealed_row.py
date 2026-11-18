"""Seal-to-fixed-contract row writer; no new row-schema keys."""
import copy
from exploration import Refused,digest
from persistent_runner import get_path
from protocol_bridge import ClockWriter
class SealedRowWriter(ClockWriter):
 def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs)
 def check(self,before,after):
  key=self.key;pid=self.path[-2];b=before['koyo_index_handoffs'][key];a=after['koyo_index_handoffs'][key]
  if pid in b['rows'] or pid not in a['rows']:raise Refused('new same-post row required')
  row=a['rows'][pid];clock=get_path(before,self.path);seal=clock.get('seal')
  if not seal or row.get('post_id')!=pid:raise Refused('sealed same-post clock required')
  if any(row['context'].get(k)!=seal[k] for k in ('searches','pages','elapsed_seconds')):raise Refused('row counts/elapsed differ from immutable seal')
  if any(r.get('result_state')=='technical_failure' for r in clock['requests'].values()):
   ctx=row['context'];attrs=ctx['attributes']
   if ctx['state']=='technical_failure':
    if ctx['stop_reason']!='tool_unavailable' or not any(a['status']=='technical_failure' for a in attrs.values()):raise Refused('failed required exploration must retain tool failure')
   else:
    # R14: an unnecessary extra failure must not erase already sufficient evidence.
    # Unknown/unsupported answers cannot silently absorb a required failed fetch.
    if not all(a['status']=='not_applicable' or (a['status']=='observed' and a.get('sources')) for a in attrs.values()):raise Refused('failed exploration cannot become unknown/no-evidence completion')

  wanted=copy.deepcopy(before);wanted['koyo_index_handoffs'][key]['rows'][pid]=row
  if wanted!=after:raise Refused('row-only write; exact sealed context immutable')
  from runtime_components import PinnedInputs
  PinnedInputs(self.base.root,a).validate_row(row,a['events'].get(pid,[]))
  return row
 def authorize_transition(self,before,after,operation,lease_token,fencing_receipt=None):
  if operation!='save-row' or lease_token!=self.token or fencing_receipt is not None:raise Refused('sealed row operation required')
  self.check(before,after);head,current=self.read();binding=get_path(before,self.path)['binding']
  if current!=before or self.guard(head,before,binding)<=self.clock()+30:raise Refused('stale lease/scope')
 def preservation(self,before,after):
  self.check(before,after)
  # Original protection validates all previously accepted rows and immutable data.
  # New row is validated directly with unmodified fixed-contract validator above.
  a=copy.deepcopy(after);a['koyo_index_handoffs'][self.key]['rows'].pop(self.path[-2])
  p=[]
  for state in (before,a):
   state=copy.deepcopy(state);node=state
   for k in self.path[:-1]:node=node[k]
   node.pop(self.path[-1],None);p.append(state)
  self.base.preservation(*p)
