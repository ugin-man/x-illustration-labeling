"""Pack already-validated legacy ASCII envelope bytes losslessly; no remote writes."""
import base64,hashlib,json,pathlib,sys,zlib
MAX_RAW=8*1024*1024;MAX_ZLIB=2*1024*1024;CHUNK=24000
def pack(raw,folder):
    if not 0<len(raw)<=MAX_RAW or not raw.isascii():raise ValueError('raw ASCII size bound')
    compressed=zlib.compress(raw,9)
    if len(compressed)>MAX_ZLIB:raise ValueError('compressed size bound')
    text=base64.b64encode(compressed).decode('ascii');folder=pathlib.Path(folder);folder.mkdir(parents=True,exist_ok=True)
    chunks=[text[i:i+CHUNK] for i in range(0,len(text),CHUNK)]
    for i,c in enumerate(chunks):(folder/f'{i:04d}.txt').write_text(c,encoding='ascii')
    m={'encoding':'zlib-base64-ascii-v1','bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'compressed_bytes':len(compressed),'encoded_chars':len(text),'encoded_sha256':hashlib.sha256(text.encode()).hexdigest(),'chunks':len(chunks),'chunk_chars':CHUNK}
    (folder/'manifest.json').write_text(json.dumps(m,sort_keys=True));return m
if __name__=='__main__':
    legacy=pathlib.Path(sys.argv[1]);m=json.loads((legacy/'manifest.json').read_text());raw=b''.join((legacy/f'{i:04d}.txt').read_bytes() for i in range(m['chunks']))
    if len(raw)!=m['bytes'] or hashlib.sha256(raw).hexdigest()!=m['sha256']:raise ValueError('legacy transport corrupt')
    print(json.dumps(pack(raw,sys.argv[2])))
