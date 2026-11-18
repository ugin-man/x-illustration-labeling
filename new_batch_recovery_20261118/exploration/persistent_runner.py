"""Isolated integration revision. No network or connector is created here.
All callbacks are installation-time trusted capabilities, never row/source data.
"""
import copy, hashlib, hmac, json, sqlite3, time, os
from contextlib import contextmanager
from pathlib import Path
from exploration import Authority, Refused, canonical, digest, transition, validate_transition, number, VERSION, new_clock


def get_path(state,path):
 for k in path:state=state[k]
 return state

def set_path(state,path,value):
 out=copy.deepcopy(state);node=out
 for k in path[:-1]:node=node[k]
 node[path[-1]]=copy.deepcopy(value)
 return out


def validate_batch(before,events,after,authority):
 cur=before
 for event in events:cur=transition(cur,event,authority)
 if cur!=after:raise Refused('writer replay mismatch')
 return True


def validate_full_write(before,after,path,events,authority):
 """Only selected clock changes, other contexts/rows/Terra/legacy untouched."""
 new=get_path(after,path)
 try:old=get_path(before,path)
 except KeyError:
  context=get_path(before,path[:-1])
  old=new_clock(new['binding'],context)
  if not events or events[0].get('kind')!='reserve':raise Refused('initial clock must reserve, not import history')
 validate_batch(old,events,new,authority)
 if set_path(before,path,new)!=after:raise Refused('unrelated state change')
 return True


def validate_sealed_row(clock,row):
 # Explicit new revision field; no implicit rewriting of historical row schema.
 seal=clock.get('seal')
 expected={'revision':clock['version'],'clock_sha256':digest(clock),'seal':seal}
 if not seal or row.get('post_id')!=clock['binding']['post_id'] or row.get('exploration_receipt')!=expected:raise Refused('row not bound to exact seal')
 return True


class Store:
 """SQLite transaction atomically persists authority, ledger, and consumed intent.
 Existing store mandatory on resume. Lost/corrupt store never auto-reinitialized.
 Single runner owns this DB; BEGIN IMMEDIATE serializes concurrent CLI clients.
 """
 def __init__(self,path):
  if not Path(path).is_file():raise Refused('authority store missing: fail closed')
  self.db=sqlite3.connect(path,timeout=2,isolation_level=None)
  self.db.execute('PRAGMA synchronous=FULL')
  self.db.execute('PRAGMA journal_mode=DELETE')
  self.db.execute('SELECT payload FROM runner WHERE id=1').fetchone()
 @classmethod
 def initialize(cls,path,clock):
  if clock!=new_clock(clock['binding']):raise Refused('initialize only fresh clock; resume persistent Authority instead')
  path=Path(path)
  # Exclusive creation is intentional: explicit new context only, never resume.
  fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
  db=sqlite3.connect(path);db.execute('CREATE TABLE runner(id INTEGER PRIMARY KEY,payload TEXT NOT NULL)')
  a=Authority();data={'clock':clock,'events':[],'key':a._key.hex(),'issued':{},'used':[], 'blocked':False,'intents':{},'last_head':None}
  db.execute('INSERT INTO runner VALUES (1,?)',(json.dumps(data),));db.commit();db.close()
  return cls(path)
 @contextmanager
 def transaction(self):
  self.db.execute('BEGIN IMMEDIATE')
  try:
   data=json.loads(self.db.execute('SELECT payload FROM runner WHERE id=1').fetchone()[0])
   a=Authority();a._key=bytes.fromhex(data['key']);a._issued=data['issued'];a._used=set(data['used'])
   for proof in a._issued.values():
    if not hmac.compare_digest(proof['mac'],hmac.new(a._key,canonical(proof['payload']),hashlib.sha256).hexdigest()):raise Refused('corrupt authority proof')
   yield data,a
   data['issued']=a._issued;data['used']=sorted(a._used)
   self.db.execute('UPDATE runner SET payload=? WHERE id=1',(json.dumps(data),));self.db.execute('COMMIT')
  except BaseException:
   self.db.execute('ROLLBACK');raise
 def close(self):self.db.close()


