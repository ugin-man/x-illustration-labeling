import copy
import test_protocol_bridge as fixture
from test_protocol_bridge import ProtocolTests
from host_bridge import HostBridge
from exploration import Refused
from persistent_runner import get_path
from prepare_live_activation import build
from protocol_bridge import LiveClockGuard
class HostTests(ProtocolTests):
 def setUp(self):
  super().setUp();self.binding=copy.deepcopy(fixture.B)
  # Fake actual-image events ONLY for validator fixtures, never production evidence.
  from runtime_components import PinnedInputs
  h=self.state['koyo_index_handoffs'][self.key];post=PinnedInputs('/tmp/x-recovery-isolated',h).posts[self.binding['post_id']]
  h['events'][self.binding['post_id']]=[{'post_id':self.binding['post_id'],'media_index':i['media_index'],'sha256':i['sha256'],'outcome':'viewed','tool':'TEST_FIXTURE','tool_call_id':'FAKE_ONLY','at':'2026-11-17T20:00:00+00:00'} for i in post['images']]
  activation,config=build(self.state,self.head,self.binding,'ISOLATED MOCK REVIEW ONLY','/tmp/x-recovery-isolated',self.path[0])
  self.guard=LiveClockGuard('/tmp/x-recovery-isolated',activation);self.host=HostBridge(self.store,self.base,self.guard,self.binding,lambda:self.t)
 def transport(self,e,lost=False):
  p=e['payload'];self.tree(p);commit=self.io.fetch_commit(self.candidate);params=self.host.pre_ref(commit)
  self.lost=lost;ack=False
  try:ack=self.update(params)
  except TimeoutError:pass
  return self.host.acknowledge(ack)
 def search(self,rid,kind='search'):
  self.transport(self.host.prepare(rid,kind,['fixture']));intent=self.host.claim(rid);result=self.tool(kind,intent['queries']);self.host.finish(rid,intent['intent_sha256'],result)
 def row(self):
  from runtime_components import PinnedInputs,provenance
  from pipeline_production.contract_v4 import template,answer,COUNT_FIELDS
  h=self.state['koyo_index_handoffs'][self.key];p=PinnedInputs('/tmp/x-recovery-isolated',h).posts[self.binding['post_id']];r=template(p,provenance(h),'koyo')
  r['execution']['finished_at']=r['execution']['started_at'];r['character_coverage']='complete'
  for im in r['images']:
   im['viewed']=True
   im['attributes']={k:answer('not_applicable',None,'fixture') for k in im['attributes']}
   im['attributes']['content_kind']=answer('observed','photo',evidence='FIXTURE, not actual classification')
   im['attributes']['illustration_present']=answer('observed',False,evidence='FIXTURE')
  for k in COUNT_FIELDS:r[k]=answer('observed',0,evidence='FIXTURE')
  r['post_attributes']={k:answer('not_applicable',None,'fixture') for k in r['post_attributes']}
  r['context']['attributes']={k:answer('not_applicable',None,'fixture') for k in r['context']['attributes']}
  r['context'].update(state='complete',stop_reason='not_applicable')
  seal=get_path(self.state,self.path)['seal']
  for k in ('searches','pages','elapsed_seconds'):r['context'][k]=seal[k]
  return r
 def test_host_five_calls_seal_fixed_row(self):
  for i,k in enumerate(['search','search','page','page','page']):self.search(str(i),k)
  self.transport(self.host.prepare_seal());row=self.row();self.transport(self.host.prepare_row(row));self.assertEqual(self.state['koyo_index_handoffs'][self.key]['rows'][self.binding['post_id']],row)
  self.assertEqual(row['context']['elapsed_seconds'],10)
 def test_host_lost_ack_no_claim(self):
  with self.assertRaises(Refused):self.transport(self.host.prepare('s','search',['q']),lost=True)
  with self.assertRaises(Refused):self.host.claim('s')
 def test_host_claim_once_across_restart(self):
  self.transport(self.host.prepare('s','search',['q']));self.host.claim('s')
  self.store.close();from persistent_runner import Store
  self.store=Store(self.tmp.name+'/db');self.host.store=self.store
  with self.assertRaises(Refused):self.host.claim('s')
 def test_host_fixed_row_wrong_elapsed(self):
  self.search('s');self.transport(self.host.prepare_seal());r=self.row();r['context']['elapsed_seconds']+=1
  with self.assertRaises(Refused):self.host.prepare_row(r)
 def test_host_row_without_image_event(self):
  self.search('s');self.transport(self.host.prepare_seal());r=self.row();self.state['koyo_index_handoffs'][self.key]['events'][self.binding['post_id']]=[]
  from recovery_adapter import Refused as ContractRefused
  with self.assertRaises((Refused,ValueError,ContractRefused)):self.host.prepare_row(r)

 def test_tool_error_outcome_and_unknown_row_rejected(self):
  self.transport(self.host.prepare('s','search',['fixture']));intent=self.host.claim('s')
  self.host.finish('s',intent['intent_sha256'],{'isError':True,'content':[{'type':'text','text':'fixture unavailable'}]})
  self.transport(self.host.prepare_seal());r=self.row()
  from pipeline_production.contract_v4 import answer
  r['context']['attributes']['creation']=answer('unknown',None,'missing evidence')
  with self.assertRaises(Refused):self.host.prepare_row(r)
  r['context']['attributes']['creation']=answer('technical_failure',None,'required source unavailable')
  r['context'].update(state='technical_failure',stop_reason='tool_unavailable')
  # Synthetic non-illustration fixture makes context not_applicable mandatory;
  # verify R14 gate independently, full contract correctly rejects this row.
  with self.assertRaises(AssertionError):self.host.prepare_row(r)
 def test_tool_error_unnecessary_evidence_preserved(self):
  self.transport(self.host.prepare('s','search',['fixture']));intent=self.host.claim('s');self.host.finish('s',intent['intent_sha256'],{'isError':True})
  self.transport(self.host.prepare_seal());r=self.row();self.transport(self.host.prepare_row(r))
  self.assertEqual(get_path(self.state,self.path)['requests']['s']['result_state'],'technical_failure')
