import copy,json,tempfile,subprocess,unittest,time
from pathlib import Path
from unittest.mock import patch
from next_batch import *
from test_next_batch import S,K,H,NOW,HEAD
from test_retained import receipt
from claim_inventory import collect_environment,assemble
from claim_writer import ClaimWriter
from runtime_components import LocalGitTransport
import connector_protocol as protocol
class Connected(unittest.TestCase):
 def test_inventory_unknown_is_not_zero(self):
  with self.assertRaises(Refused):assemble(HEAD,'job',[],{},[],{},NOW)
  with tempfile.TemporaryDirectory() as d:
   with patch('claim_inventory.subprocess.run',return_value=type('R',(),{'stdout':''})()):
    o=collect_environment('cloud',[d],['123456'],'job',clock=lambda:NOW)
   coverage={'review_reference':'fixture','environment_roots':{'cloud':[d]}}
   refs={'source_head':HEAD,'job_id':'job','exists':False,'verified_remote_reference':'mock','checked_at':NOW}
   good=assemble(HEAD,'job',['123456'],coverage,[o],refs,NOW);self.assertTrue(good['evidence_sha256'])
   Path(d,'stage.json').write_text('123456')
   with patch('claim_inventory.subprocess.run',return_value=type('R',(),{'stdout':''})()):
    dirty=collect_environment('cloud',[d],['123456'],'job',clock=lambda:NOW)
   for obs in ([],[dirty]):
    with self.assertRaises(Refused):assemble(HEAD,'job',['123456'],coverage,obs,refs,NOW)
 def test_mock_connector_end_to_end(self):
  with tempfile.TemporaryDirectory() as d:
   subprocess.run(['git','init','--bare',d],capture_output=True,check=True)
   t=LocalGitTransport(d);head=t.commit(S);t.git('update-ref','refs/heads/codex/jobs/production-v4-001/dispatch-index',head)
   jobs,cat=next_candidates(S);jid=jobs[0];ids=cat[jid]['post_ids']
   coverage={'review_reference':'ISOLATED MOCK','environment_roots':{'fixture':['/fixture']}}
   obs=[{'environment_id':'fixture','roots':['/fixture'],'checked_at':NOW,'files_sha256':'b'*64,'matching_artifacts':[],'coverage_errors':[],'observed_writer_processes':[]}]
   refs={'source_head':head,'job_id':jid,'exists':False,'checked_at':NOW,'verified_remote_reference':'MOCK ONLY'}
   bundle={'coverage':coverage,'observations':obs,'refs':refs};inv=assemble(head,jid,ids,coverage,obs,refs,NOW)
   hist={'source_head':head,'job_id':jid,'complete_ancestry':True,'verified_commit_count':1,'ever_touched':False,'ancestry_sha256':'b'*64}
   r=receipt();r['source_head']=head
   c=prepare(S,head,K,H['lease']['token'],NOW,'c'*32,hist,inv,'user retained mode',mode='retain-unresolved-and-claim',retention=r)
   files=('claim_writer.py','claim_inventory.py','next_batch.py','network_runtime.py','connector_protocol.py','connector_bridge.py','connector_transport.js','pack_compressed.py','rehearsal_pipeline.py','claim_cli.py','claim_transport.js')
   p={'mode':'reviewed-live-claim','review_reference':'isolated mock only','candidate_sha256':sha(c),'before_sha256':sha(S),'code_sha256':{str(Path(f).resolve()):digest(f) for f in files}}
   w=ClaimWriter(d,S['catalog_sha256'],K,ROOT,clock=lambda:NOW,activation_document={'payload':p,'sha256':sha(p)},claim_candidate=c,inventory_bundle=bundle)
   try:
    e=protocol.envelope(w,head,S,c['after'],'claim-retained',H['lease']['token']);protocol.validate_envelope(w,e,S)
    candidate=w.q._commit(c['after'],head);commit={'sha':candidate,'tree':{'sha':e['payload']['candidate_tree_sha']},'parents':[{'sha':head}]}
    params=protocol.pre_update_ref(w,e,S,commit);self.assertFalse(params['force']);self.assertEqual(params['expected_sha'],head)
    t.git('fetch',str(w.q.repo),candidate)
    t.git('update-ref','refs/heads/codex/jobs/production-v4-001/dispatch-index',candidate,head)
    observed=protocol.readback(w,e,candidate);self.assertTrue(observed['accepted']);self.assertEqual(observed['state']['koyo_index_handoffs'][K],H)
    bad=copy.deepcopy(c['after']);bad['koyo_index_handoffs'][K]['lease']['until']+=1
    with self.assertRaises(Refused):w.authorize_transition(S,bad,'claim-retained',H['lease']['token'])
   finally:w.close()
