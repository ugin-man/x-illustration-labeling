import sys,json,tempfile,shutil,copy,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,'/tmp/x-recovery-isolated')
import connector_bridge as b
from recovery_adapter import sha,Refused
from runtime_components import digest
S=json.load(open('/tmp/x-state-recovery.json'));K=next(k for k,h in S['koyo_index_handoffs'].items() if h['job_id']=='prod-0002');H=S['koyo_index_handoffs'][K]
class Gate(unittest.TestCase):
 def fixture(self,ack,permit):
  temp=tempfile.TemporaryDirectory();base=Path(temp.name)
  for name in ('connector_protocol.py','connector_bridge.py','connector_transport.js'):shutil.copy(b.BASE/name,base/name)
  payload={'plan_sha256':K,'code_sha256':{str((base/f).resolve()):digest(base/f) for f in ('connector_protocol.py','connector_bridge.py','connector_transport.js')}}
  (base/'connector-activation.json').write_text(json.dumps({'payload':payload}));(base/'live-preflight-state.json').write_text(json.dumps(S))
  f=base/'connector-outbox/body-reserve';f.mkdir(parents=True)
  (f/'envelope.json').write_text(json.dumps({'sha256':'envelope','payload':{'state_sha256':sha(S)}}));(f/'receipt.json').write_text(json.dumps({'envelope_sha256':'envelope','operation':'body-reserve','external_request_permitted':permit,'ref_update_acknowledged':ack,'candidate':'head'}))
  class W:
   def __init__(self,*args,**kw):pass
   def close(self):pass
   def read(self):return 'head',S
   def clock(self):return H['lease']['until']-100
  return temp,base,W
 def test_failed_ack_cannot_fetch_even_if_remote_accepted(self):
  temp,base,W=self.fixture(False,True);calls=[]
  try:
   with patch.object(b,'BASE',base),patch.object(b,'IndexWriter',W),patch.object(sys,'argv',['bridge','fetch-body']),patch.object(b,'pinned_body_fetcher',lambda *a:lambda pid:calls.append(pid)):
    with self.assertRaises(Refused):b.main()
   self.assertEqual(calls,[])
  finally:temp.cleanup()
 def test_acknowledged_fetch_once_and_restart_blocked(self):
  temp,base,W=self.fixture(True,True);calls=[]
  def factory(*args):
   def run(pid):calls.append(pid);return {'post_id':pid,'state':'technical_failure','text':None}
   return run
  try:
   with patch.object(b,'BASE',base),patch.object(b,'IndexWriter',W),patch.object(sys,'argv',['bridge','fetch-body']),patch.object(b,'pinned_body_fetcher',factory):
    b.main()
    with self.assertRaises(Refused):b.main()
   self.assertEqual(len(calls),1)
  finally:temp.cleanup()
if __name__=='__main__':unittest.main(verbosity=2)
