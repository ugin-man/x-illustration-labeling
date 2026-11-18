const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(__dirname+'/connector_transport.js','utf8');
(async()=>{for(const folder of [
 '/tmp/koyo-current-batch-candidate/connector-outbox/2096242785573913027/body-reserve',
 '/tmp/koyo-current-batch-candidate/connector-outbox/lease/body-reserve-'+'a'.repeat(32),
 '/tmp/koyo-current-batch-candidate/connector-outbox/2096242785573913027/renew-'+'a'.repeat(32),
 '/tmp/evil/connector-outbox/2096242785573913027/body-reserve-'+'a'.repeat(32),
 '/tmp/koyo-current-batch-candidate/connector-outbox/../body-reserve-'+'a'.repeat(32)]) {
 let calls=0;const tools=new Proxy({}, {get:()=>async()=>{calls++;throw Error('unexpected tool');}});
 await assert.rejects(()=>vm.runInNewContext('(async()=>{'+source+'})()',{tools,load:()=>folder,store:()=>{},text:()=>{}}),/folder scope/);assert.equal(calls,0);
 } console.log('5 malformed route refusals passed, zero tools');})().catch(e=>{console.error(e);process.exitCode=1;});
