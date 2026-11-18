"""Explicit historical fencing reconciliation. Isolated only, never new fetch permission.
A ticket is derived from verified Git snapshots of the original accepted reacquisition,
not a free-form approval or a mutable caller claim. Old stage remains immutable.
"""
import copy,json
from checkpoint import Refused,digest,prepare
from git_adapters import REPO,canonical

def snapshot_at(aggregate,head):
 c=aggregate.call('get_commit',head);entries=aggregate.entries(c['tree'])
 return json.loads(aggregate.contents(entries['state.json'])),c

def require_ancestor(aggregate,ancestor,head):
 # Existing workflow is linear; refuse merge ambiguity rather than choosing a parent.
 for _ in range(1000):
  if head==ancestor:return
  c=aggregate.call('get_commit',head)
  if len(c['parents'])!=1:raise Refused('unverified reacquisition ancestry')
  head=c['parents'][0]
 raise Refused('ancestry bound exceeded')

def validate_historical_sealed(worker,item,prior,prior_head,current,after,pid,token):
 from checkpoint import apply,target
 from types import SimpleNamespace
 from sealed_stage_validation import validate as sealed_validate
 from new_batch_scope import validate_scope,validate_document
 from runtime_components import PinnedInputs
 key=worker.key;old=item['payload'];when=old['staged_at'];clock=prior['koyo_index_handoffs'][key]['context'][pid]['exploration_clock']
 if not clock['seal']['at']<=when<prior['koyo_index_handoffs'][key]['lease']['until']-30:raise Refused('historical sealed stage time outside authorized lease')
 if target(prior['koyo_index_handoffs'][key],pid)!=old['before']:raise Refused('historical sealed dependencies differ')
 historic=copy.copy(worker);historic.clock=lambda:when;historic.writer=copy.copy(worker.writer);historic.writer.clock=lambda:when
 historic.aggregate=SimpleNamespace(read_state=lambda:(prior_head,prior,None))
 prior_after=apply(prior,key,pid,old['after'])
 sealed_validate(historic,prior,prior_after,pid,old['lease_token'],worker.exploration_activation)
 worker.check(current)
 from next_batch import require_scheduler_permission
 require_scheduler_permission(current,key)
 if current['koyo_index_handoffs'][key]['lease']['token']!=token:raise Refused('new lease mismatch')
 if apply(current,key,pid,old['after'])!=after:raise Refused('adoption may only reuse exact immutable result')
 # Current ownership/policy/scope/schema remain mandatory. Only the clock token
 # stays historical; no clock/source/receipt is rewritten and no request is granted.
 validate_document(worker.writer.activation_document,worker.writer.root)
 validate_scope(worker.writer.activation_document['payload'],current,after,key,'save-row',worker.writer.root)
 PinnedInputs(worker.writer.root,current['koyo_index_handoffs'][key]).validate_row(old['after']['rows'],current['koyo_index_handoffs'][key]['events'][pid])
 worker.writer.preservation(current,after)
 return True

