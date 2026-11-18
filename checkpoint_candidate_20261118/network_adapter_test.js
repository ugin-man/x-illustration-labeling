// Explicit synthetic-only connector activation. No production branch is allowed.
// Caller provides tools, op, args. Credentials remain in the existing connector.
const repo='ugin-man/x-illustration-labeling';
const scope={archive:'codex/koyo-checkpoint-network-archive-20261118-v2',aggregate:'codex/koyo-checkpoint-network-aggregate-20261118-v2'};
const base='a3e781d8a81fbebdb63a3c6a69987af024b2c948';
const prefix='synthetic_checkpoint_test_20261118/';
const events=[];
async function call(name,args){
const allowed=['mcp__codex_apps__github_fetch','mcp__codex_apps__github_fetch_file','mcp__codex_apps__github_create_tree','mcp__codex_apps__github_create_commit','mcp__codex_apps__github_update_ref','mcp__codex_apps__github_create_branch'];
if(!allowed.includes(name))throw Error('connector operation refused');
if(args.repository_full_name&&args.repository_full_name!==repo)throw Error('repository scope');
if(args.branch_name)branch(args.branch_name);
if(args.path&&(!args.path.startsWith(prefix)||args.path.split('/').some(p=>p==='..'||p==='.')))throw Error('path scope');
if(args.url&&!args.url.startsWith(`https://api.github.com/repos/${repo}/`))throw Error('URL scope');
const pins=await tools.exec_command({cmd:'sha256sum --check network_test/ACTIVATION.sha256',workdir:'/tmp/koyo-checkpoint-candidate',max_output_tokens:500});if(pins.exit_code!==0)throw Error('synthetic activation pins mismatch');const started=Date.now();const r=await tools[name](args);events.push({operation:name,milliseconds:Date.now()-started,isError:!!r.isError});if(r.isError)throw Error(JSON.stringify(r));return r.structuredContent;}
async function get(url){return JSON.parse((await call('mcp__codex_apps__github_fetch',{url:`https://api.github.com/repos/${repo}/${url}`})).content);}
function branch(b){if(!Object.values(scope).includes(b))throw Error('test branch scope refusal');return b;}
async function snapshot(b){branch(b);const ref=await get('git/ref/heads/'+b);const commit=await get('git/commits/'+ref.object.sha);return {head:ref.object.sha,tree:commit.tree.sha};}
async function tree(sha){const r=await get('git/trees/'+sha+'?recursive=1');if(r.truncated)throw Error('truncated tree');return Object.fromEntries(r.tree.filter(e=>e.type!=='tree').map(e=>[e.path,{sha:e.sha,mode:e.mode,type:e.type}]));}
async function read(b,path){branch(b);if(!path.startsWith(prefix))throw Error('path scope');return (await call('mcp__codex_apps__github_fetch_file',{repository_full_name:repo,ref:b,path})).content;}
function quote(x){return "'"+x.replaceAll("'","'\\''")+"'";}
async function validate(x){const r=await tools.exec_command({cmd:'python /tmp/koyo-checkpoint-candidate/network_validate.py '+quote(JSON.stringify(x)),max_output_tokens:15000});if(r.exit_code!==0)throw Error(r.output);return JSON.parse(r.output);}
async function candidate(b,old,edits){branch(b);if(Object.keys(edits).some(p=>!p.startsWith(prefix)||p.split('/').some(c=>c==='..'||c==='.')))throw Error('path scope');const before=await tree(old.tree);const t=await call('mcp__codex_apps__github_create_tree',{repository_full_name:repo,base_tree_sha:old.tree,tree_elements:Object.entries(edits).map(([path,content])=>({path,mode:'100644',type:'blob',content}))});const after=await tree(t.sha);await validate({op:'tree',base:before,candidate:after,base_sha:old.tree,candidate_sha:t.sha,edits});
const c=await call('mcp__codex_apps__github_create_commit',{repository_full_name:repo,parent_sha:old.head,tree_sha:t.sha,message:'Synthetic-only checkpoint connector test'});
const cm=await get('git/commits/'+c.sha);if(cm.tree.sha!==t.sha||cm.parents.length!==1||cm.parents[0].sha!==old.head)throw Error('commit mismatch');
for(const [path,content]of Object.entries(edits)){const r=await call('mcp__codex_apps__github_fetch_file',{repository_full_name:repo,path,ref:c.sha});if(r.content!==content)throw Error('candidate readback mismatch');}
return c.sha;}
async function publish(b,old,edits,beforeRef=null){const sha=await candidate(b,old,edits);if(beforeRef)await beforeRef();await call('mcp__codex_apps__github_update_ref',{repository_full_name:repo,branch_name:b,expected_sha:old.head,sha,force:false});const now=await snapshot(b);if(now.head!==sha)throw Error('head mismatch');for(const [p,c]of Object.entries(edits))if(await read(b,p)!==c)throw Error('readback mismatch');return {head:sha};}
async function runSuite(){
 const r=await tools.exec_command({cmd:'cat network_test/fixed_synthetic.json',workdir:'/tmp/koyo-checkpoint-candidate',max_output_tokens:30000});if(r.exit_code!==0)throw Error('fixture unavailable');const fixture=JSON.parse(r.output);
 for(const b of Object.values(scope))await call('mcp__codex_apps__github_create_branch',{repository_full_name:repo,branch_name:b,sha:base});
 for(let i=0;i<fixture.items.length;i++)await publish(scope.archive,await snapshot(scope.archive),{[prefix+'fixed_stage'+i+'.json']:JSON.stringify(fixture.items[i])});
 await publish(scope.aggregate,await snapshot(scope.aggregate),{[prefix+'fixed_state.json']:JSON.stringify(fixture.before)});
 return {phase:'seeded',stages:fixture.items.length,scope,events};
}
async function recoverAndCheckpoint(){
 const items=[];for(let i=0;i<2;i++)items.push(JSON.parse(await read(scope.archive,prefix+'fixed_stage'+i+'.json')));
 const state=JSON.parse(await read(scope.aggregate,prefix+'fixed_state.json'));const old=await snapshot(scope.aggregate);
 const prep=await validate({op:'prepare',head:old.head,state,items});
 // Validate again immediately before constructing/publishing; per-post research
 // authorization, preservation and pinned source scope are applied in Python.
 const fresh=await snapshot(scope.aggregate);if(fresh.head!==old.head)throw Error('fresh head conflict');
 const check=await validate({op:'prepare',head:fresh.head,state,items});if(JSON.stringify(check.payload.after)!==JSON.stringify(prep.payload.after))throw Error('prepared mismatch');
 const receipt=await publish(scope.aggregate,old,{[prefix+'fixed_state.json']:JSON.stringify(prep.payload.after)},async()=>{
 const current=await snapshot(scope.aggregate);if(current.head!==old.head)throw Error('pre-ref head conflict');
 const currentState=JSON.parse(await read(scope.aggregate,prefix+'fixed_state.json'));
 const again=await validate({op:'prepare',head:current.head,state:currentState,items});
 if(JSON.stringify(again.payload.after)!==JSON.stringify(prep.payload.after))throw Error('pre-ref result drift');
 if(currentState.koyo_index_handoffs[again.payload.key].lease.until<=Date.now()/1000+120)throw Error('pre-ref lease margin');
 });
 return {phase:'checkpoint',receipt,rows:2,events};
}
async function faultSuite(){
 const old=await snapshot(scope.aggregate);const stale=await candidate(scope.aggregate,old,{[prefix+'fixed_stale.json']:'synthetic stale candidate'});
 const competing=await publish(scope.aggregate,old,{[prefix+'fixed_concurrent.json']:'synthetic competing writer'});
 let staleError=null;try{await call('mcp__codex_apps__github_update_ref',{repository_full_name:repo,branch_name:scope.aggregate,expected_sha:old.head,sha:stale,force:false});}catch(e){staleError=e.message;}
 const observed=await snapshot(scope.aggregate);if(observed.head!==competing.head)throw Error('concurrent branch overwritten');
 const next=await candidate(scope.aggregate,observed,{[prefix+'fixed_ack.json']:'synthetic ACK injection'});
 await call('mcp__codex_apps__github_update_ref',{repository_full_name:repo,branch_name:scope.aggregate,expected_sha:observed.head,sha:next,force:false});
 // Simulated successful-response loss: no receipt used as acceptance evidence.
 const final=await snapshot(scope.aggregate);if(final.head!==next||await read(scope.aggregate,prefix+'fixed_ack.json')!=='synthetic ACK injection')throw Error('ACK reconciliation');
 let scopeRefused=false;try{await snapshot('codex/jobs/production-v4-001/dispatch-index');}catch(e){scopeRefused=e.message==='test branch scope refusal';}
 if(!scopeRefused)throw Error('production scope not refused');
 return {phase:'faults',head:final.head,staleError,concurrentPreserved:true,simulatedACKLoss:true,retries:0,productionScopeRefused:scopeRefused,events};
}
// Intentionally expose no raw call/get/candidate/ref interfaces or arbitrary paths.
return Object.freeze({runSuite,recoverAndCheckpoint,faultSuite});
