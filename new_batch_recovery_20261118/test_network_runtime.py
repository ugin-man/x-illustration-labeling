import copy,json,sys,tempfile,unittest,subprocess
sys.path.insert(0,'/tmp/x-recovery-isolated')
from network_runtime import *
from runtime_components import LocalGitTransport
S=json.load(open('/tmp/x-state-recovery.json'));K=next(k for k,h in S['koyo_index_handoffs'].items() if h['job_id']=='prod-0002');H=S['koyo_index_handoffs'][K];NOW=H['lease']['until']-100
class Tests(unittest.TestCase):
 def seed(self,d):
  subprocess.run(['git','init','--bare',d],check=True,capture_output=True);t=LocalGitTransport(d);commit=t.commit(S);t.git('update-ref','refs/heads/codex/jobs/production-v4-001/dispatch-index',commit);return commit
 def test_actual_git_push_to_isolated_remote(self):
  with tempfile.TemporaryDirectory() as d:
   head=self.seed(d);w=IndexWriter(d,S['catalog_sha256'],K,'/tmp/x-recovery-isolated',clock=lambda:NOW)
   try:
    out=lease_transition(S,K,H['lease']['token'],NOW);r=w.publish(head,S,out,operation="renew",lease_token=H["lease"]["token"])
    self.assertTrue(r['external_request_permitted']);self.assertEqual(w.read()[1],out);self.assertEqual(out['entries'],S['entries'])
    with self.assertRaises(Stale):w.publish(head,S,out,operation="renew",lease_token=H["lease"]["token"])
   finally:w.close()
 def test_lost_push_ack_is_reconciled_without_external_request(self):
  with tempfile.TemporaryDirectory() as d:
   head=self.seed(d);w=IndexWriter(d,S['catalog_sha256'],K,'/tmp/x-recovery-isolated',clock=lambda:NOW);original=w.q.git
   def lost(*args,**kw):
    p=original(*args,**kw)
    if args[0]=='push':return subprocess.CompletedProcess(p.args,1,b'',b'timeout')
    return p
   w.q.git=lost
   try:
    r=w.publish(head,S,lease_transition(S,K,H['lease']['token'],NOW),operation="renew",lease_token=H["lease"]["token"]);self.assertTrue(r['ack_reconciled']);self.assertFalse(r['external_request_permitted'])
   finally:w.close()
 def test_live_write_disabled(self):
  w=IndexWriter(REMOTE,S['catalog_sha256'],K,'/tmp/x-recovery-isolated',clock=lambda:NOW)
  try:
   with self.assertRaises(Refused):w.publish('head',S,S)
  finally:w.close()
 def test_terra_mutation_refused(self):
  with tempfile.TemporaryDirectory() as d:
   head=self.seed(d);w=IndexWriter(d,S['catalog_sha256'],K,'/tmp/x-recovery-isolated',clock=lambda:NOW);out=copy.deepcopy(S);out['entries']['prod-0049']['worker_id']='koyo'
   try:
    with self.assertRaises(Refused):w.publish(head,S,out,operation="renew",lease_token=H["lease"]["token"])
    self.assertEqual(w.read()[0],head)
   finally:w.close()
 def test_expired_lease_not_stolen(self):
  with self.assertRaises(Refused):lease_transition(S,K,H['lease']['token'],H['lease']['until'])
 def test_renew_does_not_touch_context(self):
  out=lease_transition(S,K,H['lease']['token'],NOW);h=out['koyo_index_handoffs'][K];self.assertEqual(h['context'],H['context']);self.assertEqual(h['rows'],H['rows']);self.assertEqual(h['lease']['token'],H['lease']['token'])
 def test_fenced_reacquisition_preserves_history(self):
  now=H['lease']['until']+1
  with self.assertRaises(Refused):reacquire_koyo_lease(S,K,H['lease']['token'],now,{})
  out=reacquire_koyo_lease(S,K,H['lease']['token'],now,{'all_previous_koyo_writers_stopped':True,'verification_reference':'isolated fixture only'})
  self.assertNotEqual(out['koyo_index_handoffs'][K]['lease']['token'],H['lease']['token'])
  self.assertEqual(out['koyo_index_handoffs'][K]['context'],H['context']);self.assertEqual(out['entries'],S['entries'])
 def test_writer_rejects_fencing_bypass(self):
  with tempfile.TemporaryDirectory() as d:
   head=self.seed(d);now=H['lease']['until']+1;w=IndexWriter(d,S['catalog_sha256'],K,'/tmp/x-recovery-isolated',clock=lambda:now);out=copy.deepcopy(S);out['koyo_index_handoffs'][K]['lease'].update(token='a'*32,until=now+1800)
   try:
    with self.assertRaises(Refused):w.publish(head,S,out,operation='reacquire',lease_token=H['lease']['token'])
    self.assertEqual(w.read()[0],head)
   finally:w.close()
 def test_writer_rejects_cache_without_committed_reservation(self):
  with tempfile.TemporaryDirectory() as d:
   head=self.seed(d);w=IndexWriter(d,S['catalog_sha256'],K,'/tmp/x-recovery-isolated',clock=lambda:NOW);out=copy.deepcopy(S);pid=H['plan']['payload']['source']['post_ids'][16];out['koyo_index_handoffs'][K]['context'][pid]={'cache':{'post_id':pid,'state':'available','text':'fake'}}
   try:
    with self.assertRaises(Refused):w.publish(head,S,out,operation='body-cache',lease_token=H['lease']['token'])
    self.assertEqual(w.read()[0],head)
   finally:w.close()
 def test_clock_rejects_after_ack_rollback(self):
  c=DurableExploration({},'wall');c.reserve('s','search',['q'],100);c.ack('s','a'*64,140)
  with self.assertRaises(Refused):c.reserve('p','page',['url'],110)
 def test_renew_accepts_advancing_clock(self):
  with tempfile.TemporaryDirectory() as d:
   head=self.seed(d);prepared=NOW;out=lease_transition(S,K,H['lease']['token'],prepared)
   w=IndexWriter(d,S['catalog_sha256'],K,'/tmp/x-recovery-isolated',clock=lambda:prepared+0.25)
   try:self.assertTrue(w.publish(head,S,out,operation='renew',lease_token=H['lease']['token'])['head'])
   finally:w.close()
 def test_reacquire_accepts_advancing_clock(self):
  with tempfile.TemporaryDirectory() as d:
   head=self.seed(d);prepared=H['lease']['until']+1;receipt={'all_previous_koyo_writers_stopped':True,'verification_reference':'test fixture only'};out=reacquire_koyo_lease(S,K,H['lease']['token'],prepared,receipt)
   w=IndexWriter(d,S['catalog_sha256'],K,'/tmp/x-recovery-isolated',clock=lambda:prepared+0.25)
   try:self.assertTrue(w.publish(head,S,out,operation='reacquire',lease_token=H['lease']['token'],fencing_receipt=receipt)['head'])
   finally:w.close()
 def test_writer_replays_clock_order_not_just_last_timestamp(self):
  pid=H['plan']['payload']['source']['post_ids'][16];c=DurableExploration({'fetch_started':99,'cache':{'post_id':pid,'state':'available','text':'fixture'}},'wall');c.reserve('s','search',['one'],100);c.ack('s','a'*64,140);old=copy.deepcopy(c.c);new=copy.deepcopy(old);new['budget']['pages']=1
  new['reservations']['bad']={'kind':'page','queries':['url'],'requested_at':110,'permitted':True,'request_sha256':'b'*64,**copy.deepcopy(new['budget'])}
  with self.assertRaises(Refused):validate_exploration_transition(old,new,200)
 def test_writer_rejects_overspent_clock_and_combined_events(self):
  old={'cache':{}};c=DurableExploration(old,'wall');new=c.reserve('s','search',['one','two'],100);new['budget']['searches']=1
  with self.assertRaises(Refused):validate_exploration_transition(old,new,200)
  c=DurableExploration(old,'wall');c.reserve('s','search',['one'],100);new=c.ack('s','a'*64,101)
  with self.assertRaises(Refused):validate_exploration_transition(old,new,200)
 def test_legal_exploration_full_writer_roundtrip(self):
  pid=H['plan']['payload']['source']['post_ids'][16];fixture=copy.deepcopy(S);fixture['koyo_index_handoffs'][K]['context'][pid]={'fetch_started':NOW-1,'cache':{'post_id':pid,'state':'available','text':'fixture'}}
  with tempfile.TemporaryDirectory() as d:
   subprocess.run(['git','init','--bare',d],check=True,capture_output=True);t=LocalGitTransport(d);head=t.commit(fixture);t.git('update-ref','refs/heads/codex/jobs/production-v4-001/dispatch-index',head);clock=[NOW]
   w=IndexWriter(d,S['catalog_sha256'],K,'/tmp/x-recovery-isolated',clock=lambda:clock[0]);current=fixture
   try:
    for action,at in [('search',NOW),('ack-search',NOW+2),('page',NOW+3),('ack-page',NOW+4),('seal',NOW+5)]:
     clock[0]=at;engine=DurableExploration(current['koyo_index_handoffs'][K]['context'][pid],'wall')
     if action=='search':context=engine.reserve('s','search',['query-one','query-two'],at)
     elif action=='page':context=engine.reserve('p','page',['https://example.com'],at)
     elif action=='ack-search':context=engine.ack('s','a'*64,at)
     elif action=='ack-page':context=engine.ack('p','b'*64,at)
     else:context=engine.seal(at)
     after=copy.deepcopy(current);after['koyo_index_handoffs'][K]['context'][pid]=context
     result=w.publish(head,current,after,operation='exploration',lease_token=H['lease']['token']);head=result['head'];current=after
    restored=w.read()[1]['koyo_index_handoffs'][K]['context'][pid]
    self.assertEqual(restored['budget']['searches'],2);self.assertEqual(restored['budget']['pages'],1);self.assertEqual(restored['exploration_clock']['seal']['elapsed_seconds'],5)
    self.assertEqual(restored['reservations']['s']['queries'],['query-one','query-two']);self.assertEqual(len(restored['reservations']['s']['budget_queries']),2)
    self.assertEqual(current['entries'],S['entries']);self.assertEqual(current['koyo_index_handoffs'][K]['rows'],H['rows'])
   finally:w.close()
 def test_reviewed_live_single_post_scope(self):
  from runtime_components import digest
  from pathlib import Path
  pid=H['plan']['payload']['source']['post_ids'][17];other=H['plan']['payload']['source']['post_ids'][18]
  files=[Path(__file__).with_name(x).resolve() for x in ('network_runtime.py','runtime_components.py','recovery_adapter.py')]
  payload={'mode':'reviewed-live','review_reference':'isolated test receipt','plan_sha256':K,'scope':{'job_id':'prod-0002','post_id':pid,'max_new_rows':1,'external_exploration':False},'baseline_rows':copy.deepcopy(H['rows']),'code_sha256':{str(f):digest(f) for f in files}}
  with tempfile.TemporaryDirectory() as d:
   self.seed(d);w=IndexWriter(d,S['catalog_sha256'],K,'/tmp/x-recovery-isolated',clock=lambda:NOW);w.live=True;w.activation_document={'payload':payload,'sha256':sha(payload)}
   try:
    out=copy.deepcopy(S);out['koyo_index_handoffs'][K]['context'][pid]={'fetch_started':NOW,'recovery_revision':'recovery-prototype-1','attempt_limit':1};w.authorize_transition(S,out,'body-reserve',H['lease']['token'])
    out=copy.deepcopy(S);out['koyo_index_handoffs'][K]['context'][other]={'fetch_started':NOW,'recovery_revision':'recovery-prototype-1','attempt_limit':1}
    with self.assertRaises(Refused):w.authorize_transition(S,out,'body-reserve',H['lease']['token'])
   finally:w.close()
 def test_recorded_failure_limited_save_scope(self):
  from runtime_components import digest
  from pathlib import Path
  pid=H['plan']['payload']['source']['post_ids'][17];row=json.load(open(Path(__file__).with_name('live-row-final.json')));before=copy.deepcopy(S);before['koyo_index_handoffs'][K]['context'][pid]={'fetch_started':NOW-1,'cache':{'post_id':pid,'state':'technical_failure','code':404,'text':None}}
  after=copy.deepcopy(before);after['koyo_index_handoffs'][K]['rows'][pid]=row
  files=[Path(__file__).with_name(x).resolve() for x in ('network_runtime.py','runtime_components.py','recovery_adapter.py')]
  payload={'mode':'reviewed-live','review_reference':'isolated test','plan_sha256':K,'scope':{'job_id':'prod-0002','post_id':pid,'max_new_rows':1,'external_exploration':False,'allow_recorded_source_failure':True},'baseline_rows':copy.deepcopy(H['rows']),'code_sha256':{str(f):digest(f) for f in files}}
  with tempfile.TemporaryDirectory() as d:
   self.seed(d);w=IndexWriter(d,S['catalog_sha256'],K,'/tmp/x-recovery-isolated',clock=lambda:NOW);w.live=True;w.activation_document={'payload':payload,'sha256':sha(payload)}
   try:
    w.authorize_transition(before,after,'save-row',H['lease']['token'])
    bad=copy.deepcopy(before);bad['koyo_index_handoffs'][K]['context'][pid]['cache']['state']='available'
    with self.assertRaises(Refused):w.authorize_transition(bad,after,'save-row',H['lease']['token'])
    bad=copy.deepcopy(after);bad['koyo_index_handoffs'][K]['rows'][pid]['context']['searches']=1
    with self.assertRaises(Refused):w.authorize_transition(before,bad,'save-row',H['lease']['token'])
    payload['scope']['allow_recorded_source_failure']=False;w.activation_document={'payload':payload,'sha256':sha(payload)}
    with self.assertRaises(Refused):w.authorize_transition(before,after,'save-row',H['lease']['token'])
   finally:w.close()
 def test_two_queries_count_two(self):
  c=DurableExploration({'cache':{}},'wall');c.reserve('s','search',['one','two'],0);c.ack('s','a'*64,1)
  with self.assertRaises(Refused):c.reserve('s2','search',['three'],2)
  self.assertEqual(c.c['budget']['searches'],2)
 def test_original_wall_deadline_not_reset_by_wait(self):
  c=DurableExploration({},'wall');c.reserve('s','search',['q'],0);c.ack('s','a'*64,100)
  with self.assertRaises(Refused):c.reserve('p','page',['url'],101)
  self.assertEqual(c.seal(102)['exploration_clock']['seal']['elapsed_seconds'],102)
 def test_explicit_alternate_not_silent(self):
  c=DurableExploration({},'active-v2-review');c.reserve('s','search',['q'],0);c.ack('s','a'*64,100);c.reserve('p','page',['url'],101)
  self.assertEqual(c.c['budget']['pages'],1)
  d=DurableExploration(c.c,'wall')
  with self.assertRaises(Refused):d.reserve('p2','page',['url'],102)
 def test_legacy_clock_not_migrated(self):
  legacy=next(c for c in H['context'].values() if 'exploration_clock' in c)
  c=DurableExploration(legacy,'wall')
  with self.assertRaises(Refused):c.reserve('new','search',['q'],NOW)
  self.assertEqual(c.c,legacy)
 def test_restart_pending_ack_blocked(self):
  c=DurableExploration({},'wall');saved=c.reserve('s','search',['q'],0);d=DurableExploration(saved,'wall')
  with self.assertRaises(Refused):d.reserve('p','page',['url'],1)
if __name__=='__main__':unittest.main(verbosity=2)
