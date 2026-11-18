"""Integration test: actual fixed schema, pinned manifest, source scope, view receipts.
Local-only synthetic body/results; no file mutations outside temporary directories.
"""
import copy,sys,unittest
sys.path.insert(0,'/tmp/koyo-checkpoint-candidate/legacy')
import test_finalize_post as orig
import zero_search as z
class FixedZero(unittest.TestCase):
 def test_actual_fixed_validator_and_preservation(self):
  f=orig.Finalize();f.setUp()
  try:
   reservation,completed,pid=f.fixture();k=orig.K;before=copy.deepcopy(completed)
   row=before['koyo_index_handoffs'][k]['rows'].pop(pid)
   text='This is my original illustration. This is not a promotion.'
   before['koyo_index_handoffs'][k]['context'][pid]['cache']={'post_id':pid,'state':'available','text':text}
   c=row['context'];c.update(state='complete',stop_reason='evidence_sufficient',searches=0,pages=0,elapsed_seconds=0)
   src={'url':'https://x.com/fixture/status/'+pid,'accessed_at':'2026-11-18T00:00:00Z','kind':'post_text'}
   c['attributes']['creation'].update(status='observed',value='original',reason='synthetic fixture explicit claim',evidence='original illustration',sources=[src])
   c['attributes']['promotion'].update(status='observed',value=False,reason='synthetic fixture explicit claim',evidence='not a promotion',sources=[src])
   after=copy.deepcopy(before);after['koyo_index_handoffs'][k]['rows'][pid]=row
   def guard(b,a,key,p,token,now):
    # Existing fixed scope identity + paused scheduler + complete preservation.
    from next_batch import require_scheduler_permission
    require_scheduler_permission(b,key)
    if p not in f.payload['scope']['post_ids'] or p in f.payload['scope']['held_post_ids']:raise ValueError('scope')
    if any(a['koyo_index_handoffs'][key]['rows'].get(p)!=r for p,r in f.payload['baseline_rows'].items()):raise ValueError('baseline')
    f.w.preservation(b,a)
   pins=orig.PinnedInputs('/tmp/x-recovery-isolated',before['koyo_index_handoffs'][k])
   self.assertTrue(z.validate(before,after,k,pid,orig.H['lease']['token'],orig.NOW,guard,pins.validate_row))
   bad=copy.deepcopy(before);bad['koyo_index_handoffs'][k]['events'][pid]=[]
   bad_after=copy.deepcopy(after);bad_after['koyo_index_handoffs'][k]['events'][pid]=[]
   with self.assertRaises(Exception):z.validate(bad,bad_after,k,pid,orig.H['lease']['token'],orig.NOW,guard,pins.validate_row)
   row['context']['attributes']['creation']['value']='invalid-contract-value'
   with self.assertRaises(AssertionError):z.validate(before,after,k,pid,orig.H['lease']['token'],orig.NOW,guard,pins.validate_row)
  finally:f.tearDown()
