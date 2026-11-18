"""Alternative eligibility proof, NOT a filesystem-empty assertion.
Coordinator must supply independently reviewed original read-only source artifacts.
No tool calls or remote mutation. Never converts unknown stores to empty lists.
"""
import hashlib,re,json
from datetime import datetime
from pathlib import Path
from recovery_adapter import Refused,sha
SCHEMA='never-assigned-protocol-v1'
def _hex(v,n):return isinstance(v,str) and re.fullmatch('[a-f0-9]{'+str(n)+'}',v)
def verify_artifacts(records):
 if not isinstance(records,list) or not records:raise Refused('original source artifacts required')
 for r in records:
  if set(r)!={'path','sha256','source_kind','source_reference'} or r['source_kind'] not in ('thread_management','github','pinned_source','saved_management_record') or not r['source_reference']:raise Refused('source provenance incomplete')
  p=Path(r['path'])
  if not p.is_file() or p.is_symlink() or not _hex(r['sha256'],64) or hashlib.sha256(p.read_bytes()).hexdigest()!=r['sha256']:raise Refused('source artifact missing/changed')
 return sha(records)
def assemble_protocol(before,head,job_id,post_ids,bundle,now):
 if bundle.get('schema')!=SCHEMA:raise Refused('wrong protocol proof schema')
 history=bundle.get('history',{});review=bundle.get('review',{});workers=bundle.get('workers',[]);refs=bundle.get('refs',{})
 if history.get('source_head')!=head or history.get('job_id')!=job_id or history.get('complete_ancestry') is not True or history.get('ever_touched') is not False or type(history.get('verified_commit_count')) is not int or history['verified_commit_count']<1 or not _hex(history.get('ancestry_sha256'),64):raise Refused('complete exact-head never-assigned history required')
 if not _hex(review.get('initial_index_root'),40) or not review.get('review_reference') or review.get('run_id')!=before.get('run_id') or review.get('catalog_sha256')!=before.get('catalog_sha256'):raise Refused('reviewed root/run/catalog evidence required')
 if review.get('history_continuity')!='verified-to-initialization-no-known-reset' or review.get('launched_revision_coverage')!='all-production-launches-accounted-for' or review.get('assignment_invariant')!='atomic-index-and-job-before-local-work' or review.get('out_of_band_assignment_coverage')!='none-for-target-after-reviewed-records':raise Refused('protocol/history coverage unconfirmed')
 revisions=review.get('reviewed_code_revisions')
 if not isinstance(revisions,list) or not revisions or any(not _hex(x.get('commit'),40) or not x.get('launch_reference') or not _hex(x.get('code_review_sha256'),64) for x in revisions):raise Refused('all deployed source revisions need review evidence')
 if bundle.get('physical_store_coverage')!='unconfirmed-not-used-as-zero':raise Refused('must not claim unknown stores are empty')
 artifacts_digest=verify_artifacts(bundle.get('artifacts'))
 if review.get('artifacts_sha256')!=artifacts_digest:raise Refused('review not bound to original source artifacts')
 def artifact_json(digest):
  matches=[a for a in bundle['artifacts'] if a['sha256']==digest]
  if len(matches)!=1:raise Refused('required original evidence missing/ambiguous')
  return json.loads(Path(matches[0]['path']).read_text())
 if artifact_json(review.get('history_source_sha256'))!=history:raise Refused('history not bound to original collector output')
 protocol=artifact_json(review.get('protocol_source_sha256'))
 if protocol.get('candidate')!=job_id or protocol.get('root')!=review['initial_index_root'] or protocol.get('root_scope_matches') is not True or protocol.get('source_commit')!=review.get('source_tip_commit') or not _hex(review.get('source_tip_commit'),40):raise Refused('protocol/root review source mismatch')
 required_revisions=protocol.get('required_deployed_revision_commits')
 if not isinstance(required_revisions,list) or len(set(required_revisions))!=len(required_revisions) or any(not _hex(v,40) for v in required_revisions) or {r['commit'] for r in revisions}!=set(required_revisions) or len(revisions)!=len(required_revisions):raise Refused('deployed revision coverage incomplete or duplicated')
 initial=protocol.get('initial_production_commit')
 if not _hex(initial,40) or len([r for r in revisions if r.get('kind')=='initial-production' and r['commit']==initial])!=1:raise Refused('initial production protocol coverage missing')
 for revision in revisions:
  code_review=artifact_json(revision['code_review_sha256'])
  if revision['commit'] not in code_review.get('reviewed_revision_commits',[]):raise Refused('revision absent from reviewed source commit evidence')
  launch=artifact_json(revision.get('launch_source_sha256'))
  if revision.get('kind')=='initial-production':
   if revision['commit']!=initial or launch.get('root')!=review['initial_index_root'] or launch.get('initial_production_commit')!=initial or launch.get('root_scope_matches') is not True:raise Refused('initial production root/code evidence mismatch')
  elif revision.get('kind')=='ops-ready':
   if launch.get('candidate_commit',launch.get('candidate'))!=revision['commit']:raise Refused('launch commit differs from code review revision')
   if len(launch.get('workers',[]))!=10 or {w.get('worker') for w in launch['workers']}!=set(before.get('worker_ids',[])):raise Refused('launch does not account for ten workers')
  else:raise Refused('unknown deployment evidence kind')
 mapping_raw=artifact_json(review.get('mapping_source_sha256'));mapping_entries=mapping_raw.get('worker_chat_states',[])
 if len(mapping_entries)!=10 or {x.get('worker'):x.get('thread_id') for x in mapping_entries}!=review.get('worker_thread_mapping'):raise Refused('mapping differs from original management record')
 expected=set(before.get('worker_ids',[]))
 if len(expected)!=10 or {r.get('worker_id') for r in workers}!=expected or len(workers)!=len(expected) or len({r.get('thread_id') for r in workers})!=10 or set(review.get('worker_thread_mapping',{}))!=expected:raise Refused('all ten production workers required exactly once')
 for r in workers:
  if r.get('status')!='completed' or r.get('explicit_stop_confirmed') is not True or not r.get('thread_id') or not r.get('source_reference') or not _hex(r.get('source_sha256'),64) or not any(a['sha256']==r['source_sha256'] and a['source_kind']=='thread_management' for a in bundle['artifacts']):raise Refused('worker stop source evidence missing')
  artifact=next(a for a in bundle['artifacts'] if a['sha256']==r['source_sha256'] and a['source_kind']=='thread_management')
  raw=json.loads(Path(artifact['path']).read_text());observed=datetime.fromisoformat(raw['retrieved_at'].replace('Z','+00:00')).timestamp()
  if abs(r.get('checked_at',-1)-observed)>1:raise Refused('worker freshness not from original read receipt')
  matches=[t for t in raw.get('threads',[]) if t.get('id')==r['thread_id']]
  if len(matches)!=1:raise Refused('thread not in original stop-source read')
  latest=matches[0].get('latest',{})
  if latest.get('threadId')!=r['thread_id'] or latest.get('latestTurn',{}).get('status')!='completed':raise Refused('original thread status not completed')
  messages=[m for m in latest.get('items',[]) if m.get('id')==r.get('stop_message_id') and m.get('role')=='assistant' and m.get('truncated') is False]
  if len(messages)!=1 or sha(messages[0]['text'])!=r.get('stop_message_sha256') or r.get('last_job_id') not in messages[0]['text']:raise Refused('stop/job not bound to original latest message')
  # Semantic stop meaning and fixed worker↔thread mapping are independently reviewed,
  # but their exact source messages and mapping artifact are pinned here.
  mapping=review.get('worker_thread_mapping',{})
  if mapping.get(r['worker_id'])!=r['thread_id'] or not any(a['sha256']==review.get('mapping_source_sha256') for a in bundle['artifacts']):raise Refused('worker thread mapping source missing')
  if r.get('last_job_id')==job_id or job_id in r.get('known_unshared_jobs',[]):raise Refused('candidate intersects known worker responsibility')
  if r.get('last_job_id') not in before.get('entries',{}):raise Refused('worker job outside run')
  if not isinstance(r.get('checked_at'),(int,float)) or not now-300<=r['checked_at']<=now:raise Refused('worker status observation stale')
 if refs.get('source_head')!=head or refs.get('job_id')!=job_id or refs.get('exists') is not False or not refs.get('verified_remote_reference') or not now-60<=refs.get('checked_at',-1)<=now:raise Refused('fresh exact target branch absence required')
 remote=artifact_json(review.get('refs_source_sha256'))
 if remote.get('source_head')!=head or remote.get('candidate_job')!=job_id or remote.get('ls_remote')!='' or remote.get('remote_branch_reference')!=refs['verified_remote_reference'] or not remote['remote_branch_reference'].endswith('/'+job_id) or remote.get('checked_at')!=refs['checked_at']:raise Refused('branch absence/freshness not bound to actual read artifact')
 if bundle.get('known_contradictions')!=[]:raise Refused('contradictory or unknown ownership evidence unresolved')
 # Candidate source and identity are read from the real catalog in next_batch;
 # scope never derives from thread prose or artifact commands.
 result={'evidence_mode':SCHEMA,'source_head':head,'job_id':job_id,'post_ids':post_ids,'job_branch_exists':False,'conclusion':'no-prior-authorized-assignment-for-target','physical_store_coverage':'unconfirmed-not-used-as-zero','checked_at':now,'coverage_reference':review['review_reference'],'history_sha256':sha(history),'evidence_sha256':sha(bundle)}
 return result

def validate_summary(inventory,head,job_id,post_ids,history,now):
 if inventory.get('evidence_mode')!=SCHEMA or inventory.get('source_head')!=head or inventory.get('job_id')!=job_id or inventory.get('post_ids')!=post_ids or inventory.get('job_branch_exists') is not False or inventory.get('conclusion')!='no-prior-authorized-assignment-for-target' or inventory.get('physical_store_coverage')!='unconfirmed-not-used-as-zero' or not inventory.get('coverage_reference') or inventory.get('history_sha256')!=sha(history) or not _hex(inventory.get('evidence_sha256'),64) or not now-60<=inventory.get('checked_at',-1)<=now:raise Refused('protocol eligibility summary mismatch/stale')
 if any(x in inventory for x in ('unshared_work','active_writers','pending_journals')):raise Refused('protocol proof must not masquerade as disk inventory')
 return True