def verify_adoption(worker,item,prior_head,reacquired_head,review_reference):
 if not review_reference or not getattr(worker.aggregate.io,'offline_fixture_only',False):raise Refused('isolated reviewed adoption only')
 key=worker.key;pid=item['payload']['pid'];oldtoken=item['payload']['lease_token']
 from stage_recovery import name_for
 _,archive_commit=worker.archive.snapshot();entries=worker.archive.entries(archive_commit['tree']);source_path='stages/'+name_for(item)
 if source_path not in entries or json.loads(worker.archive.contents(entries[source_path]))!=item:raise Refused('original stage not durably archived')
 prior,_=snapshot_at(worker.aggregate,prior_head);accepted,c=snapshot_at(worker.aggregate,reacquired_head)
 if c['parents']!=[prior_head]:raise Refused('reacquisition must be exact accepted child')
 old=prior['koyo_index_handoffs'][key];new=accepted['koyo_index_handoffs'][key]
 history=new.get('recovery_lease_history',[])
 if len(history)!=len(old.get('recovery_lease_history',[]))+1:raise Refused('missing reacquisition receipt')
 event=history[-1];at=event['at'];fencing=event.get('fencing_receipt',{})
 if old['lease']['token']!=oldtoken or old['lease']['until']>at or new['lease']['token']==oldtoken:raise Refused('not matching expired-token reacquisition')
 if not fencing.get('all_previous_koyo_writers_stopped') or not fencing.get('verification_reference'):raise Refused('fencing evidence required')
 if event.get('prior_lease')!=old['lease']:raise Refused('prior lease receipt mismatch')
 # Replay at recorded historical event time. This does not change the live clock,
 # renew a lease, or enable requests; current head/token are checked separately below.
 historical=copy.copy(worker.writer);historical.clock=lambda:at
 historical.authorize_transition(prior,accepted,'reacquire',oldtoken,fencing)
 historical.preservation(prior,accepted)
 head,current,_=worker.aggregate.read_state();require_ancestor(worker.aggregate,reacquired_head,head);worker.check(current)
 if current['koyo_index_handoffs'][key]['lease']['token']!=new['lease']['token']:raise Refused('another subsequent token change')
 if item['sha256']!=digest(item['payload']):raise Refused('stage integrity')
 adopted=copy.deepcopy(item);adopted['payload']['lease_token']=new['lease']['token'];adopted['sha256']=digest(adopted['payload'])
 # Exact current target dependencies and existing actual validators must still pass.
 def adoption_validator(b,a,op,token,p):
  context=b['koyo_index_handoffs'][key]['context'].get(p,{})
  if op=='save-row' and 'exploration_clock' in context and context['exploration_clock']['binding']['lease_token']!=token:
   validate_historical_sealed(worker,item,prior,prior_head,b,a,p,token)
  else:worker.validate(b,a,op,token,p)
 prepare(head,current,[adopted],adoption_validator,worker.clock())
 ticket={'key':key,'pid':pid,'source_stage_sha256':item['sha256'],'adopted_stage_sha256':adopted['sha256'],'prior_head':prior_head,'reacquired_head':reacquired_head,'review_reference':review_reference,'external_request_permitted':False}
 return adopted,ticket

def adopt(worker,item,prior_head,reacquired_head,review_reference):
 new,ticket=verify_adoption(worker,item,prior_head,reacquired_head,review_reference)
 if worker.archive.put(new)['status']!='accepted':raise Refused('adopted stage not durable')
 path='adoptions/'+ticket['key']+'--'+ticket['pid']+'--'+new['sha256']+'.json';text=canonical(ticket)
 old,c=worker.archive.snapshot();entries=worker.archive.entries(c['tree'])
 if path in entries:
  if worker.archive.contents(entries[path])!=text:raise Refused('adoption ticket collision')
  return new,ticket
 candidate=worker.archive.commit(old,c['tree'],{path:text},'Preserve verified stage fencing adoption')
 worker.archive.call('update_ref',worker.archive.gate.branch,old,candidate)
 _,c=worker.archive.snapshot();entries=worker.archive.entries(c['tree'])
 if path not in entries or worker.archive.contents(entries[path])!=text:raise Refused('adoption ticket unconfirmed')
 return new,ticket

def resolve_conflict(worker,pid,versions):
 head,c=worker.archive.snapshot();entries=worker.archive.entries(c['tree']);accepted=[]
 for path,entry in entries.items():
  if not path.startswith('adoptions/'+worker.key+'--'+pid+'--'):continue
  ticket=json.loads(worker.archive.contents(entry));old=next((v for v in versions if v['sha256']==ticket['source_stage_sha256']),None)
  if old is None:continue
  new,verified=verify_adoption(worker,old,ticket['prior_head'],ticket['reacquired_head'],ticket['review_reference'])
  if verified!=ticket or not any(v==new for v in versions):raise Refused('adoption ticket/stage mismatch')
  if any(v['sha256'] not in {old['sha256'],new['sha256']} for v in versions):raise Refused('unresolved additional stage variant')
  accepted.append(new)
 if len(accepted)!=1:raise Refused('no unique verified adoption')
 return accepted[0]

def validate_adopted_sealed(worker,before,after,pid,token):
 recovered=worker.archive.restore(worker.key);versions=recovered['conflicts'].get(pid)
 if not versions:raise Refused('no archived sealed adoption chain')
 adopted=resolve_conflict(worker,pid,versions)
 if adopted['payload']['lease_token']!=token or adopted['payload']['after']['rows']!=after['koyo_index_handoffs'][worker.key]['rows'][pid]:raise Refused('adopted result differs')
 # resolve_conflict revalidated full historical/current authority and exact target.
 from checkpoint import apply
 if apply(before,worker.key,pid,adopted['payload']['after'])!=after:raise Refused('outside adopted sealed result')
 return True
