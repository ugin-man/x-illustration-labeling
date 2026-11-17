import sys,json,hashlib
from pathlib import Path
sys.path.insert(0,'/tmp/x-recovery-isolated')
from pipeline_production.contract_v4 import validate
from pipeline_production.common import canonical
root=Path('/tmp/x-recovery-isolated');s=json.load(open('/tmp/x-state-recovery.json'));c=json.loads((root/'data/catalogs/data-v4-production-7113eaaefc38.json').read_text());out=[]
for key,h in s['koyo_index_handoffs'].items():
 p=h['plan']['payload'];src=p['source']; job=next(j for j in c['jobs'] if j['job_id']==h['job_id']);manifest=job['manifest']
 assert hashlib.sha256(canonical(manifest)).hexdigest()==src['manifest_sha256']
 assert hashlib.sha256((root/'pipeline_production/contract_v4.py').read_bytes()).hexdigest()==src['contract_sha256']
 assert hashlib.sha256((root/'docs/LABELING_V4_PRODUCTION.md').read_bytes()).hexdigest()==src['manual_sha256']
 assert hashlib.sha256((root/'data/catalogs/data-v4-production-7113eaaefc38.json').read_bytes()).hexdigest()==src['catalog_sha256']
 provenance={k:src[k] for k in ['catalog_sha256','contract_sha256','job_id','manual_sha256','screening_receipt_sha256']}
 provenance.update(p['destination']); provenance.update(handoff_plan_sha256=key,schema_version='v4-1',source_run_id=src['run_id']); provenance.pop('worker_id')
 for pid,row in h['rows'].items():
  post=next(x for x in manifest['posts'] if x['post_id']==pid);validate(row,post,provenance)
 out.append({'job':h['job_id'],'rows_validated':len(h['rows']),'manifest_sha256':src['manifest_sha256']})
print(json.dumps(out,indent=2))
