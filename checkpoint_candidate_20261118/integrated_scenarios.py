import unittest,tempfile,json,time,copy
from pathlib import Path
from synthetic_integrated import DATA,ROOT,IndexWriter
from integration_driver import *
from git_adapters import GitHubArchive,GitHubAggregate,REPO,ARCHIVE,DISPATCH
from local_gitdata_fixture import LocalGitData
from test_git_adapters import gate
class Integrated(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.d=json.loads(DATA.read_text());self.b=self.d['before'];self.key=self.d['key'];self.io=LocalGitData(Path(self.tmp.name)/'remote');self.io.seed(ARCHIVE,{'README':'synthetic'});head=self.io.seed(DISPATCH,{'state.json':json.dumps(self.b),'untouched':'keep'})
  self.w=IndexWriter(str(self.io.root),self.b['catalog_sha256'],self.key,str(ROOT),activation_document=self.d['activation']);self.w.live=True
  self.plan=deployment_plan(self.b,self.key,head,self.d['activation'],[Path(__file__),Path('integration_driver.py')])
  self.a=GitHubArchive(self.io,gate('archive'));self.g=GitHubAggregate(self.io,gate('aggregate'));self.c=IntegratedWorker(self.w,self.a,self.g,self.plan,Path(self.tmp.name)/'outbox')
 def tearDown(self):self.w.close();self.tmp.cleanup()
 def stage(self,index=0):
  item=self.d['items'][index];p=item['payload'];a=apply(self.b,self.key,p['pid'],p['after']);self.c.preserve_completed(self.b,a,p['pid'])
 def test_real_scope_stage_reset_checkpoint(self):
  self.stage(0);self.stage(1)
  fresh=IntegratedWorker(self.w,GitHubArchive(LocalGitData(self.io.root),gate('archive')),GitHubAggregate(LocalGitData(self.io.root),gate('aggregate')),self.plan,Path(self.tmp.name)/'new-process-outbox')
  r=fresh.restore_and_select();self.assertEqual(len(r['ready']),2);self.assertEqual(len(r['selection']['pending_staged']),2)
  self.assertEqual(fresh.checkpoint(force=True)['status'],'accepted')
  self.assertEqual(len(fresh.aggregate.read_state()[1]['koyo_index_handoffs'][self.key]['rows']),2)
  n=self.io.updates;self.assertEqual(fresh.checkpoint(force=True)['status'],'nothing_pending');self.assertEqual(self.io.updates,n)
 def test_loss_of_unarchived_stage_never_refetch(self):
  r=self.c.restore_and_select();self.assertEqual(len(r['selection']['held_requires_reconciliation']),2);self.assertFalse(r['external_request_permitted'])
  self.assertEqual(r['selection']['next_post_id'],str(9900000000000000002))
 def test_checkpoint_wait_policy(self):
  self.stage();self.assertEqual(self.c.checkpoint()['status'],'staged_waiting_checkpoint')
 def test_old_token_quarantine(self):
  self.stage();h,s,commit=self.g.read_state();s['koyo_index_handoffs'][self.key]['lease']['token']='new-synthetic-fencing'
  tree=self.io.create_tree(REPO,commit['tree'],{'state.json':json.dumps(s)});new=self.io.create_commit(REPO,tree,h,'synthetic fencing');self.io.update_ref(REPO,DISPATCH,h,new)
  r=self.c.restore_and_select();self.assertEqual(r['ready'],[]);self.assertIn(self.d['items'][0]['payload']['pid'],r['selection']['held_requires_reconciliation'])
 def test_foreign_scope_refused(self):
  b=copy.deepcopy(self.b);b['koyo_index_handoffs'][self.key]['destination']['worker_id']='other'
  with self.assertRaises(Refused):self.c.check(b)
 def test_accepted_baseline_preserved(self):
  row=self.d['items'][0]['payload'];b=apply(self.b,self.key,row['pid'],row['after']);p=deployment_plan(b,self.key,'a'*40,self.d['activation'],[Path('integration_driver.py')]);c=IntegratedWorker(self.w,self.a,self.g,p,Path(self.tmp.name)/'outbox2');bad=copy.deepcopy(b);bad['koyo_index_handoffs'][self.key]['rows'].clear()
  with self.assertRaises(Refused):c.check(bad)
 def test_zero_search_actual_scope(self):
  item=self.d['items'][0];pid=item['payload']['pid'];b=apply(self.b,self.key,pid,item['payload']['after']);row=b['koyo_index_handoffs'][self.key]['rows'].pop(pid)
  b['koyo_index_handoffs'][self.key]['context'][pid]['cache']['text']='Synthetic fixture: original illustration. Not a promotion.'
  c=row['context'];c['stop_reason']='evidence_sufficient'
  source={'url':'https://x.com/synthetic/status/'+pid,'accessed_at':'2026-11-18T00:00:00Z','kind':'post_text'}
  c['attributes']['creation'].update(status='observed',value='original',evidence='original illustration',sources=[source])
  c['attributes']['promotion'].update(status='observed',value=False,evidence='Not a promotion',sources=[source])
  a=copy.deepcopy(b);a['koyo_index_handoffs'][self.key]['rows'][pid]=row
  self.c.validate(b,a,'save-row',b['koyo_index_handoffs'][self.key]['lease']['token'],pid)
  bad=copy.deepcopy(a);bad['koyo_index_handoffs'][self.key]['rows'][pid]['context']['attributes']['creation']['sources'][0]['url']='https://x.com/other/status/123'
  with self.assertRaises(Exception):self.c.validate(b,bad,'save-row',b['koyo_index_handoffs'][self.key]['lease']['token'],pid)
 def test_no_live_transport_adoption(self):
  self.a.io.offline_fixture_only=False
  with self.assertRaises(Refused):IntegratedWorker(self.w,self.a,self.g,self.plan,Path(self.tmp.name)/'outbox3')
if __name__=='__main__':unittest.main(verbosity=2)
