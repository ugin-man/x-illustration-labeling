"""Dedicated exact-plan exploration for a newly accepted batch; no legacy migration."""
import copy,hashlib
from pathlib import Path
from protocol_bridge import ReviewedClockGuard
from exploration import Refused,digest
MODE='reviewed-live-new-batch-exploration-v1'
class NewBatchClockGuard(ReviewedClockGuard):
 def __call__(self,head,state,binding):
  from persistent_runner import FixedScopeGuard
  from runtime_components import PinnedInputs
  from ops_runtime_r5.queue import cache_value
  import json
  d=self.activation;p=d.get('payload',{});key=binding['plan_sha256'];h=state['koyo_index_handoffs'][key];base=p.get('baseline_handoff',{});planned=h['plan']['payload']['source']['post_ids']
  if key in state.get('koyo_retained_work',{}):raise Refused('retained paused new-batch exploration')
  if d.get('sha256')!=digest(p) or p.get('mode')!=MODE or not p.get('review_reference') or p.get('plan_sha256')!=key:raise Refused('exact new-batch exploration activation required')
  if p.get('research_revision')!='koyo-exploration-recovery-v3' or p.get('research_limits')!={'queries':2,'pages':3,'active_seconds':60} or p.get('authority_loss_policy')!='stop-no-reinitialize':raise Refused('research limits changed')
  if len(p.get('source_head',''))!=40 or not p.get('source_state_sha256'):raise Refused('baseline source evidence missing')
  if h['job_id'] in ('prod-0001','prod-0002') or len(planned)!=50 or len(set(planned))!=50 or h['plan']['payload'].get('revision')!='recovery-next-batch-v1':raise Refused('new fixed50 claim required')
  if h['destination'].get('worker_id')!='koyo' or h['plan']['payload'].get('destination')!=h['destination'] or h['plan']['payload']['source']['job_id']!=h['job_id']:raise Refused('plan job/destination mismatch')
  scope={'kind':'new-claimed-batch-exploration-v1','job_id':h['job_id'],'post_ids':planned,'held_post_ids':[],'external_exploration':True}
  if p.get('scope')!=scope:raise Refused('exact whole-plan exploration scope required')
  for f in ('plan','plan_sha256','destination','job_id'):
   if base.get(f)!=h.get(f):raise Refused('baseline identity changed')
  for pid,row in base.get('rows',{}).items():
   if h['rows'].get(pid)!=row:raise Refused('baseline accepted row changed')
  if any(set(planned)&set(old['plan']['payload']['source']['post_ids']) for k,old in state['koyo_index_handoffs'].items() if k!=key):raise Refused('overlapping prior batch')
  here=Path(__file__).parent
  required={str((here/f).resolve()) for f in ('new_batch_guard.py','protocol_bridge.py','persistent_runner.py','exploration.py','host_bridge.py','host_cli.py','exploration_host.js','sealed_row.py','prepare_live_activation.py','policy_tombstones.py')}
  required|={str(f.resolve()) for f in (here/'runtime_snapshot').glob('*.py')}
  pins=p.get('code_sha256',{})
  if not required<=set(pins) or any(hashlib.sha256(Path(f).read_bytes()).hexdigest()!=v for f,v in pins.items()):raise Refused('new exploration code pin mismatch')
  inputs=PinnedInputs(self.root,h)
  if set(inputs.posts)!=set(planned) or binding['post_id'] not in inputs.posts:raise Refused('pinned manifest membership')
  from policy_tombstones import require_not_refused
  directory=p.get('refusal_store')
  if not isinstance(directory,str):raise Refused('pinned refusal journal required')
  from recovery_adapter import Refused as RuntimeRefused
  try:require_not_refused(state,binding['post_id'],self.root,directory)
  except RuntimeRefused as exc:raise Refused(str(exc)) from exc
  cache_value(json.dumps(h['context'][binding['post_id']].get('cache')),binding['post_id'])
  return FixedScopeGuard(key,key,planned,h['job_id'])(head,state,binding)
