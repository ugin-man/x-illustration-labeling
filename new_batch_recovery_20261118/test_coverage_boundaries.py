import tempfile,unittest,sys,os
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,'/tmp/x-recovery-isolated')
import new_batch_images as g
from test_new_batch_images import ImageGate
class Boundaries(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.r=Path(self.t.name);self.d=self.r/'data';self.d.mkdir();self.f=self.r/'refusal';self.f.mkdir();(self.r/'.codex').mkdir()
  self.roots=[self.d,self.f];self.spec={'directory':str(self.r),'excluded_names':['.codex']}
 def tearDown(self):self.t.cleanup()
 def binding(self):return g.make_binding(self.d,self.roots,self.f,'fixture',coverage_boundaries=[self.spec])
 def test_pinned(self):
  b=self.binding();roots,snap=g.effective_forest(b);g.validate_boundaries(b,snap);self.assertEqual(g.make_binding(**b),b)
 def test_new_child(self):
  b=self.binding();_,snap=g.effective_forest(b);(self.r/'new.png').write_bytes(b'fixture')
  with self.assertRaises(g.Refused):g.validate_boundaries(b,snap)
  roots,_=g.effective_forest(b);self.assertIn(self.r/'new.png',roots)
 def test_removed_child(self):
  b=self.binding();_,snap=g.effective_forest(b);self.d.rmdir()
  with self.assertRaises(g.Refused):g.validate_boundaries(b,snap)
 def test_uncovered(self):
  (self.r/'uncovered').mkdir()
  b=self.binding();roots,_=g.effective_forest(b);self.assertIn(self.r/'uncovered',roots)
 def test_managed_churn_allowed(self):
  b=self.binding();_,snap=g.effective_forest(b);(self.r/'.codex').rmdir();(self.r/'.codex').mkdir();(self.r/'.codex'/'fixture').write_text('fixture');g.validate_boundaries(b,snap)
 def test_bad_exclusion(self):
  self.spec['excluded_names']=['data']
  with self.assertRaises(g.Refused):self.binding()
 def test_symlink_child(self):
  (self.r/'alias').symlink_to(self.d)
  with self.assertRaises(g.Refused):self.binding()
 def test_fifo_child(self):
  os.mkfifo(self.r/'pipe')
  with self.assertRaises(g.Refused):self.binding()
 def test_identity_tamper(self):
  b=self.binding();_,snap=g.effective_forest(b);snap[0]['directory_identity'][1]+=1
  with self.assertRaises(g.Refused):g.validate_boundaries(b,snap)
 def test_later_gate_includes_new_forbidden_file(self):
  import hashlib
  b=self.binding();bad=b'synthetic forbidden';(self.r/'new.png').write_bytes(bad)
  roots,snap=g.effective_forest(b)
  with self.assertRaises(ValueError):g.audit_linked_workspaces(roots,{'image_sha256':[hashlib.sha256(bad).hexdigest()]})
  g.validate_boundaries(b,snap)
class Integration(ImageGate):
 def test_addition_during_audit_blocks_result(self):
  b=g.make_binding(self.bundle,[self.root,self.bundle,self.refusals],self.refusals,'fixture',coverage_boundaries=[{'directory':str(self.w),'excluded_names':[]}])
  self.doc['payload']['image_gate']=b;self.resign()
  original=g.audit_linked_workspaces
  def changed(*args):
   result=original(*args);(self.w/'new.png').write_bytes(b'fixture');return result
  with patch.object(g,'audit_linked_workspaces',side_effect=changed):
   with self.assertRaises(g.Refused):self.call()
 def dynamic_binding(self):
  self.doc['payload']['image_gate']=g.make_binding(self.bundle,[self.root,self.bundle,self.refusals],self.refusals,'fixture',coverage_boundaries=[{'directory':str(self.w),'excluded_names':[]}]);self.resign()
 def test_second_remote_read_addition_blocks_result(self):
  import copy
  self.dynamic_binding();outer=self
  class Writer:
   n=0
   def clock(me):return 1000
   def read(me):
    me.n+=1
    if me.n==2:(outer.w/'added-on-read.png').write_bytes(b'fixture')
    return outer.head,copy.deepcopy(outer.state)
  with self.assertRaises(g.Refused):g.next_from_writer(Writer(),self.doc,self.root)
 def test_post_file_check_addition_blocks_result(self):
  self.dynamic_binding();original=g.isolation.check_post_files
  def change(*args):
   result=original(*args);(self.w/'added-on-hash.png').write_bytes(b'fixture');return result
  with patch.object(g.isolation,'check_post_files',side_effect=change):
   with self.assertRaises(g.Refused):self.call()
if __name__=='__main__':unittest.main()
