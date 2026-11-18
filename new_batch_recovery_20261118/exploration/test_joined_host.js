// Real pinned JS host -> subprocess bridge -> SQLite -> real protocol; all network mocked.
const fs=require('fs'),os=require('os'),path=require('path'),crypto=require('crypto'),cp=require('child_process'),assert=require('assert');
const {makeExplorationHost}=require('./exploration_host.js');
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'koyo-joined-'));let pending,web=0;
function py(op,a){return JSON.parse(cp.execFileSync('python',['fixture_bridge_cli.py',dir,op,JSON.stringify(a)],{encoding:'utf8',maxBuffer:8*1024*1024}));}
function read(){return JSON.parse(fs.readFileSync(path.join(dir,'remote.json')));}
(async()=>{try{
 py('setup',{});
 const tools={exec_command:async({cmd})=>{try{let args=[...cmd.matchAll(/'([^']*)'/g)].map(m=>m[1]);return {exit_code:0,output:JSON.stringify(py(args[2],JSON.parse(args[3])))}}catch(e){return {exit_code:1,output:String(e)}}},
 mcp__codex_apps__github_create_tree:async a=>{pending=a.tree_elements[0].content;return {isError:false,structuredContent:{sha:'b'.repeat(40)}}},
 mcp__codex_apps__github_create_commit:async a=>({isError:false,structuredContent:{sha:'c'.repeat(40)}}),
 mcp__codex_apps__github_fetch:async a=>({isError:false,structuredContent:{sha:'c'.repeat(40),tree:{sha:'b'.repeat(40)},parents:[{sha:read().head}]}}),
 mcp__codex_apps__github_update_ref:async a=>{assert.equal(a.expected_sha,read().head);assert.equal(a.force,false);fs.writeFileSync(path.join(dir,'remote.json'),'{"head":'+JSON.stringify(a.sha)+',"state":'+pending+'}');return {isError:false}},
 mcp__codex_apps__chat_search_web_run:async a=>{web++;fs.writeFileSync(path.join(dir,'time.json'),JSON.stringify(1794955000+web*2));return {content:[{type:'text',text:'ISOLATED FIXTURE'}]}}};
 const h=makeExplorationHost(tools,'/tmp/koyo-exploration-host-candidate/host_cli.py','/tmp/koyo-exploration-host-candidate/live-config.json');
 for(let i=0;i<5;i++)await h.request('r'+i,i<2?'search':'page',[i<2?'fixture':'https://example.com']);
 await h.seal();assert.equal(web,5);let b=JSON.parse(fs.readFileSync(path.join(dir,'binding.json'))),clock=read().state.koyo_index_handoffs[b.plan_sha256].context[b.post_id].exploration_clock;
 assert.equal(clock.seal.searches,2);assert.equal(clock.seal.pages,3);assert.equal(clock.seal.elapsed_seconds,10);console.log('Joined JS/Python/SQLite/real-protocol mock E2E: 2 queries, 3 pages, seal OK');
 }finally{fs.rmSync(dir,{recursive:true,force:true})}})().catch(e=>{console.error(e);process.exit(1)});
