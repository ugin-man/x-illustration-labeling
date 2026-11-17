import copy,json,sys,tempfile,subprocess,unittest
from pathlib import Path
sys.path.insert(0,'/tmp/x-recovery-isolated')
from connector_protocol import *
from network_runtime import IndexWriter,lease_transition
from runtime_components import LocalGitTransport
S=json.load(open('/tmp/x-state-recovery.json'));K=next(k for k,h in S['koyo_index_handoffs'].items() if h['job_id']=='prod-0002');H=S['koyo_index_handoffs'][K];NOW=H['lease']['until']-100
class Tests(unittest.TestCase):
 def test_full_connector_shape_local_rehearsal(self):
  with tempfile.TemporaryDirectory() as d:
   remote=Path(d)/'remote.git';subprocess.run(['git','init','--bare',str(remote)],capture_output=True,check=True);t=LocalGitTransport(remote);head=t.commit(S);t.git('update-ref','refs/heads/'+BRANCH,head)
   w=IndexWriter(str(remote),S['catalog_sha256'],K,'/tmp/x-recovery-isolated',clock=lambda:NOW)
   try:
    after=lease_transition(S,K,H['lease']['token'],NOW);e=envelope(w,head,S,after,'renew',H['lease']['token']);self.assertEqual(validate_envelope(w,e,S),after)
    bad=copy.deepcopy(e);bad['payload']['state_json_content']+=' '
    with self.assertRaises(Refused):validate_envelope(w,bad,S)
    # Simulated connector tree+commit preserving one parent. No remote network invocation.
    candidate=t.commit(after,head);tree=t.git('show','-s','--format=%T',candidate).stdout.decode().strip();self.assertEqual(tree,e['payload']['candidate_tree_sha'])
    validate_commit(e,{'tree':{'sha':tree},'parents':[{'sha':head}]})
    params=pre_update_ref(w,e,S,{'sha':candidate,'tree':{'sha':tree},'parents':[{'sha':head}]});self.assertEqual(params['expected_sha'],head);self.assertFalse(params['force'])
    with self.assertRaises(Refused):validate_commit(e,{'tree':{'sha':tree},'parents':[{'sha':'wrong'}]})
    self.assertFalse(readback(w,e,candidate)['accepted'])
    t.git('update-ref','refs/heads/'+BRANCH,candidate,head);self.assertTrue(readback(w,e,candidate)['accepted'])
    observed=readback(w,e,candidate);self.assertFalse(execution_receipt(e,candidate,False,observed)['external_request_permitted']);self.assertTrue(execution_receipt(e,candidate,True,observed)['external_request_permitted'])
    self.assertEqual(readback(w,e,candidate)['state']['entries'],S['entries'])
    m=pack_envelope(e,Path(d)/'chunks');raw=b''.join((Path(d)/'chunks'/('%04d.txt'%i)).read_bytes() for i in range(m['chunks']));self.assertEqual(hashlib.sha256(raw).hexdigest(),m['sha256']);self.assertEqual(json.loads(raw),e)
   finally:w.close()
if __name__=='__main__':unittest.main(verbosity=2)
