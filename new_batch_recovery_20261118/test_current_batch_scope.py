import unittest,copy,json,tempfile,subprocess
from pathlib import Path
import sys
sys.path.insert(0,'/tmp/x-recovery-isolated')
from network_runtime import *
from runtime_components import digest
S=json.load(open(Path(__file__).with_name('live-final-state.json')));K=next(k for k,h in S['koyo_index_handoffs'].items() if h['job_id']=='prod-0002');H=S['koyo_index_handoffs'][K];PLAN=H['plan']['payload']['source']['post_ids'];NOW=H['lease']['until']-100
class Scope(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();subprocess.run(['git','init','--bare',self.tmp.name],capture_output=True,check=True)
  files=[Path(__file__).with_name(f).resolve() for f in ('network_runtime.py','recovery_adapter.py','runtime_components.py')]
  self.payload={'mode':'reviewed-live','review_reference':'isolation test','plan_sha256':K,'code_sha256':{str(f):digest(f) for f in files},'baseline_rows':copy.deepcopy(H['rows']),'scope':{'kind':'current-batch-prod-0002-v1','job_id':'prod-0002','post_ids':PLAN[18:],'held_post_ids':[PLAN[16]],'max_new_rows':32,'external_exploration':False,'allow_recorded_source_failure':True}}
  self.w=IndexWriter(self.tmp.name,S['catalog_sha256'],K,'/tmp/x-recovery-isolated',clock=lambda:NOW);self.w.live=True;self.w.activation_document={'payload':self.payload,'sha256':sha(self.payload)}
 def tearDown(self):self.w.close();self.tmp.cleanup()
 def reserve(self,pid):
  a=copy.deepcopy(S);a['koyo_index_handoffs'][K]['context'][pid]={'fetch_started':NOW,'recovery_revision':'recovery-prototype-1','attempt_limit':1};return a
 def check(self,a,op='body-reserve'):self.w.authorize_transition(S,a,op,H['lease']['token']);self.w.preservation(S,a)
 def test_all_exact_32_posts_allowed(self):
  self.assertEqual(len(PLAN[18:]),32)
  for pid in PLAN[18:]:self.check(self.reserve(pid))
 def test_held_17_refused(self):
  with self.assertRaises(Refused):self.check(self.reserve(PLAN[16]))
 def test_accepted_18_refused(self):
  with self.assertRaises(Refused):self.check(self.reserve(PLAN[17]))
 def test_two_post_change_refused(self):
  a=self.reserve(PLAN[18]);a['koyo_index_handoffs'][K]['context'][PLAN[19]]=copy.deepcopy(a['koyo_index_handoffs'][K]['context'][PLAN[18]])
  with self.assertRaises(Refused):self.check(a)
 def test_missing_baseline_refused(self):
  self.payload['baseline_rows'].pop(next(iter(H['rows'])));self.w.activation_document['sha256']=sha(self.payload)
  with self.assertRaises(Refused):self.check(self.reserve(PLAN[18]))
 def test_widened_scope_refused(self):
  self.payload['scope']['post_ids']=[PLAN[16]]+PLAN[18:];self.w.activation_document['sha256']=sha(self.payload)
  with self.assertRaises(Refused):self.check(self.reserve(PLAN[18]))
 def test_other_handoff_or_terra_refused(self):
  a=self.reserve(PLAN[18]);a['entries']['prod-0049']['worker_id']='koyo'
  with self.assertRaises(Refused):self.check(a)
 def test_existing_accepted_row_edit_refused(self):
  a=copy.deepcopy(S);a['koyo_index_handoffs'][K]['rows'][PLAN[0]]['review_flags'].append('changed')
  with self.assertRaises(Refused):self.check(a,'save-row')
 def test_exploration_refused(self):
  a=self.reserve(PLAN[18])
  with self.assertRaises(Refused):self.check(a,'exploration')
 def test_cli_live_push_disabled(self):
  with self.assertRaises(Refused):self.w.publish('unused',S,self.reserve(PLAN[18]),operation='body-reserve',lease_token=H['lease']['token'])
if __name__=='__main__':unittest.main(verbosity=2)
