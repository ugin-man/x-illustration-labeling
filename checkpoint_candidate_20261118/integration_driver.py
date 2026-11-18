"""Isolated integration of current-worker scope with checkpoint selection and recovery.
No live activation; no body/image fetch and no takeover. Never mutates production.
"""
import copy,json,time,hashlib
from pathlib import Path
from checkpoint import Refused,stage,prepare,due,digest,apply
from stage_recovery import select_unstaged

def deployment_plan(state,key,head,activation,code_paths):
 h=state['koyo_index_handoffs'][key]
 if key in state.get('koyo_retained_work',{}) or h['status']!='leased' or h['lease']['owner']!='koyo':raise Refused('inactive/foreign worker')
 p=activation['payload']
 if activation['sha256']!=hashlib.sha256((json.dumps(p,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()).hexdigest() or p['plan_sha256']!=key:raise Refused('existing scope activation mismatch')
 required=[Path(__file__).with_name(f) for f in ('integration_driver.py','checkpoint.py','stage_recovery.py','git_adapters.py','zero_search.py','stage_adoption.py','sealed_stage_validation.py')]
 code_paths=list(set([Path(f).resolve() for f in code_paths]+[f.resolve() for f in required]))
 plan={'mode':'isolated-integration-only','live_enabled':False,'source_head':head,'key':key,'identity_sha256':digest({k:h[k] for k in ('plan','plan_sha256','destination','job_id')}),'activation_sha256':activation['sha256'],'baseline_rows':copy.deepcopy(h['rows']),'code_pins':{str(Path(f).resolve()):hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in code_paths},'rollout_requirements':['sole writer safe boundary','no pending uncertain publish','fresh normal activation with reviewed code pins','archive same authorized repository','fresh source/head/lease and exact readback','separate before/after timing segments']}
 return {'payload':plan,'sha256':digest(plan)}

class IntegratedWorker:
 def __init__(self,writer,archive,aggregate,plan,journal,clock=time.time,exploration_activation=None):
  if plan['sha256']!=digest(plan['payload']) or plan['payload'].get('mode')!='isolated-integration-only' or plan['payload'].get('live_enabled') is not False:raise Refused('not reviewed isolated plan')
  if not getattr(archive.io,'offline_fixture_only',False) or not getattr(aggregate.io,'offline_fixture_only',False):raise Refused('production integration not activated')
  self.writer=writer;self.archive=archive;self.aggregate=aggregate;self.plan=plan['payload'];self.key=self.plan['key'];self.journal=Path(journal);self.clock=clock;self.exploration_activation=exploration_activation
 def check(self,state):
  p=self.plan;h=state['koyo_index_handoffs'][self.key]
  if any(hashlib.sha256(Path(f).read_bytes()).hexdigest()!=sha for f,sha in p['code_pins'].items()):raise Refused('integration code changed')
  if self.writer.activation_document['sha256']!=p['activation_sha256']:raise Refused('activation changed')
  if digest({k:h[k] for k in ('plan','plan_sha256','destination','job_id')})!=p['identity_sha256']:raise Refused('scope identity changed')
  if any(h['rows'].get(pid)!=row for pid,row in p['baseline_rows'].items()):raise Refused('preexisting rows changed')
  if self.key in state.get('koyo_retained_work',{}) or h['lease']['owner']!='koyo' or h['status']!='leased' or h['lease']['until']<=self.clock()+120:raise Refused('inactive/expired; use existing renewal workflow')
 def validate(self,b,a,op,token,pid):
  self.check(b)
  row=a['koyo_index_handoffs'][self.key]['rows'].get(pid,{})
  if op=='save-row' and 'exploration_clock' in b['koyo_index_handoffs'][self.key]['context'].get(pid,{}):
   if not self.exploration_activation:raise Refused('dedicated exploration activation required')
   clock=b['koyo_index_handoffs'][self.key]['context'][pid]['exploration_clock']
   if clock['binding']['lease_token']!=token:
    from stage_adoption import validate_adopted_sealed
    validate_adopted_sealed(self,b,a,pid,token)
   else:
    from sealed_stage_validation import validate as sealed_validate
    sealed_validate(self,b,a,pid,token,self.exploration_activation)
   return
  if op=='save-row' and row.get('context',{}).get('stop_reason')=='evidence_sufficient':
   # New separately reviewed ordinary path, not false no_leads/search bookkeeping.
   from zero_search import validate as zero_validate
   from new_batch_scope import validate_document,validate_scope
   from runtime_components import PinnedInputs
   from next_batch import require_scheduler_permission
   def scope_guard(before,after,key,pid,lease,now):
    require_scheduler_permission(before,key)
    validate_document(self.writer.activation_document,self.writer.root)
    validate_scope(self.writer.activation_document['payload'],before,after,key,op,self.writer.root)
   pins=PinnedInputs(self.writer.root,b['koyo_index_handoffs'][self.key])
   zero_validate(b,a,self.key,pid,token,self.clock(),scope_guard,pins.validate_row)
  else:self.writer.authorize_transition(b,a,op,token)
  self.writer.preservation(b,a)
 def preserve_completed(self,before,after,pid,operation='finalize-post'):
  self.check(before);self.validate(before,after,operation,before['koyo_index_handoffs'][self.key]['lease']['token'],pid)
  item=stage(before,after,self.key,pid,operation,self.clock())
  receipt=self.archive.put(item)
  if receipt['status']!='accepted':raise Refused('stage not remotely accepted; do not classify as durable')
  return receipt
 def restore_and_select(self):
  head,state,_=self.aggregate.read_state();self.check(state)
  recovered=self.archive.restore(self.key);ready=[];held=set();candidates=list(recovered['stages'])
  from stage_adoption import resolve_conflict
  for pid,versions in recovered['conflicts'].items():
   try:candidates.append(resolve_conflict(self,pid,versions))
   except (ValueError,AssertionError,KeyError):held.add(pid)
  for item in candidates:
   pid=item['payload']['pid']
   try:prepare(head,state,[item],self.validate,self.clock())
   except (ValueError,AssertionError,KeyError):held.add(pid)
   else:ready.append(item)
  # Invalid/old-token/conflicting stages are never silently discarded and re-fetched.
  selection=select_unstaged(state,self.key,ready)
  if selection['next_post_id'] in held:selection['next_post_id']=next((p for p in state['koyo_index_handoffs'][self.key]['plan']['payload']['source']['post_ids'] if p not in held and p not in selection['held_requires_reconciliation'] and p not in selection['pending_staged'] and p not in state['koyo_index_handoffs'][self.key]['rows']),None)
  selection['held_requires_reconciliation']=sorted(set(selection['held_requires_reconciliation'])|held)
  return {'head':head,'state':state,'ready':ready,'selection':selection,'external_request_permitted':False}
 def checkpoint(self,force=False):
  r=self.restore_and_select();items=[x for x in r['ready'] if x['payload']['pid'] not in r['state']['koyo_index_handoffs'][self.key]['rows']]
  if not items:return {'status':'nothing_pending','external_request_permitted':False}
  items=items[:5]
  if not force and not due(items,self.clock()):return {'status':'staged_waiting_checkpoint','external_request_permitted':False}
  from types import SimpleNamespace
  def verify_many(wanted):
   fresh=self.restore_and_select()['ready']
   if not all(any(x==y for y in fresh) for x in wanted):raise Refused('stage/adoption no longer verified')
   return True
  return self.aggregate.publish(items,self.validate,SimpleNamespace(verify_many=verify_many),self.journal,self.clock)
