"""Synthetic data using unchanged research validators. Never activates a live writer."""
import sys,copy,json,time,tempfile,hashlib,shutil
from pathlib import Path
BASE=Path(__file__).parent
RUNTIME=Path('/tmp/koyo-current-batch-candidate'); ORIGINAL=Path('/tmp/x-recovery-isolated')
sys.path[:0]=[str(RUNTIME),str(ORIGINAL)]
from recovery_adapter import sha
from runtime_components import PinnedInputs,provenance
from network_runtime import IndexWriter
from new_batch_scope import build
from pipeline_production import contract_v4 as c
from checkpoint import stage
ROOT=BASE/'network_test/fixed_source'
DATA=BASE/'network_test/fixed_synthetic.json'
def build_fixture():
 ROOT.mkdir(parents=True,exist_ok=True)
 for rel in ['pipeline_production/contract_v4.py','pipeline_production/isolation.py','pipeline_production/disposition.py','docs/LABELING_V4_PRODUCTION.md']:
  out=ROOT/rel;out.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ORIGINAL/rel,out)
 for d in ['runs','data/catalogs','bundle','refusals']:(ROOT/d).mkdir(parents=True,exist_ok=True)
 def digest(rel):return hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()
 ids=['synthetic-checkpoint-'+str(i).zfill(2) for i in range(50)]
 posts=[{'post_id':p,'images':[{'media_index':1,'sha256':hashlib.sha256(('synthetic-'+p).encode()).hexdigest()}]} for p in ids]
 manifest={'posts':posts};job='synthetic-checkpoint-test'
 (ROOT/'data/catalogs/data-v4-production-7113eaaefc38.json').write_text(json.dumps({'jobs':[{'job_id':job,'manifest':manifest}]}))
 (ROOT/'runs/production-v4-001.json').write_text(json.dumps({'toolchain_sha256':{r:digest(r) for r in ['pipeline_production/isolation.py','pipeline_production/disposition.py']}}))
 src={key:digest(path) for key,path in {'contract_sha256':'pipeline_production/contract_v4.py','manual_sha256':'docs/LABELING_V4_PRODUCTION.md','catalog_sha256':'data/catalogs/data-v4-production-7113eaaefc38.json','config_sha256':'runs/production-v4-001.json'}.items()}
 src.update(job_id=job,manifest_sha256=sha(manifest),post_ids=ids,run_id='synthetic-run',screening_receipt_sha256='0'*64)
 dest={'worker_id':'koyo','run_id':'synthetic-run','model_id':'synthetic-only','model_identity_source':'synthetic-test','reasoning_effort':'none'}
 p={'revision':'recovery-next-batch-v1','source':src,'destination':dest};key=sha(p);now=int(time.time())
 h={'plan':{'payload':p,'plan_sha256':key},'plan_sha256':key,'destination':dest,'job_id':job,'status':'leased','lease':{'owner':'koyo','token':'synthetic-not-a-credential','until':now+14400},'context':{},'events':{},'rows':{},'operations':{}}
 genesis={'catalog_sha256':src['catalog_sha256'],'entries':{'synthetic-other':{'untouched':True}},'koyo_index_handoffs':{key:h}}
 activation=build(genesis,'a'*40,key,'Synthetic validator test only; no production approval',ROOT,base=RUNTIME,image_gate={'bundle_root':str(ROOT/'bundle'),'audit_roots':[str(ROOT)],'local_refusal_dir':str(ROOT/'refusals'),'review_reference':'empty synthetic-only fixture'})
 before=copy.deepcopy(genesis);hh=before['koyo_index_handoffs'][key]
 for p in ids[:2]:hh['context'][p]={'fetch_started':now,'recovery_revision':'recovery-prototype-1','attempt_limit':1}
 items=[]
 for post in posts[:2]:
  pid=post['post_id'];a=copy.deepcopy(before);ha=a['koyo_index_handoffs'][key];ha['context'][pid]['cache']={'post_id':pid,'state':'available','text':'Synthetic fixture, no real post or source claim.'}
  row=c.template(post,provenance(h),'koyo');row['execution']['finished_at']=row['execution']['started_at']
  for im in row['images']:
   im['viewed']=True;im['attributes']={k:c.answer('unknown',reason='Synthetic test, not an actual image observation') for k in c.IMAGE_FIELDS}
  row['post_attributes']={k:c.answer('unknown',reason='Synthetic test') for k in c.POST_FIELDS}
  for f in c.COUNT_FIELDS:row[f]=c.answer('unknown',reason='Synthetic test')
  row['context'].update(state='complete',stop_reason='no_leads',attributes={k:c.answer('unknown',reason='Synthetic test') for k in c.CONTEXT_FIELDS})
  ha['rows'][pid]=row;ha['events'][pid]=[{'post_id':pid,'media_index':1,'sha256':post['images'][0]['sha256'],'outcome':'viewed','tool':'synthetic-test-not-real-view','tool_call_id':'synthetic','at':'synthetic'}]
  items.append(stage(before,a,key,pid,'finalize-post',now))
 DATA.write_text(json.dumps({'before':before,'items':items,'activation':activation,'key':key}))
 return json.loads(DATA.read_text())
def validate_transition(before,after,op,token,pid):
 data=json.loads(DATA.read_text());key=data['key']
 with tempfile.TemporaryDirectory() as d:
  import subprocess
  subprocess.run(['git','init','--bare',d],check=True,capture_output=True)
  w=IndexWriter(d,before['catalog_sha256'],key,str(ROOT),activation_document=data['activation'])
  w.live=True # validation path only; never publish or enable writes
  try:w.authorize_transition(before,after,op,token);w.preservation(before,after)
  finally:w.close()
if __name__=='__main__':
 data=build_fixture()
 from checkpoint import prepare
 print(prepare('b'*40,data['before'],data['items'],validate_transition,time.time())['sha256'])