class Runner:
 """Synchronous trusted bridge with injected connector + actual tool adapters.
 snapshot()->(head,full_state); publish(head,before,after,events)->(receipt,head,state).
 publish must be the reviewed CAS connector protocol, not a permissive RPC.
 guard(head,state,binding)->lease_until validates real fixed activation/post/lease.
 clock path fixed at construction. wall/monotonic injected only by tests.
 """
 def __init__(self,store,path,snapshot,publish,guard,external,wall=time.time,monotonic=time.monotonic):
  self.store=store;self.path=tuple(path);self.snapshot=snapshot;self.publish=publish;self.guard=guard;self.external=external;self.wall=wall;self.monotonic=monotonic
 def _event(self,d,a,event):
  d['clock']=transition(d['clock'],event,a);d['events'].append(copy.deepcopy(event))
 def reserve(self,rid,kind,queries):
  with self.store.transaction() as (d,a):
   if d['blocked']:raise Refused('runner blocked')
   head,before=self.snapshot();now=self.wall()
   if self.guard(head,before,d['clock']['binding'])<=now+30:raise Refused('lease margin')
   self._event(d,a,{'kind':'reserve','at':now,'request_id':rid,'request_kind':kind,'queries':queries})
   after=set_path(before,self.path,d['clock']);events=copy.deepcopy(d['events'])
   validate_full_write(before,after,self.path,events,a)
   # Durable before connector. A crash/ACK loss cannot mint replacement permission.
   d['blocked']=True
  try:receipt,observed_head,observed=self.publish(head,before,after,events)
  except BaseException:raise # reservation and blocked marker remain durable
  with self.store.transaction() as (d,a):
   if receipt.get('ref_update_acknowledged') is not True or receipt.get('external_request_permitted') is not True or receipt.get('accepted') is not True or receipt.get('candidate')!=observed_head or observed!=after:raise Refused('connector ACK/full state readback uncertain')
   # Validate hashes ourselves, not merely a connector supplied permission boolean.
   if receipt.get('state_sha256')!=digest(after):raise Refused('full dispatch digest mismatch')
   if get_path(observed,self.path)!=d['clock']:raise Refused('clock readback mismatch')
   proof=a.verified_ack(d['clock']['binding'],rid,digest(d['clock']),observed_head,self.wall(),acknowledged=True,readback_sha=digest(get_path(observed,self.path)))
   d['events']=[];self._event(d,a,{'kind':'acknowledge','at':proof['payload']['at'],'request_id':rid,'proof':proof})
   d['last_head']=observed_head;d['remote_state_sha256']=digest(observed);d['blocked']=False
 def dispatch(self,rid):
  with self.store.transaction() as (d,a):
   if d['blocked']:raise Refused('runner blocked')
   r=d['clock']['requests'][rid]
   head,state=self.snapshot();now=self.wall()
   if head!=d['last_head'] or digest(state)!=d['remote_state_sha256']:raise Refused('fresh remote changed')
   if self.guard(head,state,d['clock']['binding'])<=now+30:raise Refused('lease no longer safe')
   # Transition checks actual time again, after fresh read; counts tool-read time.
   self._event(d,a,{'kind':'external_started','at':now,'request_id':rid})
   a.consume_permission(r['ack'])
   if rid in d['intents']:raise Refused('durable duplicate intent')
   d['intents'][rid]={'state':'started','head':head,'at':now,'clock_sha256':digest(d['clock'])}
   request=copy.deepcopy(r)
  # COMMIT is the journal-before-external boundary. Failure never calls tool.
  result=self.external(request['kind'],request['queries'])
  with self.store.transaction() as (d,a):
   self._event(d,a,{'kind':'external_finished','at':self.wall(),'request_id':rid,'result_sha256':digest(result)})
   d['intents'][rid]['state']='finished'
  return result
 def seal(self):
  with self.store.transaction() as (d,a):
   if d['blocked']:raise Refused('runner blocked')
   self._event(d,a,{'kind':'seal','at':self.wall()})
   return copy.deepcopy(d['clock'])
 def flush_seal(self):
  with self.store.transaction() as (d,a):
   if d['blocked'] or not d['clock']['seal']:raise Refused('no available seal')
   head,before=self.snapshot()
   if self.guard(head,before,d['clock']['binding'])<=self.wall()+30:raise Refused('lease margin')
   after=set_path(before,self.path,d['clock']);events=copy.deepcopy(d['events'])
   validate_full_write(before,after,self.path,events,a);d['blocked']=True
  receipt,h,observed=self.publish(head,before,after,events)
  with self.store.transaction() as (d,a):
   if receipt.get('accepted') is not True or receipt.get('ref_update_acknowledged') is not True or receipt.get('candidate')!=h or observed!=after or receipt.get('state_sha256')!=digest(after):raise Refused('seal ACK uncertain')
   d['events']=[];d['blocked']=False;d['last_head']=h;d['remote_state_sha256']=digest(observed)
  return h

