import os,tempfile,unittest
from pathlib import Path
from test_git_adapters import GitAdapters
from git_adapters import Refused,REPO,DISPATCH,ARCHIVE
class TreeIntegrity(GitAdapters):
 # Only these new tests are loaded by custom suite below; avoid duplicate inherited cases.
 def test_archive_wrong_role_refused(self):
  from test_git_adapters import gate
  from git_adapters import GitHubArchive
  with self.assertRaises(Refused):GitHubArchive(self.io,gate("aggregate"))
 def test_aggregate_wrong_role_refused(self):
  from test_git_adapters import gate
  from git_adapters import GitHubAggregate
  with self.assertRaises(Refused):GitHubAggregate(self.io,gate("archive"))
 def inject(self,kind,target):
  original=self.io.create_tree
  def fault(repo,base,elements):
   if kind=='drop_base':return original(repo,None,elements)
   if kind=='extra_path':return original(repo,base,{**elements,'injected.txt':'unexpected'})
   if kind=='wrong_content':return original(repo,base,{**elements,next(iter(elements)):'wrong content'})
   tree=original(repo,base,elements)
   with tempfile.TemporaryDirectory() as d:
    env={**self.io.env,'GIT_INDEX_FILE':str(Path(d)/'index')};self.io.git('read-tree',tree,env=env)
    entry=self.io.list_tree(repo,tree)[target]
    mode='100755' if kind=='mode' else '120000' if kind=='symlink' else '160000'
    sha=entry['sha'] if kind!='submodule' else self.io.get_ref(REPO,DISPATCH)
    self.io.git('update-index','--add','--cacheinfo',mode,sha,target,env=env)
    return self.io.git('write-tree',env=env)
  self.io.create_tree=fault
  return original
 def check_dispatch_fault(self,kind,target='other.txt'):
  self.archive_all();head=self.io.get_ref(REPO,DISPATCH);updates=self.io.updates;self.inject(kind,target)
  with self.assertRaises(Refused):self.publish()
  self.assertEqual(self.io.get_ref(REPO,DISPATCH),head);self.assertEqual(self.io.updates,updates)
 def test_dispatch_dropped_tree_refused(self):self.check_dispatch_fault('drop_base')
 def test_dispatch_extra_path_refused(self):self.check_dispatch_fault('extra_path')
 def test_dispatch_non_target_mode_refused(self):self.check_dispatch_fault('mode')
 def test_dispatch_non_target_type_refused(self):self.check_dispatch_fault('submodule')
 def test_dispatch_target_symlink_refused(self):self.check_dispatch_fault('symlink','state.json')
 def test_dispatch_wrong_content_refused(self):self.check_dispatch_fault('wrong_content')
 def test_archive_dropped_tree_refused(self):
  head=self.io.get_ref(REPO,ARCHIVE);updates=self.io.updates;self.inject('drop_base','README')
  with self.assertRaises(Refused):self.archive.put(self.items[0])
  self.assertEqual(self.io.get_ref(REPO,ARCHIVE),head);self.assertEqual(self.io.updates,updates)
 def test_truncated_listing_refused(self):
  self.archive_all();original=self.io.list_tree;head=self.io.get_ref(REPO,DISPATCH)
  def truncated(repo,sha):
   out=original(repo,sha);out.pop('other.txt',None);return out
  self.io.list_tree=truncated
  with self.assertRaises(Refused):self.publish()
  self.assertEqual(self.io.get_ref(REPO,DISPATCH),head)
 def test_archive_non_target_mode_refused(self):
  head=self.io.get_ref(REPO,ARCHIVE);self.inject('mode','README')
  with self.assertRaises(Refused):self.archive.put(self.items[0])
  self.assertEqual(self.io.get_ref(REPO,ARCHIVE),head)
def load_tests(loader,tests,pattern):
 return unittest.TestSuite(TreeIntegrity(n) for n in TreeIntegrity.__dict__ if n.startswith('test_'))
if __name__=='__main__':unittest.main()
