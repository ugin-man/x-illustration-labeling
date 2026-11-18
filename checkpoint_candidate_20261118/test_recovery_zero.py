import copy,tempfile,unittest
from pathlib import Path
from checkpoint import *
from stage_recovery import *
import zero_search as z
from test_checkpoint import fixture,items,Fake,validator,NOW,KEY
class Recovery(unittest.TestCase):
 def test_complete_local_loss_restores_stage_without_fetch(self):
  s=fixture();it=items(s)
  with tempfile.TemporaryDirectory() as remote, tempfile.TemporaryDirectory() as local:
   ar=FixtureArchive(remote)
   for x in it:archive(x,ar)
   save_journal(Path(local)/'stage.json',it)
   (Path(local)/'stage.json').unlink()
   recovered=restore(KEY,FixtureArchive(remote))
   self.assertEqual({x['sha256'] for x in recovered},{x['sha256'] for x in it})
   out=select_unstaged(s,KEY,recovered)
   self.assertEqual(len(out['pending_staged']),5);self.assertIsNone(out['next_post_id']);self.assertFalse(out['external_request_permitted'])
 def test_lost_unarchived_reservation_held_other_pristine_selected(self):
  s=fixture();s['koyo_index_handoffs'][KEY]['context'].pop('6')
  out=select_unstaged(s,KEY,[])
  self.assertEqual(out['next_post_id'],'6');self.assertEqual(len(out['held_requires_reconciliation']),6)
 def test_archive_conflicting_or_tampered_refused(self):
  it=items(fixture(),1)[0]
  with tempfile.TemporaryDirectory() as d:
   ar=FixtureArchive(d);archive(it,ar);name=name_for(it);bad=copy.deepcopy(it);bad['payload']['staged_at']=5;bad['sha256']=digest(bad['payload']);archive(bad,ar)
   with self.assertRaises(Refused):restore(KEY,ar)
 def test_dynamic_expiry_during_prepare(self):
  s=fixture();its=items(s);f=Fake(s);t=[100]
  f.prepare_transfer=lambda:t.__setitem__(0,990)
  p=prepare('head',s,its,validator,100)
  with self.assertRaises(Refused):fake_send(p,f,validator,its,100,clock=lambda:t[0])
  self.assertEqual(f.calls,0)
 def test_new_owner_during_transfer_blocks_old_writer(self):
  s=fixture();its=items(s);f=Fake(s);p=prepare('head',s,its,validator,100)
  def changed():f.head='new-lease';f.state['koyo_index_handoffs'][KEY]['lease']['token']='other'
  f.prepare_transfer=changed
  with self.assertRaises(Refused):fake_send(p,f,validator,its,100,clock=lambda:110)
  self.assertEqual(f.calls,0)
class Zero(unittest.TestCase):
 def setUp(self):
  self.b=fixture();self.pid='0';h=self.b['koyo_index_handoffs'][KEY];h['context']['0']['cache']={'post_id':'0','state':'available','text':'This is my original illustration. No promotion.'};self.a=copy.deepcopy(self.b)
  source={'kind':'post_text','url':'https://x.com/test/status/0','accessed_at':'2026-11-18'}
  attr={'status':'observed','value':'original','reason':'explicit body','evidence':'original illustration','sources':[source]}
  self.a['koyo_index_handoffs'][KEY]['rows']['0']={'post_id':'0','context':{'state':'complete','stop_reason':'evidence_sufficient','searches':0,'pages':0,'elapsed_seconds':0,'attributes':{'creation':attr}}}
  self.calls=[]
 def check(self):return z.validate(self.b,self.a,KEY,'0','t',100,lambda *x:self.calls.append('policy'),lambda *x:self.calls.append('fixed'))
 def test_body_only_without_clock_or_search(self):self.assertTrue(self.check());self.assertEqual(self.calls,['policy','fixed'])
 def test_external_source_crosspost_unsupported_refused(self):
  a=self.a['koyo_index_handoffs'][KEY]['rows']['0']['context']['attributes']['creation']
  for url in ('https://x.com/test/status/1','https://x.com.evil/test/status/0','https://example.com/test/status/0'):
   a['sources'][0]['url']=url
   with self.assertRaises(Refused):self.check()
 def test_invented_evidence_refused(self):
  self.a['koyo_index_handoffs'][KEY]['rows']['0']['context']['attributes']['creation']['evidence']='not in actual body'
  with self.assertRaises(Refused):self.check()
 def test_failed_body_refused(self):
  for state in (self.a,self.b):state['koyo_index_handoffs'][KEY]['context']['0']['cache']['state']='technical_failure'
  with self.assertRaises(Refused):self.check()
 def test_view_policy_failure_propagates(self):
  def deny(*x):raise Refused('view/policy invalid')
  with self.assertRaises(Refused):z.validate(self.b,self.a,KEY,'0','t',100,deny,lambda *x:None)
 def test_other_changes_refused(self):
  self.a['terra']['untouched']=False
  with self.assertRaises(Refused):self.check()
if __name__=='__main__':unittest.main()
