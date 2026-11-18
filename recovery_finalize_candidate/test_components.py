import copy,json,sys,tempfile,subprocess,unittest
from pathlib import Path
sys.path.insert(0,'/tmp/x-recovery-isolated')
from runtime_components import *
S=json.load(open('/tmp/x-state-recovery.json'));K=next(k for k,h in S['koyo_index_handoffs'].items() if h['job_id']=='prod-0002');H=S['koyo_index_handoffs'][K]
class Components(unittest.TestCase):
 def test_activation_preserves_state_and_detects_drift(self):
  old=copy.deepcopy(S);a=activation(S,'head',K,[__file__]);self.assertTrue(verify_activation(a,S,'head',K));self.assertEqual(old,S)
  with self.assertRaises(Refused):verify_activation(a,S,'changed',K)
 def test_activation_code_drift(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'code';p.write_text('one');a=activation(S,'head',K,[p]);p.write_text('two')
   with self.assertRaises(Refused):verify_activation(a,S,'head',K)
 def test_all_accepted_rows_and_image_events(self):
  for h in S['koyo_index_handoffs'].values():
   pins=PinnedInputs('/tmp/x-recovery-isolated',h)
   for pid,row in h['rows'].items():self.assertTrue(pins.validate_row(row,h['events'][pid]))
 def test_wrong_provenance(self):
  pins=PinnedInputs('/tmp/x-recovery-isolated',H);pid=next(iter(H['rows']));r=copy.deepcopy(H['rows'][pid]);r['provenance']['model_id']='invented'
  with self.assertRaises(AssertionError):pins.validate_row(r,H['events'][pid])
 def test_other_post_image_event_not_reusable(self):
  pins=PinnedInputs('/tmp/x-recovery-isolated',H);pid=next(iter(H['rows']));ev=copy.deepcopy(H['events'][pid]);ev[0]['post_id']='another-post'
  with self.assertRaises(Refused):pins.validate_row(H['rows'][pid],ev)
 def test_image_wrong_bytes(self):
  pins=PinnedInputs('/tmp/x-recovery-isolated',H);pid=next(iter(H['rows']))
  with tempfile.NamedTemporaryFile() as f:
   f.write(b'not image');f.flush()
   with self.assertRaises(Refused):pins.image_event(pid,1,f.name,{'tool':'view_image','tool_call_id':'receipt','at':'time'})
 def test_clock_wait_union(self):
  c=ExplorationClock(0);c.reserve('s1','search','query',2);c.ack('s1','a'*64,12);c.management_wait(10,14,'fetch')
  self.assertEqual(c.elapsed(20),8);seal=c.seal(20);self.assertEqual(seal['wall_seconds'],20)
 def test_clock_limits(self):
  c=ExplorationClock(0)
  for i in range(2):c.reserve(str(i),'search','query',i);c.ack(str(i),'a'*64,i)
  with self.assertRaises(Refused):c.reserve('3','search','query',3)
  d=ExplorationClock(0)
  for i in range(3):d.reserve(str(i),'page','https://example.com',i);d.ack(str(i),'a'*64,i)
  with self.assertRaises(Refused):d.reserve('4','page','https://example.com',4)
 def test_clock_expired(self):
  with self.assertRaises(Refused):ExplorationClock(0).reserve('s','search','q',60)
 def test_unacked_no_restart_or_second_query(self):
  c=ExplorationClock(0);c.reserve('s','search','q',1)
  with self.assertRaises(Refused):c.reserve('s2','search','q',2)
  with self.assertRaises(Refused):c.seal(3)
 def test_no_clock_reset(self):
  context={'budget':{'started_at':1}}
  with self.assertRaises(Refused):ExplorationClock.preserve_legacy(context)
  c=next(c for c in H['context'].values() if 'exploration_clock' in c)
  self.assertEqual(ExplorationClock.preserve_legacy(c),c)
 def test_clock_rollback(self):
  c=ExplorationClock(10)
  with self.assertRaises(Refused):c.elapsed(9)
 def test_ack_immutable(self):
  c=ExplorationClock(0);c.reserve('s','search','q',1);c.ack('s','a'*64,2)
  with self.assertRaises(Refused):c.ack('s','b'*64,3)
 def test_local_transport_lost_ack_and_stale(self):
  with tempfile.TemporaryDirectory() as d:
   subprocess.run(['git','init','--bare',d],capture_output=True,check=True);t=LocalGitTransport(d);a=t.commit(S);t.git('update-ref','refs/heads/recovery-test',a,'0'*40)
   s=copy.deepcopy(S);s['isolation_fixture']=True;r=t.cas(a,s,lose_ack=True)
   self.assertTrue(r['accepted']);self.assertFalse(r['request_permission']);self.assertEqual(t.read(),s)
   with self.assertRaises(Stale):t.cas(a,S)
 def test_transport_rejects_remote(self):
  with tempfile.TemporaryDirectory() as d:
   subprocess.run(['git','init','--bare',d],capture_output=True,check=True);subprocess.run(['git','--git-dir',d,'remote','add','origin','https://github.com/ugin-man/x-illustration-labeling.git'],capture_output=True,check=True)
   with self.assertRaises(Refused):LocalGitTransport(d)
if __name__=='__main__':unittest.main(verbosity=2)
