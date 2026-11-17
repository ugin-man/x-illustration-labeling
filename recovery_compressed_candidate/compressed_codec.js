// Browser/V8-compatible transport decoder. No Node, atob, crypto, TextDecoder.
// Expects pinned fflate 0.8.2 and independently verified original SHA256ASCII.
const COMPRESSED_LIMITS=Object.freeze({rawBytes:8*1024*1024,zlibBytes:2*1024*1024,chunkChars:24000,pushBytes:128});
function base64Strict(text){
 if(typeof text!=='string'||text.length%4||text.length>Math.ceil(COMPRESSED_LIMITS.zlibBytes/3)*4||!/^([A-Za-z0-9+/]{4})*([A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(text))throw Error('invalid base64 or compressed size');
 const alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/', pad=text.endsWith('==')?2:text.endsWith('=')?1:0,n=text.length/4*3-pad;
 if(n<6||n>COMPRESSED_LIMITS.zlibBytes)throw Error('compressed byte bounds');
 const out=new Uint8Array(n);let pos=0;
 for(let i=0;i<text.length;i+=4){const a=alphabet.indexOf(text[i]),b=alphabet.indexOf(text[i+1]),c=text[i+2]=='='?0:alphabet.indexOf(text[i+2]),d=text[i+3]=='='?0:alphabet.indexOf(text[i+3]);if(i+4===text.length&&((pad===2&&(b&15))||(pad===1&&(c&3))))throw Error('noncanonical base64 padding');let v=(a<<18)|(b<<12)|(c<<6)|d;out[pos++]=(v>>>16)&255;if(pos<n)out[pos++]=(v>>>8)&255;if(pos<n)out[pos++]=v&255;}
 return out;
}
function validateCompressedManifest(m){
 if(!m||m.encoding!=='zlib-base64-ascii-v1'||!Number.isSafeInteger(m.bytes)||m.bytes<1||m.bytes>COMPRESSED_LIMITS.rawBytes||!Number.isSafeInteger(m.compressed_bytes)||m.compressed_bytes<6||m.compressed_bytes>COMPRESSED_LIMITS.zlibBytes||!Number.isSafeInteger(m.encoded_chars)||m.encoded_chars!==4*Math.ceil(m.compressed_bytes/3)||m.chunk_chars!==COMPRESSED_LIMITS.chunkChars||m.chunks!==Math.ceil(m.encoded_chars/m.chunk_chars)||!Number.isSafeInteger(m.chunks)||!/^[0-9a-f]{64}$/.test(m.sha256)||!/^[0-9a-f]{64}$/.test(m.encoded_sha256))throw Error('compressed manifest bounds/shape');
}
function decodeCompressedAscii(chunks,m,fflate,sha256Ascii){
 validateCompressedManifest(m);
 if(chunks.length!==m.chunks||chunks.some((s,i)=>typeof s!=='string'||s.length!==(i===m.chunks-1?m.encoded_chars-i*m.chunk_chars:m.chunk_chars)))throw Error('compressed chunk lengths');
 const encoded=chunks.join('');if(sha256Ascii(encoded)!==m.encoded_sha256)throw Error('compressed transport hash');
 const data=base64Strict(encoded);if(data.length!==m.compressed_bytes)throw Error('compressed bytes mismatch');
 if((data[0]&15)!==8||(data[0]>>>4)>7||((data[0]<<8)|data[1])%31||(data[1]&32))throw Error('unsupported zlib header/dictionary');
 let length=0,parts=[],a=1,b=0,done=false;
 // Stream tiny input blocks to bound individual output allocations and abort a bomb
 // as soon as the declared total is exceeded. No unbounded unzlibSync allocation.
 const stream=new fflate.Unzlib((output,final)=>{
   length+=output.length;if(length>m.bytes||length>COMPRESSED_LIMITS.rawBytes)throw Error('decompression output limit');
   let piece='';for(let i=0;i<output.length;i++){const c=output[i];if(c>127)throw Error('decoded pack is not ASCII');a=(a+c)%65521;b=(b+a)%65521;piece+=String.fromCharCode(c);}parts.push(piece);if(final)done=true;
 });
 for(let i=0;i<data.length;i+=COMPRESSED_LIMITS.pushBytes)stream.push(data.subarray(i,Math.min(i+COMPRESSED_LIMITS.pushBytes,data.length)),i+COMPRESSED_LIMITS.pushBytes>=data.length);
 const adler=(((data[data.length-4]<<24)|(data[data.length-3]<<16)|(data[data.length-2]<<8)|data[data.length-1])>>>0);
 if(!done||length!==m.bytes||(((b<<16)|a)>>>0)!==adler)throw Error('incomplete zlib or Adler32/length mismatch');
 const raw=parts.join('');if(sha256Ascii(raw)!==m.sha256)throw Error('original uncompressed SHA mismatch');return raw;
}
