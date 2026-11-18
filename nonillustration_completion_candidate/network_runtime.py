"""Recovery candidate 3. Network writer implemented, disabled by default.
Only isolated local bare remotes are exercised by its tests.
"""
import copy,json,time,subprocess,uuid
from pathlib import Path
from recovery_adapter import Refused,Stale,sha
from runtime_components import PinnedInputs,number
from pipeline_production.git_queue import GitQueue,QueueError
from ops_runtime_r5.queue import OpsQueue
from ops_runtime_r5.transport import failure_details,RETRYABLE,wait_for_retry
REMOTE='https://github.com/ugin-man/x-illustration-labeling.git'
RUN='production-v4-001';JOB='dispatch-index'
class RecoveryQueue(OpsQueue):
    # Reuse pinned ops-r5 sanitization, bounded read retries and credential handling.
    def __init__(self,remote,run_id,catalog,clock):
        GitQueue.__init__(self,remote,run_id,catalog,clock=clock)

class IndexWriter:
    def __init__(self,remote,catalog,key,root,*,enable_live_writes=False,clock=time.time,activation_document=None):
        local=Path(remote).is_dir()
        if not local and remote!=REMOTE:raise Refused('destination not allowlisted')
        self.live=not local;self.enabled=enable_live_writes;self.key=key;self.root=root;self.clock=clock;self.activation_document=activation_document
        self.q=RecoveryQueue(remote,RUN,catalog,clock=clock)
    def close(self):self.q.close()
    def read(self):return self.q.read(JOB)
    def preservation(self,before,after):
        if self.key in before.get('koyo_retained_work',{}):raise Refused('retained paused writer')
        k=self.key;b=before['koyo_index_handoffs'][k];a=after['koyo_index_handoffs'][k]
        remainder=copy.deepcopy(after);remainder['koyo_index_handoffs'][k]=b
        if remainder!=before:raise Refused('outside Koyo namespace mutation')
        for field in ('plan','plan_sha256','destination','job_id','runtime_upgrade'):
            if a.get(field)!=b.get(field):raise Refused('immutable plan/identity changed')
        for pid,row in b['rows'].items():
            if a['rows'].get(pid)!=row:raise Refused('accepted row changed')
        for pid,context in b['context'].items():
            newer=a['context'].get(pid,{})
            for field in ('fetch_started','cache'):
                if field in context and newer.get(field)!=context[field]:raise Refused('fetch history changed')
            if context.get('exploration_clock',{}).get('seal') and newer!=context:raise Refused('sealed context changed')
        for pid,events in b['events'].items():
            if a['events'].get(pid,[])[:len(events)]!=events:raise Refused('view evidence changed')
        for oid,operation in b.get('operations',{}).items():
            if a.get('operations',{}).get(oid)!=operation:raise Refused('operation ledger changed')
        from ops_runtime_r5.queue import cache_value
        for pid,context in a['context'].items():
            if pid not in a['plan']['payload']['source']['post_ids']:raise Refused('context outside plan')
            if 'cache' in context:cache_value(json.dumps(context['cache']),pid)
            old=b['context'].get(pid,{})
            if 'budget' in old:
                nb=context.get('budget',{});ob=old['budget']
                if any(nb.get(k)!=ob[k] for k in ('started_at','deadline')):raise Refused('budget clock reset')
                if any(nb.get(k,-1)<ob[k] for k in ('searches','pages')):raise Refused('budget rollback')
                if nb.get('queries',[])[:len(ob['queries'])]!=ob['queries']:raise Refused('query history altered')
            if 'budget' in context:
                budget=context['budget']
                if budget['searches']>2 or budget['pages']>3 or budget['deadline']-budget['started_at']!=60:raise Refused('budget exceeds fixed limits')
            for rid,r in old.get('reservations',{}).items():
                if context.get('reservations',{}).get(rid)!=r:raise Refused('reservation ledger changed')
            oc=old.get('exploration_clock',{});nc=context.get('exploration_clock',{})
            if oc and nc!=oc and oc.get('version')!='recovery-clock-3':raise Refused('legacy clock cannot be modified')
            for rid,ack in oc.get('acks',{}).items():
                if nc.get('acks',{}).get(rid)!=ack:raise Refused('ACK ledger changed')
            if nc and nc!=oc:
                if nc.get('version')!='recovery-clock-3' or nc.get('mode') not in ('wall','active-v2-review'):raise Refused('unreviewed clock shape')
                if oc and (nc['mode']!=oc['mode'] or nc.get('last_event_at',-1)<oc.get('last_event_at',0)):raise Refused('clock mode or time rollback')
                times=[context['budget']['started_at']]
                for rid,r in context.get('reservations',{}).items():
                    times.append(r['requested_at'])
                for rid,ack in nc.get('acks',{}).items():
                    reservation=context.get('reservations',{}).get(rid)
                    if not reservation or ack['requested_at']!=reservation['requested_at'] or ack['ack_at']<ack['requested_at']:raise Refused('ACK reservation mismatch')
                    times.append(ack['ack_at'])
                if nc.get('last_event_at',-1)<max(times):raise Refused('last event precedes ledger')

        pins=PinnedInputs(self.root,a)
        for pid,row in a['rows'].items():
            if pid not in b['rows']:
                pins.validate_row(row,a['events'].get(pid,[]))
                from pipeline_production import disposition
                if disposition.is_exclusion(row):continue
                context=a['context'].get(pid,{})
                if 'cache' not in context:raise Refused('body cache missing')
                seal=context.get('exploration_clock',{}).get('seal')
                if 'budget' in context and not seal:raise Refused('unsealed exploration')
                for field in ('searches','pages','elapsed_seconds'):
                    if row['context'][field]!=(seal[field] if seal else 0):raise Refused('row clock mismatch')
        if a['lease']['owner']!='koyo' or a['destination']['worker_id']!='koyo':raise Refused('wrong lease owner')
        if a['lease']['until']<=self.clock():raise Refused('candidate expired')
        return a
    def authorize_transition(self,before,after,operation,lease_token,fencing_receipt=None):
        from next_batch import require_scheduler_permission
        require_scheduler_permission(before,self.key)
        b=before['koyo_index_handoffs'][self.key];a=after['koyo_index_handoffs'][self.key];now=self.clock()
        if operation=='finalize-post':
            if self.live and (self.activation_document or {}).get('payload',{}).get('scope',{}).get('kind') not in ('current-batch-prod-0002-v1','new-claimed-batch-v1'):raise Refused('finalize requires reviewed batch scope')
            # One atomic CAS replays the three already-reviewed transitions.
            # Reservation MUST preexist in before; cache cannot create its own permit.
            changed={p for f in ('context','events','rows') for p in set(b[f])|set(a[f]) if b[f].get(p)!=a[f].get(p)}
            if len(changed)!=1:raise Refused('finalize exactly one post')
            pid=next(iter(changed))
            old=b['context'].get(pid,{})
            if 'fetch_started' not in old or 'cache' in old or pid in b['rows']:raise Refused('finalize requires unused durable reservation')
            if pid not in a['rows'] or a['events'].get(pid)==b['events'].get(pid):raise Refused('finalize requires row and fresh image evidence')
            if any(k in old or k in a['context'].get(pid,{}) for k in ('budget','reservations','exploration_clock')):raise Refused('finalize excludes exploration')
            intermediate=copy.deepcopy(before)
            for op,field in (('body-cache','context'),('image-event','events'),('save-row','rows')):
                nxt=copy.deepcopy(intermediate)
                nxt['koyo_index_handoffs'][self.key][field][pid]=copy.deepcopy(a[field][pid])
                self.authorize_transition(intermediate,nxt,op,lease_token)
                self.preservation(intermediate,nxt)
                intermediate=nxt
            if intermediate!=after:raise Refused('finalize altered unrelated state')
            row=a['rows'][pid];cache=a['context'][pid]['cache']
            if row['context']['stop_reason']=='no_leads' and (cache.get('state')!='available' or row['context']['state']!='complete' or any(row['context'].get(k)!=0 for k in ('searches','pages','elapsed_seconds'))):raise Refused('no_leads requires available body and zero exploration')
            return
        if operation not in ('renew','reacquire','body-reserve','body-cache','image-event','save-row','exploration','exclude-post') or not lease_token:raise Refused('typed transition and lease token required')
        if b['lease']['owner']!='koyo' or b['lease']['token']!=lease_token or b['status']!='leased':raise Refused('prior ownership not authorized')
        if operation=='renew':
            history=a.get('recovery_lease_history',[])
            if len(history)!=len(b.get('recovery_lease_history',[]))+1:raise Refused('renewal timestamp receipt required')
            event=history[-1];prepared=number(event.get('at'));duration=number(event.get('seconds'))
            if not now-120<=prepared<=now:raise Refused('stale/future renewal preparation')
            wanted=lease_transition(before,self.key,lease_token,prepared,duration)
            if b['lease']['until']<=now:raise Refused('old lease expired before renewal')
            if after!=wanted:raise Refused('renewal differs from validated transition')
        elif operation=='reacquire':
            if b['lease']['until']>now:raise Refused('reacquire only expired lease')
            receipt=fencing_receipt or {}
            if not receipt.get('all_previous_koyo_writers_stopped') or not receipt.get('verification_reference'):raise Refused('missing fencing evidence')
            history=a.get('recovery_lease_history',[])
            if len(history)!=len(b.get('recovery_lease_history',[]))+1:raise Refused('reacquisition timestamp receipt required')
            prepared=number(history[-1].get('at'))
            if not now-120<=prepared<=now or b['lease']['until']>prepared:raise Refused('stale/future reacquisition preparation')
            wanted=copy.deepcopy(before);h=wanted['koyo_index_handoffs'][self.key]
            if a['lease']['token']==lease_token or not isinstance(a['lease']['token'],str) or len(a['lease']['token'])!=32:raise Refused('new fencing token required')
            h['lease']={'owner':'koyo','token':a['lease']['token'],'until':prepared+1800}
            h.setdefault('recovery_lease_history',[]).append({'prior_lease':copy.deepcopy(b['lease']),'fencing_receipt':copy.deepcopy(receipt),'at':prepared})
            if after!=wanted:raise Refused('reacquisition differs from fenced transition')
        else:
            if b['lease']['until']<=now or a['lease']!=b['lease']:raise Refused('expired or changed lease')
            allowed={'body-reserve':{'context'},'body-cache':{'context'},'image-event':{'events'},'save-row':{'rows'},'exclude-post':{'rows'},'exploration':{'context'}}[operation]
            if any(b.get(k)!=a.get(k) for k in set(b)|set(a) if k not in allowed):raise Refused('operation changes unrelated fields')
            if operation in ('body-reserve','body-cache','exploration'):
                changed=[p for p in set(a['context'])|set(b['context']) if a['context'].get(p)!=b['context'].get(p)]
                if len(changed)!=1:raise Refused('one context transition only')
                pid=changed[0];old=b['context'].get(pid,{});new=a['context'].get(pid,{})
                if pid not in b['plan']['payload']['source']['post_ids'] or pid in b['rows']:raise Refused('not an unaccepted pinned post')
                if operation=='body-reserve':
                    for handoff in before['koyo_index_handoffs'].values():
                        if pid in handoff.get('context',{}) or pid in handoff.get('rows',{}) or any(pid in oid and ('fetch' in oid or 'context' in oid) for oid in handoff.get('operations',{})):raise Refused('body historical evidence; no repeat')
                    if set(new)!={'fetch_started','recovery_revision','attempt_limit'} or new['attempt_limit']!=1 or new['recovery_revision']!='recovery-prototype-1' or not b['lease']['until']>new['fetch_started']>=0:raise Refused('invalid body reservation')
                elif operation=='body-cache':
                    if 'fetch_started' not in old or 'cache' in old:raise Refused('body cache requires previous committed reservation')
                    if new!={**old,'cache':new.get('cache')} or 'cache' not in new:raise Refused('cache-only append required')
                else:
                    if 'cache' not in old:raise Refused('exploration requires recorded body attempt')
                    if any(old.get(k)!=new.get(k) for k in set(old)|set(new) if k not in ('budget','reservations','exploration_clock')):raise Refused('exploration changed other context')
                    validate_exploration_transition(old,new,now,live=self.live)


        if operation=='exclude-post':
            from pipeline_production import disposition
            if (self.activation_document or {}).get('payload',{}).get('scope',{}).get('kind')!='new-claimed-batch-v1':raise Refused('exclusion only separately reviewed new scope')
            changed={p for p in set(b['rows'])|set(a['rows']) if b['rows'].get(p)!=a['rows'].get(p)}
            if len(changed)!=1:raise Refused('one metadata-only exclusion required')
            ep=next(iter(changed))
            if ep in b['rows'] or not disposition.is_exclusion(a['rows'][ep]):raise Refused('new exclusion required')
            PinnedInputs(self.root,a).validate_row(a['rows'][ep],[])

        if self.live:
            from runtime_components import digest
            doc=self.activation_document or {};payload=doc.get('payload',{})
            if doc.get('sha256')!=sha(payload) or payload.get('mode')!='reviewed-live' or payload.get('plan_sha256')!=self.key or not payload.get('review_reference'):raise Refused('reviewed activation required')
            expected_files={str(Path(__file__).resolve()),str(Path(__file__).with_name('recovery_adapter.py').resolve()),str(Path(__file__).with_name('runtime_components.py').resolve())}
            pins=payload.get('code_sha256',{})
            if not expected_files<=set(pins) or any(digest(f)!=v for f,v in pins.items()):raise Refused('activation code pin mismatch')
            scope=payload.get('scope',{})
            if scope.get('kind')=='new-claimed-batch-v1':
                from new_batch_scope import validate_scope
                pid=validate_scope(payload,before,after,self.key,operation,self.root)
            elif scope.get('kind')=='current-batch-prod-0002-v1':
                planned=b['plan']['payload']['source']['post_ids']
                if len(planned)!=50 or planned[16]!='2096015385070039138':raise Refused('unexpected frozen batch')
                permitted=planned[18:]
                baseline_ids=set(planned[:16]+[planned[17]])
                if (scope.get('job_id')!='prod-0002' or scope.get('post_ids')!=permitted
                    or scope.get('held_post_ids')!=[planned[16]] or scope.get('max_new_rows')!=32
                    or scope.get('external_exploration') is not False or b['job_id']!='prod-0002'):
                    raise Refused('current-batch exact scope required')
                base=payload.get('baseline_rows',{})
                if set(base)!=baseline_ids or any(a['rows'].get(p)!=r for p,r in base.items()):raise Refused('17-row baseline changed')
                if set(a['rows'])-set(base)-set(permitted) or len(set(a['rows'])-set(base))>32:raise Refused('batch row limit changed')
                changed={p for field in ('context','events','rows') for p in set(b[field])|set(a[field]) if b[field].get(p)!=a[field].get(p)}
                if operation in ('renew','reacquire'):
                    if changed:raise Refused('lease operation changed post data')
                    pid=None
                else:
                    if len(changed)!=1 or not changed<=set(permitted):raise Refused('one allowed post per operation; held post immutable')
                    pid=next(iter(changed))
                if operation=='exploration':raise Refused('external exploration remains disabled pending research clock review')
            else:
                if scope.get('job_id')!='prod-0002' or scope.get('max_new_rows')!=1 or scope.get('external_exploration') is not False:raise Refused('limited restart scope required')
                pid=scope.get('post_id')
                if b['job_id']!=scope['job_id'] or pid not in b['plan']['payload']['source']['post_ids']:raise Refused('scope mismatch')
                for field in ('context','events','rows'):
                    if any(b[field].get(p)!=a[field].get(p) for p in set(b[field])|set(a[field]) if p!=pid):raise Refused('outside single-post scope')
                if operation=='exploration':raise Refused('external exploration disabled in limited restart')
                base=payload.get('baseline_rows',{})
                if not base or any(a['rows'].get(p)!=r for p,r in base.items()) or set(a['rows'])-set(base)-{pid}:raise Refused('baseline or single-row limit changed')
            if operation=='save-row':
                context=a['rows'][pid]['context'];stop=context['stop_reason']
                if stop=='source_unavailable':
                    cache=b['context'].get(pid,{}).get('cache',{})
                    if scope.get('allow_recorded_source_failure') is not True or cache.get('state') not in ('technical_failure','unavailable') or context.get('state')!='technical_failure' or any(context.get(k)!=0 for k in ('searches','pages','elapsed_seconds')):raise Refused('source failure not supported by durable cache/scope')
                elif stop=='not_applicable':
                    # Fixed-schema non-illustrated posts need no invented research.
                    # Keep all scope, lease, image evidence and preservation gates.
                    row=a['rows'][pid];prior=b['context'].get(pid,{})
                    if scope.get('kind') not in ('current-batch-prod-0002-v1','new-claimed-batch-v1'):raise Refused('nonillustration requires reviewed batch scope')
                    if 'cache' not in prior or 'fetch_started' not in prior or any(k in prior for k in ('budget','reservations','exploration_clock')):raise Refused('nonillustration requires recorded body and no exploration history')
                    if context.get('state')!='complete' or any(context.get(k)!=0 for k in ('searches','pages','elapsed_seconds')):raise Refused('nonillustration has no research counters')
                    if not row.get('images') or any(not im.get('viewed') or im.get('read_error') is not None or im.get('attributes',{}).get('illustration_present',{}).get('status')!='observed' or im['attributes']['illustration_present'].get('value') is not False for im in row['images']):raise Refused('nonillustration requires all actual viewed images explicitly absent')
                    PinnedInputs(self.root,a).validate_row(row,a['events'].get(pid,[]))
                elif stop!='no_leads':raise Refused('limited restart only genuine no_leads or recorded source failure')

    def publish(self,expected,before,after,*,operation=None,lease_token=None,fencing_receipt=None,max_attempts=10):
        if self.live:raise Refused('live writes require reviewed connector protocol; CLI push disabled')
        self.authorize_transition(before,after,operation,lease_token,fencing_receipt)
        self.preservation(before,after)
        head,actual=self.read()
        if head!=expected or actual!=before:raise Stale('live snapshot changed')
        candidate=self.q._commit(after,expected)
        # One candidate only; non-force fast-forward push rejects concurrent siblings.
        for attempt in range(max_attempts):
            # Re-check old lease before each send, but fixed renewal timestamp belongs to the prepared candidate.
            if operation!='reacquire' and before['koyo_index_handoffs'][self.key]['lease']['until']<=self.clock():raise Refused('old lease expired before send')
            self.preservation(before,after)
            uncertain=False
            try:
                proc=self.q.git('push','--porcelain','origin',candidate+':'+self.q.ref(JOB),check=False)
                uncertain=proc.returncode!=0;info=failure_details(proc.stderr+b'\n'+proc.stdout)
            except (subprocess.TimeoutExpired,QueueError):
                uncertain=True;info=failure_details('timeout')
            try:observed,accepted=self.read()
            except Exception as exc:raise Refused('acceptance indeterminate; keep candidate; no external request') from exc
            if observed==candidate:
                if sha(accepted)!=sha(after):raise Refused('accepted content mismatch')
                return {'head':candidate,'state':accepted,'ack_reconciled':uncertain,'external_request_permitted':not uncertain}
            if observed!=expected:raise Stale('competing head; no replay')
            if not uncertain or info['category'] not in RETRYABLE or attempt+1==max_attempts:raise Refused('write not accepted; no external request')
            wait_for_retry(info,attempt,'recovery_exact_commit')
        raise Refused('bounded attempts exhausted')

