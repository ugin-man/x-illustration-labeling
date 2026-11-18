"""Read-only evidence collector. Never equates unknown coverage to empty work."""
import os,json,time,subprocess
from pathlib import Path
from recovery_adapter import Refused,sha
def collect_environment(environment_id,roots,post_ids,job_id,*,clock=time.time):
    if not environment_id or not roots:raise Refused('explicit environment/root scope required')
    targets=set(post_ids)|{job_id};hits=[];errors=[];files=[]
    for raw in roots:
        root=Path(raw)
        if not root.is_dir():errors.append({'root':str(root),'error':'unavailable'});continue
        def walk_error(e):errors.append({'path':e.filename,'error':type(e).__name__})
        for parent,dirs,names in os.walk(root,onerror=walk_error,followlinks=False):
            for name in dirs+names:
                p=Path(parent)/name
                if p.is_symlink():errors.append({'path':str(p),'error':'symlink coverage unresolved'})
            for name in names:
                p=Path(parent)/name
                if p.is_symlink():continue
                try:
                    data=p.read_bytes()
                    files.append({'path':str(p),'bytes':len(data),'sha256':__import__('hashlib').sha256(data).hexdigest()})
                    if any(x in str(p) or x.encode() in data for x in targets):hits.append(str(p))
                except OSError as exc:errors.append({'path':str(p),'error':type(exc).__name__})
    # Process list is evidence, not a claim that another connected machine is idle.
    proc=subprocess.run(['ps','-eo','pid=,args='],capture_output=True,check=True,text=True).stdout
    writers=[line.strip() for line in proc.splitlines() if any(t in line for t in ('koyo_index','connector_bridge.py','rehearsal_pipeline','ops_runtime'))]
    return {'environment_id':environment_id,'roots':[str(Path(r)) for r in roots],'checked_at':clock(),'files_sha256':sha(files),'matching_artifacts':hits,'coverage_errors':errors,'observed_writer_processes':writers}
def assemble(head,job_id,post_ids,coverage,observations,refs,now):
    # coverage is a separately reviewed exhaustive manifest of relevant connected
    # environments and stores, not selected by the scanner to get a clean result.
    if not coverage.get('review_reference') or not coverage.get('environment_roots'):raise Refused('coverage not established')
    expected=coverage['environment_roots'];seen={}
    for o in observations:
        eid=o['environment_id']
        if eid in seen:raise Refused('duplicate environment observation')
        seen[eid]=o
    if set(seen)!=set(expected):raise Refused('missing environment coverage')
    evidence=[]
    for eid,roots in expected.items():
        o=seen[eid]
        if o['roots']!=roots or not now-60<=o['checked_at']<=now:raise Refused('stale/changed root inventory')
        if o['coverage_errors'] or o['matching_artifacts'] or o['observed_writer_processes']:raise Refused('unshared work or writer/coverage uncertainty')
        evidence.append(o)
    if refs.get('source_head')!=head or refs.get('job_id')!=job_id or refs.get('exists') is not False or not refs.get('verified_remote_reference') or not now-60<=refs.get('checked_at',-1)<=now:raise Refused('remote branch absence not verified')
    return {'source_head':head,'job_id':job_id,'post_ids':post_ids,'job_branch_exists':False,'unshared_work':[],'active_writers':[],'pending_journals':[],'coverage_reference':coverage['review_reference'],'checked_at':now,'evidence_sha256':sha({'coverage':coverage,'observations':evidence,'refs':refs})}
