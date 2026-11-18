"""Read-only next-image gate. Opaque byte checks only; never opens pixels or attests viewing.
Caller must pass a fresh verified remote snapshot and use returned paths in an actual
image tool. This module neither creates view receipts nor modifies labels/remote state.
"""
import copy,json,re,time
from pathlib import Path
from recovery_adapter import Refused,sha
from runtime_components import PinnedInputs,digest
from new_batch_scope import KIND,validate_scope
from pipeline_production import isolation,disposition

def _plain_dir(path):
 p=Path(path).absolute()
 if not p.is_dir() or any(x.is_symlink() for x in (p,*p.parents)):
  raise Refused('image gate directory absent or symlinked')
 return p.resolve()

def make_binding(bundle_root,audit_roots,local_refusal_dir,review_reference):
 """No I/O beyond path checks. Returned binding MUST be pinned into activation."""
 if not isinstance(review_reference,str) or not review_reference.strip():raise Refused('image coverage review required')
 bundle=_plain_dir(bundle_root);refusals=_plain_dir(local_refusal_dir)
 roots=[_plain_dir(r) for r in audit_roots]
 if not roots or len(set(roots))!=len(roots) or not any(bundle.is_relative_to(r) for r in roots) or not any(refusals.is_relative_to(r) for r in roots):raise Refused('bundle/refusal stores outside reviewed audit coverage')
 return {'bundle_root':str(bundle),'audit_roots':[str(r) for r in roots],'local_refusal_dir':str(refusals),'review_reference':review_reference}

