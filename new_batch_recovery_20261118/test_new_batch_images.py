import copy,json,tempfile,unittest,hashlib
from pathlib import Path
import sys
sys.path.insert(0,'/tmp/x-recovery-isolated')
from recovery_adapter import Refused,sha
from runtime_components import digest
import new_batch_images as gate
from new_batch_scope import build

def write(p,v):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v))
class ImageGate(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.w=Path(self.tmp.name);self.root=self.w/'source';self.bundle=self.w/'bundle';self.refusals=self.w/'refusals'
  for p in (self.root,self.bundle,self.refusals):p.mkdir()
  self.forbidden=hashlib.sha256(b'forbidden-fixture-not-image').hexdigest()
  self.policy={'version':1,'screening_receipt_sha256':'a'*64,'post_ids':['99999999'],'image_sha256':[self.forbidden]};write(self.root/'exclusion.json',self.policy)
  posts=[]
  for n in range(50):
   images=[]
   for i in range(2 if n==0 else 1):
    data=('synthetic-non-image-%s-%s'%((0,1) if n==1 else (n,i))).encode();name='images/%s-%s.png'%(n,i);p=self.bundle/name;p.parent.mkdir(exist_ok=True);p.write_bytes(data)
    images.append({'media_index':i+1,'sha256':hashlib.sha256(data).hexdigest(),'path':name})
   posts.append({'post_id':str(10000000+n),'images':images})
  self.ids=[p['post_id'] for p in posts];manifest={'job_id':'prod-0003','posts':posts};self.posts=posts
  cat={'jobs':[{'job_id':'prod-0003','post_ids':self.ids,'manifest':manifest}]};write(self.root/'data/catalogs/data-v4-production-7113eaaefc38.json',cat)
  for rel in ('pipeline_production/contract_v4.py','docs/LABELING_V4_PRODUCTION.md'):
   p=self.root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('synthetic pinned source only')
  safety_files=('pipeline_production/isolation.py','pipeline_production/disposition.py')
  for rel in safety_files:
   (self.root/rel).write_bytes((Path('/tmp/x-recovery-isolated')/rel).read_bytes())
  config={'run_id':'production-v4-001','job_ids':['prod-0003'],'screening_receipt_sha256':'a'*64,'exclusion_policy_path':'exclusion.json','exclusion_policy_sha256':digest(self.root/'exclusion.json'),'toolchain_sha256':{rel:digest(self.root/rel) for rel in safety_files}};write(self.root/'runs/production-v4-001.json',config)
  source={'run_id':'production-v4-001','job_id':'prod-0003','post_ids':self.ids,'manifest_sha256':sha(manifest),'screening_receipt_sha256':'a'*64}
  for field,rel in [('contract_sha256','pipeline_production/contract_v4.py'),('manual_sha256','docs/LABELING_V4_PRODUCTION.md'),('catalog_sha256','data/catalogs/data-v4-production-7113eaaefc38.json'),('config_sha256','runs/production-v4-001.json')]:source[field]=digest(self.root/rel)
  destination={'worker_id':'koyo'};payload={'revision':'recovery-next-batch-v1','source':source,'destination':destination};self.key=sha(payload)
  self.h={'plan':{'payload':payload,'plan_sha256':self.key},'plan_sha256':self.key,'destination':destination,'job_id':'prod-0003','status':'leased','lease':{'owner':'koyo','token':'c'*32,'until':2000},'rows':{},'context':{},'events':{},'operations':{}}
  self.state={'koyo_index_handoffs':{self.key:self.h}};self.head='a'*40
  self.binding=gate.make_binding(self.bundle,[self.w],self.refusals,'synthetic coverage fixture')
  self.doc=build(self.state,self.head,self.key,'synthetic isolated test',self.root,image_gate=self.binding)
  # Pin gate even before caller's FILES integration; no view evidence is invented.
  self.doc['payload']['image_gate']=self.binding;self.doc['payload']['code_sha256'][str(Path(gate.__file__).resolve())]=digest(gate.__file__);self.resign()
 def tearDown(self):self.tmp.cleanup()
 def resign(self):self.doc['sha256']=sha(self.doc['payload'])
 def call(self):return gate.next_images(self.state,self.head,self.doc,self.root,now=1000)
 def exclusion(self,pid):return {'record_type':'exclusion','post_id':pid,'reason':'policy_refusal','signal':'image_tool_refusal','scope':'post','temporary':True}
 def test_success_all_attachments_no_view_receipt(self):
  result=self.call();self.assertEqual(result['post_id'],self.ids[0]);self.assertEqual(len(result['images']),2);self.assertFalse(result['viewed']);self.assertFalse(result['receipt_generated']);self.assertEqual(result['audits'][0]['excluded_images_found'],0)
 def test_accepted_first_skipped(self):
  self.h['rows'][self.ids[0]]={'placeholder':'test existing accepted row'};self.assertEqual(self.call()['post_id'],self.ids[1])
 def test_retained_complete_wrong_owner_expired_refused(self):
  for kind in ('paused','complete','owner','expired'):
   saved=copy.deepcopy(self.state)
   if kind=='paused':self.state['koyo_retained_work']={self.key:{}}
   elif kind=='complete':self.h['status']='completed'
   elif kind=='owner':self.h['lease']['owner']='terra'
   else:self.h['lease']['until']=1029
   with self.assertRaises(Refused):self.call()
   self.state=saved;self.h=self.state['koyo_index_handoffs'][self.key]
 def test_wrong_config_refused(self):
  (self.root/'runs/production-v4-001.json').write_text('{}')
  with self.assertRaises(Refused):self.call()
 def test_policy_changed_refused(self):
  write(self.root/'exclusion.json',dict(self.policy,post_ids=[]))
  with self.assertRaises(ValueError):self.call()
 def test_wrong_image_bytes_refused(self):
  (self.bundle/self.posts[0]['images'][0]['path']).write_bytes(b'corrupt fixture')
  with self.assertRaises(ValueError):self.call()
 def test_missing_image_refused(self):
  (self.bundle/self.posts[0]['images'][1]['path']).unlink()
  with self.assertRaises(FileNotFoundError):self.call()
 def test_forbidden_loose_image_stops_all(self):
  (self.w/'unrelated.png').write_bytes(b'forbidden-fixture-not-image')
  with self.assertRaises(ValueError):self.call()
 def test_forbidden_zip_stops_all(self):
  import zipfile
  with zipfile.ZipFile(self.w/'cache.zip','w') as z:z.writestr('blocked.png',b'forbidden-fixture-not-image')
  with self.assertRaises(ValueError):self.call()
 def test_internal_symlink_audit_coverage_checked(self):
  (self.w/'linked').symlink_to(self.bundle,target_is_directory=True)
  self.assertEqual(self.call()['status'],'ready_for_actual_view')
 def test_local_policy_refusal_blocks_entire_post(self):
  write(self.refusals/'first.json',self.exclusion(self.ids[0]));r=self.call();self.assertEqual(r['status'],'known_refusal_requires_exclusion');self.assertEqual(r['image_paths'],[])
 def test_shared_refused_hash_blocks_next_post(self):
  self.h['rows'][self.ids[0]]=self.exclusion(self.ids[0]);result=self.call()
  self.assertEqual(result['post_id'],self.ids[1]);self.assertEqual(result['status'],'known_refusal_requires_exclusion');self.assertEqual(result['image_paths'],[])
 def test_unknown_local_refusal_fail_closed(self):
  write(self.refusals/'unknown.json',self.exclusion('unknown'))
  with self.assertRaises(Refused):self.call()
 def test_gate_pin_and_binding_required(self):
  self.doc['payload']['code_sha256'].pop(str(Path(gate.__file__).resolve()));self.resign()
  with self.assertRaises(Refused):self.call()
 def test_binding_cannot_exclude_bundle(self):
  with self.assertRaises(Refused):gate.make_binding(self.bundle,[self.root],self.refusals,'test')
 def test_scope_outside_post_ids_refused(self):
  self.doc['payload']['scope']['post_ids']=self.ids[1:];self.resign()
  with self.assertRaises(Refused):self.call()
 def test_pinned_path_escape_refused_before_return(self):
  from unittest.mock import patch
  original=gate.PinnedInputs
  class Escape:
   def __init__(me,*args):
    pins=original(*args);me.manifest=pins.manifest;me.posts=copy.deepcopy(pins.posts);me.posts[self.ids[0]]['images'][0]['path']='../escape.png'
  (self.w/'escape.png').write_bytes(b'synthetic-non-image-0-0')
  with patch.object(gate,'PinnedInputs',Escape):
   with self.assertRaises(ValueError):self.call()
 def test_fresh_wrapper_rechecks_full_snapshot(self):
  class Writer:
   def __init__(me,state,head):me.state=state;me.head=head;me.n=0
   def clock(me):return 1000
   def read(me):me.n+=1;return me.head,copy.deepcopy(me.state)
  writer=Writer(self.state,self.head);result=gate.next_from_writer(writer,self.doc,self.root);self.assertEqual(writer.n,2);self.assertEqual(result['post_id'],self.ids[0])
  class Changed(Writer):
   def read(me):
    head,state=super().read()
    if me.n==2:state['unrelated_change']=True
    return head,state
  with self.assertRaises(Refused):gate.next_from_writer(Changed(self.state,self.head),self.doc,self.root)
if __name__=='__main__':unittest.main()
