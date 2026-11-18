"""Current prod-0002 connector bridge. No new-batch claims or live CLI pushes."""
import copy,json,sys,time,os,re,uuid
from pathlib import Path
sys.path.insert(0,'/tmp/x-recovery-isolated')
from connector_protocol import *
from network_runtime import IndexWriter,reacquire_koyo_lease,lease_transition
from runtime_components import PinnedInputs,digest
from rehearsal_pipeline import pinned_body_fetcher
from ops_runtime_r5.worker import local_lock
from pipeline_production.common import atomic_write
BASE=Path(__file__).resolve().parent;ROOT='/tmp/x-recovery-isolated'
def load(p):return json.loads(Path(p).read_text())
def put(p,v):Path(p).parent.mkdir(parents=True,exist_ok=True);atomic_write(Path(p),canonical(v))
def require_pid(p,pid):
    if not re.fullmatch(r'\d{2,20}',pid) or pid not in p['scope'].get('post_ids',[]) or pid in p['scope'].get('held_post_ids',[]):raise Refused('post outside current allowed scope')
    return pid
def postdir(pid):return BASE/'post-runtime'/pid
def checked_folder(folder):
    path=Path(folder).resolve();root=(BASE/'connector-outbox').resolve()
    if not path.is_relative_to(root) or path==root:raise Refused('outbox path outside runtime')
    return path
def check_envelope_target(e,pid):
    if e.get('sha256')!=sha(e.get('payload')):raise Refused('outbox payload integrity')
    if e['payload'].get('target_post_id')!=pid:raise Refused('cross-post outbox')
