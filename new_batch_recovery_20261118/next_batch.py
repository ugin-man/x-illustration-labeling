"""Offline recovery-next-batch-v1. No network publisher or live activation.
Single-index Koyo transfer, NOT ops-r5's two-ref native claim.
"""
import copy,json,random,re
from pathlib import Path
from recovery_adapter import Refused,Stale,sha
from runtime_components import PinnedInputs,digest,number
BASELINE=Path(__file__).with_name('accepted-baseline.json')
BASELINE_SHA256='0b3474ec548e1c94469680d673f88da458a16178d51927177087e06b793d229a'
ROOT=Path('/tmp/x-recovery-isolated')
CATALOG=ROOT/'data/catalogs/data-v4-production-7113eaaefc38.json'
def pristine(e):
    return (e.get('status')=='pending' and e.get('post_count')==50 and
      e.get('completed_posts')==0 and e.get('worker_id') is None and
      e.get('dispatch_token') is None and e.get('head') is None and
      e.get('lease_until')==0 and e.get('retry_after')==0 and e.get('updated_at')==0)
def complete(h,root=ROOT):
    if h.get('plan_sha256')!=h['plan'].get('plan_sha256') or sha(h['plan']['payload'])!=h['plan_sha256']:raise Refused('plan integrity')
    ids=h['plan']['payload']['source']['post_ids']
    if len(ids)!=50 or len(set(ids))!=50 or set(h['rows'])!=set(ids):raise Refused('current or prior batch unresolved; holds are not completion')
    pins=PinnedInputs(root,h)
    for pid in ids:
        pins.validate_row(h['rows'][pid],h['events'].get(pid,[]))
        from pipeline_production import disposition
        if disposition.is_exclusion(h['rows'][pid]):continue
        c=h['context'].get(pid,{})
        if 'cache' not in c or 'fetch_started' not in c:raise Refused('missing durable body history')
        from ops_runtime_r5.queue import cache_value
        try:cache_value(json.dumps(c['cache']),pid)
        except (ValueError,TypeError):raise Refused('invalid durable cache')
        if h['rows'][pid]['context']['stop_reason']=='source_unavailable' and c['cache'].get('state') not in ('technical_failure','unavailable'):raise Refused('source failure not backed by cache')
        seal=c.get('exploration_clock',{}).get('seal')
        if c.get('exploration_clock') and not seal:raise Refused('unsealed exploration clock')
        if 'budget' in c and not seal:
            # Preserve, never reinterpret, the already-accepted legacy baseline.
            if digest(BASELINE)!=BASELINE_SHA256:raise Refused('legacy baseline changed')
            legacy=json.loads(BASELINE.read_text())['koyo_index_handoffs'].get(h['plan_sha256'],{})
            if (legacy.get('status')!='completed' or legacy.get('rows',{}).get(pid)!=h['rows'][pid] or legacy.get('context',{}).get(pid)!=c or legacy.get('events',{}).get(pid)!=h['events'].get(pid)):raise Refused('unresolved exploration outside accepted legacy baseline')
            continue
        for k in ('searches','pages','elapsed_seconds'):
            if h['rows'][pid]['context'][k]!=(seal[k] if seal else 0):raise Refused('unreconciled research counters')
def next_candidates(state):
    cat=json.loads(CATALOG.read_text())
    if digest(CATALOG)!=state['catalog_sha256']:raise Refused('catalog changed')
    jobs={j['job_id']:j for j in cat['jobs']}
    taken={h['job_id'] for h in state['koyo_index_handoffs'].values()}
    candidates=[jid for jid,e in state['entries'].items() if pristine(e) and jid not in taken and jid in jobs and len(jobs[jid]['post_ids'])==50]
    # Same deterministic permutation rule as formal DispatchQueue.claim, narrowed
    # to untouched pending only; never seize expired Terra/available work.
    random.Random(state['run_id']+'koyo').shuffle(candidates)
    return candidates,jobs
