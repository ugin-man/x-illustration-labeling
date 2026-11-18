import copy,unittest
from exploration import *
B={'plan_sha256':'a'*64,'post_id':'2090000000000000000','worker':'koyo','lease_token':'token'}
class ClockTests(unittest.TestCase):
 def setUp(self):self.a=Authority();self.s=new_clock(B)
 def act(self,kind,at,**kw):self.s=transition(self.s,{'kind':kind,'at':at,**kw},self.a);return self.s
 def reserve(self,rid,at,queries=None,kind='search'):return self.act('reserve',at,request_id=rid,request_kind=kind,queries=queries or ['q'])
 def ack(self,rid,at):
  p=self.a.verified_ack(B,rid,digest(self.s),'b'*40,at,acknowledged=True,readback_sha=digest(self.s));return self.act('acknowledge',at,request_id=rid,proof=p)
 def perform(self,rid,start,end):self.act('external_started',start,request_id=rid);self.act('external_finished',end,request_id=rid,result_sha256='c'*64)
 def test_trusted_wrapper_measures_actual_runner(self):
  wall=iter([105,110]);mono=iter([5,10]);calls=[]
  recorder=TrustedGitRecorder(self.a,lambda *args:calls.append(args) or 'read',lambda:next(wall),lambda:next(mono))
  self.assertEqual(recorder.run(B,'s','b'*40,'fetch','origin'),'read');self.assertEqual(len(recorder.proofs),1);self.assertEqual(recorder.proofs[0]['payload']['elapsed_seconds'],5)
  with self.assertRaises(Refused):recorder.run(B,'s','b'*40,'push','origin')
 def test_dispatch_wrapper_consumes_and_journals_before_tool(self):
  self.reserve('s',0);self.ack('s',100);calls=[]
  started,result=run_external_once(self.s,'s',100,self.a,lambda state:calls.append('journal'),lambda:calls.append('tool') or 'result')
  self.assertEqual(calls,['journal','tool']);self.assertEqual(result,'result')
  with self.assertRaises(Refused):run_external_once(self.s,'s',101,self.a,lambda state:None,lambda:'second')
 def test_failed_dispatch_journal_never_calls_tool(self):
  self.reserve('s',0);self.ack('s',100);calls=[]
  def fail(state):raise OSError('disk')
  with self.assertRaises(OSError):run_external_once(self.s,'s',100,self.a,fail,lambda:calls.append('tool'))
  self.assertEqual(calls,[])
  with self.assertRaises(Refused):run_external_once(self.s,'s',101,self.a,lambda state:None,lambda:calls.append('tool'))
 def test_reproduce_four_observed_v2_seals_without_modifying_them(self):
  import json
  from pathlib import Path
  path=Path('/tmp/koyo-replacement-prototype/live-final-state.json')
  if not path.exists():self.skipTest('historical snapshot absent')
  raw=path.read_bytes();snapshot=json.loads(raw);matched=0
  for key,h in snapshot['koyo_index_handoffs'].items():
   for pid,c in h['context'].items():
    old=c.get('exploration_clock',{});seal=old.get('seal')
    if old.get('version')!='koyo-exploration-clock-v2' or not seal:continue
    with self.subTest(post=pid):
     self.a=Authority();self.s=new_clock(B);self.reserve('s',c['budget']['started_at']);ack=max(x['ack_at'] for x in old['acks'].values());self.ack('s',ack)
     intervals=seal['management_proof']['payload']['intervals'];self.perform('s',ack,intervals[0]['started_at'])
     for interval in intervals:
      start,end=interval['started_at'],interval['ended_at'];p=self.a.measured_wait(B,'s','b'*40,interval['command'],start,end,end-start);self.act('management_read',end,proof=p)
     self.act('seal',seal['ended_at']);self.assertAlmostEqual(self.s['seal']['elapsed_seconds'],seal['elapsed_seconds'],places=5);matched+=1
  self.assertEqual(matched,4);self.assertEqual(path.read_bytes(),raw)
 def test_web_wait_counts_after_ack(self):
  self.reserve('s',0);self.ack('s',100);self.perform('s',100,112);self.act('seal',112)
  self.assertEqual(self.s['seal']['elapsed_seconds'],12);self.assertEqual(self.s['seal']['wall_seconds'],112)
 def test_multiple_requests_accumulate_and_exclude_only_saving(self):
  self.reserve('s',0);self.ack('s',100);self.perform('s',100,110)
  self.reserve('p',115,['https://example.test'],'page');self.ack('p',200);self.perform('p',200,210);self.act('seal',212)
  self.assertEqual(self.s['seal']['elapsed_seconds'],27);self.assertEqual(self.s['searches'],1);self.assertEqual(self.s['pages'],1)
 def test_long_tool_finishes_but_new_request_denied(self):
  self.reserve('s',0);self.ack('s',100);self.perform('s',100,170)
  with self.assertRaises(Refused):self.reserve('p',170,['url'],'page')
  self.act('seal',170);self.assertEqual(self.s['seal']['elapsed_seconds'],70)
 def test_two_query_terms_count_two(self):
  self.reserve('s',0,['q1','q2']);self.ack('s',100);self.perform('s',100,101)
  with self.assertRaises(Refused):self.reserve('s2',102)
 def test_three_page_limit(self):
  for i in range(3):self.reserve(str(i),i*10,['url'],'page');self.ack(str(i),i*10+1);self.perform(str(i),i*10+1,i*10+2)
  with self.assertRaises(Refused):self.reserve('four',31,['url'],'page')
 def test_idle_after_ack_consumes_budget(self):
  self.reserve('s',0);self.ack('s',100)
  with self.assertRaises(Refused):self.act('external_started',160,request_id='s')
 def test_clock_rollback(self):
  self.reserve('s',100);self.ack('s',140)
  with self.assertRaises(Refused):self.act('external_started',110,request_id='s')
 def test_pending_ambiguous_never_repeats(self):
  self.reserve('s',0)
  with self.assertRaises(Refused):self.reserve('s2',100)
  with self.assertRaises(Refused):self.act('seal',100)
  with self.assertRaises(Refused):self.a.verified_ack(B,'s',digest(self.s),'b'*40,100,acknowledged=False,readback_sha=digest(self.s))
 def test_restart_loses_permission(self):
  self.reserve('s',0);self.ack('s',100);self.a=Authority()
  with self.assertRaises(Refused):self.act('external_started',101,request_id='s')
 def test_external_once(self):
  self.reserve('s',0);self.ack('s',100);self.act('external_started',100,request_id='s')
  with self.assertRaises(Refused):self.act('external_started',101,request_id='s')
 def test_untrusted_wait_recomputed_sha_rejected(self):
  self.reserve('s',0);self.ack('s',100);self.perform('s',100,105)
  p=self.a.measured_wait(B,'s','b'*40,'fetch',105,110,5);p['payload']['started_at']=100;p['sha256']=digest(p['payload'])
  with self.assertRaises(Refused):self.act('management_read',110,proof=p)
 def test_wait_cannot_cover_external_call(self):
  self.reserve('s',0);self.ack('s',100);self.perform('s',100,110)
  p=self.a.measured_wait(B,'s','b'*40,'fetch',105,115,10)
  with self.assertRaises(Refused):self.act('management_read',115,proof=p)
 def test_wrong_bound_head_and_token(self):
  self.reserve('s',0);self.ack('s',100);self.perform('s',100,105)
  for binding,head in [(dict(B,lease_token='wrong'),'b'*40),(B,'d'*40)]:
   p=self.a.measured_wait(binding,'s',head,'fetch',105,110,5)
   with self.assertRaises(Refused):self.act('management_read',110,proof=p)
 def test_union_not_double_deducted(self):
  self.reserve('s',0);self.ack('s',100);self.perform('s',100,105)
  p=self.a.measured_wait(B,'s','b'*40,'fetch',105,110,5);self.act('management_read',110,proof=p)
  p=self.a.measured_wait(B,'s','b'*40,'ls-remote',108,113,5);self.act('management_read',113,proof=p)
  self.act('seal',115);self.assertEqual(self.s['seal']['elapsed_seconds'],7)
 def test_bad_monotonic_and_command(self):
  with self.assertRaises(Refused):self.a.measured_wait(B,'s','b'*40,'web-search',0,10,10)
  with self.assertRaises(Refused):self.a.measured_wait(B,'s','b'*40,'fetch',0,10,1)
 def test_seal_immutable(self):
  self.reserve('s',0);self.ack('s',100);self.perform('s',100,105);self.act('seal',105)
  with self.assertRaises(Refused):self.act('seal',106)
 def test_existing_legacy_not_reset(self):
  old={'budget':{'started_at':1},'exploration_clock':{'version':'koyo-exploration-clock-v2','seal':{'elapsed_seconds':4.35}}};saved=copy.deepcopy(old)
  with self.assertRaises(Refused):new_clock(B,old)
  self.assertEqual(old,saved)
 def test_writer_replay_rejects_budget_edit(self):
  e={'kind':'reserve','at':0,'request_id':'s','request_kind':'search','queries':['one','two']};after=transition(self.s,e,self.a);self.assertTrue(validate_transition(self.s,e,after,self.a));after['searches']=1
  with self.assertRaises(Refused):validate_transition(self.s,e,after,self.a)
 def test_writer_validation_does_not_consume_permission(self):
  self.reserve('s',0);self.ack('s',100);event={'kind':'external_started','at':100,'request_id':'s'};clone=copy.copy(self.a);clone._used=set(self.a._used);after=transition(self.s,event,clone)
  self.assertTrue(validate_transition(self.s,event,after,self.a));self.act('external_started',100,request_id='s')
if __name__=='__main__':unittest.main(verbosity=2)
