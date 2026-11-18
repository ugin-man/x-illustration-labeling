"""Pinned CLI for JS host. Explicit setup, then no Authority recreation.
No Git push or external research tools in Python. Connector calls live in pinned JS.
"""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).with_name('runtime_snapshot')))
sys.path.insert(0,'/tmp/x-recovery-isolated')
from network_runtime import IndexWriter,REMOTE
from persistent_runner import Store
from protocol_bridge import LiveClockGuard,initialize_fresh_store
from host_bridge import HostBridge
from exploration import Refused,digest
import base64,zlib,hashlib

def export(store,envelope):
 raw=json.dumps(envelope,ensure_ascii=True,sort_keys=True,separators=(',',':')).encode('ascii')
 if len(raw)>8*1024*1024:raise Refused('transport raw bound')
 compressed=zlib.compress(raw,9)
 if len(compressed)>2*1024*1024:raise Refused('transport compressed bound')
 encoded=base64.b64encode(compressed).decode();chunks=[encoded[i:i+24000] for i in range(0,len(encoded),24000)]
 m={'encoding':'zlib-base64-ascii-v1','bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'compressed_bytes':len(compressed),'encoded_chars':len(encoded),'encoded_sha256':hashlib.sha256(encoded.encode()).hexdigest(),'chunks':len(chunks),'chunk_chars':24000}
 with store.transaction() as (d,a):
  if d['pending']['envelope']!=envelope:raise Refused('pending envelope changed')
  d['pending']['pack']={'manifest':m,'chunks':chunks}
 return m

def execute(config_path,op,arg):
 config=json.loads(Path(config_path).read_text());activation=json.loads(Path(config['activation']).read_text());baseline=json.loads(Path(config['baseline']).read_text());p=activation['payload'];binding=config['binding']
 if digest(baseline)!=p.get('source_state_sha256') or baseline['koyo_index_handoffs'][binding['plan_sha256']]!=p.get('baseline_handoff'):raise Refused('activation baseline mismatch')
 from new_batch_guard import NewBatchClockGuard,MODE
 guard=(NewBatchClockGuard if p.get('mode')==MODE else LiveClockGuard)(config['source_root'],activation)
 w=IndexWriter(REMOTE,baseline['catalog_sha256'],binding['plan_sha256'],config['source_root'],activation_document=activation)
 store=None
 try:
  # Always establish that pinned dedicated host/CLI are still reviewed before I/O.
  guard(p['source_head'],baseline,binding)
  if op=='initialize':
   head,state=w.read();store=initialize_fresh_store(config['authority_store'],head,state,binding,guard);return {'initialized':True}
  store=Store(config['authority_store']);bridge=HostBridge(store,w,guard,binding)
  if op=='pack-chunk':
   with store.transaction() as (d,a):
    packed=d['pending']['pack'];i=arg['index']
    if arg['sha256']!=packed['manifest']['sha256'] or type(i) is not int or not 0<=i<len(packed['chunks']):raise Refused('pack chunk mismatch')
    return packed['chunks'][i]
  if op=='reserve':return export(store,bridge.prepare(arg['request_id'],arg['kind'],arg['queries']))
  if op=='pre-ref':return bridge.pre_ref(arg['commit'])
  if op=='ack':return bridge.acknowledge(arg['acknowledged'])
  if op=='claim':return bridge.claim(arg['request_id'])
  if op=='result-start':
   with store.transaction() as (d,a):
    rid=arg['request_id'];intent=d['intents'].get(rid,{})
    if intent.get('state')!='started' or digest(intent)!=arg['intent_sha256'] or rid in d.get('result_transport',{}):raise Refused('result intent unavailable')
    if type(arg['bytes']) is not int or not 0<arg['bytes']<=4*1024*1024:raise Refused('result size bound')
    d.setdefault('result_transport',{})[rid]={'intent_sha256':arg['intent_sha256'],'bytes':arg['bytes'],'chunks':[]}
   return {'staged':True}
  if op=='result-chunk':
   with store.transaction() as (d,a):
    p=d['result_transport'][arg['request_id']];chunk=arg['chunk']
    if arg['index']!=len(p['chunks']) or not isinstance(chunk,str) or not chunk.isascii() or len(chunk)>12000 or sum(map(len,p['chunks']))+len(chunk)>p['bytes']:raise Refused('result chunk order/size')
    p['chunks'].append(chunk)
   return {'staged':True}
  if op=='result-finish':
   with store.transaction() as (d,a):
    p=d['result_transport'][arg['request_id']];raw=''.join(p['chunks'])
    if len(raw)!=p['bytes']:raise Refused('incomplete result')
    result=json.loads(raw);intent_sha=p['intent_sha256']
   return bridge.finish(arg['request_id'],intent_sha,result)
  if op=='finish':return bridge.finish(arg['request_id'],arg['intent_sha256'],arg['result'])
  if op=='seal':return export(store,bridge.prepare_seal())
  if op=='row':return export(store,bridge.prepare_row(arg['row']))
  raise Refused('unknown command')
 finally:
  if store:store.close()
  w.close()
if __name__=='__main__':
 print(json.dumps(execute(sys.argv[1],sys.argv[2],json.loads(sys.argv[3])),ensure_ascii=False))
