const assert=require('assert');const zlib=require('zlib'),crypto=require('crypto');const hash=s=>crypto.createHash('sha256').update(s).digest('hex');const {makeExplorationHost}=require('./exploration_host.js');
async function run(mode){const realNow=Date.now;let delay=0;Date.now=()=>realNow()+delay;let claimed=false,pending,packed,web=0,ref=0,order=[];const h='a'.repeat(40),c='b'.repeat(40),t='c'.repeat(40);
 const tools={exec_command:async({cmd})=>{const args=[...cmd.matchAll(/'([^']*)'/g)].map(m=>m[1]);const op=args[2],a=JSON.parse(args[3]);order.push(op);let out;
 if(op==='reserve'){pending=a;out={payload:{repo:'ugin-man/x-illustration-labeling',expected_head:h,base_tree_sha:t,candidate_tree_sha:t,state_json_content:'{}',commit_message:'fixture'}};const raw=JSON.stringify(out),zip=zlib.deflateSync(Buffer.from(raw));packed=zip.toString('base64');out={encoding:'zlib-base64-ascii-v1',bytes:raw.length,sha256:hash(raw),compressed_bytes:zip.length,encoded_chars:packed.length,encoded_sha256:hash(packed),chunks:1,chunk_chars:24000};}
 if(op==='pack-chunk')out=packed;
 if(op==='pre-ref')out={expected_sha:h,sha:c,force:false};
 if(op==='ack'){if(!a.acknowledged)return {exit_code:1,output:'lost ACK'};out={accepted:true,ref_update_acknowledged:true};}
 if(op==='claim'){if(claimed)return {exit_code:1,output:'already consumed'};claimed=true;out={...pending,intent_sha256:'d'.repeat(64),budget_remaining_seconds:60,lease_remaining_seconds:mode==='lease-delay'?32:1800};if(mode==='budget-delay')delay=61000;if(mode==='lease-delay')delay=5000;}
 if(op==='finish')out={finished:true};return {exit_code:0,output:JSON.stringify(out)};},
 mcp__codex_apps__github_create_tree:async a=>{assert.equal(a.tree_elements[0].path,'state.json');return {isError:false,structuredContent:{sha:t}}},
 mcp__codex_apps__github_create_commit:async a=>({isError:false,content:[{type:'text',text:JSON.stringify({sha:c})}]}),
 mcp__codex_apps__github_fetch:async a=>({isError:false,structuredContent:{content:JSON.stringify({sha:c,tree:{sha:t},parents:[{sha:h}]})}}),
 mcp__codex_apps__github_update_ref:async a=>{ref++;assert.strictEqual(a.force,false);if(mode==='lost')throw Error('timeout');return {isError:false}},
 mcp__codex_apps__chat_search_web_run:async a=>{web++;order.push('WEB');if(mode==='tool-lost')throw Error('tool timeout');if(pending.kind==='search')assert.deepEqual(a.system2_search_query,[{q:'q'}]);else assert.deepEqual(a.open,[{ref_id:'https://example.com'}]);return {isError:mode==='is-error',content:[{type:'text',text:'fixture'}]}}};
 const host=makeExplorationHost(tools,'/tmp/koyo-exploration-host-candidate/host_cli.py','/tmp/koyo-exploration-host-candidate/live-config.json');
 if(mode==='success'||mode==='page'){await host.request('s',mode==='page'?'page':'search',[mode==='page'?'https://example.com':'q']);assert.deepEqual(order,['reserve','pack-chunk','pre-ref','ack','claim','WEB','finish']);assert.equal(web,1);}
 else{await assert.rejects(host.request('s','search',['q']));assert.equal(web,['lost','budget-delay','lease-delay'].includes(mode)?0:1);assert.equal(order.includes('finish'),mode==='is-error');}
 assert.equal(ref,1);Date.now=realNow;return mode;
}
(async()=>{for(const mode of ['success','page','lost','tool-lost','budget-delay','lease-delay','is-error'])console.log(await run(mode));})().catch(e=>{console.error(e);process.exit(1)});
