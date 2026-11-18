"""Reviewable connection to existing protocol primitives; dependency-injected I/O.
No default connector, URL, credential, production activation or external tool.
"""
import copy,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).with_name('runtime_snapshot')))
sys.path.insert(0,'/tmp/x-recovery-isolated')
import connector_protocol as protocol
from exploration import Refused
from persistent_runner import connector_result,validate_full_write

class ClockWriter:
 """Dedicated clock writer boundary, preserving parent writer's read/git capability.
 DOES NOT enable existing production activation. Needs independently reviewed
 production scope + pin activation before installation. Tests use fake writer.
 """
 def __init__(self,base,path,authority,guard,events,token):
  if not isinstance(guard,ReviewedClockGuard):raise Refused('dedicated reviewed guard mandatory')
  self.base=base;self.path=path;self.authority=authority;self.guard=guard;self.events=copy.deepcopy(events);self.token=token
  self.key=base.key;self.q=base.q;self.clock=base.clock
 def read(self):return self.base.read()
 def authorize_transition(self,before,after,operation,lease_token,fencing_receipt=None):
  if operation!='exploration' or lease_token!=self.token or fencing_receipt is not None:raise Refused('clock-only operation')
  binding=after['koyo_index_handoffs'][self.key]['context'][self.path[-2]]['exploration_clock']['binding']
  head,current=self.read()
  if current!=before or binding['lease_token']!=self.token or self.guard(head,before,binding)<=self.clock()+30:raise Refused('clock writer stale scope/lease')
  validate_full_write(before,after,self.path,self.events,self.authority)
 def preservation(self,before,after):
  validate_full_write(before,after,self.path,self.events,self.authority)
  # Retain original immutable rows, body history, image events, operation ledger,
  # ownership/expiry, catalog + row validation. Only the new target clock schema
  # is removed from BOTH projections, since its validator is pure replay above.
  projections=[]
  for source in (before,after):
   projected=copy.deepcopy(source);node=projected
   for key in self.path[:-1]:node=node[key]
   node.pop(self.path[-1],None);projections.append(projected)
  self.base.preservation(*projections)

class ProtocolPublisher:
 """install io with real create_tree/create_commit/fetch_commit/update_ref methods.
 Those methods return parsed connector response or raise on error/unknown shape.
 update_ref must return an explicit bool acknowledgement; uncertainty stays false.
 """
 def __init__(self,writer_factory,io):self.factory=writer_factory;self.io=io
 def __call__(self,head,before,after,events):
  writer,token=self.factory(events)
  e=protocol.envelope(writer,head,before,after,'exploration',token)
  protocol.validate_envelope(writer,e,before);p=e['payload']
  tree=self.io.create_tree(p)
  if tree.get('sha')!=p['candidate_tree_sha']:raise Refused('connector tree mismatch')
  commit=self.io.create_commit(p);candidate=commit.get('sha')
  if not isinstance(candidate,str) or len(candidate)!=40 or any(c not in '0123456789abcdef' for c in candidate):raise Refused('bad commit id')
  fetched=self.io.fetch_commit(candidate)
  if fetched.get('sha')!=candidate:raise Refused('fetched commit mismatch')
  params=protocol.pre_update_ref(writer,e,before,fetched)
  acknowledged=False
  try:acknowledged=self.io.update_ref(params) is True
  except Exception:pass
  observed=protocol.readback(writer,e,candidate)
  receipt=protocol.execution_receipt(e,candidate,acknowledged,observed)
  if observed.get('accepted') is not True:raise Refused('write not accepted; no request')
  return connector_result(e,candidate,receipt,observed['head'],observed['state'])

class ReviewedClockGuard:
 """Mandatory dedicated guard; current implementation ISOLATED ONLY.
 Production enablement requires a separately reviewed activation implementation.
 """
 def __init__(self,root,activation):
  self.root=root;self.activation=copy.deepcopy(activation)
 def __call__(self,head,state,binding):
  from persistent_runner import FixedScopeGuard
  from exploration import digest,VERSION
  from runtime_components import PinnedInputs
  import hashlib
  a=self.activation;p=a.get('payload',{});key=binding['plan_sha256'];h=state['koyo_index_handoffs'][key]
  if key in state.get('koyo_retained_work',{}):raise Refused('retained paused exploration responsibility')
  if a.get('sha256')!=digest(p) or p.get('mode')!=getattr(self,'required_mode','isolated-exploration-review-v3') or not p.get('review_reference') or p.get('plan_sha256')!=key:raise Refused('dedicated activation required; live disabled')
  required={str(Path(__file__).resolve()),str(Path(__file__).with_name('persistent_runner.py').resolve()),str(Path(__file__).with_name('exploration.py').resolve())}
  required|={str(f.resolve()) for f in Path(__file__).with_name('runtime_snapshot').glob('*.py')}
  required|={str(Path(__file__).with_name(f).resolve()) for f in getattr(self,'extra_pins',())}
  pins=p.get('code_sha256',{})
  if not required<=set(pins) or any(hashlib.sha256(Path(f).read_bytes()).hexdigest()!=v for f,v in pins.items()):raise Refused('activation code pin mismatch')
  planned=h['plan']['payload']['source']['post_ids'];scope=p.get('scope',{})
  if len(planned)!=50 or planned[16]!='2096015385070039138' or scope.get('post_ids')!=planned[18:] or scope.get('held_post_ids')!=[planned[16]] or scope.get('job_id')!='prod-0002':raise Refused('fixed batch/held scope mismatch')
  baseline=p['baseline_handoff']
  if baseline['plan']!=h['plan'] or baseline['plan_sha256']!=key or baseline['destination']!=h['destination']:raise Refused('baseline plan/identity mismatch')
  for pid,row in baseline['rows'].items():
   if h['rows'].get(pid)!=row:raise Refused('baseline row changed')
  for field in ('context','events','rows'):
   if h[field].get(planned[16])!=baseline[field].get(planned[16]):raise Refused('held post changed')
  pins_input=PinnedInputs(self.root,h)
  if binding['post_id'] not in pins_input.posts:raise Refused('not in pinned catalog manifest')
  # Fixed cache parser also checks field projection and focal post identity.
  from ops_runtime_r5.queue import cache_value
  cache_value(__import__('json').dumps(h['context'][binding['post_id']].get('cache')),binding['post_id'])
  return FixedScopeGuard(key,key,scope['post_ids'])(head,state,binding)


def initialize_fresh_store(path,head,state,binding,guard):
 from persistent_runner import Store,get_path
 from exploration import new_clock
 if not isinstance(guard,ReviewedClockGuard):raise Refused('dedicated initialization guard required')
 guard(head,state,binding)
 context=state['koyo_index_handoffs'][binding['plan_sha256']]['context'][binding['post_id']]
 return Store.initialize(path,new_clock(binding,context))


class LiveClockGuard(ReviewedClockGuard):
 required_mode='reviewed-live-exploration-v3'
 extra_pins=('host_bridge.py','host_cli.py','exploration_host.js','sealed_row.py','new_batch_guard.py')
 def __call__(self,head,state,binding):
  from exploration import digest
  p=self.activation.get('payload',{})
  if p.get('research_revision')!='koyo-exploration-recovery-v3' or p.get('research_limits')!={'queries':2,'pages':3,'active_seconds':60} or p.get('authority_loss_policy')!='stop-no-reinitialize':raise Refused('live research/authority constraints')
  if not p.get('source_head') or len(p['source_head'])!=40 or not p.get('source_state_sha256') or p.get('scope',{}).get('external_exploration') is not True:raise Refused('live activation evidence missing')
  return super().__call__(head,state,binding)
