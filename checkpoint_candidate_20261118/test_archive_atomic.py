import copy,tempfile,unittest
from concurrent.futures import ThreadPoolExecutor
from stage_recovery import *
from checkpoint import digest
from test_checkpoint import fixture,items,KEY
class ArchiveAtomic(unittest.TestCase):
 def test_concurrent_immutable_conflict(self):
  with tempfile.TemporaryDirectory() as d:
   a=FixtureArchive(d)
   def write(n):
    try:a.put_if_absent('same.json',{'version':n});return n
    except Refused:return None
   with ThreadPoolExecutor(2) as pool:r=list(pool.map(write,[1,2]))
   winners=[x for x in r if x is not None];self.assertEqual(len(winners),1);self.assertEqual(a.get('same.json'),{'version':winners[0]})
 def test_timestamp_duplicate_safe_result_conflict_quarantined(self):
  it=items(fixture(),2)
  with tempfile.TemporaryDirectory() as d:
   a=FixtureArchive(d)
   for x in it:archive(x,a)
   dup=copy.deepcopy(it[0]);dup['payload']['staged_at']+=1;dup['sha256']=digest(dup['payload']);archive(dup,a)
   self.assertEqual(len(restore_available(KEY,a)['stages']),2)
   bad=copy.deepcopy(it[0]);bad['payload']['after']['rows']['valid']=False;bad['sha256']=digest(bad['payload']);archive(bad,a)
   result=restore_available(KEY,a);self.assertEqual(len(result['stages']),1);self.assertIn('0',result['conflicts'])
 def test_new_token_never_auto_adopted(self):
  it=items(fixture(),1)[0]
  with tempfile.TemporaryDirectory() as d:
   a=FixtureArchive(d);archive(it,a)
   new=copy.deepcopy(it);new['payload']['lease_token']='new';new['sha256']=digest(new['payload']);archive(new,a)
   self.assertEqual(restore_available(KEY,a)['stages'],[])
if __name__=='__main__':unittest.main()
