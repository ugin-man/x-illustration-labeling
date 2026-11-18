import sys,copy,unittest
sys.path.insert(0,'/tmp/koyo-checkpoint-candidate/legacy')
import test_finalize_post as original
import checkpoint as cp
class Integration(unittest.TestCase):
 def test_real_fixed_validator_five_finalizations(self):
  f=original.Finalize();f.setUp()
  try:
   b,a,p=f.fixture();k=original.K;h=b['koyo_index_handoffs'][k];ids=original.PLAN[18:23]
   # Build only synthetic results from existing fixed-contract fixture, never real views.
   states=[]
   for pid in ids:
    h['context'][pid]=copy.deepcopy(h['context'][p])
   for pid in ids:
    out=copy.deepcopy(b);oh=out['koyo_index_handoffs'][k];pins=original.PinnedInputs('/tmp/x-recovery-isolated',h);post=pins.posts[pid]
    oh['context'][pid]=copy.deepcopy(a['koyo_index_handoffs'][k]['context'][p]);oh['context'][pid]['cache']['post_id']=pid
    row=copy.deepcopy(a['koyo_index_handoffs'][k]['rows'][p]);row['post_id']=pid
    row['images']=[dict(copy.deepcopy(row['images'][0]),media_index=im['media_index'],sha256=im['sha256']) for im in post['images']]
    oh['rows'][pid]=row
    oh['events'][pid]=[{'post_id':pid,'media_index':im['media_index'],'sha256':im['sha256'],'outcome':'viewed','tool':'fixture-only','tool_call_id':'isolated-not-real','at':'fixture'} for im in post['images']]
    states.append(cp.stage(b,out,k,pid,'finalize-post',original.NOW))
   calls=[]
   def validate(before,after,operation,token,pid):
    f.w.authorize_transition(before,after,operation,token);f.w.preservation(before,after);calls.append(pid)
   result=cp.prepare('fixture-head',b,states,validate,original.NOW)
   self.assertEqual(calls,ids);self.assertEqual(result['payload']['after']['entries'],b['entries'])
   self.assertEqual(len(result['payload']['after']['koyo_index_handoffs'][k]['rows']),len(h['rows'])+5)
  finally:f.tearDown()
