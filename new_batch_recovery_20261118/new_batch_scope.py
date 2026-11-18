"""Exact newly claimed batch activation; deliberately separate from prod-0002 recovery.
No I/O, claim, migration or live activation on import. Existing scope unchanged.
"""
import copy,re,json
from pathlib import Path
from recovery_adapter import Refused,sha
from runtime_components import PinnedInputs,digest
KIND='new-claimed-batch-v1'
FILES=('network_runtime.py','runtime_components.py','recovery_adapter.py','rehearsal_pipeline.py','connector_protocol.py','connector_bridge.py','connector_transport.js','pack_compressed.py','next_batch.py','new_batch_scope.py','new_batch_images.py','policy_tombstones.py')
def identity(h):
 return {k:copy.deepcopy(h[k]) for k in ('plan','plan_sha256','destination','job_id')}
def build(state,head,key,review_reference,root,base=None,image_gate=None):
 if not re.fullmatch('[a-f0-9]{40}',head) or not review_reference.strip():raise Refused('verified accepted head and independent review required')
 h=state['koyo_index_handoffs'][key];p=h['plan']['payload'];ids=p['source']['post_ids']
 if p.get('revision')!='recovery-next-batch-v1' or key!=sha(p) or h['plan'].get('plan_sha256')!=key or h['plan_sha256']!=key:raise Refused('accepted next-batch plan required')
 if h['job_id'] in ('prod-0001','prod-0002') or len(ids)!=50 or len(set(ids))!=50:raise Refused('not pristine new fixed50 scope')
 if h['destination'].get('worker_id')!='koyo' or p.get('destination')!=h['destination'] or p['source']['job_id']!=h['job_id']:raise Refused('plan job/worker mismatch')
 if h['status']!='leased' or h['lease']['owner']!='koyo' or key in state.get('koyo_retained_work',{}):raise Refused('new active owned handoff required')
 if any(h.get(f) for f in ('rows','context','events','operations')):raise Refused('new batch must be activated before any work')
 pins=PinnedInputs(root,h)
 if set(pins.posts)!=set(ids):raise Refused('manifest membership mismatch')
 if any(set(ids)&set(old['plan']['payload']['source']['post_ids']) for k,old in state['koyo_index_handoffs'].items() if k!=key):raise Refused('overlap with prior work')
 from new_batch_images import make_binding,BINDING_KEYS
 if not isinstance(image_gate,dict):raise Refused('reviewed image gate binding required')
 image_gate=make_binding(**image_gate)
 base=Path(base or Path(__file__).parent)
 config=json.loads((Path(root)/'runs/production-v4-001.json').read_text())
 safety_files=('pipeline_production/isolation.py','pipeline_production/disposition.py')
 for f in safety_files:
  if digest(Path(root)/f)!=config['toolchain_sha256'].get(f):raise Refused('pinned safety module changed')
 payload={'mode':'reviewed-live','revision':KIND,'review_reference':review_reference,'plan_sha256':key,'source_head':head,'source_state_sha256':sha(state),'scope':{'kind':KIND,'job_id':h['job_id'],'post_ids':ids,'held_post_ids':[],'max_new_rows':50,'external_exploration':False,'allow_recorded_source_failure':True},'image_gate':image_gate,'baseline_rows':{},'baseline_identity':identity(h),'baseline_handoff':copy.deepcopy(h),'code_sha256':{str((base/f).resolve()):digest(base/f) for f in FILES}}
 payload['code_sha256'].update({str((Path(root)/f).resolve()):digest(Path(root)/f) for f in safety_files})
 return {'payload':payload,'sha256':sha(payload)}
def validate_scope(payload,before,after,key,operation,root):
 b=before['koyo_index_handoffs'][key];a=after['koyo_index_handoffs'][key];scope=payload['scope'];base=payload.get('baseline_handoff',{});ids=b['plan']['payload']['source']['post_ids']
 if payload.get('revision')!=KIND or scope!={'kind':KIND,'job_id':b['job_id'],'post_ids':ids,'held_post_ids':[],'max_new_rows':50,'external_exploration':False,'allow_recorded_source_failure':True}:raise Refused('new batch exact scope mismatch')
 from new_batch_images import make_binding,BINDING_KEYS
 binding=payload.get('image_gate',{})
 if set(binding) not in (BINDING_KEYS,BINDING_KEYS|{'coverage_boundaries'}) or make_binding(**binding)!=binding:raise Refused('pinned image gate missing or altered')
 required={str((Path(__file__).parent/f).resolve()) for f in FILES}
 required|={str((Path(root)/f).resolve()) for f in ('pipeline_production/isolation.py','pipeline_production/disposition.py')}
 if not required<=set(payload.get('code_sha256',{})):raise Refused('new batch mandatory code pins missing')
 if payload.get('baseline_rows')!={} or not base or any(base.get(f) for f in ('rows','context','events','operations')):raise Refused('new batch pristine baseline missing')
 if identity(base)!=payload.get('baseline_identity') or identity(b)!=identity(base) or identity(a)!=identity(base):raise Refused('pinned new batch identity changed')
 if b['job_id'] in ('prod-0001','prod-0002') or len(ids)!=50 or len(set(ids))!=50 or b['destination'].get('worker_id')!='koyo' or b['plan']['payload'].get('revision')!='recovery-next-batch-v1':raise Refused('not newly claimed Koyo fixed50')
 if sha(b['plan']['payload'])!=key or b['plan']['plan_sha256']!=key or b['plan_sha256']!=key:raise Refused('new plan digest mismatch')
 if base.get('status')!='leased' or base.get('lease',{}).get('owner')!='koyo':raise Refused('baseline owner invalid')
 PinnedInputs(root,b)
 for f in ('rows','context','events'):
  if (set(b[f])|set(a[f]))-set(ids):raise Refused('outside fixed post set')
 if any(set(ids)&set(old['plan']['payload']['source']['post_ids']) for k,old in before['koyo_index_handoffs'].items() if k!=key):raise Refused('overlap with prior work')
 changed={p for f in ('context','events','rows') for p in set(b[f])|set(a[f]) if b[f].get(p)!=a[f].get(p)}
 if operation in ('renew','reacquire'):
  if changed:raise Refused('lease changed post data')
  return None
 if operation=='exploration':raise Refused('new batch exploration needs separate dedicated activation')
 if len(changed)!=1 or not changed<=set(ids):raise Refused('one pinned new post required')
 pid=next(iter(changed))
 if operation!='exclude-post':
  from policy_tombstones import require_not_refused
  require_not_refused(before,pid,root,binding['local_refusal_dir'])
 return pid


def validate_document(doc,root,base=None):
 """Mandatory before local body/exclusion entry points, not only publication."""
 p=doc.get('payload',{});base=Path(base or Path(__file__).parent)
 if doc.get('sha256')!=sha(p) or p.get('mode')!='reviewed-live' or p.get('scope',{}).get('kind')!=KIND or not p.get('review_reference'):raise Refused('new activation document integrity')
 required={str((base/f).resolve()) for f in FILES}
 required|={str((Path(root)/f).resolve()) for f in ('pipeline_production/isolation.py','pipeline_production/disposition.py')}
 pins=p.get('code_sha256',{})
 if not required<=set(pins) or any(digest(f)!=v for f,v in pins.items()):raise Refused('new activation mandatory module pins')
 return True
