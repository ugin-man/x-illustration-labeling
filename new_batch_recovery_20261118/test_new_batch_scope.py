import copy,json,tempfile,subprocess,unittest
from pathlib import Path
import sys
sys.path.insert(0,'/tmp/x-recovery-isolated')
from test_retained import Retained
from test_next_batch import NOW,HEAD
from network_runtime import IndexWriter
from new_batch_scope import *
class NewScope(unittest.TestCase):
 def setUp(self):
  t=Retained();hist,inv,r=t.fixture();c=t.build(hist,inv,r);self.s=c['after'];self.key=c['new_key'];self.h=self.s['koyo_index_handoffs'][self.key];self.ids=self.h['plan']['payload']['source']['post_ids']
  self.images=tempfile.TemporaryDirectory();root=Path(self.images.name);(root/'bundle').mkdir();(root/'refusals').mkdir();self.gate={'bundle_root':str(root/'bundle'),'audit_roots':[str(root)],'local_refusal_dir':str(root/'refusals'),'review_reference':'fixture'}
  self.doc=build(self.s,HEAD,self.key,'ISOLATED FIXTURE REVIEW','/tmp/x-recovery-isolated',image_gate=self.gate)
  self.tmp=tempfile.TemporaryDirectory();subprocess.run(['git','init','--bare',self.tmp.name],capture_output=True,check=True)
  self.w=IndexWriter(self.tmp.name,self.s['catalog_sha256'],self.key,'/tmp/x-recovery-isolated',clock=lambda:NOW,activation_document=self.doc);self.w.live=True
 def tearDown(self):self.w.close();self.tmp.cleanup();self.images.cleanup()
 def reserve(self,pid=None):
  a=copy.deepcopy(self.s);a['koyo_index_handoffs'][self.key]['context'][pid or self.ids[0]]={'fetch_started':NOW,'attempt_limit':1,'recovery_revision':'recovery-prototype-1'};return a
 def check(self,a):self.w.authorize_transition(self.s,a,'body-reserve',self.h['lease']['token']);self.w.preservation(self.s,a)
 def test_all50_exact_new_posts(self):
  for pid in self.ids:self.check(self.reserve(pid))
 def test_legacy_scope_untouched(self):
  self.assertNotEqual(self.h['job_id'],'prod-0002')
  old=next(h for h in self.s['koyo_index_handoffs'].values() if h['job_id']=='prod-0002')
  with self.assertRaises(Refused):self.check(self.reserve(old['plan']['payload']['source']['post_ids'][16]))
 def test_scope_shrink_or_expand(self):
  for ids in (self.ids[:-1],self.ids+['999999999999']):
   d=copy.deepcopy(self.doc);d['payload']['scope']['post_ids']=ids;d['sha256']=sha(d['payload']);self.w.activation_document=d
   with self.assertRaises(Refused):self.check(self.reserve())
 def test_tampered_identity(self):
  for field in ('job_id','destination','plan'):
   a=self.reserve();h=a['koyo_index_handoffs'][self.key]
   if field=='job_id':h[field]='prod-0002'
   elif field=='destination':h[field]['worker_id']='terra'
   else:h[field]['payload']['source']['post_ids'].reverse()
   with self.assertRaises(Refused):self.check(a)
 def test_other_worker_unchanged(self):
  a=self.reserve();a['entries']['prod-0049']['worker_id']='koyo'
  with self.assertRaises(Refused):self.check(a)
 def test_paused_new_scope_refused(self):
  self.s['koyo_retained_work'][self.key]={}
  with self.assertRaises(Refused):self.check(self.reserve())
 def test_already_started_builder_refused(self):
  with self.assertRaises(Refused):build(self.reserve(),HEAD,self.key,'fixture','/tmp/x-recovery-isolated')
 def test_missing_new_guard_pin(self):
  self.doc['payload']['code_sha256'].pop(str(Path('new_batch_scope.py').resolve()));self.doc['sha256']=sha(self.doc['payload'])
  with self.assertRaises(Refused):self.check(self.reserve())
 def test_two_posts_refused(self):
  a=self.reserve();a['koyo_index_handoffs'][self.key]['context'][self.ids[1]]=copy.deepcopy(a['koyo_index_handoffs'][self.key]['context'][self.ids[0]])
  with self.assertRaises(Refused):self.check(a)
 def test_new_exploration_not_implicitly_enabled(self):
  with self.assertRaises(Refused):self.w.authorize_transition(self.s,self.reserve(),'exploration',self.h['lease']['token'])
