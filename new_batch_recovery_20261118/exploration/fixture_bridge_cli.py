"""TEST ONLY: real HostBridge with file-backed fake remote, never network."""
import sys,json,copy,hashlib,shutil
from pathlib import Path
from types import SimpleNamespace
from exploration import canonical
from persistent_runner import Store
from protocol_bridge import LiveClockGuard
from host_bridge import HostBridge
from host_cli import export
from network_runtime import IndexWriter

def main(folder,op,arg):
 folder=Path(folder)
 if op=='setup':
  from test_host_bridge import HostTests
  f=HostTests();f.setUp();folder.mkdir(parents=True,exist_ok=True)
  f.store.close();shutil.copy(Path(f.tmp.name)/'db',folder/'db')
  (folder/'remote.json').write_text(json.dumps({'head':f.head,'state':f.state}))
  (folder/'activation.json').write_text(json.dumps(f.guard.activation));(folder/'binding.json').write_text(json.dumps(f.binding));f.tmp.cleanup();return True
 binding=json.loads((folder/'binding.json').read_text());activation=json.loads((folder/'activation.json').read_text());store=Store(folder/'db')
 def read():
  r=json.loads((folder/'remote.json').read_text());return r['head'],r['state']
 def commit(state,head):return hashlib.sha1(canonical(state)).hexdigest()
 # Fixture wall is deterministic and advances only with mock tool calls.
 clockfile=folder/'time.json'
 def wall():return json.loads(clockfile.read_text()) if clockfile.exists() else 1794955000.
 q=SimpleNamespace(_commit=commit,git=lambda *a:SimpleNamespace(stdout=('b'*40+'\n').encode()))
 base=SimpleNamespace(key=binding['plan_sha256'],q=q,clock=wall,read=read,root='/tmp/x-recovery-isolated');base.preservation=lambda b,a:IndexWriter.preservation(base,b,a)
 guard=LiveClockGuard('/tmp/x-recovery-isolated',activation);host=HostBridge(store,base,guard,binding,wall)
 try:
  if op=='reserve':return export(store,host.prepare(arg['request_id'],arg['kind'],arg['queries']))
  if op=='pack-chunk':
   with store.transaction() as (d,a):
    p=d['pending']['pack'];assert p['manifest']['sha256']==arg['sha256'];return p['chunks'][arg['index']]
  if op=='pre-ref':return host.pre_ref(arg['commit'])
  if op=='ack':return host.acknowledge(arg['acknowledged'])
  if op=='claim':return host.claim(arg['request_id'])
  if op=='finish':return host.finish(arg['request_id'],arg['intent_sha256'],arg['result'])
  if op=='seal':return export(store,host.prepare_seal())
  if op=='row':return export(store,host.prepare_row(arg['row']))
  raise ValueError('test operation')
 finally:store.close()
if __name__=='__main__':print(json.dumps(main(sys.argv[1],sys.argv[2],json.loads(sys.argv[3])),ensure_ascii=False))
