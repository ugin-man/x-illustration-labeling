"""Build dedicated review artifact locally; does not enable/invoke live operations."""
import copy,hashlib
from pathlib import Path
from exploration import digest,Refused

def build(baseline,head,binding,review_reference,source_root,authority_store):
 from protocol_bridge import LiveClockGuard
 base=Path(__file__).resolve().parent;key=binding['plan_sha256'];h=baseline['koyo_index_handoffs'][key];planned=h['plan']['payload']['source']['post_ids']
 if not review_reference or len(head)!=40:raise Refused('verified head and independent review required')
 files=list(base.glob('*.py'))+list((base/'runtime_snapshot').glob('*.py'))+[base/'exploration_host.js']
 p={'mode':'reviewed-live-exploration-v3','research_revision':'koyo-exploration-recovery-v3','research_limits':{'queries':2,'pages':3,'active_seconds':60},'authority_loss_policy':'stop-no-reinitialize','review_reference':review_reference,'plan_sha256':key,'source_head':head,'source_state_sha256':digest(baseline),'baseline_handoff':copy.deepcopy(h),'scope':{'job_id':'prod-0002','post_ids':planned[18:],'held_post_ids':[planned[16]],'external_exploration':True},'code_sha256':{str(f.resolve()):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}}
 activation={'payload':p,'sha256':digest(p)};LiveClockGuard(source_root,activation)(head,baseline,binding)
 return activation,{'activation':str(base/'live-activation.json'),'baseline':str(base/'live-baseline.json'),'binding':binding,'source_root':source_root,'authority_store':str(Path(authority_store).resolve())}

def build_new_batch(baseline,head,binding,review_reference,source_root,authority_store,refusal_store):
 from new_batch_guard import NewBatchClockGuard,MODE
 base=Path(__file__).resolve().parent;key=binding['plan_sha256'];h=baseline['koyo_index_handoffs'][key];planned=h['plan']['payload']['source']['post_ids']
 if not review_reference or len(head)!=40:raise Refused('verified head and independent review required')
 files=list(base.glob('*.py'))+list((base/'runtime_snapshot').glob('*.py'))+[base/'exploration_host.js']
 p={'mode':MODE,'refusal_store':str(Path(refusal_store).resolve()),'research_revision':'koyo-exploration-recovery-v3','research_limits':{'queries':2,'pages':3,'active_seconds':60},'authority_loss_policy':'stop-no-reinitialize','review_reference':review_reference,'plan_sha256':key,'source_head':head,'source_state_sha256':digest(baseline),'baseline_handoff':copy.deepcopy(h),'scope':{'kind':'new-claimed-batch-exploration-v1','job_id':h['job_id'],'post_ids':planned,'held_post_ids':[],'external_exploration':True},'code_sha256':{str(f.resolve()):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}}
 activation={'payload':p,'sha256':digest(p)};NewBatchClockGuard(source_root,activation)(head,baseline,binding)
 return activation,{'activation':str(base/'live-activation.json'),'baseline':str(base/'live-baseline.json'),'binding':binding,'source_root':source_root,'authority_store':str(Path(authority_store).resolve())}