if __name__=='__main__':unittest.main()

class SchedulerRegression(unittest.TestCase):
 def test_completion_rejects_unsealed_without_budget_and_invalid_cache(self):
  from test_next_batch import full_fixture
  from ops_runtime_r5.queue import cache_value
  for kind in ('unsealed','bad_cache'):
   h=full_fixture()['koyo_index_handoffs'][K];pid=H['plan']['payload']['source']['post_ids'][17]
   if kind=='unsealed':h['context'][pid]['exploration_clock']={'version':'recovery-clock-3'}
   else:h['context'][pid]['cache']['state']='invented'
   with self.assertRaises(Refused):complete(h)
 def test_paused_writer_and_body_never_dispatch(self):
  from network_runtime import IndexWriter
  from rehearsal_pipeline import RecoverySession
  state=copy.deepcopy(S);state['koyo_retained_work']={K:receipt()}
  session=RecoverySession.__new__(RecoverySession);session.key=K
  session.w=type('W',(),{'read':lambda self:(HEAD,state)})()
  calls=[]
  with self.assertRaises(Refused):session.body_once(H['plan']['payload']['source']['post_ids'][18],lambda pid:calls.append(pid))
  self.assertEqual(calls,[])
  w=IndexWriter.__new__(IndexWriter);w.key=K
  with self.assertRaises(Refused):w.preservation(state,state)
  with self.assertRaises(Refused):w.authorize_transition(state,state,'renew',H['lease']['token'])

class RetainedContinuation(unittest.TestCase):
 def test_later_batch_keeps_previous_retained_ownership(self):
  from test_retained import Retained
  t=Retained();hist,inv,r=t.fixture();first=t.build(hist,inv,r);s=first['after'];key=first['new_key'];h=s['koyo_index_handoffs'][key];head='d'*40
  candidates,jobs=next_candidates(s);jid=candidates[0];ids=jobs[jid]['post_ids']
  hist=dict(hist,source_head=head,job_id=jid);inv=dict(inv,source_head=head,job_id=jid,post_ids=ids)
  posts=h['plan']['payload']['source']['post_ids']
  r=dict(r,source_head=head,plan_sha256=key,lease_token=h['lease']['token'],handoff_sha256=sha(h),reserved_post_ids=posts,
   unresolved={p:{'reason':'unstarted_deferred','research_disposition':None,'context_sha256':sha(None),'events_sha256':sha([])} for p in posts})
  second=prepare(s,head,key,h['lease']['token'],NOW,'e'*32,hist,inv,'user continue disjoint',mode='retain-unresolved-and-claim',retention=r)
  self.assertEqual(second['after']['koyo_index_handoffs'][K],H)
  self.assertEqual(len(second['after']['koyo_retained_work']),2)
  bad=copy.deepcopy(s);bad['koyo_retained_work'][K]['unresolved'].pop(next(iter(bad['koyo_retained_work'][K]['unresolved'])))
  with self.assertRaises(Refused):prepare(bad,head,key,h['lease']['token'],NOW,'e'*32,hist,inv,'user continue disjoint',mode='retain-unresolved-and-claim',retention=r)
