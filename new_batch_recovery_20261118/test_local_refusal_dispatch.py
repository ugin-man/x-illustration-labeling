import json,shutil
from pathlib import Path
from test_connector_body_gate import Gate,PID,S,H
from runtime_components import digest,PinnedInputs,provenance
from recovery_adapter import sha,Refused
from pipeline_production import disposition
class RefusalDispatch(Gate):
 def test_existing_ack_does_not_bypass_local_refusal(self):
  temp,base,W=self.fixture(True,True);calls=[]
  try:
   import connector_bridge as b
   from new_batch_scope import FILES
   for f in FILES:shutil.copy(b.BASE/f,base/f)
   d=json.loads((base/'connector-activation.json').read_text());p=d['payload'];p['scope']['kind']='new-claimed-batch-v1';p['source_state_sha256']=sha(S);p['baseline_handoff']=H;p['code_sha256'][str((base/'new_batch_scope.py').resolve())]=digest(base/'new_batch_scope.py')
   p['mode']='reviewed-live';p['review_reference']='ISOLATED test';p['code_sha256']={str((base/f).resolve()):digest(base/f) for f in FILES}
   for f in ('pipeline_production/isolation.py','pipeline_production/disposition.py'):p['code_sha256'][str((Path('/tmp/x-recovery-isolated')/f).resolve())]=digest(Path('/tmp/x-recovery-isolated')/f)
   folder=base/'refusals';folder.mkdir();p['image_gate']={'local_refusal_dir':str(folder)}
   row=disposition.create(PinnedInputs('/tmp/x-recovery-isolated',H).posts[PID],provenance(H),'koyo','image_tool_refusal',1);(folder/(PID+'.json')).write_text(json.dumps(row));d['sha256']=sha(p);(base/'connector-activation.json').write_text(json.dumps(d))
   with self.assertRaisesRegex(Refused,'policy refusal'):self.invoke(base,W,calls)
   self.assertEqual(calls,[]);self.assertFalse((base/'post-runtime'/PID/'body-stage.json').exists())
  finally:temp.cleanup()
