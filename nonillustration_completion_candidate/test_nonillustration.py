"""ISOLATED tests, actual accepted snapshot is read-only fixture. No remote I/O."""
import sys,json,copy,tempfile,subprocess,unittest
from pathlib import Path
sys.path.insert(0,'/tmp/x-recovery-isolated')
from network_runtime import IndexWriter,Refused,sha
from runtime_components import digest
BASE=Path(__file__).parent;LIVE=Path('/tmp/koyo-current-batch-candidate');PID='2097010804503847365';ROOT='/tmp/x-recovery-isolated'
E=json.load(open(LIVE/'connector-outbox'/PID/'image-event-91c79c8d751f426c89a7c8f28758107b/envelope.json'))
S=json.loads(E['payload']['state_json_content']);DOC=json.load(open(LIVE/'connector-activation.json'));K=DOC['payload']['plan_sha256'];ROW=json.load(open(LIVE/'post-runtime'/PID/'row-final.json'))
class NonIllustration(unittest.TestCase):
 def setUp(self):
  self.b=copy.deepcopy(S);self.a=copy.deepcopy(S);self.h=self.a['koyo_index_handoffs'][K];self.h['rows'][PID]=copy.deepcopy(ROW)
  self.tmp=tempfile.TemporaryDirectory();subprocess.run(['git','init','--bare',self.tmp.name],check=True,capture_output=True)
  d=copy.deepcopy(DOC);pins=d['payload']['code_sha256'];d['payload']['code_sha256']={str(BASE/Path(f).name) if Path(f).parent==LIVE else f:digest(BASE/Path(f).name) if Path(f).parent==LIVE else v for f,v in pins.items()};d['sha256']=sha(d['payload'])
  self.w=IndexWriter(self.tmp.name,S['catalog_sha256'],K,ROOT,clock=lambda:self.b['koyo_index_handoffs'][K]['lease']['until']-100,activation_document=d);self.w.live=True
 def tearDown(self):self.w.close();self.tmp.cleanup()
 def check(self):
  self.w.authorize_transition(self.b,self.a,'save-row',self.b['koyo_index_handoffs'][K]['lease']['token']);self.w.preservation(self.b,self.a)
 def test_nonillustration_save_row(self):self.check();self.assertEqual(self.b['entries'],self.a['entries'])
 def test_negative_mutations(self):
  for kind in ['has_illustration','unknown_presence','not_viewed','missing_event','wrong_image','fake_count','observed_creation','unknown_creation','nonzero_search','missing_cache','missing_reservation','exploration_history','terra','accepted_row','crosspost','wrong_lease','expired']:
   with self.subTest(kind=kind):
    self.tearDown();self.setUp()
    try:
     r=self.h['rows'][PID];bh=self.b['koyo_index_handoffs'][K]
     if kind=='has_illustration':r['images'][0]['attributes']['illustration_present']['value']=True
     elif kind=='unknown_presence':r['images'][0]['attributes']['illustration_present'].update(status='unknown',value=None,reason='fixture')
     elif kind=='not_viewed':r['images'][0]['viewed']=False
     elif kind=='missing_event':self.h['events'].pop(PID);bh['events'].pop(PID)
     elif kind=='wrong_image':r['images'][0]['sha256']='0'*64
     elif kind=='fake_count':r['person_count']['value']=1
     elif kind=='observed_creation':r['context']['attributes']['creation'].update(status='observed',value='original',evidence='fixture')
     elif kind=='unknown_creation':r['context']['attributes']['creation'].update(status='unknown',value=None,reason='fixture')
     elif kind=='nonzero_search':r['context']['searches']=1
     elif kind in ('missing_cache','missing_reservation'):
      f='cache' if kind=='missing_cache' else 'fetch_started';bh['context'][PID].pop(f);self.h['context'][PID].pop(f)
     elif kind=='exploration_history':bh['context'][PID]['exploration_clock']={};self.h['context'][PID]['exploration_clock']={}
     elif kind=='terra':self.a['entries'][next(iter(self.a['entries']))]['worker_id']='changed'
     elif kind=='accepted_row':self.h['rows'][next(x for x in self.h['rows'] if x!=PID)]['review_flags'].append('fixture mutation')
     elif kind=='crosspost':self.h['rows']['9999999999']=copy.deepcopy(r)
     elif kind=='wrong_lease':self.h['lease']['token']='a'*32
     elif kind=='expired':self.w.clock=lambda:bh['lease']['until']+1
     with self.assertRaises((Refused,AssertionError)):self.check()
    finally:pass
 def test_atomic_finalize_nonillustration(self):
  bh=self.b['koyo_index_handoffs'][K];bh['context'][PID].pop('cache');bh['events'].pop(PID)
  self.w.authorize_transition(self.b,self.a,'finalize-post',bh['lease']['token']);self.w.preservation(self.b,self.a)
 def test_finalize_without_reservation_refused(self):
  bh=self.b['koyo_index_handoffs'][K];bh['context'].pop(PID);bh['events'].pop(PID)
  with self.assertRaises(Refused):self.w.authorize_transition(self.b,self.a,'finalize-post',bh['lease']['token'])
 def test_context_cache_not_rewritten(self):
  self.h['context'][PID]['cache']['text']='changed'
  with self.assertRaises(Refused):self.check()
 def test_cli_live_publish_remains_disabled(self):
  with self.assertRaises(Refused):self.w.publish('unused',self.b,self.a,operation='save-row',lease_token=self.h['lease']['token'])
 def test_source_code_remains_pinned(self):
  self.w.activation_document['payload']['code_sha256'][str(BASE/'network_runtime.py')]='0'*64;self.w.activation_document['sha256']=sha(self.w.activation_document['payload'])
  with self.assertRaises(Refused):self.check()
if __name__=='__main__':unittest.main(verbosity=2)