def validate_retention(before,key,head,token,now,r):
    h=before['koyo_index_handoffs'][key];ids=h['plan']['payload']['source']['post_ids']
    if h.get('plan_sha256')!=h['plan'].get('plan_sha256') or sha(h['plan']['payload'])!=key or len(ids)!=50 or len(set(ids))!=50:raise Refused('retained plan invalid')
    pins=PinnedInputs(ROOT,h)
    if not set(h['rows'])<=set(ids):raise Refused('retained rows outside plan')
    for pid,row in h['rows'].items():pins.validate_row(row,h['events'].get(pid,[]))
    unresolved=set(ids)-set(h['rows'])
    if not unresolved:raise Refused('use complete mode for fully resolved batch')
    if not isinstance(r,dict) or r.get('version')!='retained-responsibility-v1' or r.get('source_head')!=head or r.get('plan_sha256')!=key or r.get('owner')!='koyo' or r.get('lease_token')!=token or r.get('handoff_sha256')!=sha(h) or r.get('reserved_post_ids')!=ids:raise Refused('retained ownership mismatch')
    if r.get('research_disposition') is not None or r.get('status')!='operationally_paused' or r.get('body_replay_allowed') is not False:raise Refused('pause is not research failure/completion')
    if not r.get('authorization_reference') or not r.get('all_previous_writers_stopped') is True or not r.get('fencing_reference') or not now-60<=r.get('checked_at',-1)<=now:raise Refused('fresh retained-writer fencing required')
    reasons=r.get('unresolved',{})
    if set(reasons)!=unresolved:raise Refused('every unresolved post retains explicit responsibility')
    for pid,item in reasons.items():
        if set(item)!={'reason','research_disposition','context_sha256','events_sha256'} or item['reason'] not in ('uncertain_fetch_history','external_exploration_required','awaiting_resolution','unstarted_deferred') or item['research_disposition'] is not None or item['context_sha256']!=sha(h['context'].get(pid)) or item['events_sha256']!=sha(h['events'].get(pid,[])):raise Refused('unresolved evidence/reason changed')
    return True

def require_scheduler_permission(state,key):
    # Must be integrated into ALL affected write/body-entry points before live.
    if key in state.get('koyo_retained_work',{}):raise Refused('retained paused responsibility: explicit fenced resumption required')
    return True

def prepare(before,head,current_key,token,now,new_token,history,inventory,authorization,*,mode="complete-then-claim",retention=None):
    number(now)
    if not re.fullmatch('[a-f0-9]{40}',head) or not re.fullmatch('[a-f0-9]{32}',new_token):raise Refused('head/token shape')
    h=before['koyo_index_handoffs'][current_key]
    if h['status']!='leased' or h['lease']['owner']!='koyo' or h['lease']['token']!=token or h['lease']['until']<=now+30:raise Refused('current lease not owned with margin')
    if mode not in ('complete-then-claim','retain-unresolved-and-claim'):raise Refused('unknown claim mode')
    for key,prior in before['koyo_index_handoffs'].items():
        if prior['destination']['worker_id']!='koyo':raise Refused('unexpected handoff owner')
        if key!=current_key and prior['status']!='completed':
            r=before.get('koyo_retained_work',{}).get(key)
            if not r:raise Refused('unfinished handoff has no retained responsibility')
            validate_retention(before,key,r.get('source_head'),prior['lease']['token'],r.get('checked_at'),r)
            successors=[x for x in before['koyo_index_handoffs'].values() if x['plan']['payload'].get('retention')==r]
            if len(successors)!=1:raise Refused('retention lacks unique accepted successor')
        elif key!=current_key or mode=='complete-then-claim':complete(prior)
    if mode=='retain-unresolved-and-claim':validate_retention(before,current_key,head,token,now,retention)
    candidates,jobs=next_candidates(before)
    if not candidates:raise Refused('no untouched fixed 50 available')
    if new_token==token or any(new_token==x['lease']['token'] for x in before['koyo_index_handoffs'].values()):raise Refused('new unique lease token required')
    jid=candidates[0];job=jobs[jid];ids=job['post_ids']
    if any(set(ids)&set(prior['plan']['payload']['source']['post_ids']) for prior in before['koyo_index_handoffs'].values()):raise Refused('duplicate prior post')
    # Evidence MUST be generated from full, verified ancestry and a fresh source
    # inventory. These objects are artifacts for review, never self-authorizing.
    if history.get('source_head')!=head or history.get('job_id')!=jid or history.get('complete_ancestry') is not True or not history.get('verified_commit_count',0)>0 or history.get('ever_touched') is not False or not re.fullmatch('[a-f0-9]{64}',history.get('ancestry_sha256','')):raise Refused('missing complete untouched ancestry proof')
    if inventory.get('evidence_mode')=='never-assigned-protocol-v1':
        from protocol_claim_evidence import validate_summary
        validate_summary(inventory,head,jid,ids,history,now)
    elif inventory.get('source_head')!=head or inventory.get('job_id')!=jid or inventory.get('post_ids')!=ids or inventory.get('job_branch_exists') is not False or inventory.get('unshared_work')!=[] or inventory.get('active_writers')!=[] or inventory.get('pending_journals')!=[] or not inventory.get('coverage_reference') or not now-60<=inventory.get('checked_at',-1)<=now:raise Refused('unshared work/branch/writer inventory unresolved')
    if not authorization:raise Refused('explicit ongoing user authorization reference required')
    source=copy.deepcopy(h['plan']['payload']['source'])
    source.update(job_id=jid,post_ids=ids,manifest_sha256=sha(job['manifest']))
    destination=copy.deepcopy(h['destination']);destination['run_id']='production-v4-koyo-'+jid.removeprefix('prod-').lstrip('0').zfill(3)
    payload={'revision':'recovery-next-batch-v1','semantics':'operational_transfer_not_research_exclusion_or_completion','source':source,'destination':destination,'expected_source_index_head':head,'authorization_reference':authorization,'claim_mode':mode,'retention':retention,'eligibility':{'history':history,'inventory':inventory},'code_sha256':{str(Path(__file__).resolve()):digest(__file__)}}
    plan={'payload':payload,'plan_sha256':sha(payload)};key=plan['plan_sha256']
    after=copy.deepcopy(before)
    if mode=='complete-then-claim':after['koyo_index_handoffs'][current_key]['status']='completed'
    else:
        if current_key in after.get('koyo_retained_work',{}):raise Refused('retention already exists; reconcile')
        after.setdefault('koyo_retained_work',{})[current_key]=copy.deepcopy(retention)
    after['entries'][jid]['status']='needs_review'
    after['koyo_index_handoffs'][key]={'plan':plan,'plan_sha256':key,'destination':destination,'job_id':jid,'status':'leased','lease':{'owner':'koyo','token':new_token,'until':now+1800},'rows':{},'context':{},'events':{},'operations':{}}
    return {'revision':'recovery-next-batch-v1','mode':'offline-review-only','expected_head':head,'before_sha256':sha(before),'after_sha256':sha(after),'after':after,'current_key':current_key,'new_key':key,'prepared_at':now,'current_token':token}
