"""One-post connector outbox bridge. Git CLI never writes remote refs here."""
import copy,json,sys,time,os
from pathlib import Path
sys.path.insert(0,'/tmp/x-recovery-isolated')
from connector_protocol import *
from network_runtime import IndexWriter,reacquire_koyo_lease
from runtime_components import PinnedInputs,digest
from rehearsal_pipeline import pinned_body_fetcher
from ops_runtime_r5.worker import local_lock
from pipeline_production.common import atomic_write
BASE=Path(__file__).parent;ROOT='/tmp/x-recovery-isolated';PID='2096139409821405202'
def load(p):return json.loads(Path(p).read_text())
def put(p,v):atomic_write(Path(p),canonical(v))
def main():
    command=sys.argv[1];doc=load(BASE/'connector-activation.json');p=doc['payload'];key=p['plan_sha256']
    # Protect the connector dispatcher/bridge too, not just the state-transition modules.
    for f in ('connector_protocol.py','connector_bridge.py','connector_transport.js'):
        if p['code_sha256'].get(str((BASE/f).resolve()))!=digest(BASE/f):raise Refused('connector code not activation-pinned')
    original=load(BASE/'live-preflight-state.json')
    w=IndexWriter(REMOTE,original['catalog_sha256'],key,ROOT,enable_live_writes=True,activation_document=doc)
    try:
      with local_lock(Path(ROOT)/'.runtime','koyo'):
        if command=='prepare':
            op=sys.argv[2];head,before=w.read();h=before['koyo_index_handoffs'][key];after=copy.deepcopy(before);a=after['koyo_index_handoffs'][key];token=h['lease']['token'];fence=None
            if op=='reacquire':
                if head!=p['source_head'] or before!=original:raise Refused('initial baseline changed')
                fence={'all_previous_koyo_writers_stopped':True,'verification_reference':'root+old resume_labeling confirmations; old worker stopped before post18; local scan clean; one-post18 connector resume'}
                after=reacquire_koyo_lease(before,key,token,w.clock(),fence)
            elif op=='body-reserve':a['context'][PID]={'fetch_started':w.clock(),'recovery_revision':'recovery-prototype-1','attempt_limit':1}
            elif op=='body-cache':
                stage=load(BASE/'connector-body-stage.json')
                if stage['post_id']!=PID or stage['status']!='result-staged':raise Refused('missing staged body result')
                a['context'][PID]['cache']=stage['cache']
            elif op=='image-event':
                receipt=load(BASE/'live-view-receipt-18.json');pins=PinnedInputs(ROOT,h);path=BASE/'real-image-bundle/images/5adad0504d01d3de8987722e2a5d67615f45059231d7d54f7ea20fda94f9eb92.jpg'
                a['events'].setdefault(PID,[]).append(pins.image_event(PID,1,path,receipt))
            elif op=='save-row':a['rows'][PID]=load(BASE/'live-row-final.json')
            else:raise Refused('operation not allowed')
            e=envelope(w,head,before,after,op,token,fence);folder=BASE/'connector-outbox'/op;folder.mkdir(parents=True,exist_ok=True)
            put(folder/'before.json',before);put(folder/'envelope.json',e);manifest=pack_envelope(e,folder/'pack');print(json.dumps({'folder':str(folder),'manifest':manifest,'envelope_sha256':e['sha256']}))
        elif command in ('validate','pre-ref','readback'):
            folder=Path(sys.argv[2]);e=load(folder/'envelope.json');before=load(folder/'before.json')
            if command=='validate':
                validate_envelope(w,e,before);print(json.dumps({'valid':True,'sha256':e['sha256'],'pack':load(folder/'pack/manifest.json')}))
            elif command=='pre-ref':
                commit=load(folder/'commit.json');params=pre_update_ref(w,e,before,commit);print(json.dumps(params))
            else:
                candidate=sys.argv[3];ack=sys.argv[4]=='acknowledged';observed=readback(w,e,candidate);receipt=execution_receipt(e,candidate,ack,observed);put(folder/'receipt.json',receipt)
                print(json.dumps(receipt))
        elif command=='fetch-body':
            folder=BASE/'connector-outbox/body-reserve';e=load(folder/'envelope.json');r=load(folder/'receipt.json');journal=BASE/'connector-body-stage.json'
            if r['envelope_sha256']!=e['sha256'] or r['operation']!='body-reserve' or r['external_request_permitted'] is not True or r['ref_update_acknowledged'] is not True:raise Refused('no acknowledged body request permit')
            if journal.exists():raise Refused('dispatch journal exists: no second request')
            head,state=w.read();h=state['koyo_index_handoffs'][key]
            if head!=r['candidate'] or sha(state)!=e['payload']['state_sha256']:raise Refused('reservation state changed')
            if h['lease']['until']<=w.clock()+30:raise Refused('lease margin insufficient')
            put(journal,{'post_id':PID,'status':'dispatch-intent','reservation_head':head})
            cache=pinned_body_fetcher(ROOT,BASE/'connector-cache')(PID)
            put(journal,{'post_id':PID,'status':'result-staged','cache':cache});print(json.dumps(cache,ensure_ascii=False))
        else:raise Refused('unknown command')
    finally:w.close()
if __name__=='__main__':main()
