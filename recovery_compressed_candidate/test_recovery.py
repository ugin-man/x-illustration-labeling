import copy,json,sys,unittest
sys.path.insert(0,'/tmp/x-recovery-isolated')
from recovery_adapter import *
S=json.load(open('/tmp/x-state-recovery.json'))
K=next(k for k,h in S['koyo_index_handoffs'].items() if h['job_id']=='prod-0002')
H=S['koyo_index_handoffs'][K];PID=H['plan']['payload']['source']['post_ids'][16]
class Tests(unittest.TestCase):
 def setUp(self):
  self.s=OfflineStore(S);self.a=Adapter(self.s,K,H['lease']['token'],H['lease']['until']-1)
 def test_plan_digest(self):self.assertEqual(sha(H['plan']['payload']),K)
 def test_snapshot_counts(self):self.assertEqual(sorted(len(h['rows']) for h in S['koyo_index_handoffs'].values()),[16,50])
 def test_reservation_preserves_terra_and_all_existing_rows(self):
  before=copy.deepcopy(self.s.state);self.a.reserve_body(self.s.head,PID)
  self.assertEqual(before['entries'],self.s.state['entries'])
  for k,h in before['koyo_index_handoffs'].items():self.assertEqual(h['rows'],self.s.state['koyo_index_handoffs'][k]['rows'])
 def test_repeat_fetch_blocked(self):
  self.a.reserve_body(self.s.head,PID)
  with self.assertRaises(Refused):self.a.reserve_body(self.s.head,PID)
 def test_crash_after_reserve_blocks_restart(self):
  self.a.reserve_body(self.s.head,PID);fresh=Adapter(self.s,K,H['lease']['token'],H['lease']['until']-1)
  with self.assertRaises(Refused):fresh.reserve_body(self.s.head,PID)
 def test_lost_ack_does_not_allow_replay(self):
  old=self.s.head;self.a.reserve_body(old,PID)
  with self.assertRaises(Stale):self.a.reserve_body(old,PID)
  with self.assertRaises(Refused):self.a.reserve_body(self.s.head,PID)
 def test_stale_cas(self):
  old=self.s.head;self.a.reserve_body(old,PID)
  with self.assertRaises(Stale):self.s.cas(old,S)
 def test_existing_body_cache_blocked(self):
  for pid in H['context']:
   with self.assertRaises(Refused):self.a.reserve_body(self.s.head,pid)
 def test_terra_post_blocked(self):
  with self.assertRaises(Refused):self.a.reserve_body(self.s.head,'terra-unowned-post')
 def test_expired_lease(self):
  self.a.now=H['lease']['until']
  with self.assertRaises(Refused):self.a.reserve_body(self.s.head,PID)
 def test_wrong_token(self):
  self.a.token='wrong'
  with self.assertRaises(Refused):self.a.reserve_body(self.s.head,PID)
 def test_no_cache_without_reservation(self):
  with self.assertRaises(Refused):self.a.cache_body(self.s.head,PID,{'post_id':PID,'state':'technical_failure','text':None})
 def test_cache_failure_is_final(self):
  self.a.reserve_body(self.s.head,PID);c={'post_id':PID,'state':'technical_failure','text':None}
  self.a.cache_body(self.s.head,PID,c)
  with self.assertRaises(Refused):self.a.reserve_body(self.s.head,PID)
  with self.assertRaises(Refused):self.a.cache_body(self.s.head,PID,dict(c,state='available',text='replacement'))
 def test_mutation_guard(self):
  p=next(iter(H['rows']))
  def bad(h):h['rows'][p]['review_flags'].append('bad')
  with self.assertRaises(Refused):self.a.transition(self.s.head,p,bad)
  self.assertEqual(self.s.state,S)
 def test_other_handoff_untouched(self):
  other=next(k for k in S['koyo_index_handoffs'] if k!=K);self.a.reserve_body(self.s.head,PID)
  self.assertEqual(S['koyo_index_handoffs'][other],self.s.state['koyo_index_handoffs'][other])
if __name__=='__main__':unittest.main(verbosity=2)
