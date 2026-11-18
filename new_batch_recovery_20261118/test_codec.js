const fs=require('fs'),vm=require('vm'),assert=require('assert'),crypto=require('crypto'),zlib=require('zlib');
const fflate=require('./vendor/fflate-0.8.2.umd.js');let source=fs.readFileSync('compressed_codec.js','utf8');const context={Uint8Array,fflate};vm.createContext(context);vm.runInContext(source+';globalThis.decode=decodeCompressedAscii;globalThis.b64=base64Strict;',context);
const sha=s=>crypto.createHash('sha256').update(s,'ascii').digest('hex');
function fixture(raw,compressed=zlib.deflateSync(Buffer.from(raw,'ascii')),size=raw.length){let encoded=compressed.toString('base64');let m={encoding:'zlib-base64-ascii-v1',bytes:size,sha256:sha(raw),compressed_bytes:compressed.length,encoded_chars:encoded.length,encoded_sha256:sha(encoded),chunk_chars:24000,chunks:Math.ceil(encoded.length/24000)};let chunks=encoded.match(/.{1,24000}/g);return {m,chunks};}
let passed=0;function test(name,fn){fn();passed++;console.log('PASS',name);}
test('real full envelope roundtrip byte exact',()=>{let m=JSON.parse(fs.readFileSync('fixture-pack/manifest.json'));let chunks=Array.from({length:m.chunks},(_,i)=>fs.readFileSync(`fixture-pack/${String(i).padStart(4,'0')}.txt`,'ascii'));let raw=context.decode(chunks,m,fflate,sha);let old=JSON.parse(fs.readFileSync('/tmp/koyo-replacement-prototype/connector-outbox/save-row/pack/manifest.json'));let expected=Array.from({length:old.chunks},(_,i)=>fs.readFileSync(`/tmp/koyo-replacement-prototype/connector-outbox/save-row/pack/${String(i).padStart(4,'0')}.txt`,'ascii')).join('');assert.strictEqual(raw,expected);});
test('invalid base64',()=>assert.throws(()=>context.b64('!!!!')));
test('noncanonical base64 pad bits',()=>assert.throws(()=>context.b64('AAAAAAAB==AA')));
test('corrupted compressed data with updated transport hash',()=>{let data=zlib.deflateSync(Buffer.from('abc'.repeat(100)));data[5]^=255;let f=fixture('abc'.repeat(100),data);assert.throws(()=>context.decode(f.chunks,f.m,fflate,sha));});
test('truncated compressed stream',()=>{let f=fixture('abc'.repeat(100),zlib.deflateSync(Buffer.from('abc'.repeat(100))).subarray(0,-3));assert.throws(()=>context.decode(f.chunks,f.m,fflate,sha));});
test('changed Adler32',()=>{let data=zlib.deflateSync(Buffer.from('hello'));data[data.length-1]^=1;let f=fixture('hello',data);assert.throws(()=>context.decode(f.chunks,f.m,fflate,sha));});
test('declared raw size over maximum rejected before decompression',()=>{let f=fixture('x');f.m.bytes=8*1024*1024+1;assert.throws(()=>context.decode(f.chunks,f.m,fflate,sha));});
test('decompression bomb aborts on declared limit',()=>{let f=fixture('x'.repeat(20*1024*1024),undefined,64);let began=Date.now();assert.throws(()=>context.decode(f.chunks,f.m,fflate,sha),/output limit/);assert(Date.now()-began<2000);});
test('nonASCII raw rejected',()=>{let data=zlib.deflateSync(Buffer.from([65,255]));let f=fixture('xx',data);assert.throws(()=>context.decode(f.chunks,f.m,fflate,sha),/ASCII/);});
test('original SHA mismatch',()=>{let f=fixture('abc');f.m.sha256='0'.repeat(64);assert.throws(()=>context.decode(f.chunks,f.m,fflate,sha));});
test('transport SHA mismatch',()=>{let f=fixture('abc');f.m.encoded_sha256='0'.repeat(64);assert.throws(()=>context.decode(f.chunks,f.m,fflate,sha));});
test('too few chunks rejected',()=>{let f=fixture('abc');assert.throws(()=>context.decode([],f.m,fflate,sha));});
console.log(`${passed} codec tests passed`);
