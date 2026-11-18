import copy,json,tempfile,unittest,sys
from pathlib import Path
sys.path.insert(0,'/tmp/x-recovery-isolated')
from new_batch_guard import NewBatchClockGuard
from prepare_live_activation import build_new_batch
from protocol_bridge import initialize_fresh_store
from exploration import digest,Refused
# Synthetic accepted-claim snapshot derived from actual frozen catalog, no remote IO.
def fixture():
 root=Path('/tmp/x-recovery-isolated');s=json.load(open('/tmp/koyo-joined-resume-candidate/live-final-state.json'));old=next(h for h in s['koyo_index_handoffs'].values() if h['job_id']=='prod-0002')
 cat=json.load(open(root/'data/catalogs/data-v4-production-7113eaaefc38.json'));occupied={p for h in s['koyo_index_handoffs'].values() for p in h['plan']['payload']['source']['post_ids']};job=next(j for j in cat['jobs'] if len(j['manifest']['posts'])==50 and not occupied&{p['post_id'] for p in j['manifest']['posts']})
 h=copy.deepcopy(old);payload=copy.deepcopy(old['plan']['payload']);payload['revision']='recovery-next-batch-v1';src=payload['source'];ids=[p['post_id'] for p in job['manifest']['posts']];src.update(job_id=job['job_id'],post_ids=ids,manifest_sha256=digest(job['manifest']));payload['destination']=copy.deepcopy(h['destination']);key=digest(payload);h.update(plan={'payload':payload,'plan_sha256':key},plan_sha256=key,job_id=job['job_id'],rows={},context={},events={},operations={});h['lease']['token']='a'*32;s['koyo_index_handoffs'][key]=h
 pid=ids[0];h['context'][pid]={'fetch_started':100,'attempt_limit':1,'cache':{'post_id':pid,'state':'available','text':'ISOLATED FIXTURE'}};binding={'plan_sha256':key,'post_id':pid,'worker':'koyo','lease_token':'a'*32};return s,h,key,binding
class NewGuard(unittest.TestCase):
 def setUp(self):
  self.journal=tempfile.TemporaryDirectory();self.s,self.h,self.key,self.binding=fixture();self.doc,_=build_new_batch(self.s,'a'*40,self.binding,'ISOLATED TEST','/tmp/x-recovery-isolated','/tmp/not-created-test.db',self.journal.name);self.g=NewBatchClockGuard('/tmp/x-recovery-isolated',self.doc)
 def tearDown(self):self.journal.cleanup()
 def test_exact_new_scope_available_cache(self):self.g('a'*40,self.s,self.binding)
 def test_changed_scope_or_pin_or_baseline(self):
  for kind in ('scope','pin','baseline','limit'):
   d=copy.deepcopy(self.doc);p=d['payload']
   if kind=='scope':p['scope']['post_ids']=p['scope']['post_ids'][:-1]
   if kind=='pin':p['code_sha256'].pop(str(Path('new_batch_guard.py').resolve()))
   if kind=='baseline':p['baseline_handoff']['destination']['worker_id']='other'
   if kind=='limit':p['research_limits']['queries']=3
   d['sha256']=digest(p)
   with self.assertRaises(Refused):NewBatchClockGuard('/tmp/x-recovery-isolated',d)('a'*40,self.s,self.binding)
 def test_paused_failed_cache_other_token(self):
  for kind in ('paused','cache','token','legacy'):
   s=copy.deepcopy(self.s);h=s['koyo_index_handoffs'][self.key]
   if kind=='paused':s['koyo_retained_work']={self.key:{}}
   if kind=='cache':h['context'][self.binding['post_id']]['cache']['state']='technical_failure'
   if kind=='token':h['lease']['token']='b'*32
   if kind=='legacy':h['context'][self.binding['post_id']]['budget']={}
   with self.assertRaises((Refused,ValueError)):self.g('a'*40,s,self.binding)
 def test_authority_create_once(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'a.db';store=initialize_fresh_store(p,'a'*40,self.s,self.binding,self.g);store.close()
   with self.assertRaises((Refused,FileExistsError)):initialize_fresh_store(p,'a'*40,self.s,self.binding,self.g)
 def test_old_plan_cannot_new_scope(self):
  s=copy.deepcopy(self.s);h=s['koyo_index_handoffs'][self.key];h['job_id']='prod-0002'
  with self.assertRaises(Refused):self.g('a'*40,s,self.binding)
if __name__=='__main__':unittest.main()

class LocalRefusal(NewGuard):
 def test_local_refusal_blocks_exploration(self):
  from pipeline_production import disposition
  from runtime_components import PinnedInputs,provenance
  pid=self.binding['post_id'];post=PinnedInputs('/tmp/x-recovery-isolated',self.h).posts[pid]
  row=disposition.create(post,provenance(self.h),'koyo','image_tool_refusal',1);Path(self.journal.name,pid+'.json').write_text(json.dumps(row))
  with self.assertRaises(Refused):self.g('a'*40,self.s,self.binding)
