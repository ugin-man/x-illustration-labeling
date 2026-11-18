import copy,json,tempfile,hashlib,unittest
from pathlib import Path
from datetime import datetime,timezone
from protocol_claim_evidence import *
from test_retained import Retained
from test_next_batch import S,K,H,NOW,HEAD
from next_batch import next_candidates,prepare,validate_candidate
class ProtocolEvidence(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();t=Retained();self.hist,_,self.ret=t.fixture();jobs,cat=next_candidates(S);self.jid=jobs[0];self.ids=cat[self.jid]['post_ids'];self.workers=S['worker_ids'];others=[j for j in S['entries'] if j!=self.jid][:10];self.mapping={w:'thread-'+str(i) for i,w in enumerate(self.workers)}
  raw={'worker_chat_states':[{'worker':w,'thread_id':self.mapping[w]} for w in self.workers],'retrieved_at':datetime.fromtimestamp(NOW,timezone.utc).isoformat(),'threads':[]};records=[]
  for i,w in enumerate(self.workers):
   tid=self.mapping[w];text='Synthetic stopped worker, job '+others[i];mid='message-'+str(i);raw['threads'].append({'id':tid,'latest':{'threadId':tid,'latestTurn':{'status':'completed'},'items':[{'id':mid,'role':'assistant','text':text,'truncated':False}]}})
   records.append({'worker_id':w,'thread_id':tid,'status':'completed','explicit_stop_confirmed':True,'source_reference':'MOCK ONLY','last_job_id':others[i],'known_unshared_jobs':[others[i]],'checked_at':NOW,'stop_message_id':mid,'stop_message_sha256':sha(text)})
  file=Path(self.tmp.name)/'stops.json';file.write_text(json.dumps(raw));a={'path':str(file),'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'source_kind':'thread_management','source_reference':'MOCK ONLY'}
  for r in records:r['source_sha256']=a['sha256']
  artifacts=[a]
  for name,data in [('history',self.hist),('protocol',{'candidate':self.jid,'root':'f'*40,'root_scope_matches':True,'source_commit':'e'*40,'reviewed_revision_commits':['d'*40,'e'*40],'required_deployed_revision_commits':['d'*40,'e'*40],'initial_production_commit':'d'*40}),('launch',{'candidate':'e'*40,'workers':[{'worker':w} for w in self.workers]}),('refs',{'source_head':HEAD,'candidate_job':self.jid,'ls_remote':'','remote_branch_reference':'refs/heads/codex/jobs/production-v4-001/'+self.jid,'checked_at':NOW})]:
   f=Path(self.tmp.name)/(name+'.json');f.write_text(json.dumps(data));artifacts.append({'path':str(f),'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'source_kind':'github' if name=='history' else 'pinned_source','source_reference':'MOCK ONLY'})
  self.bundle={'schema':SCHEMA,'physical_store_coverage':'unconfirmed-not-used-as-zero','history':self.hist,'workers':records,'refs':{'source_head':HEAD,'job_id':self.jid,'exists':False,'verified_remote_reference':'refs/heads/codex/jobs/production-v4-001/'+self.jid,'checked_at':NOW},'known_contradictions':[],'artifacts':artifacts, 'review':{'source_tip_commit':'e'*40,'initial_index_root':'f'*40,'review_reference':'ISOLATED FIXTURE','run_id':S['run_id'],'catalog_sha256':S['catalog_sha256'],'history_continuity':'verified-to-initialization-no-known-reset','launched_revision_coverage':'all-production-launches-accounted-for','assignment_invariant':'atomic-index-and-job-before-local-work','out_of_band_assignment_coverage':'none-for-target-after-reviewed-records','reviewed_code_revisions':[{'kind':'initial-production','commit':'d'*40,'launch_reference':'MOCK initial','code_review_sha256':artifacts[2]['sha256'],'launch_source_sha256':artifacts[2]['sha256']},{'kind':'ops-ready','commit':'e'*40,'launch_reference':'MOCK','code_review_sha256':artifacts[2]['sha256'],'launch_source_sha256':artifacts[3]['sha256']}],'artifacts_sha256':sha(artifacts),'refs_source_sha256':artifacts[4]['sha256'],'history_source_sha256':artifacts[1]['sha256'],'protocol_source_sha256':artifacts[2]['sha256'],'worker_thread_mapping':self.mapping,'mapping_source_sha256':a['sha256']}}
 def tearDown(self):self.tmp.cleanup()
 def assemble(self,b=None):return assemble_protocol(S,HEAD,self.jid,self.ids,b or self.bundle,NOW)
 def test_honest_protocol_summary_and_claim(self):
  inv=self.assemble();self.assertNotIn('unshared_work',inv);self.assertEqual(inv['physical_store_coverage'],'unconfirmed-not-used-as-zero')
  c=prepare(S,HEAD,K,H['lease']['token'],NOW,'c'*32,self.hist,inv,'authorized fixed50',mode='retain-unresolved-and-claim',retention=self.ret);validate_candidate(c,S,HEAD,NOW+1);self.assertEqual(c['after']['koyo_index_handoffs'][K],H)
 def test_negative_evidence(self):
  for kind in ('missing_worker','duplicate_thread','wrong_head','ever_touched','stale_ref','stale_worker','root_unknown','revision_unknown','missing_revision','disk_empty','contradiction','wrong_message','mapping_missing','unbound_artifact','target_known_unshared'):
   with self.subTest(kind=kind):
    b=copy.deepcopy(self.bundle)
    if kind=='missing_worker':b['workers'].pop()
    if kind=='duplicate_thread':b['workers'][1]['thread_id']=b['workers'][0]['thread_id']
    if kind=='wrong_head':b['history']['source_head']='d'*40
    if kind=='ever_touched':b['history']['ever_touched']=True
    if kind=='stale_ref':b['refs']['checked_at']=NOW-61
    if kind=='stale_worker':b['workers'][0]['checked_at']=NOW-301
    if kind=='root_unknown':b['review']['history_continuity']='unknown'
    if kind=='revision_unknown':b['review']['launched_revision_coverage']='unknown'
    if kind=='missing_revision':b['review']['reviewed_code_revisions']=b['review']['reviewed_code_revisions'][1:]
    if kind=='disk_empty':b['physical_store_coverage']='empty'
    if kind=='contradiction':b['known_contradictions']=['other owner']
    if kind=='wrong_message':b['workers'][0]['stop_message_id']='fake'
    if kind=='mapping_missing':b['review']['worker_thread_mapping']={}
    if kind=='unbound_artifact':b['review']['artifacts_sha256']='0'*64
    if kind=='target_known_unshared':b['workers'][0]['known_unshared_jobs']=[self.jid]
    with self.assertRaises(Refused):self.assemble(b)
 def test_artifact_changed(self):
  Path(self.bundle['artifacts'][0]['path']).write_text('{}')
  with self.assertRaises(Refused):self.assemble()
 def test_no_zero_disk_masquerade(self):
  inv=self.assemble();inv['unshared_work']=[]
  with self.assertRaises(Refused):validate_summary(inv,HEAD,self.jid,self.ids,self.hist,NOW)
if __name__=='__main__':unittest.main()

class ProtocolWriter(ProtocolEvidence):
 def writer(self,inv):
  from claim_writer import ClaimWriter
  from runtime_components import digest
  c=prepare(S,HEAD,K,H['lease']['token'],NOW,'c'*32,self.hist,inv,'authorized fixed50',mode='retain-unresolved-and-claim',retention=self.ret)
  w=ClaimWriter.__new__(ClaimWriter);w.claim_candidate=c;w.inventory_bundle=self.bundle;w.clock=lambda:NOW;w.key=K
  names=('claim_writer.py','claim_inventory.py','next_batch.py','network_runtime.py','connector_protocol.py','connector_bridge.py','connector_transport.js','pack_compressed.py','rehearsal_pipeline.py','claim_cli.py','claim_transport.js','protocol_claim_evidence.py')
  p={'mode':'reviewed-live-claim','review_reference':'MOCK ONLY','candidate_sha256':sha(c),'before_sha256':sha(S),'code_sha256':{str(Path(f).resolve()):digest(f) for f in names}}
  w.activation_document={'payload':p,'sha256':sha(p)};return w,c
 def test_exact_bundle_guard(self):
  w,c=self.writer(self.assemble());w.guard(S,c['after'])
 def test_same_evidence_hash_different_summary_refused(self):
  inv=self.assemble();inv['coverage_reference']='different nonexistent review';w,c=self.writer(inv)
  with self.assertRaisesRegex(Refused,'summary differs'):w.guard(S,c['after'])
 def test_new_evidence_module_pin_required(self):
  w,c=self.writer(self.assemble());w.activation_document['payload']['code_sha256'].pop(str(Path('protocol_claim_evidence.py').resolve()));w.activation_document['sha256']=sha(w.activation_document['payload'])
  with self.assertRaises(Refused):w.guard(S,c['after'])
