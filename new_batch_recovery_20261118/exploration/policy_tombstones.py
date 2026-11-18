"""Fail-closed local/remote refusal guard. Metadata only, never images or network."""
import json
from pathlib import Path
from recovery_adapter import Refused

def require_not_refused(state,pid,source_root,refusal_dir):
 from pipeline_production import disposition
 directory=Path(refusal_dir)
 if not directory.is_dir() or any(p.is_symlink() for p in (directory,*directory.parents)):raise Refused('refusal journal unavailable')
 catalog=json.loads((Path(source_root)/'data/catalogs/data-v4-production-7113eaaefc38.json').read_text())
 posts={p['post_id']:p for j in catalog['jobs'] for p in j['manifest']['posts']}
 if pid not in posts:raise Refused('unknown target post')
 target={im['sha256'] for im in posts[pid]['images']};records=[]
 for h in state.get('koyo_index_handoffs',{}).values():records.extend(r for r in h.get('rows',{}).values() if disposition.is_exclusion(r))
 for f in directory.iterdir():
  if f.is_symlink() or not f.is_file() or f.suffix!='.json':raise Refused('unknown refusal journal artifact')
  records.append(json.loads(f.read_text()))
 for r in records:
  if not disposition.is_exclusion(r) or r.get('reason')!='policy_refusal' or r.get('signal') not in disposition.SIGNALS or r.get('scope')!='post' or r.get('temporary') is not True:raise Refused('invalid refusal tombstone')
  post=posts.get(r.get('post_id'))
  if not post:raise Refused('unknown refused post')
  if post['post_id']==pid or target&{im['sha256'] for im in post['images']}:raise Refused('post or same image has policy refusal; metadata exclusion only')
 return True