def validate_candidate(candidate,before,actual_head,now):
    if actual_head!=candidate['expected_head'] or sha(before)!=candidate['before_sha256']:raise Stale('source moved; discard candidate')
    if not candidate['prepared_at']<=now<=candidate['prepared_at']+60:raise Refused('candidate stale/future')
    a=candidate['after'];new=a['koyo_index_handoffs'][candidate['new_key']];p=new['plan']['payload']
    rebuilt=prepare(before,actual_head,candidate['current_key'],candidate['current_token'],candidate['prepared_at'],new['lease']['token'],p['eligibility']['history'],p['eligibility']['inventory'],p['authorization_reference'],mode=p['claim_mode'],retention=p['retention'])
    if rebuilt!=candidate or before['koyo_index_handoffs'][candidate['current_key']]['lease']['until']<=now+30:raise Refused('candidate mutation or expired lease')
    return True
def live_publish(*args,**kwargs):
    raise Refused('offline only: independent claim writer/activation/history collector review required')

def collect_local_history(repo,head,job_id):
    """Read-only local full Git ancestry proof. Fetch/remote refs verification is
    a separate reviewed step; this never considers absence of a local ref proof
    of absence remotely. Refuses shallow checkouts and history gaps."""
    import subprocess
    def git(*args):
        p=subprocess.run(['git','-C',str(repo),*args],capture_output=True,check=True)
        return p.stdout.decode()
    if git('rev-parse','--is-shallow-repository').strip()!='false':raise Refused('shallow history is not complete')
    if git('rev-parse',head+'^{commit}').strip()!=head:raise Refused('head not exact commit')
    commits=git('rev-list','--topo-order',head).splitlines()
    touched=False;chain=[]
    for commit in commits:
        state=json.loads(git('show',commit+':state.json'))
        entry=state.get('entries',{}).get(job_id)
        if entry is None or not pristine(entry):touched=True
        if any(h.get('job_id')==job_id for h in state.get('koyo_index_handoffs',{}).values()):touched=True
        chain.append({'commit':commit,'parents':git('show','-s','--format=%P',commit).split(),'state_sha256':sha(state)})
    return {'source_head':head,'job_id':job_id,'complete_ancestry':True,'verified_commit_count':len(chain),'ever_touched':touched,'ancestry_sha256':sha(chain)}
