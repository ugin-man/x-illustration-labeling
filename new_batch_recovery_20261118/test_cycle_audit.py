import tempfile,unittest,hashlib,zipfile,os
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0,"/tmp/x-recovery-isolated")
from new_batch_images import audit_linked_workspaces,Refused
class CycleAudit(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.r=Path(self.t.name);self.bad=b'synthetic forbidden';self.policy={'image_sha256':[hashlib.sha256(self.bad).hexdigest()]}
 def tearDown(self):self.t.cleanup()
 def runaudit(self):return audit_linked_workspaces([self.r],self.policy)
 def test_directory_cycle_and_internal_alias(self):
  (self.r/'d').mkdir();(self.r/'d/ok.png').write_bytes(b'synthetic okay');(self.r/'d/back').symlink_to(self.r);(self.r/'current').symlink_to(self.r/'d')
  self.assertEqual(self.runaudit()['loose_images_checked'],1)
 def test_outside_and_denied_rejected_before_target_lstat(self):
  for dst in ['/etc','/home/agent/.codex/sessions']:
   p=self.r/'link';p.symlink_to(dst)
   with self.assertRaises(Refused):self.runaudit()
   p.unlink()
 def test_broken_rejected(self):
  (self.r/'broken').symlink_to(self.r/'absent')
  with self.assertRaises(FileNotFoundError):self.runaudit()
 def test_unresolved_link_cycle_refused(self):
  (self.r/'a').symlink_to('b');(self.r/'b').symlink_to('a')
  with self.assertRaises(Refused):self.runaudit()
 def test_hidden_linked_excluded(self):
  (self.r/'.hidden').mkdir();(self.r/'.hidden/image.png').write_bytes(self.bad);(self.r/'current').symlink_to(self.r/'.hidden')
  with self.assertRaises(ValueError):self.runaudit()
 def test_alias_extension_no_inode_skip(self):
  (self.r/'raw.bin').write_bytes(self.bad);(self.r/'image.jpg').symlink_to('raw.bin')
  with self.assertRaises(ValueError):self.runaudit()
 def test_zip_alias_and_intermediate_suffix(self):
  with zipfile.ZipFile(self.r/'raw.bin','w') as z:z.writestr('hidden/image.png',self.bad)
  (self.r/'cache.zip').symlink_to('raw.bin');(self.r/'alias.txt').symlink_to('cache.zip')
  with self.assertRaises(ValueError):self.runaudit()
 def test_cross_root_link_covered(self):
  (self.r/'one').mkdir();(self.r/'two').mkdir();(self.r/'two/image.png').write_bytes(b'ok');(self.r/'one/linked').symlink_to(self.r/'two')
  r=audit_linked_workspaces([self.r/'one',self.r/'two'],self.policy);self.assertEqual(r['loose_images_checked'],1)
 def test_hardlinked_image_alias(self):
  (self.r/'raw.bin').write_bytes(self.bad);os.link(self.r/'raw.bin',self.r/'alias.png')
  with self.assertRaises(ValueError):self.runaudit()
 def test_scandir_permission_is_not_empty(self):
  with patch('os.scandir',side_effect=PermissionError('synthetic')):
   with self.assertRaises(PermissionError):self.runaudit()
 def test_nonregular_image_rejected(self):
  os.mkfifo(self.r/'fifo.png')
  with self.assertRaises(Refused):self.runaudit()
 def test_alias_swap_detected(self):
  (self.r/'safe').mkdir();(self.r/'safe/image.png').write_bytes(b'ok');(self.r/'link').symlink_to('safe');orig=os.scandir
  def scan(p):
   if isinstance(p,int) and Path(os.readlink('/proc/self/fd/'+str(p)))==self.r/'safe':
    (self.r/'link').unlink();(self.r/'link').symlink_to('/etc')
   return orig(p)
  with patch('os.scandir',side_effect=scan):
   with self.assertRaises(Refused):self.runaudit()
 def test_relative_parent_internal_safe(self):
  (self.r/'d').mkdir();(self.r/'safe.png').write_bytes(b'ok');(self.r/'d/link.png').symlink_to('../safe.png')
  self.assertEqual(self.runaudit()['loose_images_checked'],1)
 def test_dotdot_after_outside_link_is_not_normalized_away(self):
  (self.r/'outside').symlink_to('/etc');(self.r/'alias').symlink_to('outside/../safe')
  with self.assertRaises(Refused):self.runaudit()
 def test_root_escape_then_reentry_refused(self):
  (self.r/'link').symlink_to('../'+self.r.name)
  with self.assertRaises(Refused):self.runaudit()
if __name__=='__main__':unittest.main()
