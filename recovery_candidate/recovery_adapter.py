"""recovery-prototype-1, NOT v8. Offline-only transition proof. No network writer.
A production adapter requires separate migration/activation and integration review.
"""
import copy, hashlib, json
VERSION='recovery-prototype-1'
def canonical(x):return (json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def sha(x):return hashlib.sha256(canonical(x)).hexdigest()
class Refused(Exception):pass
class Stale(Refused):pass
class OfflineStore:
    def __init__(self,state):self.state=copy.deepcopy(state);self.head=sha(self.state)
    def cas(self,expected,next_state):
        if self.head!=expected:raise Stale('stale state, rebuild operation from current head')
        self.state=copy.deepcopy(next_state);self.head=sha(self.state);return self.head
class Adapter:
    def __init__(self,store,plan_key,token,now):
        self.store,self.key,self.token,self.now=store,plan_key,token,now
    def checked(self,state,pid):
        h=state['koyo_index_handoffs'][self.key]
        if h['plan_sha256']!=self.key or h['plan']['plan_sha256']!=self.key or sha(h['plan']['payload'])!=self.key:raise Refused('plan integrity')
        if h['destination']['worker_id']!='koyo' or h['lease']['owner']!='koyo':raise Refused('not koyo owner')
        if h['lease']['token']!=self.token or h['lease']['until']<=self.now:raise Refused('lease invalid')
        if pid not in h['plan']['payload']['source']['post_ids']:raise Refused('post outside plan')
        if h['status']!='leased':raise Refused('handoff not leased')
        return h
    def transition(self,expected,pid,op):
        if expected!=self.store.head:raise Stale('stale head')
        before=copy.deepcopy(self.store.state); after=copy.deepcopy(before)
        h=self.checked(after,pid);result=op(h)
        # Reconstruct only this namespace; preserve ALL Terra state and other handoffs.
        other=copy.deepcopy(after);other['koyo_index_handoffs'][self.key]=before['koyo_index_handoffs'][self.key]
        if other!=before:raise Refused('outside namespace mutation')
        for p,row in before['koyo_index_handoffs'][self.key]['rows'].items():
            if h['rows'].get(p)!=row:raise Refused('accepted classification mutation')
        head=self.store.cas(expected,after)
        return head,result
    def reserve_body(self,expected,pid):
        def op(h):
            if pid in h['rows']:raise Refused('already classified')
            # Any historical evidence anywhere blocks a new body fetch, even after lease expiry.
            for prior in self.store.state['koyo_index_handoffs'].values():
                if pid in prior.get('context',{}) or pid in prior.get('rows',{}):raise Refused('historical body evidence or ambiguity')
                if any(pid in key and ('fetch' in key or 'context' in key) for key in prior.get('operations',{})):raise Refused('historical operation evidence')
            h['context'][pid]={'fetch_started':self.now,'recovery_revision':VERSION,'attempt_limit':1}
            return {'allowed_once_in_this_process':True,'post_id':pid}
        # Caller may dispatch ONE request only after successful CAS ACK.
        # Lost ACK or restart => never replay request. Reservation remains ambiguous.
        return self.transition(expected,pid,op)
    def cache_body(self,expected,pid,cache):
        from ops_runtime_r5.queue import cache_value
        cache_value(json.dumps(cache),pid)
        def op(h):
            c=h['context'].get(pid)
            if not c or 'fetch_started' not in c:raise Refused('missing durable reservation')
            if 'cache' in c:
                if c['cache']!=cache:raise Refused('cache immutable')
                return 'same cache'
            c['cache']=copy.deepcopy(cache);return 'cached'
        return self.transition(expected,pid,op)
    def append_row(self,expected,pid,row,post,provenance):
        from pipeline_production.contract_v4 import validate
        validate(row,post,provenance)
        def op(h):
            if pid in h['rows']:
                if row!=h['rows'][pid]:raise Refused('accepted row immutable')
                return 'already accepted'
            if row['post_id']!=pid:raise Refused('row pid mismatch')
            if 'cache' not in h['context'].get(pid,{}):raise Refused('body cache missing/ambiguous')
            required={(im['media_index'],im['sha256']) for im in post['images']}
            viewed={(e['media_index'],e['sha256']) for e in h['events'].get(pid,[]) if e.get('outcome')=='viewed'}
            if not required<=viewed:raise Refused('missing actual image events')
            h['rows'][pid]=copy.deepcopy(row);return 'appended'
        return self.transition(expected,pid,op)
