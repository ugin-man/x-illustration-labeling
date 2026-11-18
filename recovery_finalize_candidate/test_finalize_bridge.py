from contextlib import nullcontext
import copy,json,sys,unittest
from unittest.mock import patch
from test_connector_body_gate import Gate,PID,OTHER,K,H
from recovery_adapter import sha,Refused
import connector_bridge as b
class BridgeFinalize(unittest.TestCase):
 def run_fixture(self,bad=None):
  helper=Gate();temp,base,W=helper.fixture(True,True);d=base/'post-runtime'/PID
  try:
   cache={'post_id':PID,'state':'technical_failure','text':None}
   stage={'post_id':PID,'status':'result-staged','cache':cache}
   receipts=[{'post_id':PID,'media_index':1,'sha256':'a'*64,'tool':'fixture','tool_call_id':'fixture','at':'fixture'}]
   row={'post_id':PID}
   if bad=='stage':stage['post_id']=OTHER
   if bad=='receipt':receipts[0]['post_id']=OTHER
   if bad=='row':row['post_id']=OTHER
   b.put(d/'body-stage.json',stage);b.put(d/'view-receipts.json',receipts);b.put(d/'row-final.json',row)
   captured=[]
   class Pins:
    def __init__(self,*args):self.posts={PID:{'images':[{'media_index':1,'sha256':'a'*64,'path':'fixture'}]}}
    def image_event(self,pid,index,path,receipt):return dict(receipt,outcome='viewed')
   def envelope(w,head,before,after,op,token,fence):
    captured.append((op,after))
    payload={'target_post_id':PID};return {'payload':payload,'sha256':sha(payload)}
   with patch.object(b,'local_lock',lambda *args:nullcontext()),patch.object(b,'BASE',base),patch.object(b,'IndexWriter',W),patch.object(b,'PinnedInputs',Pins),patch.object(b,'envelope',envelope),patch.object(b,'pack_envelope',lambda *args:{}),patch.object(sys,'argv',['bridge','prepare','finalize-post',PID]):b.main()
   op,after=captured[0];h=after['koyo_index_handoffs'][K]
   self.assertEqual(op,'finalize-post');self.assertEqual(h['context'][PID]['cache'],cache);self.assertEqual(h['rows'][PID],row);self.assertEqual(len(h['events'][PID]),1)
   self.assertTrue((d/'outboxes/finalize-post.json').exists())
  finally:temp.cleanup()
 def test_all_three_in_single_envelope(self):self.run_fixture()
 def test_cross_post_inputs_rejected(self):
  for kind in ('stage','receipt','row'):
   with self.subTest(kind=kind),self.assertRaises(Refused):self.run_fixture(kind)
if __name__=='__main__':unittest.main()