def audit_linked_workspaces(roots,policy):
 """Opaque-byte audit of the complete declared root union, including linked caches.
 Root escapes, unreadable/mutating paths and unresolved links fail closed. Directory
 cycles are exhausted by inode identity, not by dropping symlink-containing trees.
 """
 import os,stat,hashlib,zipfile
 roots=tuple(_plain_dir(r) for r in roots)
 denied=Path('/home/agent/.codex/sessions')
 records={};visited_dirs=set();checked=set();images=archives=0
 def permitted(p):
  if p==denied or denied in p.parents:raise Refused('audit target denied')
  if not any(p==r or r in p.parents for r in roots):raise Refused('audit link outside reviewed roots')
 def signature(st):return (st.st_dev,st.st_ino,st.st_mode,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
 def parent_fd(p):
  fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
  try:
   cur=Path('/')
   for part in p.parts[1:-1]:
    nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
    os.close(fd);fd=nxt;cur=cur/part
    if cur in records and signature(os.fstat(fd))!=records[cur]:raise Refused('audit parent identity changed')
   return fd
  except BaseException:
   os.close(fd);raise
 def safe_stat(p):
  fd=parent_fd(p)
  try:return os.stat(p.name,dir_fd=fd,follow_symlinks=False)
  finally:os.close(fd)
 def safe_readlink(p):
  fd=parent_fd(p)
  try:return os.readlink(p.name,dir_fd=fd)
  finally:os.close(fd)
 def record(p):
  permitted(p)
  st=safe_stat(p);sig=signature(st)
  if p in records and records[p]!=sig:raise Refused('audit path changed')
  records[p]=sig
  return st
 def resolve(p):
  # Resolve one component at a time: never stat/read a link target outside coverage.
  p=Path(p);permitted(p);hops=0;aliases={p.suffix.lower()}
  while True:
   root=max((r for r in roots if p==r or r in p.parents),key=lambda r:len(r.parts))
   cur=root;record(cur);parts=list(p.relative_to(root).parts);restarted=False
   for i,part in enumerate(parts):
    if part=='..':
     cur=cur.parent;permitted(cur);record(cur);continue
    cur=cur/part;st=record(cur)
    if stat.S_ISLNK(st.st_mode):
     hops+=1
     if hops>256:raise Refused('unresolvable symlink chain')
     if i==len(parts)-1:aliases.add(cur.suffix.lower())
     target=safe_readlink(cur)
     q=Path(target) if os.path.isabs(target) else cur.parent/target
     permitted(q)
     p=q.joinpath(*parts[i+1:]);permitted(p);restarted=True;break
   if not restarted:return cur,record(cur),aliases|{cur.suffix.lower()}
 def open_checked(p):
  # Open every directory without following links; final O_NOFOLLOW alone is insufficient.
  fd=parent_fd(p)
  try:return os.open(p.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
  finally:os.close(fd)
 def check_file(p,st,kind):
  nonlocal images,archives
  key=(st.st_dev,st.st_ino,kind)
  if key in checked:return
  checked.add(key)
  fd=open_checked(p)
  with os.fdopen(fd,'rb') as stream:
   if signature(os.fstat(stream.fileno()))!=signature(st):raise Refused('audit open identity changed')
   if kind=='image':
    h=hashlib.sha256()
    while chunk:=stream.read(1024*1024):h.update(chunk)
    images+=1
    if h.hexdigest() in policy['image_sha256']:raise ValueError('Excluded image exists in linked workspace; do not view')
   else:
    with zipfile.ZipFile(stream) as archive:
     for info in archive.infolist():
      if Path(info.filename).suffix.lower() not in extensions:continue
      archives+=1;h=hashlib.sha256()
      with archive.open(info) as entry:
       while chunk:=entry.read(1024*1024):h.update(chunk)
      if h.hexdigest() in policy['image_sha256']:raise ValueError('Excluded image exists in linked workspace archive; do not view')
   if signature(os.fstat(stream.fileno()))!=signature(st):raise Refused('audit file mutated during read')
  record(p)
 extensions={'.jpg','.jpeg','.png','.webp','.gif'}
 pending=list(roots)
 while pending:
  alias=pending.pop();p,st,suffixes=resolve(alias)
  if stat.S_ISDIR(st.st_mode):
   key=(st.st_dev,st.st_ino)
   if key in visited_dirs:continue
   visited_dirs.add(key)
   # scandir errors are not suppressed, unlike recursive glob on some runtimes.
   fd=open_checked(p)
   try:
    if signature(os.fstat(fd))!=signature(st):raise Refused('audit directory changed before listing')
    with os.scandir(fd) as entries:pending.extend(p/e.name for e in entries)
    if signature(os.fstat(fd))!=signature(st):raise Refused('audit directory changed during listing')
   finally:os.close(fd)
   record(p)
  elif stat.S_ISREG(st.st_mode):
   if suffixes & extensions:check_file(p,st,'image')
   if '.zip' in suffixes:check_file(p,st,'zip')
  elif alias.suffix.lower() in extensions|{'.zip'} or p.suffix.lower() in extensions|{'.zip'}:
   raise Refused('image/archive path is not a regular file')
 # Detect swaps of aliases, directories, and files before returning any image path.
 for p,sig in records.items():
  if signature(safe_stat(p))!=sig:raise Refused('audit tree changed before completion')
 return {'workspaces':[str(r) for r in roots],'loose_images_checked':images,'archive_images_checked':archives,'directories_checked':len(visited_dirs),'excluded_images_found':0}

def _refusals(state,catalog,folder):
 posts={p['post_id']:p for j in catalog['jobs'] for p in j['manifest']['posts']}
 records=[]
 for h in state.get('koyo_index_handoffs',{}).values():
  records.extend(r for r in h.get('rows',{}).values() if disposition.is_exclusion(r))
 # Metadata-only local journal; no code/evidence from image contents is followed.
 for p in Path(folder).iterdir():
  if p.is_symlink() or not p.is_file() or p.suffix!='.json':raise Refused('unexpected local refusal artifact')
  r=json.loads(p.read_text())
  if not disposition.is_exclusion(r):raise Refused('invalid local policy-refusal record')
  records.append(r)
 refused_ids=set();refused_hashes=set()
 for r in records:
  pid=r.get('post_id');post=posts.get(pid)
  if post is None:raise Refused('unknown refusal post; cannot determine matching image hashes')
  if r.get('reason')!='policy_refusal' or r.get('signal') not in disposition.SIGNALS or r.get('scope')!='post' or r.get('temporary') is not True:raise Refused('malformed policy-refusal record')
  refused_ids.add(pid);refused_hashes.update(im['sha256'] for im in post['images'])
 return refused_ids,refused_hashes

def next_images(state,head,activation,source_root,*,now=None):
 """Return first safe unaccepted post, or metadata-only required exclusion/complete.
 No caller-supplied skip list. Known refusal in ANY attachment blocks whole post.
 All validation/auditing occurs before the result contains any image paths.
 """
 now=time.time() if now is None else now
 if not isinstance(now,(float,int)) or not re.fullmatch('[a-f0-9]{40}',head):raise Refused('fresh verified head/clock required')
 p=activation.get('payload',{});key=p.get('plan_sha256')
 if activation.get('sha256')!=sha(p) or p.get('mode')!='reviewed-live' or p.get('scope',{}).get('kind')!=KIND or not p.get('review_reference'):raise Refused('exact new batch activation required')
 pins=p.get('code_sha256',{})
 if pins.get(str(Path(__file__).resolve()))!=digest(__file__) or any(digest(f)!=v for f,v in pins.items()):raise Refused('image gate or activation code pin mismatch')
 h=state['koyo_index_handoffs'][key]
 if key in state.get('koyo_retained_work',{}) or h.get('status')!='leased' or h.get('lease',{}).get('owner')!='koyo' or h['lease']['until']<=now+30:raise Refused('inactive/paused/expired owner')
 validate_scope(p,state,state,key,'renew',source_root)
 inputs=PinnedInputs(source_root,h)
 binding=p.get('image_gate',{})
 if set(binding)!={'bundle_root','audit_roots','local_refusal_dir','review_reference'} or make_binding(**binding)!=binding:raise Refused('reviewed image coverage missing or changed')
 root=Path(source_root).resolve();config=json.loads((root/'runs/production-v4-001.json').read_text());source=h['plan']['payload']['source']
 if config.get('run_id')!=source['run_id'] or config.get('screening_receipt_sha256')!=source['screening_receipt_sha256'] or h['job_id'] not in config.get('job_ids',[]):raise Refused('run/config/screening mismatch')
 policy=isolation.load_policy(config,root)
 catalog=json.loads((root/'data/catalogs/data-v4-production-7113eaaefc38.json').read_text())
 isolation.check_catalog(catalog,policy);isolation.check_manifest(inputs.manifest,policy)
 refused_ids,refused_hashes=_refusals(state,catalog,binding['local_refusal_dir'])
 # Existing excluded files stop ALL viewing, not only their own catalog post.
 audits=[audit_linked_workspaces(binding['audit_roots'],policy)]
 for pid in source['post_ids']:
  if pid in h['rows']:continue
  post=inputs.posts[pid]
  if pid in refused_ids or any(im['sha256'] in refused_hashes for im in post['images']):
   return {'status':'known_refusal_requires_exclusion','post_id':pid,'scope':'post','image_paths':[],'viewed':False,'head':head,'instruction':'Persist metadata-only post exclusion and checkpoint; do not view or retry this post.'}
  isolation.check_post_files(binding['bundle_root'],post,policy)
  paths=[]
  for im in post['images']:
   path=Path(binding['bundle_root'])/im['path']
   if any(x.is_symlink() for x in (path,*path.parents)):raise Refused('image path contains symlink')
   paths.append({'media_index':im['media_index'],'sha256':im['sha256'],'path':str(path.resolve())})
  return {'status':'ready_for_actual_view','post_id':pid,'images':paths,'head':head,'state_sha256':sha(state),'plan_sha256':key,'audits':audits,'viewed':False,'receipt_generated':False}
 return {'status':'batch_rows_complete','head':head,'image_paths':[],'viewed':False}

def next_from_writer(writer,activation,source_root):
 """Fresh-read wrapper for the connector CLI. Never expose snapshot-file paths.
 Audit and byte checks may take time, so head/full state/lease are rechecked before
 returning. Any concurrent write fails closed; no retry or view occurs here.
 """
 before_head,before=writer.read()
 result=next_images(before,before_head,activation,source_root,now=writer.clock())
 after_head,after=writer.read()
 if before_head!=after_head or before!=after:raise Refused('snapshot changed during image gate; no paths exposed')
 key=activation['payload']['plan_sha256']
 if after['koyo_index_handoffs'][key]['lease']['until']<=writer.clock()+30:raise Refused('lease elapsed during image audit')
 return result

if __name__=='__main__':
 import argparse
 from network_runtime import IndexWriter,REMOTE
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--activation',required=True);ap.add_argument('--baseline',required=True);ap.add_argument('--source-root',required=True);a=ap.parse_args()
 activation=json.loads(Path(a.activation).read_text());baseline=json.loads(Path(a.baseline).read_text());p=activation['payload'];key=p['plan_sha256']
 if sha(baseline)!=p.get('source_state_sha256') or baseline['koyo_index_handoffs'][key]!=p.get('baseline_handoff'):raise Refused('activation baseline mismatch')
 w=IndexWriter(REMOTE,baseline['catalog_sha256'],key,a.source_root,activation_document=activation)
 try:print(json.dumps(next_from_writer(w,activation,a.source_root)))
 finally:w.close()
