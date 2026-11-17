"""Local-only activation builder. Call after independent review and fresh remote verification."""
import json,sys,re
from pathlib import Path
from recovery_adapter import canonical,sha,Refused
from runtime_components import PinnedInputs,digest
BASE=Path(__file__).resolve().parent
if len(sys.argv)!=4:raise SystemExit('usage: prepare_current_batch_activation.py BASELINE_STATE_JSON VERIFIED_HEAD REVIEW_REFERENCE')
state=json.loads(Path(sys.argv[1]).read_text());head=sys.argv[2];review=sys.argv[3]
if not re.fullmatch('[a-f0-9]{40}',head) or not review.strip():raise Refused('verified head/review required')
key=next(k for k,h in state['koyo_index_handoffs'].items() if h['job_id']=='prod-0002');h=state['koyo_index_handoffs'][key];pins=PinnedInputs('/tmp/x-recovery-isolated',h);planned=h['plan']['payload']['source']['post_ids']
if len(planned)!=50 or planned[16]!='2096015385070039138' or set(h['rows'])!=set(planned[:16]+[planned[17]]):raise Refused('expected original17 accepted baseline')
for pid,row in h['rows'].items():pins.validate_row(row,h['events'][pid])
files=['network_runtime.py','runtime_components.py','recovery_adapter.py','rehearsal_pipeline.py','connector_protocol.py','connector_bridge.py','connector_transport.js','pack_compressed.py']
p={'mode':'reviewed-live','revision':'recovery-current-prod-0002-1','review_reference':review,'plan_sha256':key,'source_head':head,'source_state_sha256':sha(state),'scope':{'kind':'current-batch-prod-0002-v1','job_id':'prod-0002','post_ids':planned[18:],'held_post_ids':[planned[16]],'max_new_rows':32,'external_exploration':False,'allow_recorded_source_failure':True},'baseline_rows':h['rows'],'code_sha256':{str((BASE/f).resolve()):digest(BASE/f) for f in files}}
(BASE/'current-batch-baseline.json').write_bytes(canonical(state));(BASE/'connector-activation.json').write_bytes(canonical({'payload':p,'sha256':sha(p)}));print(json.dumps({'activation_sha256':sha(p),'allowed_posts':len(planned[18:]),'baseline_posts':len(h['rows']),'held_posts':[planned[16]]}))