def lease_transition(state,key,token,now,seconds=1800):
    number(now);number(seconds)
    if not 0<seconds<=3600:raise Refused('lease duration')
    out=copy.deepcopy(state);h=out['koyo_index_handoffs'][key];lease=h['lease']
    if h['status']!='leased' or lease['owner']!='koyo' or lease['token']!=token:raise Refused('lease ownership changed')
    if lease['until']<=now:raise Refused('expired: explicit fenced reacquisition required')
    prior=copy.deepcopy(lease)
    lease['until']=max(lease['until'],now+seconds)
    h.setdefault('recovery_lease_history',[]).append({'kind':'renew','prior_lease':prior,'at':now,'seconds':seconds})
    return out

class DurableExploration:
    """Existing context shape, immutable reservation/ACK/seal. Mode is explicit.
    wall: pinned original rule. active-v2-review: observed later implementation;
    requires separately reviewed authorization/equivalence before live selection.
    """
    def __init__(self,context,mode):
        if mode not in ('wall','active-v2-review'):raise Refused('choose reviewed clock mode explicitly')
        self.c=copy.deepcopy(context);self.mode=mode
    def elapsed(self,now):
        number(now);b=self.c['budget'];start=b['started_at']
        if now<self.c['exploration_clock'].get('last_event_at',start):raise Refused('clock rollback after event')
        if now<start:raise Refused('clock rollback')
        clock=self.c['exploration_clock'];intervals=[]
        for rid,r in self.c['reservations'].items():
            if r['permitted'] and rid not in clock['acks']:raise Refused('pending ACK; do not reset or replay')
        if self.mode=='active-v2-review':
            intervals=[(a['requested_at'],a['ack_at']) for a in clock['acks'].values()]
            intervals+=clock.get('management_intervals',[])
        merged=[]
        for a,z in sorted(intervals):
            if not start<=a<=z<=now:raise Refused('bad wait interval')
            if merged and a<=merged[-1][1]:merged[-1][1]=max(merged[-1][1],z)
            else:merged.append([a,z])
        return now-start-sum(z-a for a,z in merged)
    def reserve(self,rid,kind,queries,now):
        if self.c.get('exploration_clock',{}).get('seal'):raise Refused('sealed')
        if kind not in ('search','page') or not isinstance(queries,list) or not queries or not all(isinstance(q,str) and q.strip() for q in queries):raise Refused('request shape')
        if kind=='page' and len(queries)!=1:raise Refused('one page per reservation')
        if 'budget' not in self.c:
            self.c.update(budget={'started_at':now,'deadline':now+60,'searches':0,'pages':0,'queries':[]},reservations={},exploration_clock={'version':'recovery-clock-3','mode':self.mode,'acks':{},'last_event_at':now})
        c=self.c['exploration_clock']
        if c.get('version')!='recovery-clock-3' or c.get('mode')!=self.mode:raise Refused('legacy clock: no silent migration/reset')
        if rid in self.c['reservations']:raise Refused('duplicate reservation')
        elapsed=self.elapsed(now);b=self.c['budget'];n=len(queries)
        if elapsed>=60 or b['searches']+(n if kind=='search' else 0)>2 or b['pages']+(n if kind=='page' else 0)>3:raise Refused('exploration budget exhausted')
        if kind=='search':b['searches']+=n;b['queries'] += [{'query':q,'reserved_at':now} for q in queries]
        else:b['pages']+=1
        request={**copy.deepcopy(b),'budget_queries':copy.deepcopy(b['queries']),'kind':kind,'queries':copy.deepcopy(queries),'requested_at':now,'permitted':True,'request_sha256':sha({'kind':kind,'queries':queries,'requested_at':now})}
        self.c['reservations'][rid]=request
        c['last_event_at']=now
        return copy.deepcopy(self.c)
    def ack(self,rid,result_sha,now):
        if self.c['exploration_clock'].get('seal'):raise Refused('sealed')
        if len(result_sha)!=64 or any(c not in '0123456789abcdef' for c in result_sha):raise Refused('invalid result hash')
        r=self.c['reservations'][rid]
        if now<self.c['exploration_clock'].get('last_event_at',r['requested_at']):raise Refused('ACK time rollback')
        if now<r['requested_at']:raise Refused('ACK predates request')
        value={'requested_at':r['requested_at'],'ack_at':now,'request_sha256':r['request_sha256'],'result_sha256':result_sha}
        a=self.c['exploration_clock']['acks']
        if rid in a and a[rid]!=value:raise Refused('immutable ACK')
        a[rid]=value;self.c['exploration_clock']['last_event_at']=now;return copy.deepcopy(self.c)
    def seal(self,now):
        c=self.c['exploration_clock']
        if c.get('seal'):raise Refused('sealed')
        c['last_event_at']=max(c.get('last_event_at',0),now)
        c['seal']={'ended_at':now,'elapsed_seconds':self.elapsed(now),'searches':self.c['budget']['searches'],'pages':self.c['budget']['pages'],'acks_sha256':sha(c['acks'])}
        return copy.deepcopy(self.c)

