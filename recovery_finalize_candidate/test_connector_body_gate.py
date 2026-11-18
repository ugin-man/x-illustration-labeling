from contextlib import nullcontext
import sys,json,tempfile,shutil,copy,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,'/tmp/x-recovery-isolated')
import connector_bridge as b
from recovery_adapter import sha,Refused
from runtime_components import digest
S=json.load(open(Path(__file__).with_name('live-final-state.json')));K=next(k for k,h in S['koyo_index_handoffs'].items() if h['job_id']=='prod-0002');H=S['koyo_index_handoffs'][K];PLAN=H['plan']['payload']['source']['post_ids'];PID=PLAN[18];OTHER=PLAN[19]
class Gate(unittest.TestCase):
 def fixture(self,ack,permit):
  temp=tempfile.TemporaryDirectory();base=Path(temp.name)
  for name in ('connector_protocol.py','connector_bridge.py','connector_transport.js','pack_compressed.py'):shutil.copy(b.BASE/name,base/name)
  payload={'plan_sha256':K,'scope':{'kind':'current-batch-prod-0002-v1','post_ids':PLAN[18:],'held_post_ids':[PLAN[16]]},'code_sha256':{str((base/f).resolve()):digest(base/f) for f in ('connector_protocol.py','connector_bridge.py','connector_transport.js','pack_compressed.py')}}
  (base/'connector-activation.json').write_text(json.dumps({'payload':payload}));(base/'current-batch-baseline.json').write_text(json.dumps(S))
  state=copy.deepcopy(S);state['koyo_index_handoffs'][K]['context'][PID]={'fetch_started':1,'recovery_revision':'recovery-prototype-1','attempt_limit':1}
  f=base/'connector-outbox'/PID/('body-reserve-'+'a'*32);f.mkdir(parents=True)
  ep={'target_post_id':PID,'state_sha256':sha(state),'operation':'body-reserve'};eh=sha(ep)
  (f/'envelope.json').write_text(json.dumps({'sha256':eh,'payload':ep}));(f/'receipt.json').write_text(json.dumps({'target_post_id':PID,'envelope_sha256':eh,'operation':'body-reserve','external_request_permitted':permit,'ref_update_acknowledged':ack,'candidate':'head'}))
  out=base/'post-runtime'/PID/'outboxes';out.mkdir(parents=True);(out/'body-reserve.json').write_text(json.dumps({'folder':str(f),'envelope_sha256':eh}))
  class W:
   def __init__(self,*args,**kw):pass
   def close(self):pass
   def read(self):return 'head',state
   def clock(self):return H['lease']['until']-100
  return temp,base,W
 def invoke(self,base,W,calls,pid=PID):
  def factory(*args):
   def run(post):calls.append(post);return {'post_id':post,'state':'technical_failure','text':None}
   return run
  with patch.object(b,'local_lock',lambda *args:nullcontext()),patch.object(b,'BASE',base),patch.object(b,'IndexWriter',W),patch.object(sys,'argv',['bridge','fetch-body',pid]),patch.object(b,'pinned_body_fetcher',factory):b.main()
 def test_failed_ack_cannot_fetch_even_if_accepted(self):
  temp,base,W=self.fixture(False,True);calls=[]
  try:
   with self.assertRaises(Refused):self.invoke(base,W,calls)
   self.assertEqual(calls,[])
  finally:temp.cleanup()
 def test_acknowledged_fetch_once_and_perpost_journal(self):
  temp,base,W=self.fixture(True,True);calls=[]
  try:
   self.invoke(base,W,calls)
   with self.assertRaises(Refused):self.invoke(base,W,calls)
   self.assertEqual(calls,[PID]);self.assertTrue((base/'post-runtime'/PID/'body-stage.json').exists());self.assertFalse((base/'post-runtime'/OTHER/'body-stage.json').exists())
  finally:temp.cleanup()
 def test_cross_post_receipt_refused(self):
  temp,base,W=self.fixture(True,True);calls=[]
  try:
   target=base/'post-runtime'/OTHER/'outboxes';target.mkdir(parents=True);shutil.copy(base/'post-runtime'/PID/'outboxes/body-reserve.json',target/'body-reserve.json')
   with self.assertRaises(Refused):self.invoke(base,W,calls,OTHER)
   self.assertEqual(calls,[])
  finally:temp.cleanup()
 def test_held17_refused_before_fetch(self):
  temp,base,W=self.fixture(True,True);calls=[]
  try:
   with self.assertRaises(Refused):self.invoke(base,W,calls,PLAN[16])
   self.assertEqual(calls,[])
  finally:temp.cleanup()
if __name__=='__main__':unittest.main(verbosity=2)