if __name__=='__main__':unittest.main()

class NewFinal(NewScope):
 def final_fixture(self):
  from runtime_components import provenance,PinnedInputs
  from test_current_batch_scope import H,PLAN
  pid=self.ids[0];before=self.reserve(pid);after=copy.deepcopy(before);h=after['koyo_index_handoffs'][self.key];post=PinnedInputs('/tmp/x-recovery-isolated',h).posts[pid]
  cache=copy.deepcopy(H['context'][PLAN[17]]['cache']);cache['post_id']=pid;h['context'][pid]['cache']=cache
  row=copy.deepcopy(H['rows'][PLAN[17]]);row['post_id']=pid;row['provenance']=provenance(h);row['images']=[dict(copy.deepcopy(row['images'][0]),media_index=im['media_index'],sha256=im['sha256']) for im in post['images']];h['rows'][pid]=row
  h['events'][pid]=[{'post_id':pid,'media_index':im['media_index'],'sha256':im['sha256'],'outcome':'viewed','tool':'fixture-only','tool_call_id':'isolated-not-real','at':'fixture'} for im in post['images']]
  return before,after
 def test_new_finalize_source_failure(self):
  b,a=self.final_fixture();self.w.authorize_transition(b,a,'finalize-post',self.h['lease']['token']);self.w.preservation(b,a)
 def test_new_finalize_missing_image_refused(self):
  b,a=self.final_fixture();a['koyo_index_handoffs'][self.key]['events']={}
  with self.assertRaises(Refused):self.w.authorize_transition(b,a,'finalize-post',self.h['lease']['token'])
 def test_metadata_exclusion_without_body_or_image(self):
  from pipeline_production import disposition
  from runtime_components import PinnedInputs,provenance
  a=copy.deepcopy(self.s);h=a['koyo_index_handoffs'][self.key];pid=self.ids[0];post=PinnedInputs('/tmp/x-recovery-isolated',h).posts[pid]
  h['rows'][pid]=disposition.create(post,provenance(h),'koyo','image_tool_refusal',1)
  self.w.authorize_transition(self.s,a,'exclude-post',self.h['lease']['token']);self.w.preservation(self.s,a)
  h['rows'][pid]['invented_label']='must never be accepted'
  with self.assertRaises((Refused,AssertionError)):self.w.authorize_transition(self.s,a,'exclude-post',self.h['lease']['token'])

class Tombstones(NewScope):
 def test_local_refusal_blocks_reservation_and_same_image(self):
  from pipeline_production import disposition
  from runtime_components import PinnedInputs,provenance
  pid=self.ids[0];post=PinnedInputs('/tmp/x-recovery-isolated',self.h).posts[pid];row=disposition.create(post,provenance(self.h),'koyo','image_tool_refusal',1)
  Path(self.gate['local_refusal_dir'],pid+'.json').write_text(json.dumps(row))
  with self.assertRaises(Refused):self.check(self.reserve(pid))
  # A metadata-only terminal record remains permitted despite local tombstone.
  a=copy.deepcopy(self.s);a['koyo_index_handoffs'][self.key]['rows'][pid]=row
  self.w.authorize_transition(self.s,a,'exclude-post',self.h['lease']['token']);self.w.preservation(self.s,a)

class StartupPins(NewScope):
 def test_document_and_all_module_pins_mandatory(self):
  from new_batch_scope import validate_document
  validate_document(self.doc,'/tmp/x-recovery-isolated')
  for kind in ('digest','tombstone','imagegate'):
   doc=copy.deepcopy(self.doc)
   if kind=='digest':doc['sha256']='0'*64
   else:
    f='policy_tombstones.py' if kind=='tombstone' else 'new_batch_images.py'
    doc['payload']['code_sha256'].pop(str(Path(f).resolve()));doc['sha256']=sha(doc['payload'])
   with self.assertRaises(Refused):validate_document(doc,'/tmp/x-recovery-isolated')
