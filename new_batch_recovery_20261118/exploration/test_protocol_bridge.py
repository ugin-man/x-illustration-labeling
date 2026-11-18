import copy,hashlib,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from exploration import *
from persistent_runner import *
from protocol_bridge import *
B={'plan_sha256':'a'*64,'post_id':'123','worker':'koyo','lease_token':'token'}
class ProtocolTests(unittest.TestCase):
 def setUp(self):
  global B
  self.tmp=tempfile.TemporaryDirectory();self.t=1794955000.;self.head='a'*40;self.calls=[];self.lost=False
  self.state=json.load(open('/tmp/koyo-current-batch-candidate/live-final-state.json'))
  self.key=next(k for k,h in self.state['koyo_index_handoffs'].items() if h['job_id']=='prod-0002');h=self.state['koyo_index_handoffs'][self.key];pid=h['plan']['payload']['source']['post_ids'][18]
  B={'plan_sha256':self.key,'post_id':pid,'worker':'koyo','lease_token':h['lease']['token']};self.path=('koyo_index_handoffs',self.key,'context',pid,'exploration_clock')
  h['context'][pid]={'fetch_started':self.t-1,'attempt_limit':1,'cache':{'post_id':pid,'state':'available','text':'fixture'},'exploration_clock':new_clock(B)}
  self.store=Store.initialize(Path(self.tmp.name)/'db',new_clock(B));self.pending=None
  files=list(Path(__file__).parent.glob('*.py'))+list((Path(__file__).parent/'runtime_snapshot').glob('*.py'))
  payload={'mode':'isolated-exploration-review-v3','review_reference':'isolated test fixture only','plan_sha256':self.key,'baseline_handoff':copy.deepcopy(h),'scope':{'job_id':'prod-0002','post_ids':h['plan']['payload']['source']['post_ids'][18:],'held_post_ids':[h['plan']['payload']['source']['post_ids'][16]]},'code_sha256':{str(f.resolve()):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}}
  self.guard=ReviewedClockGuard('/tmp/x-recovery-isolated',{'payload':payload,'sha256':digest(payload)})
  self.q=SimpleNamespace(_commit=self.commit,git=lambda *args:SimpleNamespace(stdout=('b'*40+'\n').encode()))
  self.base=SimpleNamespace(key=self.key,q=self.q,clock=lambda:self.t,read=self.snapshot,root='/tmp/x-recovery-isolated')
  from network_runtime import IndexWriter
  self.base.preservation=lambda before,after:IndexWriter.preservation(self.base,before,after)
  self.io=SimpleNamespace(create_tree=self.tree,create_commit=lambda p:{'sha':self.candidate},fetch_commit=lambda sha:{'sha':sha,'tree':{'sha':'b'*40},'parents':[{'sha':self.head}]},update_ref=self.update)
  def factory(events):
   with self.store.transaction() as (d,a):return ClockWriter(self.base,self.path,a,self.guard,events,B['lease_token']),B['lease_token']
  self.publisher=ProtocolPublisher(factory,self.io)
  self.runner=Runner(self.store,self.path,self.snapshot,self.publisher,self.guard,self.tool,lambda:self.t,lambda:self.t)
 def tearDown(self):self.store.close();self.tmp.cleanup()
 def snapshot(self):return self.head,copy.deepcopy(self.state)
 def commit(self,state,head):self.pending=copy.deepcopy(state);self.candidate=hashlib.sha1(canonical(state)).hexdigest();return self.candidate
 def tree(self,p):self.assertEqual(json.loads(p['state_json_content']),self.pending);return {'sha':'b'*40}
 def update(self,p):
  self.assertEqual(p['expected_sha'],self.head);self.assertFalse(p['force']);self.head=p['sha'];self.state=copy.deepcopy(self.pending);self.t+=10
  if self.lost:raise TimeoutError('ACK lost')
  return True
 def tool(self,k,q):self.calls.append((k,q));self.t+=2;return {'fixture':q}
 def test_real_protocol_five_requests(self):
  for i,k in enumerate(['search','search','page','page','page']):self.runner.reserve(str(i),k,['q']);self.runner.dispatch(str(i))
  clock=self.runner.seal();self.runner.flush_seal();self.assertEqual(clock['seal']['elapsed_seconds'],10);self.assertEqual(get_path(self.state,self.path),clock);self.assertEqual(len(self.calls),5)
 def test_real_protocol_ack_loss(self):
  self.lost=True
  with self.assertRaises(Refused):self.runner.reserve('s','search',['q'])
  with self.assertRaises(Refused):self.runner.dispatch('s')
  self.assertEqual(self.calls,[])
 def test_actual_guard_token_changed(self):
  self.runner.reserve('s','search',['q']);self.state['koyo_index_handoffs'][self.key]['lease']['token']='changed'
  with self.assertRaises(Refused):self.runner.dispatch('s')
 def test_scope_guard_disallows_other_post(self):
  wrong=dict(B,post_id='999')
  with self.assertRaises(Refused):self.guard(self.head,self.state,wrong)
 def test_cache_missing_reserve_and_dispatch(self):
  h=self.state['koyo_index_handoffs'][self.key];h['context'][B['post_id']].pop('cache')
  with self.assertRaises((Refused,ValueError)):self.runner.reserve('s','search',['q'])
  self.assertEqual(self.calls,[])
 def test_body_reservation_missing(self):
  self.state['koyo_index_handoffs'][self.key]['context'][B['post_id']].pop('fetch_started')
  with self.assertRaises(Refused):self.runner.reserve('s','search',['q'])
 def test_payload_tamper_same_claimed_hash(self):
  self.state['koyo_index_handoffs'][self.key]['plan']['payload']['source']['post_ids'][18]='fake'
  with self.assertRaises(Refused):self.runner.reserve('s','search',['q'])
 def test_bad_activation_pin(self):
  p=self.guard.activation['payload'];p['code_sha256'][str(Path(__file__).parent/'persistent_runner.py')]='0'*64;self.guard.activation['sha256']=digest(p)
  with self.assertRaises(Refused):self.runner.reserve('s','search',['q'])
 def test_held_post_change(self):
  self.state['koyo_index_handoffs'][self.key]['context']['2096015385070039138']={'changed':True}
  with self.assertRaises(Refused):self.runner.reserve('s','search',['q'])
 def test_existing_clock_cannot_reinitialize(self):
  with self.assertRaises(Refused):initialize_fresh_store(Path(self.tmp.name)/'second',self.head,self.state,B,self.guard)
 def test_fresh_clock_initialization_and_first_reserve(self):
  self.store.close();self.state['koyo_index_handoffs'][self.key]['context'][B['post_id']].pop('exploration_clock')
  self.store=initialize_fresh_store(Path(self.tmp.name)/'fresh',self.head,self.state,B,self.guard);self.runner.store=self.store
  self.runner.reserve('s','search',['q']);self.runner.dispatch('s');self.assertEqual(len(self.calls),1)
if __name__=='__main__':unittest.main()
