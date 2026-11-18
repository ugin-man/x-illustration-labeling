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

def _reject_symlinks(root):
 # The pinned legacy audit does not follow directory symlinks. Fail closed rather
 # than interpreting an unaudited linked cache as empty. Explicit reads only.
 for p in root.rglob('*'):
  if p.is_symlink():raise Refused('audit coverage contains symlink; do not expose images')

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
 audits=[]
 for path in binding['audit_roots']:
  audited=Path(path);_reject_symlinks(audited);audits.append(isolation.audit_workspace(audited,policy))
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