def main():
    command=sys.argv[1];doc=load(BASE/'connector-activation.json');p=doc['payload'];key=p['plan_sha256']
    if p.get('scope',{}).get('kind') not in ('current-batch-prod-0002-v1','new-claimed-batch-v1'):raise Refused('reviewed batch activation required')
    for f in ('connector_protocol.py','connector_bridge.py','connector_transport.js','pack_compressed.py','next_batch.py'):
        if p['code_sha256'].get(str((BASE/f).resolve()))!=digest(BASE/f):raise Refused('connector code not activation-pinned')
    if p['scope']['kind']=='new-claimed-batch-v1':
        if p['code_sha256'].get(str((BASE/'new_batch_scope.py').resolve()))!=digest(BASE/'new_batch_scope.py'):raise Refused('new batch scope not pinned')
        from new_batch_scope import validate_document
        validate_document(doc,ROOT,BASE)
    original=load(BASE/'current-batch-baseline.json')
    if p['scope']['kind']=='new-claimed-batch-v1' and (sha(original)!=p.get('source_state_sha256') or original['koyo_index_handoffs'].get(key)!=p.get('baseline_handoff')):raise Refused('new batch activation baseline mismatch')
    w=IndexWriter(REMOTE,original['catalog_sha256'],key,ROOT,enable_live_writes=True,activation_document=doc)
    try:
      with local_lock(Path(ROOT)/'.runtime','koyo'):
        if command=='prepare':
            op=sys.argv[2];pid=None if op in ('reacquire','renew') else require_pid(p,sys.argv[3]);head,before=w.read();h=before['koyo_index_handoffs'][key];after=copy.deepcopy(before);a=after['koyo_index_handoffs'][key];token=h['lease']['token'];fence=None
            if op=='reacquire':
                # No automatic claims from expired age. Operator supplies current verified fencing.
                fence=load(BASE/'current-fencing-receipt.json')
                if fence.get('expected_head')!=head or fence.get('expected_lease_token')!=token:raise Refused('fencing receipt not for latest head/token')
                after=reacquire_koyo_lease(before,key,token,w.clock(),fence)
            elif op=='renew':after=lease_transition(before,key,token,w.clock())
            elif op=='body-reserve':
                if (postdir(pid)/'body-stage.json').exists():raise Refused('local body journal exists; reconcile only')
                a['context'][pid]={'fetch_started':w.clock(),'recovery_revision':'recovery-prototype-1','attempt_limit':1}
            elif op in ('body-cache','finalize-post'):
                stage=load(postdir(pid)/'body-stage.json')
                if stage['post_id']!=pid or stage['status']!='result-staged' or stage['cache'].get('post_id')!=pid:raise Refused('missing same-post staged body result')
                a['context'][pid]['cache']=stage['cache']
            if op in ('image-event','finalize-post'):
                receipts=load(postdir(pid)/'view-receipts.json');pins=PinnedInputs(ROOT,h);post=pins.posts[pid]
                if not isinstance(receipts,list) or len(receipts)!=len(post['images']):raise Refused('one actual receipt for every pinned image required')
                byindex={r.get('media_index'):r for r in receipts}
                if len(byindex)!=len(receipts):raise Refused('duplicate image receipt')
                for im in post['images']:
                    receipt=byindex.get(im['media_index'],{})
                    if receipt.get('post_id')!=pid or receipt.get('sha256')!=im['sha256']:raise Refused('cross-post/image receipt')
                    path=(Path(p['image_gate']['bundle_root']) if p['scope']['kind']=='new-claimed-batch-v1' else BASE/'real-image-bundle')/im['path'];event=pins.image_event(pid,im['media_index'],path,receipt)
                    if any(e.get('media_index')==im['media_index'] and e.get('outcome')=='viewed' for e in a['events'].get(pid,[])):raise Refused('image evidence already recorded; do not duplicate')
                    a['events'].setdefault(pid,[]).append(event)
            if op in ('save-row','finalize-post'):
                row=load(postdir(pid)/'row-final.json')
                if row.get('post_id')!=pid:raise Refused('cross-post row')
                a['rows'][pid]=row
            if op=='exclude-post':
                if p['scope']['kind']!='new-claimed-batch-v1':raise Refused('exclusion only new scope')
                row=load(postdir(pid)/'exclusion.json')
                if row.get('post_id')!=pid:raise Refused('cross-post exclusion')
                a['rows'][pid]=row
            if op not in ('reacquire','renew','body-reserve','body-cache','image-event','save-row','finalize-post','exclude-post'):raise Refused('operation not allowed')
            e=envelope(w,head,before,after,op,token,fence)
            if pid:check_envelope_target(e,pid)
            folder=BASE/'connector-outbox'/(pid or 'lease')/(op+'-'+uuid.uuid4().hex);folder.mkdir(parents=True)
            put(folder/'before.json',before);put(folder/'envelope.json',e);manifest=pack_envelope(e,folder/'pack')
            if pid:put(postdir(pid)/'outboxes'/f'{op}.json',{'folder':str(folder),'envelope_sha256':e['sha256']})
            print(json.dumps({'folder':str(folder),'manifest':manifest,'envelope_sha256':e['sha256']}))
        elif command in ('validate','pre-ref','readback'):
            folder=checked_folder(sys.argv[2]);e=load(folder/'envelope.json');before=load(folder/'before.json');pid=e['payload'].get('target_post_id')
            if pid:require_pid(p,pid)
            if command=='validate':
                validate_envelope(w,e,before);print(json.dumps({'valid':True,'sha256':e['sha256'],'pack':load(folder/'pack/manifest.json')}))
            elif command=='pre-ref':print(json.dumps(pre_update_ref(w,e,before,load(folder/'commit.json'))))
            else:
                candidate=sys.argv[3];ack=sys.argv[4]=='acknowledged';observed=readback(w,e,candidate);receipt=execution_receipt(e,candidate,ack,observed);put(folder/'receipt.json',receipt)
                if receipt['accepted'] and pid and receipt['operation'] in ('body-cache','finalize-post'):
                    stage=load(postdir(pid)/'body-stage.json')
                    if stage.get('post_id')!=pid or stage.get('cache')!=observed['state']['koyo_index_handoffs'][key]['context'][pid]['cache']:raise Refused('staged cache mismatch')
                    stage.update(status='accepted',cache_checkpoint_head=candidate);put(postdir(pid)/'body-stage.json',stage)
                print(json.dumps(receipt))
        elif command=='fetch-body':
            pid=require_pid(p,sys.argv[2]);pointer=load(postdir(pid)/'outboxes/body-reserve.json');folder=checked_folder(pointer['folder']);e=load(folder/'envelope.json');r=load(folder/'receipt.json');journal=postdir(pid)/'body-stage.json'
            check_envelope_target(e,pid)
            if e['payload'].get('operation')!='body-reserve':raise Refused('not a body reservation envelope')
            if pointer['envelope_sha256']!=e['sha256'] or r.get('target_post_id')!=pid or r['envelope_sha256']!=e['sha256'] or r['operation']!='body-reserve' or r['external_request_permitted'] is not True or r['ref_update_acknowledged'] is not True:raise Refused('no same-post acknowledged body permit')
            if journal.exists():raise Refused('dispatch journal exists: no second request')
            head,state=w.read();h=state['koyo_index_handoffs'][key]
            if p['scope']['kind']=='new-claimed-batch-v1':
                from policy_tombstones import require_not_refused
                require_not_refused(state,pid,ROOT,p['image_gate']['local_refusal_dir'])
            from next_batch import require_scheduler_permission
            require_scheduler_permission(state,key)
            if head!=r['candidate'] or sha(state)!=e['payload']['state_sha256']:raise Refused('reservation state changed')
            if h['lease']['until']<=w.clock()+30:raise Refused('lease margin insufficient')
            if pid in h['rows'] or 'fetch_started' not in h['context'].get(pid,{}) or 'cache' in h['context'][pid]:raise Refused('body reservation not unused')
            put(journal,{'post_id':pid,'status':'dispatch-intent','reservation_head':head})
            cache=pinned_body_fetcher(ROOT,postdir(pid)/'projected-cache')(pid)
            put(journal,{'post_id':pid,'status':'result-staged','cache':cache});print(json.dumps(cache,ensure_ascii=False))
        elif command=='hold':
            pid=require_pid(p,sys.argv[2]);reason=sys.argv[3]
            if reason not in ('external_exploration_required','uncertain_fetch_history','needs_research_review'):raise Refused('invalid operational hold reason')
            put(postdir(pid)/'operational-hold.json',{'post_id':pid,'reason':reason,'research_disposition':None});print('operational hold recorded; no research result written')
        elif command=='record-exclusion':
            if p['scope']['kind']!='new-claimed-batch-v1':raise Refused('exclusion only new scope')
            from pipeline_production import disposition
            from runtime_components import provenance
            pid=require_pid(p,sys.argv[2]);head,state=w.read();h=state['koyo_index_handoffs'][key]
            from next_batch import require_scheduler_permission
            require_scheduler_permission(state,key)
            if pid in h['rows']:raise Refused('accepted post cannot be excluded')
            pins=PinnedInputs(ROOT,h);row=disposition.create(pins.posts[pid],provenance(h),'koyo',sys.argv[3],int(sys.argv[4]) if len(sys.argv)>4 else None)
            out=postdir(pid)/'exclusion.json'
            if out.exists():
                old=load(out);disposition.validate(old,pins.posts[pid],provenance(h))
                if old['signal']!=row['signal'] or old['blocked_media_index']!=row['blocked_media_index']:raise Refused('existing exclusion differs')
                row=old
            put(Path(p['image_gate']['local_refusal_dir'])/(pid+'.json'),row);put(out,row)
            print(json.dumps({'post_id':pid,'metadata_saved_locally':True,'needs_remote_checkpoint':True}))
        elif command=='next-images':
            if p['scope']['kind']!='new-claimed-batch-v1':raise Refused('next-images requires exact new batch')
            from new_batch_images import next_from_writer
            print(json.dumps(next_from_writer(w,doc,ROOT),ensure_ascii=False))
        elif command=='status':
            head,state=w.read();h=state['koyo_index_handoffs'][key]
            from next_batch import require_scheduler_permission
            require_scheduler_permission(state,key)
            result=[]
            for pid in p['scope']['post_ids']:
                status='accepted' if pid in h['rows'] else 'operational_hold' if (postdir(pid)/'operational-hold.json').exists() else 'reconcile_body' if pid in h['context'] and 'cache' not in h['context'][pid] else 'pending'
                result.append({'post_id':pid,'status':status})
            print(json.dumps({'head':head,'accepted_posts':len(h['rows']),'held_post_ids':p['scope']['held_post_ids'],'posts':result}))
        else:raise Refused('unknown command')
    finally:w.close()
if __name__=='__main__':main()
