"""Original connector protocol restored, with reviewed typed state transition guards.
CLI is READ/object construction ONLY; no git push and no credential changes.
"""
import copy,json,hashlib,time
from pathlib import Path
from recovery_adapter import canonical,sha,Refused,Stale
from network_runtime import REMOTE,JOB
BRANCH='codex/jobs/production-v4-001/dispatch-index';REPO='ugin-man/x-illustration-labeling'
def envelope(writer,expected,before,after,operation,token,fencing_receipt=None):
    writer.authorize_transition(before,after,operation,token,fencing_receipt);writer.preservation(before,after)
    head,current=writer.read()
    if head!=expected or current!=before:raise Stale('source moved before envelope creation')
    q=writer.q;candidate=q._commit(after,expected)
    base_tree=q.git('show','-s','--format=%T',expected).stdout.decode().strip()
    tree=q.git('show','-s','--format=%T',candidate).stdout.decode().strip()
    raw=canonical(after).decode();payload={'protocol':'recovery-connector-1','repo':REPO,'branch':BRANCH,'expected_head':expected,'base_tree_sha':base_tree,'candidate_tree_sha':tree,'state_json_content':raw,'state_sha256':hashlib.sha256(raw.encode()).hexdigest(),'state_bytes':len(raw.encode()),'operation':operation,'lease_token':token,'fencing_receipt':fencing_receipt,'commit_message':'Koyo limited recovery '+operation,'plan_key':writer.key,'after_lease_until':after['koyo_index_handoffs'][writer.key]['lease']['until']}
    return {'payload':payload,'sha256':sha(payload)}
def validate_envelope(writer,e,before):
    p=e['payload']
    if e['sha256']!=sha(p) or p['repo']!=REPO or p['branch']!=BRANCH or p['plan_key']!=writer.key:raise Refused('envelope integrity/scope')
    raw=p['state_json_content'].encode()
    if len(raw)!=p['state_bytes'] or hashlib.sha256(raw).hexdigest()!=p['state_sha256']:raise Refused('payload bytes/hash')
    after=json.loads(raw)
    if canonical(after)!=raw:raise Refused('noncanonical payload')
    fresh=envelope(writer,p['expected_head'],before,after,p['operation'],p['lease_token'],p['fencing_receipt'])
    if fresh!=e:raise Refused('revalidated envelope changed')
    if p['after_lease_until']<=writer.clock()+30:raise Refused('insufficient lease margin')
    return after
def validate_commit(e,commit):
    p=e['payload']
    if commit.get('tree',{}).get('sha')!=p['candidate_tree_sha'] or len(commit.get('parents',[]))!=1 or commit['parents'][0].get('sha')!=p['expected_head']:raise Refused('connector commit tree/parent differs')
    return True
def readback(writer,e,candidate):
    head,state=writer.read();p=e['payload']
    if head==candidate:
        if hashlib.sha256(canonical(state)).hexdigest()!=p['state_sha256']:raise Refused('remote accepted wrong content')
        return {'accepted':True,'head':head,'state_sha256':p['state_sha256'],'state':state}
    if head==p['expected_head']:return {'accepted':False,'head':head,'reason':'not_accepted'}
    raise Stale('head changed; do not overwrite or refetch body')

def pack_envelope(e,path,chunk_chars=24000):
    # ASCII JSON transport allows deterministic lossless reconstruction in V8 without decoder dependencies.
    raw=json.dumps(e,ensure_ascii=True,sort_keys=True,separators=(',',':')).encode('ascii')
    folder=Path(path);folder.mkdir(parents=True,exist_ok=True)
    pieces=[raw[i:i+chunk_chars] for i in range(0,len(raw),chunk_chars)]
    for i,piece in enumerate(pieces):(folder/('%04d.txt'%i)).write_bytes(piece)
    manifest={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'chunks':len(pieces),'chunk_chars':chunk_chars}
    (folder/'manifest.json').write_text(json.dumps(manifest));return manifest

def execution_receipt(e,candidate,ref_update_acknowledged,observed):
    """Remote acceptance and permission for a new external request are separate.
    A lost/failed/denied/cancelled ref-update ACK never grants request permission.
    """
    if type(ref_update_acknowledged) is not bool:raise Refused('explicit ACK status required')
    accepted=observed.get('accepted') is True and observed.get('head')==candidate and observed.get('state_sha256')==e['payload']['state_sha256']
    return {'envelope_sha256':e['sha256'],'candidate':candidate,'accepted':accepted,'ref_update_acknowledged':ref_update_acknowledged,'external_request_permitted':accepted and ref_update_acknowledged,'operation':e['payload']['operation']}

def pre_update_ref(writer,e,before,commit):
    validate_commit(e,commit)
    validate_envelope(writer,e,before)
    return {'repository_full_name':e['payload']['repo'],'branch_name':e['payload']['branch'],'expected_sha':e['payload']['expected_head'],'sha':commit['sha'],'force':False}
