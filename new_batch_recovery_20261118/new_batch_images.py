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

def _audit_root(path):
 # A forest root can be an exact regular file; this never broadens to its parent.
 import stat
 p=Path(path).absolute()
 if any(x.is_symlink() for x in (p,*p.parents)):
  raise Refused('audit forest root is symlinked')
 mode=p.lstat().st_mode
 if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
  raise Refused('audit forest root must be directory or regular file')
 return p.resolve()

BOUNDARY_EXCLUSIONS={'.agents','.aws','.codex','.git'}
BINDING_KEYS={'bundle_root','audit_roots','local_refusal_dir','review_reference'}

def _boundary_snapshot(boundary):
 import os,stat
 if not isinstance(boundary,dict) or set(boundary)!={'directory','excluded_names'}:
  raise Refused('invalid coverage boundary')
 raw_directory=Path(boundary['directory']).absolute()
 denied=Path('/home/agent/.codex/sessions')
 if raw_directory==denied or denied in raw_directory.parents:raise Refused('coverage boundary denied')
 directory=_plain_dir(raw_directory)
 excluded=boundary.get('excluded_names',[])
 if not isinstance(excluded,list) or len(set(excluded))!=len(excluded) or not set(excluded)<=BOUNDARY_EXCLUSIONS:
  raise Refused('unsupported boundary exclusion')
 # Open every component without following a symlink, including the boundary.
 fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
 try:
  for part in directory.parts[1:]:
   nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
   os.close(fd);fd=nxt
  before=os.fstat(fd);identity=[before.st_dev,before.st_ino]
  entries=[]
  with os.scandir(fd) as scan:
   for entry in scan:
    if entry.name in excluded:continue
    if directory/entry.name==denied:raise Refused('coverage boundary child denied')
    st=os.stat(entry.name,dir_fd=fd,follow_symlinks=False)
    if stat.S_ISREG(st.st_mode):kind='file'
    elif stat.S_ISDIR(st.st_mode):kind='directory'
    else:raise Refused('nonplain coverage boundary child')
    entries.append({'name':entry.name,'type':kind})
  after=os.fstat(fd)
  if (after.st_dev,after.st_ino)!=(before.st_dev,before.st_ino):raise Refused('coverage boundary identity changed')
 finally:os.close(fd)
 # Reopen through the same no-follow chain to catch replacement of the boundary.
 fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
 try:
  for part in directory.parts[1:]:
   nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
   os.close(fd);fd=nxt
  st=os.fstat(fd)
  if [st.st_dev,st.st_ino]!=identity:raise Refused('coverage boundary replaced')
 finally:os.close(fd)
 result={'directory':str(directory),'excluded_names':sorted(excluded),'entries':sorted(entries,key=lambda e:e['name']),'directory_identity':identity}
 return result

def effective_forest(binding):
 snapshots=[_boundary_snapshot(b) for b in binding.get('coverage_boundaries',[])]
 roots={Path(r) for r in binding['audit_roots']}
 for snap in snapshots:
  roots.update(Path(snap['directory'])/e['name'] for e in snap['entries'])
 return sorted(roots,key=str),snapshots

def validate_boundaries(binding,expected):
 if [_boundary_snapshot(b) for b in binding.get('coverage_boundaries',[])]!=expected:
  raise Refused('coverage boundary changed during gate')

def make_binding(bundle_root,audit_roots,local_refusal_dir,review_reference,coverage_boundaries=None):
 """No I/O beyond path checks. Returned binding MUST be pinned into activation."""
 if not isinstance(review_reference,str) or not review_reference.strip():raise Refused('image coverage review required')
 bundle=_plain_dir(bundle_root);refusals=_plain_dir(local_refusal_dir)
 roots=[_audit_root(r) for r in audit_roots]
 if not roots or len(set(roots))!=len(roots) or not any(bundle.is_relative_to(r) for r in roots) or not any(refusals.is_relative_to(r) for r in roots):raise Refused('bundle/refusal stores outside reviewed audit coverage')
 result={'bundle_root':str(bundle),'audit_roots':[str(r) for r in roots],'local_refusal_dir':str(refusals),'review_reference':review_reference}
 if coverage_boundaries is not None:
  if not isinstance(coverage_boundaries,list) or not coverage_boundaries:raise Refused('empty coverage boundaries')
  result['coverage_boundaries']=[]
  for boundary in coverage_boundaries:
   snap=_boundary_snapshot(boundary)
   result['coverage_boundaries'].append({k:snap[k] for k in ('directory','excluded_names')})
  if len({b['directory'] for b in result['coverage_boundaries']})!=len(coverage_boundaries):raise Refused('duplicate coverage boundary')
 return result

