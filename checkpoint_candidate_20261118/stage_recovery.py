"""Offline durable-stage protocol, independently persisted fake object store only.
A production adapter would use same authorized repo, a dedicated branch and immutable
objects plus discoverable keys. This module has NO network implementation.
"""
import copy,json,re,os,tempfile
from pathlib import Path
from checkpoint import digest,Refused,save_journal
class FixtureArchive:
    offline_fixture_only=True
    def __init__(self,path):self.path=Path(path);self.path.mkdir(parents=True,exist_ok=True)
    def put_if_absent(self,name,obj):
        file=self.path/name
        # Publish a fully written immutable object atomically; never replace existing.
        fd,tmp=tempfile.mkstemp(dir=self.path,prefix='.stage-')
        try:
            with os.fdopen(fd,'w') as stream:
                json.dump(obj,stream,ensure_ascii=False,sort_keys=True)
                stream.flush();os.fsync(stream.fileno())
            try:os.link(tmp,file)
            except FileExistsError:
                if json.loads(file.read_text())!=obj:raise Refused('immutable archive collision')
            directory=os.open(self.path,os.O_DIRECTORY)
            try:os.fsync(directory)
            finally:os.close(directory)
        finally:
            os.unlink(tmp)
    def get(self,name):return json.loads((self.path/name).read_text())
    def names(self):return sorted(p.name for p in self.path.glob('*.json'))

def name_for(item):
    p=item['payload']
    if not re.fullmatch(r'[A-Za-z0-9_-]+',p['key']) or not re.fullmatch(r'\d+',p['pid']):raise Refused('archive identity')
    return p['key']+'--'+p['pid']+'--'+item['sha256']+'.json'

def archive(item,store):
    if not getattr(store,'offline_fixture_only',False):raise Refused('live archive not enabled')
    if digest(item['payload'])!=item['sha256']:raise Refused('stage integrity')
    name=name_for(item);store.put_if_absent(name,item)
    if store.get(name)!=item:raise Refused('archive readback differs')
    return {'archive_name':name,'stage_sha256':item['sha256'],'durable_in_fixture':True,'external_request_permitted':False}

def restore(key,store):
    """Return unique immutable stages, fail closed on competing versions of a post."""
    if not getattr(store,'offline_fixture_only',False):raise Refused('live archive not enabled')
    found={}
    for name in store.names():
        if not name.startswith(key+'--'):continue
        item=store.get(name);p=item['payload']
        if digest(p)!=item['sha256'] or name_for(item)!=name or p['key']!=key:raise Refused('archive tampered')
        if p['pid'] in found and found[p['pid']]!=item:raise Refused('conflicting staged versions require review')
        found[p['pid']]=item
    return list(found.values())

def select_unstaged(state,key,staged):
    """No fetch permission. Lost stages with reserved body remain held, never replayed."""
    h=state['koyo_index_handoffs'][key];local={x['payload']['pid'] for x in staged if x['payload']['key']==key}
    for x in staged:
        if digest(x['payload'])!=x['sha256']:raise Refused('stage integrity')
    if key in state.get('koyo_retained_work',{}) or h['status']!='leased':raise Refused('inactive scope')
    held=[];eligible=[];ready=[]
    for pid in h['plan']['payload']['source']['post_ids']:
        if pid in h['rows']:continue
        if pid in local:ready.append(pid);continue
        # Any attempt record in ANY handoff means do not create a new fetch attempt.
        evidence=any(pid in other.get('context',{}) or pid in other.get('rows',{}) or
                     any(pid in op and ('fetch' in op or 'context' in op) for op in other.get('operations',{}))
                     for other in state['koyo_index_handoffs'].values())
        if evidence:held.append(pid)
        else:eligible.append(pid)
    return {'next_post_id':eligible[0] if eligible else None,'pending_staged':ready,'held_requires_reconciliation':held,'external_request_permitted':False}


def restore_available(key,store):
    """Quarantine conflicting post versions; restore independent posts without guessing.
    Timestamp-only duplicates with same token/dependencies/result are identical work.
    Changed result or lease-token versions require explicit fencing/review, never latest-wins.
    """
    if not getattr(store,'offline_fixture_only',False):raise Refused('live archive not enabled')
    groups={}
    for name in store.names():
        if not name.startswith(key+'--'):continue
        item=store.get(name);p=item['payload']
        if digest(p)!=item['sha256'] or name_for(item)!=name or p['key']!=key:raise Refused('archive tampered')
        groups.setdefault(p['pid'],[]).append(item)
    ready=[];conflicts={}
    for pid,versions in groups.items():
        identities={digest({k:v for k,v in it['payload'].items() if k!='staged_at'}) for it in versions}
        if len(identities)==1:ready.append(min(versions,key=lambda it:it['payload']['staged_at']))
        else:conflicts[pid]=[it['sha256'] for it in versions]
    return {'stages':ready,'conflicts':conflicts,'external_request_permitted':False}
