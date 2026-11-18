import copy,json,unittest,sys
sys.path.insert(0,'/tmp/x-recovery-isolated')
from next_batch import *
S=json.load(open('/tmp/koyo-current-batch-candidate/live-final-state.json'));K=next(k for k,h in S['koyo_index_handoffs'].items() if h['job_id']=='prod-0002');H=S['koyo_index_handoffs'][K];NOW=H['lease']['until']-100;HEAD='a'*40
def full_fixture():
 s=copy.deepcopy(S);h=s['koyo_index_handoffs'][K];pins=PinnedInputs(ROOT,h);template=h['plan']['payload']['source']['post_ids'][17]
 for pid in h['plan']['payload']['source']['post_ids']:
  if pid in h['rows']:continue
  row=copy.deepcopy(h['rows'][template]);row['post_id']=pid;post=pins.posts[pid]
  row['images']=[dict(copy.deepcopy(row['images'][0]),media_index=i['media_index'],sha256=i['sha256']) for i in post['images']]
  for ch in row['characters']:ch['appearances']=[dict(copy.deepcopy(ch['appearances'][0]),media_index=i['media_index']) for i in post['images']]
  h['rows'][pid]=row;h['context'][pid]=copy.deepcopy(h['context'][template]);h['context'][pid]['cache']['post_id']=pid
  h['events'][pid]=[{'post_id':pid,'media_index':i['media_index'],'sha256':i['sha256'],'outcome':'viewed','tool':'fixture','tool_call_id':'isolated-only'} for i in post['images']]
 return s
class Next(unittest.TestCase):
 def fixtures(self):
  s=full_fixture();ids,jobs=next_candidates(s);jid=ids[0]
  hist={'source_head':HEAD,'job_id':jid,'complete_ancestry':True,'verified_commit_count':1,'ever_touched':False,'ancestry_sha256':'b'*64}
  inv={'source_head':HEAD,'job_id':jid,'post_ids':jobs[jid]['post_ids'],'job_branch_exists':False,'unshared_work':[],'active_writers':[],'pending_journals':[],'coverage_reference':'ISOLATED FIXTURE ONLY','checked_at':NOW}
  return s,hist,inv
 def build(self,s,h,i):return prepare(s,HEAD,K,H['lease']['token'],NOW,'c'*32,h,i,'user ongoing next50; fixture')
 def test_current_real_snapshot_blocked(self):
  s,h,i=self.fixtures()
  with self.assertRaises(Refused):self.build(S,h,i)
 def test_valid_candidate_and_protection(self):
  s,h,i=self.fixtures();c=self.build(s,h,i);self.assertTrue(validate_candidate(c,s,HEAD,NOW+1));a=c['after'];new=a['koyo_index_handoffs'].pop(c['new_key']);a['koyo_index_handoffs'][K]['status']='leased';a['entries'][new['job_id']]['status']='pending';self.assertEqual(a,s)
 def test_rejections(self):
  for kind in ('hold','cache','image','lease','history','branch','unshared','writer','journal','stale_inventory','prior_active'):
   with self.subTest(kind=kind):
    s,h,i=self.fixtures();p=H['plan']['payload']['source']['post_ids'][16]
    if kind=='hold':s['koyo_index_handoffs'][K]['rows'].pop(p)
    if kind=='cache':s['koyo_index_handoffs'][K]['context'][p].pop('cache')
    if kind=='image':s['koyo_index_handoffs'][K]['events'][p]=[]
    if kind=='lease':s['koyo_index_handoffs'][K]['lease']['until']=NOW
    if kind=='history':h['ever_touched']=True
    if kind=='branch':i['job_branch_exists']=True
    if kind=='unshared':i['unshared_work']=['unpublished result']
    if kind=='writer':i['active_writers']=['terra']
    if kind=='journal':i['pending_journals']=['not reconciled']
    if kind=='stale_inventory':i['checked_at']=NOW-61
    if kind=='prior_active':s['koyo_index_handoffs'][next(k for k in s['koyo_index_handoffs'] if k!=K)]['status']='leased'
    with self.assertRaises(Refused):self.build(s,h,i)
 def test_tamper_stale_and_live_denial(self):
  s,h,i=self.fixtures();c=self.build(s,h,i)
  with self.assertRaises(Stale):validate_candidate(c,s,'d'*40,NOW+1)
  with self.assertRaises(Refused):validate_candidate(c,s,HEAD,NOW+61)
  c['after']['entries']['prod-0049']['worker_id']='koyo'
  with self.assertRaises(Refused):validate_candidate(c,s,HEAD,NOW+1)
  with self.assertRaises(Refused):live_publish(c)
if __name__=='__main__':unittest.main()
