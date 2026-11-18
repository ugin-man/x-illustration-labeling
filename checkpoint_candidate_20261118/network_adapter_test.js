// Explicit synthetic-only connector activation. No production branch is allowed.
// Caller provides tools, op, args. Credentials remain in the existing connector.
const repo='ugin-man/x-illustration-labeling';
const scope={archive:'codex/koyo-checkpoint-network-archive-20261118',aggregate:'codex/koyo-checkpoint-network-aggregate-20261118'};
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
async function publish(b,old,edits){const sha=await candidate(b,old,edits);await call('mcp__codex_apps__github_update_ref',{repository_full_name:repo,branch_name:b,expected_sha:old.head,sha,force:false});const now=await snapshot(b);if(now.head!==sha)throw Error('head mismatch');for(const [p,c]of Object.entries(edits))if(await read(b,p)!==c)throw Error('readback mismatch');return {head:sha};}
return {repo,scope,base,prefix,events,call,get,snapshot,tree,read,validate,candidate,publish};
