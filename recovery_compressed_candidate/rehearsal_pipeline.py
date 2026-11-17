"""Connected recovery candidate, rehearsal only. No live startup entry point."""
import copy,json,os,sys,time
from pathlib import Path
from recovery_adapter import Refused,canonical,sha
from runtime_components import PinnedInputs,activation,verify_activation
from pipeline_production.common import atomic_write
from pipeline_production.context import fetch

class RecoverySession:
    def __init__(self,writer,key,token,root,journal,activation_doc):
        self.w=writer;self.key=key;self.token=token;self.root=root;self.journal=Path(journal);self.journal.mkdir(parents=True,exist_ok=True)
        head,state=writer.read()
        if writer.live:
            payload=activation_doc.get('payload',{})
            if activation_doc.get('sha256')!=sha(payload) or payload.get('mode')!='reviewed-live' or payload.get('plan_sha256')!=key or payload.get('scope',{}).get('job_id')!='prod-0002':raise Refused('limited reviewed activation required')
            if writer.activation_document!=activation_doc or not writer.enabled:raise Refused('writer activation mismatch')
            # The writer revalidates pinned code, scope, old-token and immutable baselines on every publish.
        else:verify_activation(activation_doc,state,head,key)
        self.activation=activation_doc
        from ops_runtime_r5.worker import local_lock
        self._lock=local_lock(Path(root)/'.runtime','koyo');self._lock.__enter__()
    def close(self):
        if getattr(self,'_lock',None):
            self._lock.__exit__(None,None,None);self._lock=None
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def publish(self,head,before,after,operation):
        return self.w.publish(head,before,after,operation=operation,lease_token=self.token)
    def body_once(self,pid,fetcher):
        head,state=self.w.read();h=state['koyo_index_handoffs'][self.key]
        prior=h['context'].get(pid)
        if prior:
            if 'cache' in prior:return prior['cache']
            raise Refused('body reservation exists without cache: reconcile, never refetch')
        path=self.journal/(pid+'.body.json')
        if path.exists():raise Refused('local dispatch journal exists: never repeat')
        after=copy.deepcopy(state);after['koyo_index_handoffs'][self.key]['context'][pid]={'fetch_started':self.w.clock(),'recovery_revision':'recovery-prototype-1','attempt_limit':1}
        accepted=self.publish(head,state,after,'body-reserve')
        if not accepted['external_request_permitted']:raise Refused('reservation ACK uncertain, no fetch')
        atomic_write(path,canonical({'status':'dispatch-intent','post_id':pid,'reservation_head':accepted['head']}))
        # The supplied fetcher is pinned real HTTP adapter OR explicitly identified recorded fixture.
        # Exceptions do not cause another attempt. A permanent record permits later diagnosis.
        try:cache=fetcher(pid)
        except Exception as exc:
            atomic_write(path,canonical({'status':'dispatch-unknown','post_id':pid,'exception_type':type(exc).__name__}))
            raise Refused('body result uncertain, no repeat') from exc
        atomic_write(path,canonical({'status':'result-staged','post_id':pid,'cache':cache}))
        head,current=self.w.read();after=copy.deepcopy(current);after['koyo_index_handoffs'][self.key]['context'][pid]['cache']=cache
        self.publish(head,current,after,'body-cache')
        atomic_write(path,canonical({'status':'accepted','post_id':pid,'cache_sha256':sha(cache)}))
        return cache
    def record_view(self,pid,media_index,path,actual_tool_receipt):
        head,state=self.w.read();h=state['koyo_index_handoffs'][self.key];pins=PinnedInputs(self.root,h)
        event=pins.image_event(pid,media_index,path,actual_tool_receipt)
        after=copy.deepcopy(state);after['koyo_index_handoffs'][self.key]['events'].setdefault(pid,[]).append(event)
        return self.publish(head,state,after,'image-event')
    def save(self,row):
        head,state=self.w.read();h=state['koyo_index_handoffs'][self.key];pid=row['post_id'];pins=PinnedInputs(self.root,h)
        pins.validate_row(row,h['events'].get(pid,[]))
        if pid in h['rows']:
            if h['rows'][pid]!=row:raise Refused('accepted row immutable')
            return {'already_accepted':True,'head':head}
        after=copy.deepcopy(state);after['koyo_index_handoffs'][self.key]['rows'][pid]=copy.deepcopy(row)
        return self.publish(head,state,after,'save-row')

def pinned_body_fetcher(root,journal):
    # This adapter is implemented but NEVER called in rehearsal. Its caller must
    # successfully reserve, journal dispatch and hold the single-worker lock first.
    from runtime_components import digest
    config=json.loads((Path(root)/'runs/production-v4-001.json').read_text())
    if digest(Path(root)/'pipeline_production/context.py')!=config['toolchain_sha256']['pipeline_production/context.py']:raise Refused('body code mismatch')
    def once(pid):return fetch(pid,Path(journal)/(pid+'.projected-cache.json'))
    return once
