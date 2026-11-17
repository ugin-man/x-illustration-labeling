// Reviewed connector orchestration. load('connectorFolder') identifies one validated outbox.
function sha256Ascii(s){
 const rotr=(x,n)=>(x>>>n)|(x<<(32-n));let k=[],h=[],prime=2;
 while(k.length<64){let ok=true;for(let d=2;d*d<=prime;d++)if(prime%d===0){ok=false;break;}if(ok){if(h.length<8)h.push((Math.sqrt(prime)%1*4294967296)|0);k.push((Math.cbrt(prime)%1*4294967296)|0);}prime++;}
 let bytes=Array.from(s,c=>c.charCodeAt(0));if(bytes.some(x=>x>127))throw Error('nonascii pack');let bitlen=bytes.length*8;bytes.push(128);while(bytes.length%64!==56)bytes.push(0);for(let i=7;i>=0;i--)bytes.push(i>=4?Math.floor(bitlen/2**(i*8))&255:(bitlen>>> (i*8))&255);
 for(let o=0;o<bytes.length;o+=64){let w=[];for(let i=0;i<16;i++)w[i]=(bytes[o+4*i]<<24)|(bytes[o+4*i+1]<<16)|(bytes[o+4*i+2]<<8)|bytes[o+4*i+3];for(let i=16;i<64;i++){let a=w[i-15],b=w[i-2];w[i]=(w[i-16]+(rotr(a,7)^rotr(a,18)^(a>>>3))+w[i-7]+(rotr(b,17)^rotr(b,19)^(b>>>10)))|0;}let [a,b,c,d,e,f,g,z]=h;for(let i=0;i<64;i++){let t1=(z+(rotr(e,6)^rotr(e,11)^rotr(e,25))+((e&f)^(~e&g))+k[i]+w[i])|0;let t2=((rotr(a,2)^rotr(a,13)^rotr(a,22))+((a&b)^(a&c)^(b&c)))|0;[a,b,c,d,e,f,g,z]=[(t1+t2)|0,a,b,c,(d+t1)|0,e,f,g];}h=h.map((v,i)=>(v+[a,b,c,d,e,f,g,z][i])|0);}
 return h.map(v=>(v>>>0).toString(16).padStart(8,'0')).join('');
}
if(sha256Ascii('abc')!=='ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')throw Error('SHA selftest');
const folder=load('connectorFolder');if(!/^\/tmp\/koyo-replacement-prototype\/connector-outbox\/(reacquire|body-reserve|body-cache|image-event|save-row)$/.test(folder))throw Error('folder scope');
async function command(cmd,max=2000){let r=await tools.exec_command({cmd,max_output_tokens:max,yield_time_ms:1000});let output=r.output||'';while(r.session_id&&r.exit_code===undefined){r=await tools.write_stdin({session_id:r.session_id,chars:'',yield_time_ms:1000,max_output_tokens:max});output+=r.output||'';}if(r.exit_code!==0)throw Error('bridge command failed: '+output.slice(-1500));return output;}
const prefix='cd /tmp/koyo-replacement-prototype && PYTHONPATH=/tmp/x-recovery-isolated:. python connector_bridge.py ';
let verified=JSON.parse(await command(prefix+'validate '+folder));let m=verified.pack;let chunks=new Array(m.chunks);
for(let i=0;i<m.chunks;i+=8)await Promise.all(Array.from({length:Math.min(8,m.chunks-i)},async(_,j)=>{let n=i+j;chunks[n]=await command('cat '+folder+'/pack/'+String(n).padStart(4,'0')+'.txt',20000);}));
let raw=chunks.join('');if(raw.length!==m.bytes||sha256Ascii(raw)!==m.sha256)throw Error('transport bytes/hash mismatch');let envelope=JSON.parse(raw),e=envelope.payload;if(envelope.sha256!==verified.sha256)throw Error('envelope hash differs');
let again=JSON.parse(await command(prefix+'validate '+folder));if(again.sha256!==verified.sha256||again.pack.sha256!==m.sha256)throw Error('fresh envelope changed');
function value(r){if(r.isError)throw Error('connector returned error; stop');let s=r.structuredContent;if(s&&typeof s==='object')return s;for(let c of r.content||[])if(c.type==='text'){try{return JSON.parse(c.text);}catch{}}throw Error('connector response unavailable');}
function object(r){let v=value(r);if(v.content&&typeof v.content==='string'){try{return JSON.parse(v.content);}catch{}}return v;}
const tree=object(await tools.mcp__codex_apps__github_create_tree({repository_full_name:e.repo,base_tree_sha:e.base_tree_sha,tree_elements:[{path:'state.json',mode:'100644',type:'blob',content:e.state_json_content}]}));if(tree.sha!==e.candidate_tree_sha)throw Error('connector tree mismatch');
const commit=object(await tools.mcp__codex_apps__github_create_commit({repository_full_name:e.repo,parent_sha:e.expected_head,tree_sha:e.candidate_tree_sha,message:e.commit_message}));if(!/^[a-f0-9]{40}$/.test(commit.sha))throw Error('commit sha missing');
const fetched=object(await tools.mcp__codex_apps__github_fetch({url:'https://api.github.com/repos/'+e.repo+'/git/commits/'+commit.sha}));
if(fetched.sha!==commit.sha||fetched.tree?.sha!==e.candidate_tree_sha||fetched.parents?.length!==1||fetched.parents[0].sha!==e.expected_head)throw Error('commit parent/tree mismatch');
// Write only fetched small metadata. Then revalidate actual current head/lease immediately before ref update.
const meta=JSON.stringify({sha:fetched.sha,tree:{sha:fetched.tree.sha},parents:[{sha:fetched.parents[0].sha}]});
await command("python -c 'import pathlib;pathlib.Path(\""+folder+"/commit.json\").write_text("+JSON.stringify(meta)+")'");
const params=JSON.parse(await command(prefix+'pre-ref '+folder));
if(params.expected_sha!==e.expected_head||params.sha!==commit.sha||params.force!==false)throw Error('pre-ref parameters mismatch');
let ack=false,refResult;try{refResult=await tools.mcp__codex_apps__github_update_ref(params);ack=refResult.isError===false;}catch(error){ack=false;}
// Always read back. Inability to confirm, explicit connector denial, cancel or lost ACK must not trigger another request.
const receipt=JSON.parse(await command(prefix+'readback '+folder+' '+commit.sha+' '+(ack?'acknowledged':'uncertain')));
store('lastConnectorReceipt',receipt);text({operation:e.operation,receipt});
if(!ack||!receipt.accepted)throw Error('ref update not certainly acknowledged/accepted: no external request and no automatic retry');
