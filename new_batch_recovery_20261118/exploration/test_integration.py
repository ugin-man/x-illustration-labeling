import copy,json,tempfile,unittest
from pathlib import Path
from exploration import *
from persistent_runner import *
B={'plan_sha256':'a'*64,'post_id':'123','worker':'koyo','lease_token':'token'}
class Fake:
 def __init__(self):
  self.t=100.;self.head='a'*40;self.state={'context':{'123':{'clock':new_clock(B)}},'terra':{'unchanged':[1]},'rows':{'old':'keep'}};self.calls=[];self.ack=True;self.expiry=10000
 def snap(self):return self.head,copy.deepcopy(self.state)
 def guard(self,h,s,b):
  if b!=B:raise Refused('binding')
  return self.expiry
 def publish(self,h,b,a,events):
  assert h==self.head and b==self.state
  self.t+=100;self.head=hashlib.sha1(canonical(a)).hexdigest();self.state=copy.deepcopy(a)
  return {'ref_update_acknowledged':self.ack,'external_request_permitted':self.ack,'accepted':True,'candidate':self.head,'state_sha256':digest(a)},self.head,copy.deepcopy(a)
 def tool(self,k,q):self.calls.append((k,q));self.t+=2;return {'result':'fixture'}
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'runner.db';self.f=Fake();self.s=Store.initialize(self.path,new_clock(B));self.make()
 def tearDown(self):self.s.close();self.tmp.cleanup()
 def make(self):self.r=Runner(self.s,('context','123','clock'),self.f.snap,self.f.publish,self.f.guard,self.f.tool,lambda:self.f.t,lambda:self.f.t)
 def test_two_search_three_page_e2e(self):
  original=copy.deepcopy(self.f.state)
  for i,kind in enumerate(['search','search','page','page','page']):
   self.r.reserve(str(i),kind,['query' if kind=='search' else 'url']);self.r.dispatch(str(i));self.f.t+=1
  c=self.r.seal();self.assertEqual(c['seal']['elapsed_seconds'],15);self.assertEqual((c['searches'],c['pages']),(2,3));self.r.flush_seal()
  self.assertEqual(self.f.state['terra'],original['terra']);self.assertEqual(self.f.state['rows'],original['rows']);self.assertEqual(get_path(self.f.state,self.r.path),c)
  row={'post_id':'123','exploration_receipt':{'revision':VERSION,'clock_sha256':digest(c),'seal':c['seal']}};self.assertTrue(validate_sealed_row(c,row));row['exploration_receipt']['clock_sha256']='bad'
  with self.assertRaises(Refused):validate_sealed_row(c,row)
 def test_restart_ack_persists_and_one_use(self):
  self.r.reserve('s','search',['q']);self.s.close();self.s=Store(self.path);self.make();self.r.dispatch('s');self.s.close();self.s=Store(self.path);self.make()
  with self.assertRaises(Refused):self.r.dispatch('s')
  self.assertEqual(len(self.f.calls),1)
 def test_ack_lost_remote_accepted_blocked(self):
  self.f.ack=False
  with self.assertRaises(Refused):self.r.reserve('s','search',['q'])
  self.s.close();self.s=Store(self.path);self.make()
  with self.assertRaises(Refused):self.r.dispatch('s')
  self.assertEqual(self.f.calls,[])
 def test_dispatch_current_head(self):
  self.r.reserve('s','search',['q']);self.f.head='b'*40
  with self.assertRaises(Refused):self.r.dispatch('s')
 def test_dispatch_current_lease(self):
  self.r.reserve('s','search',['q']);self.f.expiry=self.f.t
  with self.assertRaises(Refused):self.r.dispatch('s')
 def test_dispatch_sixty(self):
  self.r.reserve('s','search',['q']);self.f.t+=60
  with self.assertRaises(Refused):self.r.dispatch('s')
 def test_journal_failure_no_call(self):
  self.r.reserve('s','search',['q']);self.s.db.execute("CREATE TRIGGER fail BEFORE UPDATE ON runner BEGIN SELECT RAISE(ABORT,'journal unavailable'); END")
  with self.assertRaises(sqlite3.IntegrityError):self.r.dispatch('s')
  self.assertEqual(self.f.calls,[])
 def test_tool_crash_no_replay_restart(self):
  self.r.reserve('s','search',['q'])
  def fail(k,q):self.f.calls.append((k,q));raise RuntimeError('lost tool response')
  self.r.external=fail
  with self.assertRaises(RuntimeError):self.r.dispatch('s')
  self.s.close();self.s=Store(self.path);self.make()
  with self.assertRaises(Refused):self.r.dispatch('s')
  with self.assertRaises(Refused):self.r.seal()
  self.assertEqual(len(self.f.calls),1)
 def test_missing_store(self):
  with self.assertRaises(Refused):Store(Path(self.tmp.name)/'lost.db')
  with self.assertRaises(FileExistsError):Store.initialize(self.path,new_clock(B))
 def test_full_state_readback_wrong(self):
  old=self.r.publish
  def wrong(*a):r,h,s=old(*a);s['terra']['changed']=True;return r,h,s
  self.r.publish=wrong
  with self.assertRaises(Refused):self.r.reserve('s','search',['q'])
  self.assertEqual(self.f.calls,[])
 def test_measured_wait_deduction(self):
  self.r.reserve('s','search',['q']);self.r.dispatch('s')
  def git(*args):self.f.t+=40;return 'ok'
  measured_git_read(self.r,'s',git,'fetch','fixed-remote');c=self.r.seal();self.assertEqual(c['seal']['elapsed_seconds'],2)
 def test_writer_other_namespace(self):
  before=self.f.state;after=copy.deepcopy(before);after['terra']['changed']=True
  with self.assertRaises(Refused):validate_full_write(before,after,self.r.path,[],Authority())
 def test_writer_changed_historical_clock(self):
  before=copy.deepcopy(self.f.state);before['old_clock']={'version':'v2','elapsed':4.3};after=copy.deepcopy(before);after['old_clock']['elapsed']=0
  with self.assertRaises(Refused):validate_full_write(before,after,self.r.path,[],Authority())
 def test_authority_corruption_fails_closed(self):
  self.r.reserve('s','search',['q']);d=json.loads(self.s.db.execute('select payload from runner').fetchone()[0]);d['key']='00'*32;self.s.db.execute('update runner set payload=?',(json.dumps(d),))
  with self.assertRaises(Refused):self.r.dispatch('s')

if __name__=='__main__':unittest.main()