def reacquire_koyo_lease(state,key,expected_token,now,fencing_receipt,seconds=1800):
    """Only own expired Koyo handoff, with external verified old-writer stop evidence.
    Fencing receipt is a coordination attestation, not proof from lease age alone.
    Must be published via expected-head CAS before any new request.
    """
    number(now)
    if not 0<seconds<=3600:raise Refused('lease duration')
    if not fencing_receipt.get('all_previous_koyo_writers_stopped') or not fencing_receipt.get('verification_reference'):raise Refused('no verified fencing')
    out=copy.deepcopy(state);h=out['koyo_index_handoffs'][key];l=h['lease']
    if h['status']!='leased' or l['owner']!='koyo' or l['token']!=expected_token or l['until']>now:raise Refused('not own expired Koyo lease')
    h['lease']={'owner':'koyo','token':uuid.uuid4().hex,'until':now+seconds}
    h.setdefault('recovery_lease_history',[]).append({'prior_lease':copy.deepcopy(l),'fencing_receipt':copy.deepcopy(fencing_receipt),'at':now})
    return out


def validate_exploration_transition(old,new,now,live=False):
    nc=new.get('exploration_clock',{});oc=old.get('exploration_clock',{})
    mode=nc.get('mode')
    if live:raise Refused('live exploration scheduling disabled pending clock specification review')
    if oc and oc.get('version')!='recovery-clock-3':raise Refused('legacy exploration is immutable')
    engine=DurableExploration(old,mode)
    nr=new.get('reservations',{});orr=old.get('reservations',{})
    na=nc.get('acks',{});oa=oc.get('acks',{})
    new_res=set(nr)-set(orr);new_ack=set(na)-set(oa);new_seal='seal' in nc and 'seal' not in oc
    if len(new_res)+len(new_ack)+int(new_seal)!=1:raise Refused('one exploration event per commit')
    if new_res:
        rid=next(iter(new_res));r=nr[rid];at=number(r['requested_at'])
        if at>now:raise Refused('future request')
        wanted=engine.reserve(rid,r['kind'],r['queries'],at)
    elif new_ack:
        rid=next(iter(new_ack));a=na[rid];at=number(a['ack_at'])
        if at>now:raise Refused('future ACK')
        wanted=engine.ack(rid,a['result_sha256'],at)
    else:
        at=number(nc['seal']['ended_at'])
        if at>now:raise Refused('future seal')
        wanted=engine.seal(at)
    if wanted!=new:raise Refused('exploration event differs from budget/order validated transition')
    return True
