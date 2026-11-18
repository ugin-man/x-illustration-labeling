"""Only generated catalog/state/IDs; production code is read-only test dependency."""
import copy,importlib.util,json,shutil,sys,tempfile,unittest
from pathlib import Path
from successor_fixture import *
CODE=Path('/tmp/koyo-current-batch-candidate');PATCH=Path('/tmp/koyo-nonillustration-candidate');SOURCE=Path('/tmp/x-recovery-isolated')
sys.path[:0]=[str(CODE),str(SOURCE)]
from recovery_adapter import sha
from runtime_components import digest,provenance,PinnedInputs
from pipeline_production.contract_v4 import template,answer
from new_batch_scope import FILES

def load_scope(path,name):
 spec=importlib.util.spec_from_file_location(name,path/'new_batch_scope.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def make_fixture():
 tmp=tempfile.TemporaryDirectory(prefix='synthetic-successor-',dir='/tmp');root=Path(tmp.name);(root/'FIXTURE_ONLY').write_text('SYNTHETIC, NOT APPROVAL\n');old=root/'old';new=root/'new';src=root/'source';old.mkdir();new.mkdir()
 for n in FILES:
  shutil.copyfile(CODE/n,old/n);shutil.copyfile((PATCH if n=='network_runtime.py' else CODE)/n,new/n)
 for n in ['pipeline_production/contract_v4.py','pipeline_production/isolation.py','pipeline_production/disposition.py']:
  p=src/n;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(SOURCE/n,p)
 for p in ['docs','data/catalogs','runs','bundle','refusals']:(src/p).mkdir(parents=True,exist_ok=True)
 (src/'docs/LABELING_V4_PRODUCTION.md').write_text('SYNTHETIC manual fixture, not research data')
 ids=[str(900000+i) for i in range(50)];manifest={'posts':[{'post_id':p,'images':[{'media_index':1,'sha256':'a'*64,'path':'synthetic-no-pixels.bin'}]} for p in ids]}
 (src/'data/catalogs/data-v4-production-7113eaaefc38.json').write_text(json.dumps({'fixture_only':True,'jobs':[{'job_id':'synthetic-job','manifest':manifest}]}))
 config={'fixture_only':True,'toolchain_sha256':{n:digest(src/n) for n in ['pipeline_production/isolation.py','pipeline_production/disposition.py']}}
 (src/'runs/production-v4-001.json').write_text(json.dumps(config))
 s={'job_id':'synthetic-job','run_id':'synthetic-run','post_ids':ids,'manifest_sha256':sha(manifest),'screening_receipt_sha256':'b'*64}
 for key,n in {'contract_sha256':'pipeline_production/contract_v4.py','manual_sha256':'docs/LABELING_V4_PRODUCTION.md','catalog_sha256':'data/catalogs/data-v4-production-7113eaaefc38.json','config_sha256':'runs/production-v4-001.json'}.items():s[key]=digest(src/n)
 dest={'worker_id':'koyo','run_id':'synthetic-destination','model_id':'fixture','model_identity_source':'fixture','reasoning_effort':'fixture'}
 plan={'revision':'recovery-next-batch-v1','source':s,'destination':dest};key=sha(plan)
 h={'plan':{'payload':plan,'plan_sha256':key},'plan_sha256':key,'destination':dest,'job_id':'synthetic-job','status':'leased','lease':{'owner':'koyo','token':'0'*32,'until':3000},'rows':{},'events':{},'context':{},'operations':{}}
 genesis={'fixture_only':True,'entries':{'synthetic-terra':{'worker_id':'terra','fixture_only':True}},'koyo_index_handoffs':{key:h}}
 ov=load_scope(old,'fixture_old_scope');nv=load_scope(new,'fixture_new_scope');doc=ov.build(genesis,'1'*40,key,'SYNTHETIC test review, never issuance',str(src),str(old),image_gate={'bundle_root':str(src/'bundle'),'audit_roots':[str(src)],'local_refusal_dir':str(src/'refusals'),'review_reference':'SYNTHETIC'})
 state=copy.deepcopy(genesis);hh=state['koyo_index_handoffs'][key];pid=ids[0];row=template(manifest['posts'][0],provenance(h),'koyo');im=row['images'][0];im['viewed']=True
 for k in im['attributes']:im['attributes'][k]=answer('not_applicable',reason='SYNTHETIC no illustration')
 im['attributes']['content_kind']=answer('observed','screenshot',evidence='SYNTHETIC fixture');im['attributes']['illustration_present']=answer('observed',False,evidence='SYNTHETIC fixture')
 row['post_attributes']['work_form']=answer('not_applicable',reason='SYNTHETIC');row['character_coverage']='complete'
 for k in ['character_count','person_count','animal_count']:row[k]=answer('observed',0,evidence='SYNTHETIC')
 row['context']={'state':'complete','attributes':{k:answer('not_applicable',reason='SYNTHETIC') for k in ['creation','promotion']},'searches':0,'pages':0,'elapsed_seconds':0,'stop_reason':'not_applicable'};row['execution']['finished_at']=row['execution']['started_at']
 events=[{'post_id':pid,'media_index':1,'sha256':'a'*64,'outcome':'viewed','tool':'SYNTHETIC_ONLY','tool_call_id':'SYNTHETIC_NOT_ACTUAL_VIEW'}];PinnedInputs(src,h).validate_row(row,events)
 hh['rows'][pid]=row;hh['events'][pid]=events;hh['context'][pid]={'fetch_started':900,'cache':{'state':'available','post_id':pid,'text':'SYNTHETIC'}}
 # This demonstrates an already-progressed handoff without changing genesis.
 m={'fixture_only':True,'generation':2,'parent_generation':1,'head':'2'*40,'state_digest':digest_obj(state),'old_document_digest':digest_obj(doc),'checked_at':1000,'changes':[{'name':'network_runtime.py','old':digest(old/'network_runtime.py'),'new':digest(new/'network_runtime.py')}]}
 (old/'fixture-old-activation.json').write_text(json.dumps(doc));(new/'fixture-old-activation.json').write_text(json.dumps(doc))
 case={'fixture_root':str(root),'old_code':str(old),'new_code':str(new),'source_root':str(src),'old_activation':doc,'old_validators':ov,'new_validators':nv,'runtime_sha':sha,'state':state,'genesis':genesis,'manifest':m,'expected_manifest':copy.deepcopy(m),'head':'2'*40,'now':1000,'pending':False,'active_writers':0}
 return tmp,case

class SuccessorTests(unittest.TestCase):
 def setUp(self):self.tmp,self.c=make_fixture()
 def tearDown(self):self.tmp.cleanup()
 def approval(self):return FixtureApproval(digest_obj(self.c['manifest']),True,True)
 def test_positive_passes_existing_validators_and_preserves_every_input(self):
  before={k:copy.deepcopy(self.c[k]) for k in ['old_activation','state','genesis','manifest']};old_bytes=(Path(self.c['old_code'])/'fixture-old-activation.json').read_bytes();r=simulate_successor(self.c,self.approval());self.assertFalse(r['deployment_allowed']);self.assertFalse(r['issuance_approved']);self.assertTrue(r['fixture_only'])
  self.assertEqual(before,{k:self.c[k] for k in before});self.assertEqual(old_bytes,(Path(self.c['old_code'])/'fixture-old-activation.json').read_bytes())
  new=r['candidate_for_validator_test'];self.c['new_validators'].validate_document(new,self.c['source_root'],self.c['new_code']);self.c['new_validators'].validate_scope(new['payload'],self.c['state'],self.c['state'],new['payload']['plan_sha256'],'renew',self.c['source_root'])
 def test_real_issuance_always_refused(self):
  for grant in [None,True,{'approved':True},self.approval(),'user authorized']:
   with self.subTest(grant=type(grant).__name__),self.assertRaises(Refused):issue_successor(self.c,approval=grant)
 def test_missing_review_or_approval(self):
  for a in [None,{'approved':True},FixtureApproval(digest_obj(self.c['manifest']),True,False),FixtureApproval(digest_obj(self.c['manifest']),False,True),FixtureApproval('bad',True,True)]:
   with self.subTest(approval=type(a).__name__),self.assertRaises(Refused):simulate_successor(self.c,a)
 def test_pending_and_active_writer_refuse(self):
  self.c['pending']=True
  with self.assertRaises(Refused):simulate_successor(self.c,self.approval())
  self.c['pending']=False;self.c['active_writers']=1
  with self.assertRaises(Refused):simulate_successor(self.c,self.approval())
 def test_stale_preflight(self):
  self.c['now']=1061
  with self.assertRaises(Refused):simulate_successor(self.c,self.approval())
 def test_head_drift(self):
  self.c['head']='3'*40
  with self.assertRaises(Refused):simulate_successor(self.c,self.approval())
 def test_state_or_terra_mutation(self):
  self.c['state']['entries']['synthetic-terra']['worker_id']='koyo'
  with self.assertRaises(Refused):simulate_successor(self.c,self.approval())
 def test_expired_lease_even_if_snapshot_bound(self):
  h=next(iter(self.c['state']['koyo_index_handoffs'].values()));h['lease']['until']=1001
  self.c['manifest']['state_digest']=digest_obj(self.c['state']);self.c['expected_manifest']=copy.deepcopy(self.c['manifest'])
  with self.assertRaises(Refused):simulate_successor(self.c,self.approval())
 def test_scope_edit_rejected(self):
  self.c['old_activation']['payload']['scope']['max_new_rows']=51
  with self.assertRaises(Refused):simulate_successor(self.c,self.approval())
 def test_genesis_rebase_rejected(self):
  self.c['genesis']=copy.deepcopy(self.c['state'])
  with self.assertRaises(Refused):simulate_successor(self.c,self.approval())
 def test_additional_module_rejected(self):
  p=Path(self.c['new_code'])/'runtime_components.py';p.write_text(p.read_text()+'\n# unapproved\n')
  with self.assertRaises(Refused):simulate_successor(self.c,self.approval())
 def test_missing_module_rejected(self):
  (Path(self.c['new_code'])/'connector_bridge.py').unlink()
  with self.assertRaises(Refused):simulate_successor(self.c,self.approval())
 def test_old_code_drift_rejected(self):
  p=Path(self.c['old_code'])/'network_runtime.py';p.write_text(p.read_text()+'\n# drift\n')
  with self.assertRaises(Exception):simulate_successor(self.c,self.approval())
 def test_candidate_hash_mismatch_rejected(self):
  self.c['manifest']['changes'][0]['new']='f'*64;self.c['expected_manifest']=copy.deepcopy(self.c['manifest'])
  with self.assertRaises(Refused):simulate_successor(self.c,self.approval())
 def test_generation_rollback_rejected(self):
  self.c['manifest']['generation']=1;self.c['expected_manifest']=copy.deepcopy(self.c['manifest'])
  with self.assertRaises(Refused):simulate_successor(self.c,self.approval())
 def test_symlink_rejected(self):
  p=Path(self.c['new_code'])/'network_runtime.py';p.unlink();p.symlink_to(Path(self.c['old_code'])/'network_runtime.py')
  with self.assertRaises(Refused):simulate_successor(self.c,self.approval())
 def test_production_root_rejected(self):
  self.c['fixture_root']=str(CODE)
  with self.assertRaises(Refused):simulate_successor(self.c,self.approval())
 def test_no_network_or_file_write_during_simulation(self):
  from unittest.mock import patch
  with patch('socket.socket',side_effect=AssertionError('network forbidden')),patch('subprocess.run',side_effect=AssertionError('process forbidden')),patch.object(Path,'write_bytes',side_effect=AssertionError('write forbidden')),patch.object(Path,'write_text',side_effect=AssertionError('write forbidden')):
   self.assertTrue(simulate_successor(self.c,self.approval())['fixture_only'])
 def test_fixed_contract_change_rejected(self):
  p=Path(self.c['source_root'])/'pipeline_production/contract_v4.py';p.write_text(p.read_text()+'\n# forbidden change\n')
  with self.assertRaises(Exception):simulate_successor(self.c,self.approval())
 def test_partial_install_fails_closed_and_matching_pair_restores(self):
  p=Path(self.c['old_code'])/'network_runtime.py';old=p.read_bytes();p.write_bytes((Path(self.c['new_code'])/'network_runtime.py').read_bytes())
  with self.assertRaises(Exception):self.c['old_validators'].validate_document(self.c['old_activation'],self.c['source_root'],self.c['old_code'])
  p.write_bytes(old);self.c['old_validators'].validate_document(self.c['old_activation'],self.c['source_root'],self.c['old_code'])
if __name__=='__main__':unittest.main(verbosity=2)
