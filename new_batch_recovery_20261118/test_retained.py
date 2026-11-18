import copy,unittest
from next_batch import *
from test_next_batch import S,K,H,NOW,HEAD,Next
def receipt():
 return {'version':'retained-responsibility-v1','source_head':HEAD,'plan_sha256':K,'owner':'koyo','lease_token':H['lease']['token'],'handoff_sha256':sha(H),'reserved_post_ids':H['plan']['payload']['source']['post_ids'],'research_disposition':None,'status':'operationally_paused','body_replay_allowed':False,'authorization_reference':'user retain unresolved and do disjoint work','all_previous_writers_stopped':True,'fencing_reference':'isolated fixture','checked_at':NOW,'unresolved':{p:{'reason':'uncertain_fetch_history' if p=='2096015385070039138' else 'unstarted_deferred','research_disposition':None,'context_sha256':sha(H['context'].get(p)),'events_sha256':sha(H['events'].get(p,[]))} for p in H['plan']['payload']['source']['post_ids'] if p not in H['rows']}}
class Retained(unittest.TestCase):
 def fixture(self):
  _,h,i=Next().fixtures();return h,i,receipt()
 def build(self,h,i,r):
  return prepare(S,HEAD,K,H['lease']['token'],NOW,'c'*32,h,i,'user continuing separate work',mode='retain-unresolved-and-claim',retention=r)
 def test_real_unfinished_can_create_disjoint_offline_claim(self):
  h,i,r=self.fixture();c=self.build(h,i,r);validate_candidate(c,S,HEAD,NOW+1);a=c['after']
  self.assertEqual(a['koyo_index_handoffs'][K],H)
  self.assertEqual(a['entries'][H['job_id']],S['entries'][H['job_id']])
  self.assertEqual(a['koyo_retained_work'][K]['unresolved']['2096015385070039138']['research_disposition'],None)
  with self.assertRaises(Refused):require_scheduler_permission(a,K)
  self.assertTrue(require_scheduler_permission(a,c['new_key']))
  new=a['koyo_index_handoffs'].pop(c['new_key']);a.pop('koyo_retained_work');a['entries'][new['job_id']]['status']='pending';self.assertEqual(a,S)
 def test_negative_retention(self):
  for kind in ('missing_post','fake_completion','replay','lease','owner','source','context','fence','stale','schema','wrong_plan'):
   with self.subTest(kind=kind):
    h,i,r=self.fixture();p=next(iter(r['unresolved']))
    if kind=='missing_post':r['unresolved'].pop(p)
    if kind=='fake_completion':r['research_disposition']='completed'
    if kind=='replay':r['body_replay_allowed']=True
    if kind=='lease':r['lease_token']='d'*32
    if kind=='owner':r['owner']='terra'
    if kind=='source':r['source_head']='d'*40
    if kind=='context':r['unresolved'][p]['context_sha256']='d'*64
    if kind=='fence':r['all_previous_writers_stopped']=False
    if kind=='stale':r['checked_at']=NOW-61
    if kind=='schema':r['status']='completed'
    if kind=='wrong_plan':r['reserved_post_ids']=r['reserved_post_ids'][1:]
    with self.assertRaises(Refused):self.build(h,i,r)
 def test_tampering_old_lease_or_hold_after_creation_denied(self):
  h,i,r=self.fixture();c=self.build(h,i,r);c['after']['koyo_index_handoffs'][K]['lease']['until']+=1
  with self.assertRaises(Refused):validate_candidate(c,S,HEAD,NOW+1)
if __name__=='__main__':unittest.main()
