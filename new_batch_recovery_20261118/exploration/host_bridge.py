"""Durable split bridge for pinned JS host. No automatic network/tool retries."""
import copy,json,time
from exploration import Refused,digest,elapsed
from persistent_runner import Runner,Store,get_path,set_path,connector_result
from protocol_bridge import ClockWriter,protocol
class Prepared(Exception):pass
class HostBridge:
 def __init__(self,store,base,guard,binding,wall=time.time):
  self.store=store;self.base=base;self.guard=guard;self.binding=binding;self.wall=wall
  self.path=('koyo_index_handoffs',binding['plan_sha256'],'context',binding['post_id'],'exploration_clock')
 def writer(self,events,a):return ClockWriter(self.base,self.path,a,self.guard,events,self.binding['lease_token'])
 def clock_read(self,d,a):
  clock=d['clock'];eligible=[(rid,r) for rid,r in clock['requests'].items() if 'ack' in r]
  if clock['seal'] or not eligible:return self.base.read()
  rid,r=eligible[-1];original=self.base.q.git;proofs=[]
  def measured(*args,**kwargs):
   if not args or args[0] not in ('fetch','ls-remote'):return original(*args,**kwargs)
   start=self.wall();mono=time.monotonic()
   try:return original(*args,**kwargs)
   finally:proofs.append(a.measured_wait(self.binding,rid,r['ack']['payload']['head'],args[0],start,self.wall(),time.monotonic()-mono))
  self.base.q.git=measured
  try:result=self.base.read()
  finally:self.base.q.git=original
  for proof in proofs:
   event={'kind':'management_read','at':proof['payload']['ended_at'],'proof':proof}
   d['clock']=__import__('exploration').transition(d['clock'],event,a);d['events'].append(event)
  return result
 def prepare(self,rid,kind,queries):
  with self.store.transaction() as (d,a):
   if d['blocked']:raise Refused('pending transport')
   head,before=self.clock_read(d,a);now=self.wall()
   if self.guard(head,before,self.binding)<=now+30:raise Refused('lease expiry')
   event={'kind':'reserve','at':now,'request_id':rid,'request_kind':kind,'queries':queries}
   d['clock']=__import__('exploration').transition(d['clock'],event,a);d['events'].append(event)
   after=set_path(before,self.path,d['clock']);w=self.writer(d['events'],a)
   e=protocol.envelope(w,head,before,after,'exploration',self.binding['lease_token'])
   d['blocked']=True;d['pending']={'envelope':e,'before':before,'events':copy.deepcopy(d['events']),'request_id':rid,'purpose':'reserve'}
   return e
 def prepare_seal(self):
  with self.store.transaction() as (d,a):
   if d['blocked']:raise Refused('pending transport')
   r=Runner(self.store,self.path,None,None,None,None,self.wall)
   if not d['clock']['seal']:r._event(d,a,{'kind':'seal','at':self.wall()})
   head,before=self.base.read();after=set_path(before,self.path,d['clock']);w=self.writer(d['events'],a)
   e=protocol.envelope(w,head,before,after,'exploration',self.binding['lease_token']);d['blocked']=True
   d['pending']={'envelope':e,'before':before,'events':copy.deepcopy(d['events']),'request_id':None,'purpose':'seal'}
   return e
 def prepare_row(self,row):
  from sealed_row import SealedRowWriter
  with self.store.transaction() as (d,a):
   if d['blocked'] or not d['clock']['seal'] or d['events']:raise Refused('seal must be acknowledged before row')
   head,before=self.base.read()
   if get_path(before,self.path)!=d['clock']:raise Refused('durable seal differs')
   after=copy.deepcopy(before);after['koyo_index_handoffs'][self.binding['plan_sha256']]['rows'][self.binding['post_id']]=copy.deepcopy(row)
   w=SealedRowWriter(self.base,self.path,a,self.guard,[],self.binding['lease_token'])
   e=protocol.envelope(w,head,before,after,'save-row',self.binding['lease_token']);d['blocked']=True
   d['pending']={'envelope':e,'before':before,'events':[],'request_id':None,'purpose':'row'}
   return e
 def pending_writer(self,p,a):
  if p['purpose']=='row':
   from sealed_row import SealedRowWriter
   return SealedRowWriter(self.base,self.path,a,self.guard,[],self.binding['lease_token'])
  return self.writer(p['events'],a)
 def pre_ref(self,commit):
  with self.store.transaction() as (d,a):
   p=d['pending'];w=self.pending_writer(p,a)
   params=protocol.pre_update_ref(w,p['envelope'],p['before'],commit)
   d['pending']['commit']=copy.deepcopy(commit)
   return params
 def acknowledge(self,ack):
  if type(ack) is not bool:raise Refused('typed transport ACK required')
  with self.store.transaction() as (d,a):
   p=d['pending'];e=p['envelope'];candidate=p['commit']['sha'];w=self.pending_writer(p,a)
   observed=protocol.readback(w,e,candidate);receipt=protocol.execution_receipt(e,candidate,ack,observed)
   if observed.get('accepted') is not True or not ack:raise Refused('uncertain ACK; no permission; preserve blocked reservation')
   receipt,h,state=connector_result(e,candidate,receipt,observed['head'],observed['state'])
   if get_path(state,self.path)!=d['clock']:raise Refused('clock readback differs')
   d['events']=[]
   if p['purpose']=='reserve':
    proof=a.verified_ack(self.binding,p['request_id'],digest(d['clock']),h,self.wall(),acknowledged=True,readback_sha=digest(get_path(state,self.path)))
    d['clock']=__import__('exploration').transition(d['clock'],{'kind':'acknowledge','at':proof['payload']['at'],'request_id':p['request_id'],'proof':proof},a)
    d['events']=[{'kind':'acknowledge','at':proof['payload']['at'],'request_id':p['request_id'],'proof':proof}]
   d['last_head']=h;d['remote_state_sha256']=digest(state);d['blocked']=False;d.pop('pending')
   return receipt
 def claim(self,rid):
  """Return tool arguments ONLY once, after committed consumed intent.
  Pinned host executes returned call once; crash/lost return means abandon, not replay.
  """
  with self.store.transaction() as (d,a):
   if d['blocked']:raise Refused('pending transport')
   head,state=self.clock_read(d,a);now=self.wall()
   if head!=d['last_head'] or digest(state)!=d['remote_state_sha256']:raise Refused('fresh state drift')
   lease_until=self.guard(head,state,self.binding)
   if lease_until<=now+30:raise Refused('lease expiry')
   req=d['clock']['requests'][rid]
   if rid in d['intents']:raise Refused('consumed durable intent')
   event={'kind':'external_started','at':now,'request_id':rid}
   d['clock']=__import__('exploration').transition(d['clock'],event,a);a.consume_permission(req['ack']);d['events'].append(event)
   d['intents'][rid]={'state':'started','head':head,'at':now,'clock_sha256':digest(d['clock']),'budget_remaining_seconds':60-elapsed(d['clock'],now),'lease_remaining_seconds':lease_until-now}
   out={'request_id':rid,'kind':req['kind'],'queries':copy.deepcopy(req['queries']),'intent_sha256':digest(d['intents'][rid]),'budget_remaining_seconds':d['intents'][rid]['budget_remaining_seconds'],'lease_remaining_seconds':d['intents'][rid]['lease_remaining_seconds']}
  return out
 def finish(self,rid,intent_sha256,result):
  with self.store.transaction() as (d,a):
   intent=d['intents'].get(rid,{})
   if intent.get('state')!='started' or digest(intent)!=intent_sha256:raise Refused('not the uncompleted intent')
   event={'kind':'external_finished','at':self.wall(),'request_id':rid,'result_sha256':digest(result),'result_state':'technical_failure' if isinstance(result,dict) and result.get('isError') is True else 'available'}
   d['clock']=__import__('exploration').transition(d['clock'],event,a);d['events'].append(event);intent['state']='finished'
   d.setdefault('results',{})[rid]=copy.deepcopy(result)
   return {'finished':True,'result_sha256':digest(result),'result_state':'technical_failure' if isinstance(result,dict) and result.get('isError') is True else 'available'}
