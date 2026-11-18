import copy,unittest
from test_current_batch_scope import Scope,S,K,H,PLAN,NOW
from runtime_components import PinnedInputs
from recovery_adapter import Refused
class Finalize(Scope):
 def fixture(self):
  pid=PLAN[18];before=self.reserve(pid);after=copy.deepcopy(before);h=after['koyo_index_handoffs'][K]
  pins=PinnedInputs('/tmp/x-recovery-isolated',h);post=pins.posts[pid]
  cache=copy.deepcopy(H['context'][PLAN[17]]['cache']);cache['post_id']=pid;h['context'][pid]['cache']=cache
  row=copy.deepcopy(H['rows'][PLAN[17]]);row['post_id']=pid
  row['images']=[dict(copy.deepcopy(row['images'][0]),media_index=im['media_index'],sha256=im['sha256']) for im in post['images']]
  h['rows'][pid]=row
  h['events'][pid]=[{'post_id':pid,'media_index':im['media_index'],'sha256':im['sha256'],'outcome':'viewed','tool':'fixture-only','tool_call_id':'isolated-not-real','at':'fixture'} for im in post['images']]
  return before,after,pid
 def checkfinal(self,b,a):
  self.w.authorize_transition(b,a,'finalize-post',H['lease']['token']);self.w.preservation(b,a)
 def test_finalize_one_local_cas_readback(self):
  from runtime_components import LocalGitTransport
  b,a,p=self.fixture()
  t=LocalGitTransport(self.tmp.name);head=t.commit(b);t.git('update-ref','refs/heads/codex/jobs/production-v4-001/dispatch-index',head)
  self.w.live=False
  result=self.w.publish(head,b,a,operation='finalize-post',lease_token=H['lease']['token'])
  self.assertTrue(result['external_request_permitted']);self.assertEqual(self.w.read()[1],a)
  self.assertEqual(a['entries'],b['entries'])
  self.assertEqual({pid:a['koyo_index_handoffs'][K]['rows'][pid] for pid in H['rows']},H['rows'])
 def test_finalize_sourcefailure_success(self):
  b,a,p=self.fixture();self.checkfinal(b,a)
 def test_finalize_noleads_success(self):
  b,a,p=self.fixture();h=a['koyo_index_handoffs'][K];h['context'][p]['cache']={'post_id':p,'state':'available','text':'fixture'}
  c=h['rows'][p]['context'];c.update(state='complete',stop_reason='no_leads')
  for v in c['attributes'].values():v.update(status='unknown',value=None,reason='isolated fixture',sources=[])
  self.checkfinal(b,a)
 def test_finalize_negative_mutations(self):
  for kind in ('missing_reservation','preexisting_cache','no_image','wrong_image','cross_post','terra','baseline','exploration','lease','failure_as_noleads','missing_row','cache_edit'):
   with self.subTest(kind=kind):
    b,a,p=self.fixture();bh=b['koyo_index_handoffs'][K];h=a['koyo_index_handoffs'][K]
    if kind=='missing_reservation':del bh['context'][p]
    elif kind=='preexisting_cache':bh['context'][p]['cache']=copy.deepcopy(h['context'][p]['cache'])
    elif kind=='no_image':h['events'].pop(p)
    elif kind=='wrong_image':h['events'][p][0]['post_id']=PLAN[19]
    elif kind=='cross_post':h['context'][PLAN[19]]={'fetch_started':NOW}
    elif kind=='terra':a['entries']['prod-0049']['worker_id']='koyo'
    elif kind=='baseline':h['rows'][PLAN[0]]['review_flags'].append('bad')
    elif kind=='exploration':h['context'][p]['budget']={}
    elif kind=='lease':h['lease']['until']+=100
    elif kind=='failure_as_noleads':h['rows'][p]['context']['stop_reason']='no_leads'
    elif kind=='missing_row':h['rows'].pop(p)
    elif kind=='cache_edit':h['context'][p]['fetch_started']+=1
    with self.assertRaises((Refused,AssertionError)):self.checkfinal(b,a)
 def test_finalize_held17_refused(self):
  b,a,p=self.fixture()
  for field in ('context','events','rows'):
   for state in (b,a):
    d=state['koyo_index_handoffs'][K][field]
    if p in d:d[PLAN[16]]=d.pop(p)
  with self.assertRaises((Refused,AssertionError)):self.checkfinal(b,a)
if __name__=='__main__':unittest.main()
