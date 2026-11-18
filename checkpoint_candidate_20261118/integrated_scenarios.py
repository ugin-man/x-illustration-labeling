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
 def commit_state(self,state,message):
  head,_,c=self.g.read_state();t=self.io.create_tree(REPO,c['tree'],{'state.json':json.dumps(state)});n=self.io.create_commit(REPO,t,head,message);self.io.update_ref(REPO,DISPATCH,head,n);return head,n
 def test_same_token_renewal_retains_stage(self):
  from network_runtime import lease_transition
  self.stage();head,b,_=self.g.read_state();token=b['koyo_index_handoffs'][self.key]['lease']['token'];now=b['koyo_index_handoffs'][self.key]['lease']['until']-300;self.w.clock=lambda:now;self.c.clock=lambda:now;after=lease_transition(b,self.key,token,now,1800);self.assertGreater(after['koyo_index_handoffs'][self.key]['lease']['until'],b['koyo_index_handoffs'][self.key]['lease']['until'])
  self.w.authorize_transition(b,after,'renew',token);self.w.preservation(b,after);self.commit_state(after,'synthetic normal renewal')
  self.assertEqual(self.c.checkpoint(force=True)['status'],'accepted')
 def reacquire(self):
  head,b,_=self.g.read_state();old=b['koyo_index_handoffs'][self.key]['lease'];at=old['until']+1;self.c.clock=lambda:at;self.w.clock=lambda:at
  a=copy.deepcopy(b);h=a['koyo_index_handoffs'][self.key];fencing={'all_previous_koyo_writers_stopped':True,'verification_reference':'isolated sole fake writer verified'}
  h['lease']={'owner':'koyo','token':'b'*32,'until':at+1800};h.setdefault('recovery_lease_history',[]).append({'prior_lease':copy.deepcopy(old),'fencing_receipt':fencing,'at':at})
  self.w.authorize_transition(b,a,'reacquire',old['token'],fencing);self.w.preservation(b,a)
  return self.commit_state(a,'synthetic accepted normal reacquisition')
 def test_explicit_adoption_after_verified_reacquisition(self):
  from stage_adoption import adopt
  self.stage();prior,accepted=self.reacquire();item=self.a.restore(self.key)['stages'][0]
  new,ticket=adopt(self.c,item,prior,accepted,'isolated explicit adoption review')
  self.assertNotEqual(new['sha256'],item['sha256']);self.assertEqual(new['payload']['after'],item['payload']['after'])
  recovered=self.c.restore_and_select();self.assertEqual(len(recovered['ready']),1);self.assertEqual(self.c.checkpoint(force=True)['status'],'accepted')
 def test_adoption_without_accepted_reacquisition_refused(self):
  from stage_adoption import adopt
  self.stage();head,_,_=self.g.read_state()
  with self.assertRaises(Exception):adopt(self.c,self.d['items'][0],head,head,'not enough')
 def test_adoption_after_target_mutation_refused(self):
  from stage_adoption import adopt
  self.stage();prior,accepted=self.reacquire();_,s,_=self.g.read_state();pid=self.d['items'][0]['payload']['pid'];s['koyo_index_handoffs'][self.key]['context'][pid]['other']='changed';self.commit_state(s,'synthetic concurrent target changed')
  with self.assertRaises(Exception):adopt(self.c,self.d['items'][0],prior,accepted,'review cannot authorize altered dependency')
 def sealed_fixture(self):
  import sys
  path='/tmp/koyo-current-batch-candidate/exploration'
  if path not in sys.path:sys.path.insert(0,path)
  from exploration import Authority,new_clock,transition,digest as edigest
  from persistent_runner import validate_batch
  from prepare_live_activation import build_new_batch
  item=self.d['items'][0];pid=item['payload']['pid'];b=apply(self.b,self.key,pid,item['payload']['after']);row=b['koyo_index_handoffs'][self.key]['rows'].pop(pid)
  bind={'plan_sha256':self.key,'post_id':pid,'worker':'koyo','lease_token':b['koyo_index_handoffs'][self.key]['lease']['token']}
  activation,_=build_new_batch(b,'a'*40,bind,'isolated existing sealed-ledger review',str(ROOT),Path(self.tmp.name)/'authority-unused',ROOT/'refusals')
  authority=Authority();clock=new_clock(bind);initial=copy.deepcopy(clock);events=[];t=time.time()-10
  def event(e):
   nonlocal clock
   events.append(e);clock=transition(clock,e,authority)
  event({'kind':'reserve','at':t,'request_id':'synthetic-search','request_kind':'search','queries':['synthetic test only']})
  proof=authority.verified_ack(bind,'synthetic-search',edigest(clock),'a'*40,t+1,acknowledged=True,readback_sha=edigest(clock))
  event({'kind':'acknowledge','at':t+1,'request_id':'synthetic-search','proof':proof})
  event({'kind':'external_started','at':t+2,'request_id':'synthetic-search'})
  event({'kind':'external_finished','at':t+3,'request_id':'synthetic-search','result_sha256':'a'*64,'result_state':'available'})
  event({'kind':'seal','at':t+4});validate_batch(initial,events,clock,authority)
  b['koyo_index_handoffs'][self.key]['context'][pid]['exploration_clock']=clock
  row['context'].update(searches=clock['seal']['searches'],pages=clock['seal']['pages'],elapsed_seconds=clock['seal']['elapsed_seconds'],stop_reason='no_leads')
  a=copy.deepcopy(b);a['koyo_index_handoffs'][self.key]['rows'][pid]=row
  self.commit_state(b,'synthetic fully replay-validated sealed ledger')
  self.c.exploration_activation=activation
  return b,a,pid
 def test_sealed_exploration_stage_restore_requires_original_authority(self):
  b,a,pid=self.sealed_fixture()
  with self.assertRaisesRegex(Exception,'original authority'):self.c.preserve_completed(b,a,pid,'save-row')
 def test_sealed_budget_tampering_refused(self):
  b,a,pid=self.sealed_fixture();b['koyo_index_handoffs'][self.key]['context'][pid]['exploration_clock']['seal']['elapsed_seconds']=0
  a['koyo_index_handoffs'][self.key]['context'][pid]=copy.deepcopy(b['koyo_index_handoffs'][self.key]['context'][pid])
  with self.assertRaises(Exception):self.c.preserve_completed(b,a,pid,'save-row')
 def test_unfinished_exploration_refused(self):
  b,a,pid=self.sealed_fixture();b['koyo_index_handoffs'][self.key]['context'][pid]['exploration_clock']['requests']['synthetic-search'].pop('finished_at')
  a['koyo_index_handoffs'][self.key]['context'][pid]=copy.deepcopy(b['koyo_index_handoffs'][self.key]['context'][pid])
  with self.assertRaises(Exception):self.c.preserve_completed(b,a,pid,'save-row')
 def test_sealed_old_token_adoption_held_without_authority(self):
  from stage_adoption import adopt
  b,a,pid=self.sealed_fixture();original=stage(b,a,self.key,pid,'save-row',time.time());self.a.put(original);prior,accepted=self.reacquire()
  with self.assertRaisesRegex(Exception,'authority'):adopt(self.c,original,prior,accepted,'review does not authenticate proof')
  r=self.c.restore_and_select();self.assertEqual(r['ready'],[]);self.assertIn(pid,r['selection']['held_requires_reconciliation'])
 def tampered_sealed(self,kind):
  b,a,pid=self.sealed_fixture()
  from exploration import digest as edigest
  c=b['koyo_index_handoffs'][self.key]['context'][pid]['exploration_clock']
  if kind=='mac':c['requests']['synthetic-search']['ack']['mac']='0'*64
  else:
   r=c['requests']['synthetic-search'];c['management_reads']['forged']={'payload':{'binding':{},'request_id':'nonexistent','command':'arbitrary','started_at':r['started_at'],'ended_at':r['finished_at'],'duration':1},'sha256':'0'*64,'mac':'0'*64}
  unsealed=copy.deepcopy(c);unsealed['seal']=None;unsealed['last_event_at']=c['requests']['synthetic-search']['finished_at']
  from exploration import elapsed
  c['seal']['ledger_sha256']=edigest(unsealed);c['seal']['elapsed_seconds']=elapsed(unsealed,c['seal']['at'])
  a['koyo_index_handoffs'][self.key]['context'][pid]=copy.deepcopy(b['koyo_index_handoffs'][self.key]['context'][pid]);self.commit_state(b,'synthetic forged proof accepted state')
  # A rehashed ledger is not trusted, even if already present in Git.
  with self.assertRaisesRegex(Exception,'authority'):self.c.preserve_completed(b,a,pid,'save-row')
  original=stage(b,a,self.key,pid,'save-row',time.time());self.a.put(original);prior,accepted=self.reacquire()
  from stage_adoption import adopt
  with self.assertRaisesRegex(Exception,'authority'):adopt(self.c,original,prior,accepted,'not an authority')
  self.assertEqual(self.c.restore_and_select()['ready'],[])
 def test_forged_ack_mac_rehashed_refused(self):self.tampered_sealed('mac')
 def test_forged_management_read_rehashed_refused(self):self.tampered_sealed('management')
 def test_reacquisition_without_fencing_refused(self):
  from stage_adoption import adopt
  self.stage();prior,accepted=self.reacquire();state,c=__import__('stage_adoption').snapshot_at(self.g,accepted)
  state['koyo_index_handoffs'][self.key]['recovery_lease_history'][-1]['fencing_receipt']['all_previous_koyo_writers_stopped']=False
  tree=self.io.create_tree(REPO,c['tree'],{'state.json':json.dumps(state)});forged=self.io.create_commit(REPO,tree,prior,'synthetic invalid fencing')
  with self.assertRaises(Exception):adopt(self.c,self.a.restore(self.key)['stages'][0],prior,forged,'review cannot replace fencing')
 def test_archive_ticket_ack_loss_resolves_without_replay(self):
  from stage_adoption import adopt
  self.stage();prior,accepted=self.reacquire();original=self.a.restore(self.key)['stages'][0];self.io.lose_ack=True
  with self.assertRaises(TimeoutError):adopt(self.c,original,prior,accepted,'isolated reviewed adoption')
  self.io.lose_ack=False;updates=self.io.updates;r=self.c.restore_and_select();self.assertEqual(len(r['ready']),1);self.assertEqual(self.io.updates,updates)
 def test_no_live_transport_adoption(self):
  self.a.io.offline_fixture_only=False
  with self.assertRaises(Refused):IntegratedWorker(self.w,self.a,self.g,self.plan,Path(self.tmp.name)/'outbox3')
if __name__=='__main__':unittest.main(verbosity=2)
