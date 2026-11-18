"""Isolated recovery clock v3: ACK is BEFORE the web call, never its result.
No networking, remote writes, or external-request execution in this module.
"""
import copy, hashlib, hmac, json, math, secrets
VERSION='koyo-exploration-recovery-v3'
class Refused(ValueError):pass
def canonical(x):return (json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def digest(x):return hashlib.sha256(canonical(x)).hexdigest()
def number(x):
 if type(x) not in (int,float) or not math.isfinite(x):raise Refused('invalid finite timestamp')
 return x
class Authority:
 """Trusted runner boundary, not arbitrary SHA-as-authentication.
 Receipt issuance methods are for verified connector/measurement wrappers ONLY.
 This isolated authority is process-local: restart loses outstanding permissions.
 """
 def __init__(self):self._key=secrets.token_bytes(32);self._issued={};self._used=set()
 def _issue(self,payload):
  key=secrets.token_hex(16);p=copy.deepcopy(payload);p['receipt_id']=key
  proof={'payload':p,'sha256':digest(p),'mac':hmac.new(self._key,canonical(p),hashlib.sha256).hexdigest()};self._issued[key]=copy.deepcopy(proof);return proof
 def verified_ack(self,binding,request_id,reservation_sha,head,now,*,acknowledged,readback_sha):
  if not acknowledged or reservation_sha!=readback_sha or not isinstance(head,str) or len(head)!=40 or any(c not in '0123456789abcdef' for c in head):raise Refused('ACK/readback not certain')
  return self._issue({'type':'ack','binding':binding,'request_id':request_id,'reservation_sha256':reservation_sha,'head':head,'at':number(now)})
 def measured_wait(self,binding,request_id,head,command,start,end,monotonic_seconds):
  # In integration, only the actual q.git measurement wrapper may call this.
  number(start);number(end);number(monotonic_seconds)
  if command not in ('fetch','ls-remote') or start>end or monotonic_seconds<0 or abs((end-start)-monotonic_seconds)>0.05:raise Refused('not a valid measured management read')
  return self._issue({'type':'management-read','binding':binding,'request_id':request_id,'head':head,'command':command,'started_at':start,'ended_at':end,'elapsed_seconds':monotonic_seconds})
 def verify(self,proof,kind,binding):
  p=proof.get('payload',{});rid=p.get('receipt_id')
  if proof!=self._issued.get(rid) or p.get('type')!=kind or p.get('binding')!=binding or proof.get('sha256')!=digest(p):raise Refused('untrusted, altered or wrong-binding receipt')
  return p
 def consume_permission(self,proof):
  rid=proof['payload']['receipt_id']
  if rid in self._used:raise Refused('permission already consumed')
  self._used.add(rid)

def new_clock(binding,legacy_context=None):
 if set(binding)!={'plan_sha256','post_id','worker','lease_token'} or binding['worker']!='koyo':raise Refused('binding required')
 if legacy_context and any(k in legacy_context for k in ('budget','reservations','exploration_clock')):raise Refused('existing exploration cannot reset/migrate implicitly')
 return {'version':VERSION,'binding':copy.deepcopy(binding),'started_at':None,'last_event_at':None,'requests':{},'management_reads':{},'searches':0,'pages':0,'seal':None}

def check(s,now):
 number(now)
 if s.get('version')!=VERSION or s['seal'] is not None:raise Refused('wrong revision or sealed')
 if s['last_event_at'] is not None and now<s['last_event_at']:raise Refused('clock rollback')
def union_length(intervals):
 merged=[]
 for a,b in sorted(intervals):
  if merged and a<=merged[-1][1]:merged[-1][1]=max(merged[-1][1],b)
  else:merged.append([a,b])
 return sum(b-a for a,b in merged)
def elapsed(s,now,*,pending=False):
 number(now)
 if s['last_event_at'] is not None and now<s['last_event_at']:raise Refused('clock rollback')
 if s['started_at'] is None:return 0.0
 intervals=[]
 for r in s['requests'].values():
  if 'ack' not in r:
   if not pending:raise Refused('pending ACK: no new request or seal')
   end=now
  else:end=r['ack']['payload']['at']
  if not s['started_at']<=r['reserved_at']<=end<=now:raise Refused('inconsistent reservation interval')
  intervals.append((r['reserved_at'],end))
 for proof in s['management_reads'].values():
  p=proof['payload'];a,b=p['started_at'],p['ended_at']
  if not s['started_at']<=a<=b<=now:raise Refused('management interval outside clock')
  intervals.append((a,b))
 return max(0.0,now-s['started_at']-union_length(intervals))
def transition(state,event,authority):
 """Writer boundary: recompute this transition and require exact candidate equality."""
 s=copy.deepcopy(state);kind=event['kind'];now=number(event['at']);check(s,now)
 requests=s['requests'];binding=s['binding']
 if kind=='reserve':
  rid=event['request_id'];typ=event['request_kind'];queries=event['queries']
  if rid in requests or typ not in ('search','page') or not isinstance(queries,list) or not queries or not all(isinstance(q,str) and q.strip() and len(q)<=2000 for q in queries):raise Refused('invalid/duplicate request')
  if typ=='page' and len(queries)!=1:raise Refused('one page per operation')
  if any('finished_at' not in r for r in requests.values()):raise Refused('previous request pending/in-flight/ambiguous')
  if elapsed(s,now)>=60:raise Refused('new exploration cannot start at/after 60 active seconds')
  n=len(queries);field='searches' if typ=='search' else 'pages'
  if s[field]+n>{'searches':2,'pages':3}[field]:raise Refused('fixed count limit')
  if s['started_at'] is None:s['started_at']=now
  s[field]+=n;requests[rid]={'kind':typ,'queries':copy.deepcopy(queries),'reserved_at':now}
 elif kind=='acknowledge':
  rid=event['request_id'];r=requests[rid]
  if 'ack' in r:raise Refused('ACK immutable; no repeated permission')
  p=authority.verify(event['proof'],'ack',binding)
  if p['request_id']!=rid or p['at']!=now or p['reservation_sha256']!=digest(state):raise Refused('ACK not bound to exact committed reservation')
  r['ack']=copy.deepcopy(event['proof'])
 elif kind=='external_started':
  rid=event['request_id'];r=requests[rid]
  if 'ack' not in r or 'started_at' in r:raise Refused('no ACK or request already started')
  authority.verify(r['ack'],'ack',binding)
  if elapsed(s,now)>=60:raise Refused('permission expired while idle after ACK')
  r['started_at']=now
 elif kind=='external_finished':
  r=requests[event['request_id']]
  if 'started_at' not in r or 'finished_at' in r or len(event['result_sha256'])!=64 or any(c not in '0123456789abcdef' for c in event['result_sha256']):raise Refused('unexpected result')
  if 'result_state' in event:
   if event['result_state'] not in ('available','technical_failure'):raise Refused('unknown result outcome')
   r['result_state']=event['result_state']
  r['finished_at']=now;r['result_sha256']=event['result_sha256']
 elif kind=='management_read':
  p=authority.verify(event['proof'],'management-read',binding);rid=p['request_id']
  if rid not in requests or p['head']!=requests[rid].get('ack',{}).get('payload',{}).get('head') or p['ended_at']!=now:raise Refused('measurement binding mismatch')
  if s['started_at'] is None or p['started_at']<s['started_at']:raise Refused('measurement before clock')
  for r in requests.values():
   if 'started_at' in r:
    end=r.get('finished_at',now)
    if max(p['started_at'],r['started_at'])<min(p['ended_at'],end):raise Refused('cannot deduct external tool/analysis execution')
  receipt_id=p['receipt_id']
  if receipt_id in s['management_reads']:raise Refused('duplicate management receipt')
  s['management_reads'][receipt_id]=copy.deepcopy(event['proof'])
 elif kind=='seal':
  if any('finished_at' not in r for r in requests.values()):raise Refused('unfinished/ambiguous request cannot seal')
  s['seal']={'at':now,'elapsed_seconds':elapsed(s,now),'searches':s['searches'],'pages':s['pages'],'wall_seconds':0 if s['started_at'] is None else now-s['started_at'],'ledger_sha256':digest(state)}
 else:raise Refused('unknown event')
 s['last_event_at']=now;return s

def validate_transition(before,event,candidate,authority):
 # Validation must not consume the live authority's permission until actual dispatch.
 clone=copy.copy(authority);clone._used=set(authority._used)
 expected=transition(before,event,clone)
 if expected!=candidate:raise Refused('candidate differs from validated transition')
 return True

class TrustedGitRecorder:
 """Production integration wraps the already-authorized q.git callable once.
 Callers cannot submit measured timestamps through this interface.
 The authority/recorder must not be exposed to source text or row JSON.
 """
 def __init__(self,authority,runner,wall_clock,monotonic_clock):
  self.authority=authority;self.runner=runner;self.wall=wall_clock;self.monotonic=monotonic_clock;self.proofs=[]
 def run(self,binding,request_id,head,*argv):
  if not argv or argv[0] not in ('ls-remote','fetch'):raise Refused('only measured Git reads')
  start=self.wall();mono=self.monotonic()
  try:return self.runner(*argv)
  finally:
   end=self.wall();duration=self.monotonic()-mono
   proof=self.authority.measured_wait(binding,request_id,head,argv[0],start,end,duration)
   self.proofs.append(proof)


def run_external_once(state,request_id,now,authority,journal_write,runner):
    """Trusted tool bridge: consume capability and persist intent BEFORE tool call.
    Caller returns/records the actual finish time via external_finished afterward.
    If journaling or runner fails, never mint replacement permission automatically.
    """
    r=state['requests'][request_id]
    started=transition(state,{'kind':'external_started','request_id':request_id,'at':now},authority)
    authority.consume_permission(r['ack'])
    journal_write(copy.deepcopy(started))
    return started,runner()
