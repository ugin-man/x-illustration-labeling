"""GitHub Git-Data-shaped adapters, explicitly ISOLATED ONLY until separately reviewed.
No credentials or tool binding. All network implementations are rejected. These
interfaces map to get ref, get blob/tree/commit, create tree/commit and CAS update_ref.
"""
import copy,json,hashlib,time
from pathlib import Path
from checkpoint import prepare,digest,Refused,Conflict,save_journal,reconcile
from stage_recovery import name_for
REPO='ugin-man/x-illustration-labeling'
DISPATCH='codex/jobs/production-v4-001/dispatch-index'
ARCHIVE='codex/koyo-result-stage-archive-v1'
def canonical(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def git_object_sha(kind,raw):
 return hashlib.sha1((kind+' '+str(len(raw))).encode()+b'\0'+raw).hexdigest()
def complete_tree_sha(entries):
 """Reconstruct Git Merkle root from complete recursive leaf entries.
 Detect omitted/truncated/incorrect tree listings, including non-target mode/type.
 """
 root={}
 for path,entry in entries.items():
  if not isinstance(path,str) or path.startswith('/') or any(p in ('','.','..') for p in path.split('/')):raise Refused('invalid tree path')
  parts=path.split('/');node=root
  for component in parts[:-1]:
   if component in node and not isinstance(node[component],dict):raise Refused('file/directory collision')
   node=node.setdefault(component,{})
  if parts[-1] in node:raise Refused('duplicate tree path')
  mode=entry['mode'];typ=entry['type'];sha=entry['sha']
  if (mode,typ) not in (('100644','blob'),('100755','blob'),('120000','blob'),('160000','commit')):raise Refused('unsupported tree entry')
  try:rawsha=bytes.fromhex(sha)
  except (ValueError,TypeError):raise Refused('invalid object sha')
  if len(rawsha)!=20:raise Refused('invalid object sha length')
  node[parts[-1]]=(mode,rawsha)
 def tree(node):
  result=[]
  for name,value in node.items():
   isdir=isinstance(value,dict);mode,sha=('40000',tree(value)) if isdir else value
   result.append((name.encode()+(b'/' if isdir else b''),mode.encode()+b' '+name.encode()+b'\0'+sha))
  raw=b''.join(value for _,value in sorted(result));return bytes.fromhex(git_object_sha('tree',raw))
 return tree(root).hex()

class PermissionDenied(Refused):pass
class ReviewGate:
 def __init__(self,repo,branch,role,pins,review_reference):
  self.repo=repo;self.branch=branch;self.role=role;self.pins=copy.deepcopy(pins);self.reference=review_reference
 def check(self,io):
  if getattr(io,'offline_fixture_only',False) is not True:raise Refused('live adapter not activated')
  if self.repo!=REPO or self.branch!={'archive':ARCHIVE,'aggregate':DISPATCH}.get(self.role):raise Refused('destination scope')
  mandatory={str(Path(__file__).resolve()),str(Path(__file__).with_name('checkpoint.py').resolve()),str(Path(__file__).with_name('stage_recovery.py').resolve())}
  if not self.reference or not mandatory<=set(self.pins) or any(hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h for p,h in self.pins.items()):raise Refused('review/code pins required')
class Metrics:
 def __init__(self):self.events=[]
 def call(self,name,fn,*args,**kwargs):
  started=time.monotonic();outcome='ok';response=None
  try:
   response=fn(*args,**kwargs);return response
  except Exception as e:outcome=type(e).__name__;raise
  finally:self.events.append({'operation':name,'elapsed_seconds':time.monotonic()-started,'request_bytes':len(canonical([args,kwargs]).encode()),'outcome':outcome,'response_bytes':len(canonical(response).encode())})
 def summary(self):
  return {'calls':len(self.events),'request_bytes':sum(e['request_bytes'] for e in self.events),'response_bytes':sum(e['response_bytes'] for e in self.events),'elapsed_seconds':sum(e['elapsed_seconds'] for e in self.events),'by_operation':{n:sum(e['operation']==n for e in self.events) for n in sorted({e['operation'] for e in self.events})},'measurement':'isolated local GitData fixture, not GitHub latency'}
class Base:
 def __init__(self,io,gate,metrics=None):self.io=io;self.gate=gate;self.metrics=metrics or Metrics();gate.check(io)
 def call(self,name,*args):self.gate.check(self.io);return self.metrics.call(name,getattr(self.io,name),self.gate.repo,*args)
 def entries(self,tree):
  entries=self.call('list_tree',tree)
  if complete_tree_sha(entries)!=tree:raise Refused('incomplete or inconsistent tree listing')
  return entries
 def contents(self,entry):
  if entry['mode']!='100644' or entry['type']!='blob':raise Refused('not ordinary data file')
  raw=self.call('get_blob',entry['sha'])
  if git_object_sha('blob',raw.encode())!=entry['sha']:raise Refused('blob content hash mismatch')
  return raw
 def snapshot(self):
  head=self.call('get_ref',self.gate.branch);commit=self.call('get_commit',head);return head,commit
 def commit(self,head,base_tree,elements,message):
  base_entries=self.call('list_tree',base_tree)
  tree=self.call('create_tree',base_tree,elements)
  candidate_entries=self.call('list_tree',tree)
  if complete_tree_sha(base_entries)!=base_tree or complete_tree_sha(candidate_entries)!=tree:raise Refused('incomplete or inconsistent tree listing')
  expected_paths=set(base_entries)|set(elements)
  if set(candidate_entries)!=expected_paths:raise Refused('candidate tree added/deleted unrelated paths')
  for path,entry in candidate_entries.items():
   if path not in elements:
    if entry!=base_entries[path]:raise Refused('candidate tree changed unrelated mode/type/content')
   else:
    # Our written targets are normal UTF-8 files; reject an unexpected old type/mode.
    if path in base_entries and (base_entries[path]['mode']!='100644' or base_entries[path]['type']!='blob'):raise Refused('target previously not ordinary file')
    if entry['mode']!='100644' or entry['type']!='blob':raise Refused('candidate target mode/type')
    if entry['sha']!=git_object_sha('blob',elements[path].encode()) or self.call('get_blob',entry['sha'])!=elements[path]:raise Refused('candidate target content')
  candidate=self.call('create_commit',tree,head,message)
  commit=self.call('get_commit',candidate)
  if commit['tree']!=tree or commit['parents']!=[head]:raise Refused('commit tree/parent mismatch')
  return candidate
class GitHubArchive(Base):
 def __init__(self,io,gate,metrics=None):
  if gate.role!="archive":raise Refused("archive role mismatch")
  super().__init__(io,gate,metrics)
 def put(self,item):
  if item['sha256']!=digest(item['payload']):raise Refused('stage integrity')
  path='stages/'+name_for(item);content=canonical(item)
  head,commit=self.snapshot();entries=self.entries(commit['tree'])
  if path in entries:
   if self.contents(entries[path])!=content:raise Refused('immutable archive collision')
   return {'status':'accepted','head':head,'path':path,'stage_sha256':item['sha256'],'external_request_permitted':False}
  candidate=self.commit(head,commit['tree'],{path:content},'Preserve immutable completed post stage')
  # No automatic retry. A concurrent append will fail CAS and is reconciled below.
  try:self.call('update_ref',self.gate.branch,head,candidate)
  except TimeoutError:pass
  except Conflict:pass
  # A safety/permission refusal propagates, never becomes retryable transport failure.
  observed,observed_commit=self.snapshot();files=self.entries(observed_commit['tree'])
  accepted=path in files and self.contents(files[path])==content
  return {'status':'accepted' if accepted else 'not_accepted','head':observed,'path':path,'stage_sha256':item['sha256'],'external_request_permitted':False}
 def restore(self,key):
  head,commit=self.snapshot();items=[];conflicts={};groups={}
  for path,blob in self.entries(commit['tree']).items():
   if not path.startswith('stages/'+key+'--'):continue
   
   if blob['mode']!='100644' or blob['type']!='blob':raise Refused('archive entry mode/type')
   item=json.loads(self.contents(blob));p=item['payload']
   if p['key']!=key or item['sha256']!=digest(p) or path!='stages/'+name_for(item):raise Refused('archive identity/hash mismatch')
   groups.setdefault(p['pid'],[]).append(item)
  for pid,versions in groups.items():
   if len({digest({k:v for k,v in x['payload'].items() if k!='staged_at'}) for x in versions})>1:conflicts[pid]=versions
   else:items.append(min(versions,key=lambda x:x['payload']['staged_at']))
  return {'head':head,'stages':items,'conflicts':conflicts,'external_request_permitted':False}
 def verify_many(self,items):
  keys={item['payload']['key'] for item in items}
  if len(keys)!=1:raise Refused('one archive scope required')
  result=self.restore(next(iter(keys)))
  identity=lambda x:{k:v for k,v in x['payload'].items() if k!='staged_at'}
  for item in items:
   if item['sha256']!=digest(item['payload']):raise Refused('stage integrity')
   if item['payload']['pid'] in result['conflicts']:raise Refused('conflicting stage versions')
   if not any(identity(x)==identity(item) for x in result['stages']):raise Refused('stage archive not durable')
  return True
 def verify(self,item):return self.verify_many([item])
class GitHubAggregate(Base):
 def __init__(self,io,gate,metrics=None):
  if gate.role!="aggregate":raise Refused("aggregate role mismatch")
  super().__init__(io,gate,metrics)
 def read_state(self):
  head,commit=self.snapshot();files=self.entries(commit['tree'])
  return head,json.loads(self.contents(files['state.json'])),commit
 def publish(self,items,validate_one,archive,journal,clock,margin=120):
  # Independent durable recovery exists before any aggregate send. No external request.
  archive.verify_many(items)
  head,before,commit=self.read_state();p=prepare(head,before,items,validate_one,clock())
  payload=p['payload'];key=payload['key'];lease=before['koyo_index_handoffs'][key]['lease']
  if lease['until']<=clock()+margin:raise Refused('renew early before aggregate')
  save_journal(journal,{'status':'prepared','envelope':p})
  if not payload['items']:return {'status':'accepted','head':head,'external_request_permitted':False}
  candidate=self.commit(head,commit['tree'],{'state.json':canonical(payload['after'])},'Checkpoint completed posts atomically')
  save_journal(journal,{'status':'candidate','envelope':p,'candidate':candidate})
  current_head,current,_=self.read_state()
  fresh=prepare(current_head,current,items,validate_one,clock())
  if current_head!=head or fresh['payload']['after_sha256']!=payload['after_sha256']:raise Conflict('fresh pre-ref state changed')
  if current['koyo_index_handoffs'][key]['lease']['until']<=clock()+margin:raise Refused('pre-ref lease margin')
  try:self.call('update_ref',self.gate.branch,head,candidate)
  except PermissionDenied:
   save_journal(journal,{'status':'permission_denied','envelope':p,'candidate':candidate});raise
  except TimeoutError:pass
  except Conflict:pass
  observed,state,_=self.read_state();r=reconcile(p,observed,state)
  if r['status']=='accepted' and observed!=candidate:r['status']='reconcile_required'
  r['lease_expired_after_send']=clock()>=lease['until']
  if r['lease_expired_after_send']:r['continue_without_renewal']=False
  save_journal(journal,{'status':r['status'],'envelope':p,'candidate':candidate,'receipt':r})
  return r
