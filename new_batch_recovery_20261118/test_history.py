import json,tempfile,subprocess,unittest
from pathlib import Path
from next_batch import collect_local_history
class History(unittest.TestCase):
 def test_full_ancestry_detects_even_reverted_claim(self):
  with tempfile.TemporaryDirectory() as d:
   def git(*a):return subprocess.run(['git','-C',d,*a],check=True,capture_output=True).stdout.decode().strip()
   git('init');git('config','user.email','fixture@example.invalid');git('config','user.name','fixture')
   e={'status':'pending','post_count':50,'completed_posts':0,'worker_id':None,'dispatch_token':None,'head':None,'lease_until':0,'retry_after':0,'updated_at':0}
   def commit(state):
    Path(d,'state.json').write_text(json.dumps(state));git('add','state.json');git('commit','-m','fixture');return git('rev-parse','HEAD')
   state={'entries':{'prod-0003':e}};one=commit(state);proof=collect_local_history(d,one,'prod-0003');self.assertFalse(proof['ever_touched']);self.assertEqual(proof['verified_commit_count'],1)
   e['worker_id']='terra';commit(state);e['worker_id']=None;last=commit(state);proof=collect_local_history(d,last,'prod-0003')
   self.assertTrue(proof['ever_touched']);self.assertEqual(proof['verified_commit_count'],3)
if __name__=='__main__':unittest.main()
