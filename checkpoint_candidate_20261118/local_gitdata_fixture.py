"""Local bare-Git implementation of the GitHub-shaped interface. Never a network client."""
import json,os,subprocess,tempfile
from pathlib import Path
from git_adapters import Conflict,PermissionDenied,REPO
class LocalGitData:
 offline_fixture_only=True
 def __init__(self,root):
  self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
  subprocess.run(['git','init','--bare',str(self.root)],capture_output=True,check=True)
  self.env={**os.environ,'GIT_AUTHOR_NAME':'Offline fixture','GIT_COMMITTER_NAME':'Offline fixture','GIT_AUTHOR_EMAIL':'fixture@example.invalid','GIT_COMMITTER_EMAIL':'fixture@example.invalid'}
  self.update_hook=None;self.create_hook=None;self.lose_ack=False;self.deny=False;self.updates=0
 def git(self,*args,input=None,env=None):
  r=subprocess.run(['git','--git-dir',str(self.root),*args],input=input,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env or self.env)
  if r.returncode:raise RuntimeError(r.stderr.decode())
  return r.stdout.decode().strip()
 def check(self,repo):
  if repo!=REPO:raise ValueError('fixture repository mismatch')
 def seed(self,branch,files):
  tree=self.create_tree(REPO,None,files);commit=self.git('commit-tree',tree,input=b'Fixture initial state\n');self.git('update-ref','refs/heads/'+branch,commit);return commit
 def get_ref(self,repo,branch):self.check(repo);return self.git('rev-parse','refs/heads/'+branch)
 def get_commit(self,repo,sha):
  self.check(repo);return {'sha':sha,'tree':self.git('show','-s','--format=%T',sha),'parents':self.git('show','-s','--format=%P',sha).split()}
 def list_tree(self,repo,sha):
  self.check(repo);out={}
  for line in self.git('ls-tree','-r',sha).splitlines():
   mode,typ,rest=line.split(' ',2);blob,path=rest.split('\t');out[path]={'sha':blob,'mode':mode,'type':typ}
  return out
 def get_blob(self,repo,sha):
  self.check(repo)
  # Preserve exact trailing newlines; .git helper strips them for metadata only.
  return subprocess.run(['git','--git-dir',str(self.root),'cat-file','blob',sha],check=True,stdout=subprocess.PIPE).stdout.decode()
 def create_tree(self,repo,base,elements):
  self.check(repo)
  with tempfile.TemporaryDirectory() as d:
   env={**self.env,'GIT_INDEX_FILE':str(Path(d)/'index')}
   self.git('read-tree',base or '--empty',env=env)
   for path,text in elements.items():
    if path.startswith('/') or '..' in path.split('/'):raise ValueError('unsafe fixture path')
    blob=self.git('hash-object','-w','--stdin',input=text.encode())
    self.git('update-index','--add','--cacheinfo','100644',blob,path,env=env)
   return self.git('write-tree',env=env)
 def create_commit(self,repo,tree,parent,message):
  self.check(repo);sha=self.git('commit-tree',tree,'-p',parent,input=(message+'\n').encode())
  if self.create_hook:self.create_hook()
  return sha
 def update_ref(self,repo,branch,expected,sha):
  self.check(repo);self.updates+=1
  if self.deny:raise PermissionDenied('fixture explicit permission refusal')
  if self.update_hook:self.update_hook(branch,expected,sha)
  r=subprocess.run(['git','--git-dir',str(self.root),'update-ref','refs/heads/'+branch,sha,expected],capture_output=True,env=self.env)
  if r.returncode:raise Conflict('fixture compare-and-swap rejected')
  if self.lose_ack:raise TimeoutError('fixture ACK lost after successful CAS')
  return True
