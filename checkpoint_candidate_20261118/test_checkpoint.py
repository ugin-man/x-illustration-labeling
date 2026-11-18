import copy,json,tempfile,unittest
from checkpoint import *
NOW=100
KEY='k'
def fixture():
 h=dict(plan={'payload':{'source':{'post_ids':[str(i) for i in range(7)]}}},destination={'worker_id':'koyo'},job_id='test',status='leased',lease={'owner':'koyo','token':'t','until':1000},context={},events={},rows={})
 for pid in h['plan']['payload']['source']['post_ids']:h['context'][pid]={'fetch_started':1,'cache':{'post_id':pid}}
 return {'terra':{'untouched':True},'koyo_index_handoffs':{KEY:h}}
def validator(b,a,op,token,pid):
 # fixture-only analogue; integration test below exercises actual production validators.
 h=a['koyo_index_handoffs'][KEY]
 if h['rows'][pid].get('valid') is not True:raise Refused('invalid row')
 if apply(b,KEY,pid,target(h,pid))!=a:raise Refused('scope')
def items(s,n=5):
 result=[]
 for i in range(n):
  a=copy.deepcopy(s);p=str(i);a['koyo_index_handoffs'][KEY]['rows'][p]={'post_id':p,'valid':True}
  result.append(stage(s,a,KEY,p,'save-row',NOW))
 return result
class Fake:
 offline_fixture_only=True
 def __init__(self,s):self.head='head';self.state=copy.deepcopy(s);self.calls=0;self.lose=False;self.conflict=False
 def read(self):return self.head,copy.deepcopy(self.state)
 def cas(self,expected,s):
  self.calls+=1
  if self.conflict:self.head='other';self.state['terra']['new']=True
  if expected!=self.head:raise Conflict('CAS conflict')
  self.head='next';self.state=copy.deepcopy(s)
  if self.lose:raise TimeoutError('ACK lost')
class Tests(unittest.TestCase):
 def setUp(self):self.s=fixture();self.items=items(self.s);self.f=Fake(self.s)
 def prepare(self):return prepare('head',self.s,self.items,validator,NOW)
 def test_five_rows_one_cas(self):
  p=self.prepare();r=fake_send(p,self.f,validator,self.items,NOW)
  self.assertEqual(r['status'],'accepted');self.assertEqual(self.f.calls,1);self.assertFalse(r['external_request_permitted']);self.assertEqual(self.f.state['terra'],self.s['terra'])
 def test_lost_ack_readback_no_replay(self):
  p=self.prepare();self.f.lose=True;r=fake_send(p,self.f,validator,self.items,NOW);self.assertEqual(r['status'],'accepted');self.assertEqual(self.f.calls,1)
 def test_resume_exact_rows_no_new_write(self):
  p=self.prepare();fake_send(p,self.f,validator,self.items,NOW)
  p=prepare(*self.f.read(),self.items,validator,NOW);self.assertEqual(p['payload']['items'],[])
  fake_send(p,self.f,validator,self.items,NOW);self.assertEqual(self.f.calls,1)
 def test_conflict_does_not_overwrite(self):
  p=self.prepare();self.f.conflict=True
  with self.assertRaises(Conflict):fake_send(p,self.f,validator,self.items,NOW)
  self.assertTrue(self.f.state['terra']['new']);self.assertEqual(self.f.state['koyo_index_handoffs'][KEY]['rows'],{})
 def test_rebase_preserves_other_work(self):
  self.s['terra']['new']=True;p=self.prepare();self.assertTrue(p['payload']['after']['terra']['new'])
 def test_target_conflict(self):
  self.s['koyo_index_handoffs'][KEY]['context']['0']['cache']['changed']=True
  with self.assertRaises(Conflict):self.prepare()
 def test_lease_and_scope(self):
  for field,value in [('token','new'),('until',110),('owner','terra')]:
   s=fixture();s['koyo_index_handoffs'][KEY]['lease'][field]=value
   with self.assertRaises(Refused):prepare('head',s,self.items,validator,NOW)
 def test_invalid_member_atomic_reject(self):
  item=self.items[2];item['payload']['after']['rows']['valid']=False;item['sha256']=digest(item['payload'])
  with self.assertRaises(Refused):self.prepare()
  self.assertEqual(self.f.calls,0)
 def test_reservation_required_and_preserved(self):
  s=fixture();del s['koyo_index_handoffs'][KEY]['context']['0']['fetch_started']
  with self.assertRaises(Refused):items(s,1)
  a=copy.deepcopy(self.s);h=a['koyo_index_handoffs'][KEY];h['rows']['0']={'post_id':'0'};h['context']['0']['fetch_started']=2
  with self.assertRaises(Refused):stage(self.s,a,KEY,'0','finalize-post',NOW)
 def test_journal_roundtrip(self):
  with tempfile.TemporaryDirectory() as d:
   p=self.prepare();path=Path(d)/'outbox.json';save_journal(path,p);self.assertEqual(json.loads(path.read_text()),p)
 def test_due_five_or_ten_minutes(self):
  self.assertTrue(due(self.items,NOW));self.assertFalse(due(self.items[:1],NOW+599));self.assertTrue(due(self.items[:1],NOW+600));self.assertFalse(due([],NOW))
 def test_tamper_duplicate_limit(self):
  for bad in ([self.items[0]]*2,self.items+[self.items[0]]):
   with self.assertRaises(Refused):prepare('head',self.s,bad,validator,NOW)
  self.items[0]['payload']['staged_at']=0
  with self.assertRaises(Refused):self.prepare()
 def test_advanced_head_requires_reconcile(self):
  p=self.prepare();s=copy.deepcopy(p['payload']['after']);s['terra']['new']=True
  self.assertEqual(reconcile(p,'advanced',s)['status'],'reconcile_required')
 def test_live_adapter_rejected(self):
  self.f.offline_fixture_only=False
  with self.assertRaises(Refused):fake_send(self.prepare(),self.f,validator,self.items,NOW)
if __name__=='__main__':unittest.main()
