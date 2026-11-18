"""Synthetic-only successor activation simulator. Not a deployment/issuance API.
No filesystem writes, network, production path support or real approval adapter.
"""
import copy,hashlib,json,math
from pathlib import Path
class Refused(RuntimeError):pass

def digest_obj(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def digest_bytes(x):return hashlib.sha256(x).hexdigest()

def issue_successor(*args,**kwargs):
    # There is no authenticated issuance-approval capability installed here.
    # User supplied strings, fixture grants and approved=True cannot change that.
    raise Refused('real issuance unavailable: authenticated operational approval and independent review adapter not installed')

class FixtureApproval:
    """Explicitly fake, in-memory test approval. Never accepted by issue_successor."""
    def __init__(self,manifest_digest,approved=False,reviewed=False):
        self.manifest_digest=manifest_digest;self.approved=approved;self.reviewed=reviewed


def simulate_successor(case,approval):
    """Return a labelled test wrapper; only accepts synthetic fixture structures.
    validators are unmodified real runtime validators supplied by fixture harness.
    This is NOT an authority boundary for production, which always refuses above.
    """
    root=Path(case['fixture_root'])
    if root.is_symlink() or not root.name.startswith('synthetic-successor-') or root.parent!=Path('/tmp'):
        raise Refused('fixture root only')
    if (root/'FIXTURE_ONLY').read_text()!='SYNTHETIC, NOT APPROVAL\n':raise Refused('fixture marker')
    old=case['old_activation'];new_code=case['new_code'];old_code=case['old_code'];manifest=case['manifest'];state=case['state'];genesis=case['genesis'];now=case['now'];key=old['payload']['plan_sha256']
    expected_manifest=case['expected_manifest']
    if manifest!=expected_manifest:raise Refused('manifest differs from synthetic issuance request')
    if type(approval) is not FixtureApproval or not approval.approved or not approval.reviewed or approval.manifest_digest!=digest_obj(manifest):raise Refused('fixture operational approval and independent review required')
    if manifest['fixture_only'] is not True or manifest['generation']!=manifest['parent_generation']+1:raise Refused('fixture generation or rollback')
    if manifest['old_document_digest']!=digest_obj(old):raise Refused('old document drift')
    if manifest['head']!=case['head'] or manifest['state_digest']!=digest_obj(state):raise Refused('fresh state/head drift')
    if type(now) not in (int,float) or not math.isfinite(now) or not 0<=now-manifest['checked_at']<=60:raise Refused('freshness')
    if case['pending'] or case['active_writers']!=0:raise Refused('pending operation or active writer')
    h=state['koyo_index_handoffs'][key]
    if h['lease']['until']<=now+120 or h['lease']['owner']!='koyo' or h['status']!='leased' or key in state.get('koyo_retained_work',{}):raise Refused('lease or scheduler')
    if state.get('fixture_only') is not True or h['job_id']!='synthetic-job' or h['plan']['payload']['source']['post_ids']!=[str(900000+i) for i in range(50)]:raise Refused('synthetic data only')
    # Reject undeclared paths/symlinks before any file content read.
    for base in (old_code,new_code,case['source_root']):
        base=Path(base)
        if not base.is_relative_to(root) or any(p.is_symlink() for p in (base,*base.parents)):raise Refused('outside fixture or symlink')
    for path in old['payload']['code_sha256']:
        p=Path(path)
        if not p.is_relative_to(root) or any(q.is_symlink() for q in (p,*p.parents)):raise Refused('pin outside fixture or symlink')
    old_check=case['old_validators'];new_check=case['new_validators']
    old_check.validate_document(old,case['source_root'],old_code)
    old_check.validate_scope(old['payload'],state,state,key,'renew',case['source_root'])
    if old['payload']['source_state_sha256']!=case['runtime_sha'](genesis) or old['payload']['baseline_handoff']!=genesis['koyo_index_handoffs'][key]:raise Refused('genesis baseline differs')
    # Manifest permits one exact content update; path translation is solely the
    # isolated old/new fixture directory. No production installation exists.
    old_names={p.name for p in Path(old_code).iterdir() if p.is_file()};new_names={p.name for p in Path(new_code).iterdir() if p.is_file()}
    if old_names!=new_names:raise Refused('module set changed')
    changed=[]
    for name in sorted(old_names):
        a=Path(old_code)/name;b=Path(new_code)/name
        if a.is_symlink() or b.is_symlink():raise Refused('module symlink')
        ah=digest_bytes(a.read_bytes());bh=digest_bytes(b.read_bytes())
        if ah!=bh:changed.append({'name':name,'old':ah,'new':bh})
    if changed!=manifest['changes'] or [x['name'] for x in changed]!=['network_runtime.py']:raise Refused('unapproved module changes')
    candidate=copy.deepcopy(old);p=candidate['payload'];pins={}
    for path,hash_ in p['code_sha256'].items():
        pp=Path(path)
        if pp.parent==Path(old_code):pins[str(Path(new_code)/pp.name)]=digest_bytes((Path(new_code)/pp.name).read_bytes())
        else:pins[path]=hash_
    p['code_sha256']=pins;candidate['sha256']=case['runtime_sha'](p)
    # Everything but the isolated code map must retain identical semantics.
    lhs=copy.deepcopy(p);rhs=copy.deepcopy(old['payload']);lhs.pop('code_sha256');rhs.pop('code_sha256')
    if lhs!=rhs:raise Refused('immutable activation field changed')
    new_check.validate_document(candidate,case['source_root'],new_code)
    new_check.validate_scope(p,state,state,key,'renew',case['source_root'])
    return {'fixture_only':True,'deployment_allowed':False,'issuance_approved':False,
            'note':'Only synthetic validation exercised; real issuance is unavailable',
            'candidate_for_validator_test':candidate,
            'receipt':{'parent_digest':digest_obj(old),'candidate_digest':digest_obj(candidate),'manifest_digest':digest_obj(manifest),'preflight_state_digest':digest_obj(state)}}
