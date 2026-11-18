"""Separately reviewable ordinary evidence_sufficient guard; offline candidate only.
No old row rewriting, synthetic no_leads, exploration clock fabrication or network.
The caller must provide pinned policy/scope/ownership checks and fixed row validator.
"""
import copy
from urllib.parse import urlsplit
from checkpoint import Refused,apply,target

def same_post_url(url,pid):
    try:
        u=urlsplit(url);parts=u.path.rstrip('/').split('/')
        return u.scheme=='https' and u.hostname in ('x.com','www.x.com','twitter.com','www.twitter.com') and not u.username and not u.password and not u.query and not u.fragment and len(parts)==4 and bool(parts[1]) and parts[2]=='status' and parts[3]==pid
    except (ValueError,AttributeError):return False

def validate(before,after,key,pid,token,now,policy_scope_guard,fixed_validator):
    b=before['koyo_index_handoffs'][key];a=after['koyo_index_handoffs'][key]
    if key in before.get('koyo_retained_work',{}):raise Refused('paused scope')
    if b['status']!='leased' or b['lease']['owner']!='koyo' or b['lease']['token']!=token or b['lease']['until']<=now+30:raise Refused('lease')
    if pid not in b['plan']['payload']['source']['post_ids'] or pid in b['rows']:raise Refused('not unaccepted pinned post')
    wanted=copy.deepcopy(before);wanted['koyo_index_handoffs'][key]['rows'][pid]=copy.deepcopy(a['rows'][pid])
    if wanted!=after:raise Refused('row only; durable body/views required')
    ctx=b['context'].get(pid,{})
    if 'fetch_started' not in ctx or any(k in ctx for k in ('budget','reservations','exploration_clock')):raise Refused('ordinary existing one-shot body required')
    cache=ctx.get('cache',{});text=cache.get('text')
    if cache.get('post_id')!=pid or cache.get('state')!='available' or not isinstance(text,str) or not text.strip():raise Refused('available body required')
    row=a['rows'][pid];c=row['context']
    if row['post_id']!=pid or c['state']!='complete' or c['stop_reason']!='evidence_sufficient' or any(c[k]!=0 for k in ('searches','pages','elapsed_seconds')):raise Refused('zero-search complete result required')
    for attr in c['attributes'].values():
        if attr['status']=='not_applicable':continue
        if attr['status']!='observed' or not attr['sources'] or not attr['evidence'].strip() or attr['evidence'] not in text:raise Refused('direct textual evidence required for every applicable context answer')
        for source in attr['sources']:
            if source['kind']!='post_text' or not same_post_url(source['url'],pid):raise Refused('same-post text source only')
    # Mandatory hooks retain actual policy/view receipt/manifest/provenance validation.
    policy_scope_guard(before,after,key,pid,token,now)
    fixed_validator(row,b['events'].get(pid,[]))
    return True
