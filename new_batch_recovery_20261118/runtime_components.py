"""Recovery runtime components, local-only. Distinct from missing v8.
No remote network writes. Evidence attestation still requires actual trusted viewer.
"""
import copy, hashlib, json, math, os, subprocess
from pathlib import Path
from recovery_adapter import canonical, sha, Refused, Stale
REVISION='recovery-isolated-2'
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def number(x):
    if type(x) not in (int,float) or not math.isfinite(x):raise Refused('invalid time')
    return x

def provenance(h):
    source=h['plan']['payload']['source'];d=h['destination']
    return {**{k:source[k] for k in ('catalog_sha256','contract_sha256','job_id','manual_sha256','screening_receipt_sha256')},
      **{k:d[k] for k in ('run_id','model_id','model_identity_source','reasoning_effort')},
      'handoff_plan_sha256':h['plan_sha256'],'source_run_id':source['run_id'],'schema_version':'v4-1'}

class PinnedInputs:
    def __init__(self,root,h):
        self.root=Path(root);self.h=h;src=h['plan']['payload']['source']
        files={'contract_sha256':'pipeline_production/contract_v4.py','manual_sha256':'docs/LABELING_V4_PRODUCTION.md',
          'catalog_sha256':'data/catalogs/data-v4-production-7113eaaefc38.json',
          'config_sha256':'runs/production-v4-001.json'}
        for key,path in files.items():
            if digest(self.root/path)!=src[key]:raise Refused('pinned input changed: '+key)
        cat=json.loads((self.root/files['catalog_sha256']).read_text())
        job=next(j for j in cat['jobs'] if j['job_id']==h['job_id']);self.manifest=job['manifest']
        if sha(self.manifest)!=src['manifest_sha256'] or [p['post_id'] for p in self.manifest['posts']]!=src['post_ids']:raise Refused('manifest changed')
        self.posts={p['post_id']:p for p in self.manifest['posts']}
    def validate_row(self,row,events):
        from pipeline_production.contract_v4 import validate
        pid=row['post_id'];post=self.posts[pid]
        from pipeline_production import disposition
        if disposition.is_exclusion(row):
            disposition.validate(row,post,provenance(self.h))
            if row['worker_id']!='koyo':raise Refused('exclusion worker mismatch')
            return True
        validate(row,post,provenance(self.h))
        required={(i['media_index'],i['sha256']) for i in post['images']}
        observed={(e['media_index'],e['sha256']) for e in events if e.get('post_id')==pid and e.get('outcome')=='viewed' and e.get('tool') and e.get('tool_call_id')}
        if not required<=observed:raise Refused('actual per-post image event missing')
        return True
    def image_event(self,pid,media_index,path,tool_receipt):
        im=next(i for i in self.posts[pid]['images'] if i['media_index']==media_index)
        if digest(path)!=im['sha256']:raise Refused('image bytes mismatch')
        if not tool_receipt.get('tool') or not tool_receipt.get('tool_call_id') or not tool_receipt.get('at'):raise Refused('viewer receipt required')
        # Receipt must come from trusted viewing orchestration, never model inference or OCR.
        return dict(tool_receipt,post_id=pid,media_index=media_index,sha256=im['sha256'],outcome='viewed')

def activation(state,head,key,code_files):
    h=state['koyo_index_handoffs'][key]
    if sha(h['plan']['payload'])!=key:raise Refused('bad plan')
    payload={'revision':REVISION,'mode':'isolated-only','source_head':head,'state_sha256':sha(state),'plan_sha256':key,
      'accepted_rows_sha256':{k:sha(x['rows']) for k,x in state['koyo_index_handoffs'].items()},
      'terra_entries_sha256':sha(state['entries']),'code_sha256':{str(Path(f).resolve()):digest(f) for f in code_files}}
    return {'payload':payload,'sha256':sha(payload)}
def verify_activation(a,state,head,key):
    p=a['payload']
    if a['sha256']!=sha(p) or p['revision']!=REVISION or p['mode']!='isolated-only':raise Refused('activation invalid')
    if p['source_head']!=head or p['state_sha256']!=sha(state) or p['plan_sha256']!=key:raise Refused('source drift')
    for f,v in p['code_sha256'].items():
        if digest(f)!=v:raise Refused('code drift')
    if p['terra_entries_sha256']!=sha(state['entries']) or p['accepted_rows_sha256']!={k:sha(x['rows']) for k,x in state['koyo_index_handoffs'].items()}:raise Refused('preservation mismatch')
    return True

