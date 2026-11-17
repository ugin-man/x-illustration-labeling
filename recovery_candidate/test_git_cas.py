import subprocess,tempfile,os,json,unittest
from recovery_adapter import canonical
S=json.load(open('/tmp/x-state-recovery.json'))
class LocalGitCAS(unittest.TestCase):
 def test_atomic_expected_head(self):
  with tempfile.TemporaryDirectory(prefix='offline-cas-') as d:
   env=dict(os.environ,GIT_AUTHOR_NAME='Offline test',GIT_AUTHOR_EMAIL='offline@example.invalid',GIT_COMMITTER_NAME='Offline test',GIT_COMMITTER_EMAIL='offline@example.invalid')
   def git(*args,data=None,check=True):return subprocess.run(['git','--git-dir',d,*args],input=data,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,check=check)
   git('init','--bare')
   blob=git('hash-object','-w','--stdin',data=canonical(S)).stdout.decode().strip()
   tree=git('mktree',data=f'100644 blob {blob}\tstate.json\n'.encode()).stdout.decode().strip()
   def commit(msg,parent=None):return git('commit-tree',tree,*(['-p',parent] if parent else []),data=msg.encode()).stdout.decode().strip()
   a=commit('initial');b=commit('first writer',a);c=commit('competing writer',a);ref='refs/heads/offline-test'
   git('update-ref',ref,a,'0'*40);git('update-ref',ref,b,a)
   rejected=git('update-ref',ref,c,a,check=False)
   self.assertNotEqual(rejected.returncode,0);self.assertEqual(git('rev-parse',ref).stdout.decode().strip(),b)
   # Lost acknowledgement: inspect actual ref, never blindly replay mutation.
   self.assertEqual(git('rev-parse',ref).stdout.decode().strip(),b)
   self.assertEqual(git('remote').stdout,b'')
if __name__=='__main__':unittest.main(verbosity=2)