def audit_linked_workspaces(roots,policy):
 """Opaque-byte audit of the complete declared root union, including linked caches.
 Root escapes, unreadable directories and unresolved links fail closed.
 Symlink metadata is checked before/after the pinned original byte audit;
 directory cycles are not followed, and their real targets remain in the forest.
 """
 import os,stat,hashlib,zipfile
 roots=tuple(_audit_root(r) for r in roots)
 rootset=set(roots)
 def covering_root(p):
  return next((q for q in (p,*p.parents) if q in rootset),None)
 denied=Path('/home/agent/.codex/sessions')
 records={};images=archives=0
 def permitted(p):
  if p==denied or denied in p.parents:raise Refused('audit target denied')
  if covering_root(p) is None:raise Refused('audit link outside reviewed roots')
 def signature(st):
  identity=(st.st_dev,st.st_ino,st.st_mode)
  return identity if stat.S_ISDIR(st.st_mode) else identity+(st.st_size,st.st_mtime_ns,st.st_ctime_ns)
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
   root=covering_root(p)
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
 extensions={'.jpg','.jpeg','.png','.webp','.gif'}
 def check_exact(p,suffixes):
  # Same opaque image/ZIP byte algorithm as the pinned original workspace audit.
  nonlocal images,archives
  if suffixes & extensions:
   images+=1
   if digest(p) in policy['image_sha256']:raise ValueError('Excluded image exists in linked workspace; do not view')
  if '.zip' in suffixes:
   with zipfile.ZipFile(p) as archive:
    for info in archive.infolist():
     if Path(info.filename).suffix.lower() not in extensions:continue
     archives+=1;h=hashlib.sha256()
     with archive.open(info) as entry:
      while chunk:=entry.read(1024*1024):h.update(chunk)
     if h.hexdigest() in policy['image_sha256']:raise ValueError('Excluded image exists in linked workspace archive; do not view')
 def walk_error(error):raise error
 # os.walk verifies every ordinary directory is readable; unlike rglob its
 # onerror callback is strict. It does not descend into symlink directories.
 aliases=[];directory_aliases=set()
 for root in roots:
  permitted(root)
  if root.is_file():continue
  for directory,dirs,files in os.walk(root,followlinks=False,onerror=walk_error):
   for name in dirs+files:
    path=Path(directory)/name
    if path.is_symlink():
     target,st,suffixes=resolve(path)
     if stat.S_ISREG(st.st_mode):aliases.append((target,suffixes))
     elif stat.S_ISDIR(st.st_mode):directory_aliases.add(target)
     else:raise Refused('symlink target is not plain file/directory')
    elif path.suffix.lower() in extensions|{'.zip'} and not path.is_file():
     raise Refused('image/archive path is not a regular file')
 # Resolve every alias before any bytes are hashed. Explicitly audit directory
 # alias targets too: an original root may otherwise skip their .git ancestor.
 for root in roots:
  if root.is_dir():
   result=isolation.audit_workspace(root,policy)
   images+=result['loose_images_checked'];archives+=result['archive_images_checked']
  else:check_exact(root,{root.suffix.lower()})
 for target in sorted(directory_aliases-set(roots),key=str):
  result=isolation.audit_workspace(target,policy)
  images+=result['loose_images_checked'];archives+=result['archive_images_checked']
 # Cover intermediate extension aliases even if the final file has no extension.
 for target,suffixes in aliases:check_exact(target,suffixes)
 for p,sig in records.items():
  if signature(safe_stat(p))!=sig:raise Refused('audit symlink path changed before completion')
 return {'workspaces':[str(r) for r in roots],'loose_images_checked':images,'archive_images_checked':archives,'excluded_images_found':0,'byte_audit':'pinned-isolation.audit_workspace'}

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
 if set(binding) not in (BINDING_KEYS,BINDING_KEYS|{'coverage_boundaries'}) or make_binding(**binding)!=binding:raise Refused('reviewed image coverage missing or changed')
 root=Path(source_root).resolve();config=json.loads((root/'runs/production-v4-001.json').read_text());source=h['plan']['payload']['source']
 if config.get('run_id')!=source['run_id'] or config.get('screening_receipt_sha256')!=source['screening_receipt_sha256'] or h['job_id'] not in config.get('job_ids',[]):raise Refused('run/config/screening mismatch')
 policy=isolation.load_policy(config,root)
 catalog=json.loads((root/'data/catalogs/data-v4-production-7113eaaefc38.json').read_text())
 isolation.check_catalog(catalog,policy);isolation.check_manifest(inputs.manifest,policy)
 refused_ids,refused_hashes=_refusals(state,catalog,binding['local_refusal_dir'])
 # Existing excluded files stop ALL viewing, not only their own catalog post.
 effective_roots,boundary_snapshot=effective_forest(binding)
 audits=[audit_linked_workspaces(effective_roots,policy)]
 validate_boundaries(binding,boundary_snapshot)
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
  validate_boundaries(binding,boundary_snapshot)
  return {'status':'ready_for_actual_view','post_id':pid,'images':paths,'head':head,'state_sha256':sha(state),'plan_sha256':key,'audits':audits,'viewed':False,'receipt_generated':False}
 return {'status':'batch_rows_complete','head':head,'image_paths':[],'viewed':False}

def next_from_writer(writer,activation,source_root):
 """Fresh-read wrapper for the connector CLI. Never expose snapshot-file paths.
 Audit and byte checks may take time, so head/full state/lease are rechecked before
 returning. Any concurrent write fails closed; no retry or view occurs here.
 """
 binding=activation.get('payload',{}).get('image_gate',{})
 _,wrapper_boundary_snapshot=effective_forest(binding)
 before_head,before=writer.read()
 result=next_images(before,before_head,activation,source_root,now=writer.clock())
 after_head,after=writer.read()
 validate_boundaries(binding,wrapper_boundary_snapshot)
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