class ExplorationClock:
    """New revision: 60s active wall time, 2 searches/3 pages, immutable receipts.
    Request-to-ACK waits and measured control waits are excluded once by union.
    Crash with unacked request is blocked, not replayed. Old v2 is preserved only.
    """
    def __init__(self,started):
        self.started=number(started);self.last=self.started;self.requests={};self.waits=[];self.sealed=None
    def tick(self,now):
        number(now)
        if now<self.last:raise Refused('clock rollback')
        self.last=now
    def interval(self,start,end):
        number(start);number(end)
        if not self.started<=start<=end<=self.last:raise Refused('bad interval')
        return start,end
    def management_wait(self,start,end,command):
        if self.sealed:raise Refused('sealed')
        self.tick(end)
        if command not in ('fetch','ls-remote','renewal-cas'):raise Refused('not a management wait')
        self.waits.append(self.interval(start,end))
    def elapsed(self,now):
        self.tick(now);intervals=list(self.waits)
        for r in self.requests.values():
            if 'ack' not in r:raise Refused('unacked request: investigate, never replay')
            intervals.append((r['at'],r['ack']))
        merged=[]
        for a,b in sorted(intervals):
            if merged and a<=merged[-1][1]:merged[-1][1]=max(merged[-1][1],b)
            else:merged.append([a,b])
        return max(0,now-self.started-sum(b-a for a,b in merged))
    def reserve(self,request_id,kind,query,now):
        if self.sealed or request_id in self.requests:raise Refused('sealed or duplicate request')
        if kind not in ('search','page') or not isinstance(query,str) or not query.strip():raise Refused('invalid request')
        if self.elapsed(now)>=60:raise Refused('budget expired')
        if sum(r['kind']==kind for r in self.requests.values())>={'search':2,'page':3}[kind]:raise Refused('count limit')
        self.requests[request_id]={'kind':kind,'query':query,'at':now}
    def ack(self,request_id,result_sha,now):
        if self.sealed:raise Refused('sealed')
        self.tick(now);r=self.requests[request_id]
        if len(result_sha)!=64 or any(c not in '0123456789abcdef' for c in result_sha):raise Refused('result hash')
        if 'ack' in r:
            if (r['ack'],r['result_sha256'])!=(now,result_sha):raise Refused('ack immutable')
            return
        if now<r['at']:raise Refused('ack before request')
        r.update(ack=now,result_sha256=result_sha)
    def seal(self,now):
        if self.sealed:raise Refused('already sealed')
        self.sealed={'revision':REVISION,'elapsed_seconds':self.elapsed(now),'wall_seconds':now-self.started,'ended_at':now,'requests_sha256':sha(self.requests)}
        return copy.deepcopy(self.sealed)
    @staticmethod
    def preserve_legacy(context):
        c=copy.deepcopy(context)
        if any(k in c for k in ('budget','reservations','exploration_clock')):
            if not c.get('exploration_clock',{}).get('seal'):raise Refused('unsealed legacy clock requires recovery; no reset')
        return c

class LocalGitTransport:
    """Local bare-repo integration target. Explicitly rejects any network remote."""
    def __init__(self,path):
        self.path=Path(path).resolve()
        if not self.path.is_dir():raise Refused('local directory required')
        if self.git('remote').stdout:raise Refused('network/remotes forbidden in isolation')
    def git(self,*args,data=None,check=True):
        return subprocess.run(['git','--git-dir',str(self.path),*args],input=data,capture_output=True,check=check,env=dict(os.environ,GIT_AUTHOR_NAME='Recovery isolated',GIT_AUTHOR_EMAIL='offline@example.invalid',GIT_COMMITTER_NAME='Recovery isolated',GIT_COMMITTER_EMAIL='offline@example.invalid'))
    def head(self):return self.git('rev-parse','refs/heads/recovery-test').stdout.decode().strip()
    def read(self):return json.loads(self.git('show','refs/heads/recovery-test:state.json').stdout)
    def commit(self,state,parent=None):
        b=self.git('hash-object','-w','--stdin',data=canonical(state)).stdout.decode().strip()
        t=self.git('mktree',data=f'100644 blob {b}\tstate.json\n'.encode()).stdout.decode().strip()
        return self.git('commit-tree',t,*(['-p',parent] if parent else []),data=b'isolated recovery transition').stdout.decode().strip()
    def cas(self,expected,state,lose_ack=False):
        candidate=self.commit(state,expected)
        p=self.git('update-ref','refs/heads/recovery-test',candidate,expected,check=False)
        observed=self.head()
        if observed==candidate:
            if sha(self.read())!=sha(state):raise Refused('ACK content mismatch')
            return {'accepted':True,'head':candidate,'ack_reconciled':lose_ack,'request_permission':not lose_ack}
        if p.returncode or observed!=expected:raise Stale('competing state; re-read, never overwrite')
        raise Refused('unknown CAS outcome; do not issue external request')

from recovery_adapter import Adapter
class PinnedAdapter(Adapter):
    """Integrates pinned manifest/provenance and context budget seals at save boundary."""
    def __init__(self,store,plan_key,token,now,root):
        super().__init__(store,plan_key,token,now);self.root=root
    def append_row(self,expected,pid,row):
        h=self.checked(self.store.state,pid);pins=PinnedInputs(self.root,h)
        pins.validate_row(row,h['events'].get(pid,[]))
        context=h['context'].get(pid,{})
        ExplorationClock.preserve_legacy(context)
        # Existing legacy research clock is retained; new clocks require separate migration seal.
        seal=context.get('exploration_clock',{}).get('seal')
        if seal:
            for key in ('searches','pages','elapsed_seconds'):
                if row['context'][key]!=seal[key]:raise Refused('row clock does not match durable seal')
        elif any(row['context'][key]!=0 for key in ('searches','pages','elapsed_seconds')):
            raise Refused('exploration evidence missing')
        return super().append_row(expected,pid,row,pins.posts[pid],provenance(h))