class FixedScopeGuard:
 """Installation pins reviewed activation values; no dynamic post expansion."""
 def __init__(self,plan_key,plan_sha256,allowed_posts,job_id='prod-0002'):
  self.key=plan_key;self.plan=plan_sha256;self.posts=frozenset(allowed_posts);self.job=job_id
 def __call__(self,head,state,binding):
  r=state['koyo_index_handoffs'][self.key];lease=r['lease']
  if r['status']!='leased' or r['job_id']!=self.job or r['plan_sha256']!=self.plan or binding['plan_sha256']!=self.plan or binding['post_id'] not in self.posts or binding['post_id'] in r['rows'] or lease['owner']!='koyo' or lease['token']!=binding['lease_token']:raise Refused('current plan/post/token guard')
  plan=r.get('plan',{});payload=plan.get('payload',{});posts=payload.get('source',{}).get('post_ids',[])
  if digest(payload)!=self.plan or plan.get('plan_sha256')!=self.plan or binding['post_id'] not in posts:raise Refused('plan payload or membership mismatch')
  context=r.get('context',{}).get(binding['post_id'],{})
  if 'budget' in context or 'reservations' in context:raise Refused('legacy exploration cannot migrate')
  if 'fetch_started' not in context or number(context['fetch_started'])<0 or context.get('attempt_limit')!=1:raise Refused('one-time body reservation missing')
  cache=context.get('cache',{})
  if cache.get('post_id')!=binding['post_id'] or cache.get('state')!='available' or not isinstance(cache.get('text'),str):raise Refused('available focal body cache required for exploration')
  clock=context.get('exploration_clock')
  if clock and (clock.get('version')!=VERSION or clock.get('binding')!=binding):raise Refused('wrong/legacy clock binding')
  return lease['until']


def connector_result(envelope,candidate,receipt,readback_head,readback_state):
 """Adapter for connector_protocol.execution_receipt, plus independently read state.
 Never manufacture success from head matching after a lost ACK.
 Called inside trusted transport, not loaded from untrusted request JSON.
 """
 p=envelope['payload']
 if envelope['sha256']!=digest(p) or receipt.get('envelope_sha256')!=envelope['sha256'] or receipt.get('candidate')!=candidate or readback_head!=candidate or receipt.get('target_post_id')!=p['target_post_id'] or receipt.get('operation')!=p['operation'] or digest(readback_state)!=p['state_sha256'] or readback_state!=json.loads(p['state_json_content']):raise Refused('connector envelope/readback mismatch')
 r=copy.deepcopy(receipt);r['state_sha256']=digest(readback_state)
 return r,readback_head,readback_state


def measured_git_read(runner,rid,git_runner,command,*args):
 """Install only with fixed q.git. Endpoints/command args must be fixed by caller.
 Never accepts caller timestamps or deductions. Persist before returning result.
 """
 if command not in ('fetch','ls-remote'):raise Refused('not a management read')
 with runner.store.transaction() as (d,a):
  if d['blocked']:raise Refused('runner blocked')
  start=runner.wall();mono=runner.monotonic();failure=None;result=None
  try:result=git_runner(command,*args)
  except Exception as exc:failure=exc
  end=runner.wall();duration=runner.monotonic()-mono
  proof=a.measured_wait(d['clock']['binding'],rid,d['last_head'],command,start,end,duration)
  runner._event(d,a,{'kind':'management_read','at':end,'proof':proof})
 if failure:raise failure
 return result
