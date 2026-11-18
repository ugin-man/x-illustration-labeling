import copy,json,tempfile,unittest,hashlib
from pathlib import Path
from git_adapters import *
from local_gitdata_fixture import LocalGitData
from test_checkpoint import fixture,items,validator,NOW,KEY
BASE=Path(__file__).parent
def gate(role):
 return ReviewGate(REPO,ARCHIVE if role=='archive' else DISPATCH,role,{str((BASE/f).resolve()):hashlib.sha256((BASE/f).read_bytes()).hexdigest() for f in ('git_adapters.py','checkpoint.py','stage_recovery.py')},'isolated test only')
class GitAdapters(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.io=LocalGitData(Path(self.tmp.name)/'remote.git');self.s=fixture();self.items=items(self.s)
  self.io.seed(ARCHIVE,{'README':'fixture archive'});self.io.seed(DISPATCH,{'state.json':canonical(self.s),'other.txt':'preserve'})
  self.archive=GitHubArchive(self.io,gate('archive'));self.writer=GitHubAggregate(self.io,gate('aggregate'));self.journal=Path(self.tmp.name)/'outbox.json'
 def tearDown(self):self.tmp.cleanup()
 def archive_all(self):
  for x in self.items:self.assertEqual(self.archive.put(x)['status'],'accepted')
 def publish(self):return self.writer.publish(self.items,validator,self.archive,self.journal,lambda:NOW)
 def test_archive_and_aggregate_roundtrip(self):
  self.archive_all();updates=self.io.updates;r=self.publish();self.assertEqual(r['status'],'accepted');self.assertEqual(self.io.updates-updates,1)
  h,s,c=self.writer.read_state();self.assertEqual(len(s['koyo_index_handoffs'][KEY]['rows']),5);self.assertEqual(s['terra'],self.s['terra']);self.assertIn('other.txt',self.io.list_tree(REPO,c['tree']))
 def test_reset_restores_git_archive_no_local_stage(self):
  self.archive_all();archive=GitHubArchive(LocalGitData(self.io.root),gate('archive'));self.assertEqual(len(archive.restore(KEY)['stages']),5)
  self.items=archive.restore(KEY)['stages'];self.assertEqual(self.publish()['status'],'accepted')
 def test_archive_lost_ack_no_duplicate_commit(self):
  self.io.lose_ack=True;r=self.archive.put(self.items[0]);self.assertEqual(r['status'],'accepted');n=self.io.updates
  self.assertEqual(self.archive.put(self.items[0])['status'],'accepted');self.assertEqual(self.io.updates,n)
 def test_aggregate_lost_ack_reconciles(self):
  self.archive_all();self.io.lose_ack=True;self.assertEqual(self.publish()['status'],'accepted');n=self.io.updates
  self.assertEqual(self.publish()['status'],'accepted');self.assertEqual(self.io.updates,n)
 def test_archive_missing_blocks_aggregate(self):
  with self.assertRaises(Refused):self.publish()
  self.assertEqual(self.io.updates,0)
 def test_permission_denial_no_retry(self):
  self.archive_all();self.io.deny=True;n=self.io.updates
  with self.assertRaises(PermissionDenied):self.publish()
  self.assertEqual(self.io.updates,n+1);self.assertEqual(json.loads(self.journal.read_text())['status'],'permission_denied')
 def test_lease_expiry_while_constructing_commit(self):
  self.archive_all();clock=[NOW];self.io.create_hook=lambda:clock.__setitem__(0,990);n=self.io.updates
  with self.assertRaises(Refused):self.writer.publish(self.items,validator,self.archive,self.journal,lambda:clock[0])
  self.assertEqual(self.io.updates,n)
 def test_cas_competitor_no_overwrite(self):
  self.archive_all()
  def race(branch,expected,sha):
   s=copy.deepcopy(self.s);s['terra']['concurrent']='preserved';tree=self.io.create_tree(REPO,self.io.get_commit(REPO,expected)['tree'],{'state.json':canonical(s)});other=self.io.create_commit(REPO,tree,expected,'concurrent worker');self.io.git('update-ref','refs/heads/'+branch,other,expected)
  self.io.update_hook=race;r=self.publish();self.assertEqual(r['status'],'reconcile_required');self.assertEqual(self.writer.read_state()[1]['terra']['concurrent'],'preserved')
 def test_ambiguous_before_commit_never_retried(self):
  self.archive_all();n=self.io.updates
  def before_send(*args):raise TimeoutError('did not reach server')
  self.io.update_hook=before_send
  self.assertEqual(self.publish()['status'],'not_accepted');self.assertEqual(self.io.updates,n+1)
 def test_unknown_readback_keeps_candidate_journal(self):
  self.archive_all();original=self.io.get_ref
  def lost_read(repo,branch):
   if self.io.lose_ack and branch==DISPATCH:raise TimeoutError('readback unavailable')
   return original(repo,branch)
  self.io.get_ref=lost_read
  self.io.update_hook=lambda *args:setattr(self.io,'lose_ack',True)
  with self.assertRaises(TimeoutError):self.publish()
  self.assertEqual(json.loads(self.journal.read_text())['status'],'candidate')
 def test_expiry_inside_cas_reported_not_hidden(self):
  # GitHub cannot test lease time atomically: demonstrate and expose that limitation.
  self.archive_all();clock=[NOW];self.io.update_hook=lambda *args:clock.__setitem__(0,1001)
  r=self.writer.publish(self.items,validator,self.archive,self.journal,lambda:clock[0])
  self.assertEqual(r['status'],'accepted');self.assertTrue(r['lease_expired_after_send']);self.assertFalse(r['continue_without_renewal'])
 def test_bad_pins_wrong_branch_live_adapter_rejected(self):
  g=gate('archive');g.branch='main'
  with self.assertRaises(Refused):GitHubArchive(self.io,g)
  g=gate('archive');g.pins[next(iter(g.pins))]='bad'
  with self.assertRaises(Refused):GitHubArchive(self.io,g)
  self.io.offline_fixture_only=False
  with self.assertRaises(Refused):GitHubArchive(self.io,gate('archive'))
 def test_archive_conflict_preserves_existing(self):
  self.archive.put(self.items[0]);bad=copy.deepcopy(self.items[0]);bad['payload']['lease_token']='new';bad['sha256']=digest(bad['payload']);self.archive.put(bad)
  self.assertIn('0',self.archive.restore(KEY)['conflicts'])
  with self.assertRaises(Refused):self.archive.verify(self.items[0])
if __name__=='__main__':unittest.main()
