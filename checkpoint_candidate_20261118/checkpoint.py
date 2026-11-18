"""Offline checkpoint candidate. No network, credentials or production activation.
Only completed post deltas are combined. Body/search reservations remain synchronous.
Production integration MUST supply the existing per-post scope, policy, provenance and
schema validator for every member; this module never grants external-request permission.
"""
import copy, hashlib, json, os, tempfile, time
from pathlib import Path

def digest(x):
    return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
class Refused(ValueError): pass
class Conflict(Refused): pass
FIELDS=('context','events','rows')
def target(h,pid): return {f:copy.deepcopy(h[f].get(pid)) for f in FIELDS}
def apply(state,key,pid,value):
    s=copy.deepcopy(state)
    for f in FIELDS:
        if value[f] is None: s['koyo_index_handoffs'][key][f].pop(pid,None)
        else: s['koyo_index_handoffs'][key][f][pid]=copy.deepcopy(value[f])
    return s

def stage(before,after,key,pid,operation,now):
    """Capture a completed row with exact dependencies, never reservation or lease changes."""
    if operation not in ('finalize-post','save-row'): raise Refused('completed results only')
    b=before['koyo_index_handoffs'][key];a=after['koyo_index_handoffs'][key]
    if pid in b['rows'] or pid not in a['rows']: raise Refused('new completed row required')
    if apply(before,key,pid,target(a,pid))!=after: raise Refused('outside target change')
    if 'fetch_started' not in b['context'].get(pid,{}): raise Refused('reservation must preexist')
    if a['context'][pid].get('fetch_started')!=b['context'][pid]['fetch_started']: raise Refused('reservation altered')
    payload=dict(key=key,pid=pid,operation=operation,lease_token=b['lease']['token'],identity=digest({f:b[f] for f in ('plan','destination','job_id')}),before=target(b,pid),after=target(a,pid),staged_at=now)
    return dict(payload=payload,sha256=digest(payload))

def prepare(head,state,items,validate_one,now,max_rows=5):
    """Rebase onto fresh state, validate independent original transitions, combine atomically.
    validate_one(before, after, operation, token, pid) must be trusted/pinned by caller.
    No weakening to fixed research validator or existing safety checks is permitted.
    """
    if not items or len(items)>max_rows: raise Refused('checkpoint size')
    seen=set();out=copy.deepcopy(state);accepted=[];pending=[];key=None;token=None
    for item in items:
        p=item['payload']
        if item['sha256']!=digest(p): raise Refused('stage integrity')
        if key is None: key=p['key'];token=p['lease_token']
        if p['key']!=key or p['lease_token']!=token or p['pid'] in seen: raise Refused('mixed binding or duplicate')
        seen.add(p['pid']);h=state['koyo_index_handoffs'][key];pid=p['pid']
        if key in state.get('koyo_retained_work',{}):raise Refused('paused scope')
        if h['status']!='leased' or h['lease']['owner']!='koyo' or h['lease']['token']!=token or h['lease']['until']<=now+30: raise Refused('lease fenced/expired')
        if digest({f:h[f] for f in ('plan','destination','job_id')})!=p['identity']: raise Refused('scope changed')
        if pid not in h['plan']['payload']['source']['post_ids']:raise Refused('outside plan')
        if target(h,pid)==p['after']:
            accepted.append(item['sha256']);continue # only exact remote evidence counts
        if target(h,pid)!=p['before']: raise Conflict('target dependencies changed')
        one=apply(state,key,pid,p['after'])
        validate_one(state,one,p['operation'],token,pid)
        out=apply(out,key,pid,p['after']);pending.append(item['sha256'])
    p=dict(expected_head=head,before_sha256=digest(state),after_sha256=digest(out),key=key,token=token,after=out,items=pending,already_accepted=accepted,prepared_at=now,external_request_permitted=False)
    return dict(payload=p,sha256=digest(p))

def due(items,now):
    return bool(items) and (len(items)>=5 or now-min(x['payload']['staged_at'] for x in items)>=600)

def save_journal(path,doc):
    """Durable local outbox before send; caller must also back up reset-sensitive storage."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.checkpoint-')
    try:
        with os.fdopen(fd,'w') as f:json.dump(doc,f,ensure_ascii=False,sort_keys=True);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
        d=os.open(path.parent,os.O_DIRECTORY)
        try:os.fsync(d)
        finally:os.close(d)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def reconcile(prepared,head,state):
    p=prepared['payload']
    if prepared['sha256']!=digest(p):raise Refused('outbox integrity')
    # Accepted only for exact readback; an advanced head needs per-item rebase/revalidation.
    if digest(state)==p['after_sha256']:return dict(status='accepted',head=head,external_request_permitted=False)
    if head==p['expected_head'] and digest(state)==p['before_sha256']:return dict(status='not_accepted',head=head,external_request_permitted=False)
    return dict(status='reconcile_required',head=head,external_request_permitted=False)

def fake_send(prepared,transport,validate_one,items,now,*,clock=None,send_margin=120):
    """Fake-only driver; validate again immediately before CAS and always read back.
    Exceptions/unknown outcomes are not retried here. Explicit denied outcomes must be
    handled by the operator under policy, never treated as transient transport errors.
    """
    if getattr(transport,'offline_fixture_only',False) is not True:raise Refused('no live adapter')
    p=prepared['payload']
    if prepared['sha256']!=digest(p) or digest(p['after'])!=p['after_sha256']:raise Refused('outbox integrity')
    clock=clock or (lambda:now) # static clocks are fixture-only compatibility
    if hasattr(transport,'prepare_transfer'):transport.prepare_transfer()
    head,state=transport.read()
    now=clock()
    if state['koyo_index_handoffs'][p['key']]['lease']['until']<=now+send_margin:raise Refused('renew before transfer; lease margin')
    fresh=prepare(head,state,items,validate_one,now)
    if fresh['payload']['expected_head']!=p['expected_head'] or fresh['payload']['after_sha256']!=p['after_sha256']:raise Conflict('reprepare on fresh head')
    if p['items']:
        try:transport.cas(p['expected_head'],p['after'])
        except TimeoutError:pass # only ambiguous ACK; readback, not replay
    return reconcile(prepared,*transport.read())
