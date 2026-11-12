'use strict';
const $ = id => document.getElementById(id);
const COLORS = ['black','brown','blond_yellow','red','orange','pink','purple','blue','green','white','gray','other'];
const NAMES = {content_kind:'画像の種類',format:'形式',subject_types:'描かれた対象',depiction_count:'描写数',color_mode:'色の表現',background:'背景',background_detail:'背景の細かさ',design_kind:'デザイン要素',environment:'場所',technique:'制作方法',time_of_day:'時間帯',visible_promotion:'画像内の宣伝',work_in_progress:'制作途中',body_form:'体の形',animal_features:'動物の特徴',anthropomorphism:'人間的な特徴',crop:'描写範囲',expression:'表情',hair_colors:'髪の色',fur_colors:'毛皮などの色',style:'画風',creation:'創作の由来',poster_relation:'投稿者との関係',promotion:'投稿の宣伝'};
const WORDS = {illustration:'イラスト',photo:'写真',screenshot:'画面のスクリーンショット',mixed:'混合',comic:'漫画',design:'デザイン',other:'その他',human_like:'人型',animal_like:'動物型',hybrid:'人・動物などの混合型',object:'物体',object_like:'物体型',landscape:'風景',monochrome:'単色・白黒',grayscale:'グレースケール',limited_palette:'限定された色数',multicolor:'多色',plain_paper:'紙・白地',solid_color:'単色の背景',abstract_decorative:'抽象・装飾',environment:'描かれた環境',none:'なし',simple:'シンプル',detailed:'細かい',analog:'アナログ',digital:'デジタル',daytime:'昼',night:'夜',interior:'室内',city:'街',nature:'自然',fantasy:'幻想的な場所',text:'文字',poster:'ポスター',logo:'ロゴ',decoration:'装飾',realistic:'写実寄り',stylized:'様式化・デフォルメ',face:'顔',bust:'胸から上',waist_up:'腰から上',full_body:'全身',partial:'一部分',smile:'笑顔',neutral:'中立・真顔',angry:'怒り',sad:'悲しみ',surprised:'驚き',black:'黒',brown:'茶',blond_yellow:'金・黄',red:'赤',orange:'オレンジ',pink:'ピンク',purple:'紫',blue:'青',green:'緑',white:'白',gray:'灰',original:'一次創作',derivative:'二次創作',official:'公式の作品',creator:'作者として申告',repost:'転載として申告',unknown:'不明',not_applicable:'対象外',not_assessed:'未評価',technical_failure:'取得・照合の失敗',pending:'未確認',ok:'合ってそう',issue:'気になる',hold:'保留',identified:'特定済み',claimed_original:'独自キャラの申告',unresolved:'未特定'};
Object.assign(WORDS,{waist:'腰から上',other_partial:'その他の部分',anger:'怒り',sadness:'悲しみ',surprise:'驚き',morning:'朝',evening:'夕方',pattern:'パターン',self_claimed:'自作として申告',repost_claimed:'転載として申告'});
Object.assign(NAMES,{depiction_count:'旧・描写回数',style:'旧版の画風'});
Object.assign(WORDS,{stylized:'様式化（アニメ・漫画表現など）',limited_palette:'限定色（旧区分・見直し対象）'});
const REVISION_NOTES = {
  '2094827205117567234':'見直し例：同じ人物の表情・ポーズ違いを、次版では1人にまとめます。以下の旧版の詳細は、同じ人物の繰り返しを別々に記録したものです。',
  '2096602285036163293':'見直し例：登場人物は2人です。同じ2人が3コマに登場するため、旧版は6描写と数えていました。次版では2人にまとめます。'
};
const STATUS_SYMBOL = {pending:'○',ok:'✓',issue:'⚑',hold:'…'};
let posts=[], byId=new Map(), reviews={}, revisions={}, token='', currentId='', imageIndex=0, sampleIds=null;
let pending=new Map(), noteTimers=new Map(), saving=false, saveFailed=false, runId='', fingerprint='';

function el(tag, className, text) { const n=document.createElement(tag); if(className)n.className=className; if(text!==undefined)n.textContent=String(text); return n; }
function word(v) { return WORDS[v] || String(v); }
function value(a) { if(!a)return '未評価'; if(a.status!=='observed')return word(a.status); if(Array.isArray(a.value))return a.value.map(word).join('・') || 'なし'; if(typeof a.value==='boolean')return a.value?'あり':'なし'; return word(a.value); }
function statusValue(a){return a?.status==='observed'?a.value:null;}
function review(pid=currentId) { return reviews[pid] ||= {post_id:pid,status:'pending',note:'',flags:[],displayed_media:[],revision:revisions[pid]||0}; }
function current(){return byId.get(currentId);}
function imageUrl(im){return `/images/${im.sha256}.jpg`;}
function filtered(){const q=$('search').value.trim(),f=$('filter').value;return posts.filter(p=>(!sampleIds||sampleIds.has(p.post_id))&&(!q||p.post_id.includes(q))&&(f==='all'||review(p.post_id).status===f));}
function showError(message){$('error-message').textContent=message;$('error').hidden=false;}
function clearError(){$('error').hidden=true;}
function safeLink(url, label){try{const u=new URL(url);if(!['https:','http:'].includes(u.protocol))return null;const a=el('a','',label||u.hostname);a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';return a;}catch{return null;}}

function scheduleSave(pid){if(noteTimers.has(pid)){clearTimeout(noteTimers.get(pid));noteTimers.delete(pid);}pending.set(pid,JSON.parse(JSON.stringify(review(pid))));updateSaveState();if(!saveFailed)void drain();}
function flushNotes(){for(const [pid,timer] of noteTimers){clearTimeout(timer);pending.set(pid,JSON.parse(JSON.stringify(review(pid))));}noteTimers.clear();if(pending.size&&!saveFailed)void drain();}
function updateSaveState(){$('save-state').textContent=saveFailed?'保存に失敗しました':(saving||pending.size||noteTimers.size)?'保存中…':'このPCに保存済み';}
async function drain(){if(saving||saveFailed)return;saving=true;updateSaveState();try{while(pending.size){const [pid,item]=pending.entries().next().value;pending.delete(pid);try{const response=await fetch('/api/review',{method:'POST',headers:{'Content-Type':'application/json','X-Review-Token':token},body:JSON.stringify({...item,revision:revisions[pid]||0})});const result=await response.json();if(!response.ok)throw new Error(result.error||'保存できませんでした');revisions[pid]=result.revision;review(pid).updated_at=result.updated_at;}catch(e){if(!pending.has(pid))pending.set(pid,item);saveFailed=true;showError(`確認結果を保存できませんでした。${e.message}`);break;}}}finally{saving=false;updateSaveState();}}
async function waitForSaves(){flushNotes();await drain();while(saving)await new Promise(r=>setTimeout(r,30));return !saveFailed&&!pending.size;}

function renderList(){const list=filtered();$('post-list').replaceChildren();$('list-count').textContent=`${sampleIds?'ランダム抽出 · ':''}${list.length}投稿を表示`;$('reset-sample').hidden=!sampleIds;for(const p of list){const r=review(p.post_id),button=el('button','post-item'+(p.post_id===currentId?' active':''));button.dataset.pid=p.post_id;button.setAttribute('aria-current',p.post_id===currentId?'true':'false');const img=el('img','post-thumb');img.src=imageUrl(p.images[0]);img.alt='';img.loading='lazy';button.append(img);const meta=el('div');meta.append(el('div','post-title',`投稿 ${String(posts.indexOf(p)+1).padStart(3,'0')}`),el('div','post-sub',`${p.images.length}枚 · ${word(r.status)}`));button.append(meta,el('span',`status-dot ${r.status}`,STATUS_SYMBOL[r.status]));button.onclick=()=>go(p.post_id);$('post-list').append(button);}updateProgress();}
function updateProgress(){const marked=posts.filter(p=>review(p.post_id).status!=='pending').length;$('progress').replaceChildren(el('strong','',marked),document.createTextNode(` / ${posts.length} 投稿を確認`));}
function go(pid){flushNotes();if(!byId.has(pid))return;currentId=pid;imageIndex=0;localStorage.setItem(`pilot-review-position:${fingerprint}`,pid);render();}
function navigate(delta){const list=filtered(),i=list.findIndex(p=>p.post_id===currentId),target=list[i<0?0:i+delta];if(target)go(target.post_id);}
function applyFilter(){flushNotes();const list=filtered();if(!list.some(p=>p.post_id===currentId)){currentId=list[0]?.post_id||'';imageIndex=0;}render();}

function render(){renderList();const p=current();$('empty').hidden=!!p;$('comparison').hidden=!p;$('review-footer').hidden=!p;if(!p){$('post-position').textContent='投稿なし';$('previous').disabled=true;$('next').disabled=true;return;}$('post-position').textContent=`投稿 ${String(posts.indexOf(p)+1).padStart(3,'0')} / ${posts.length}`;$('post-link').href=`https://x.com/i/status/${p.post_id}`;const list=filtered(),i=list.findIndex(x=>x.post_id===currentId);$('previous').disabled=i<=0;$('next').disabled=i>=list.length-1;renderImage();renderLabels();renderReview();}
function renderImage(){const p=current(),im=p.images[imageIndex];$('image-number').textContent=`画像 ${imageIndex+1} / ${p.images.length}${p.images.length>1?' · 下の画像を押して切り替え':''}`;const img=$('main-image');$('image-load-error').hidden=true;img.onload=()=>{if(currentId!==p.post_id)return;const r=review(p.post_id);if(!r.displayed_media.includes(im.media_index)){r.displayed_media.push(im.media_index);scheduleSave(p.post_id);renderReviewStatus();}};img.onerror=()=>{$('image-load-error').hidden=false;};img.alt=`投稿 ${posts.indexOf(p)+1} の画像 ${imageIndex+1}`;img.src=imageUrl(im);$('image-thumbs').replaceChildren();for(const [index,other] of p.images.entries()){const b=el('button',index===imageIndex?'active':'');b.setAttribute('aria-label',`画像${index+1}を表示`);b.setAttribute('aria-pressed',String(index===imageIndex));const thumb=el('img');thumb.src=imageUrl(other);thumb.alt='';b.append(thumb,el('span','',index+1));b.onclick=()=>{imageIndex=index;renderImage();renderLabels();renderReviewStatus();};$('image-thumbs').append(b);}}
function flagKey(scope,field){return `${scope}.${field}`;}
function toggleFlag(key){const r=review();r.flags=r.flags.includes(key)?r.flags.filter(k=>k!==key):[...r.flags,key];if(r.flags.length&&r.status==='pending')r.status='issue';scheduleSave(currentId);renderLabels();renderList();renderReview();}
function attribute(field,a,scope){const key=flagKey(scope,field),flagged=review().flags.includes(key),row=el('div','attribute'+(flagged?' flagged':''));row.dataset.field=key;row.append(el('div','attribute-name',NAMES[field]||(field.startsWith('has_')?`${word(field.slice(4,-5))}の髪`:field)));const content=el('div','attribute-value');if(a.status==='observed')content.append(el('span','',value(a)));else content.append(el('span',`badge ${a.status==='technical_failure'?'failure':'unknown'}`,value(a)));if(a.reason||a.evidence||a.sources?.length){const details=el('details','evidence');details.append(el('summary','',a.status==='observed'?'判定の根拠':'理由を表示'));if(a.reason)details.append(el('p','',a.reason));if(a.evidence)details.append(el('p','',a.evidence));for(const source of a.sources||[]){const link=safeLink(source.url);if(link)details.append(link);}content.append(details);}row.append(content);const flag=el('button','flag-button'+(flagged?' flagged':''),'⚑');flag.title=flagged?'この項目の旗を外す':'この項目が気になる';flag.setAttribute('aria-label',`${NAMES[field]||field}：${flag.title}`);flag.setAttribute('aria-pressed',String(flagged));flag.onclick=()=>toggleFlag(key);row.append(flag);return row;}
function section(title,sub){const n=el('div','section-head');n.append(el('h3','',title));if(sub)n.append(el('span','',sub));return n;}
function detail(title,subtitle){const d=el('details','detail-block'),s=el('summary','',title);if(subtitle)s.append(el('span','',`　${subtitle}`));d.append(s);return d;}
function overview(p,im){
  const box=el('div','overview'),a=im.attributes;
  const subject=el('div','overview-subject');
  for(const field of ['format','subject_types'])subject.append(el('span','badge',value(a[field])));
  subject.append(el('span','badge',a.depiction_count.status==='observed'?`旧・描写回数 ${a.depiction_count.value}`:'旧・描写回数は不明'));
  box.append(subject);
  const colors=COLORS.filter(c=>statusValue(a[`has_${c}_hair`])===true);
  const uncertain=COLORS.some(c=>a[`has_${c}_hair`]?.status!=='observed');
  const hair=el('div','overview-line');hair.append(el('span','overview-key','髪色'));
  if(colors.length)for(const color of colors){const chip=el('span','hair-chip');chip.append(el('i',`swatch ${color}`),document.createTextNode(word(color)));hair.append(chip);}
  else hair.append(el('span','',uncertain?'判別できず':'該当する髪色なし'));
  if(colors.length&&uncertain)hair.append(el('span','small-note','ほかに不明の色あり'));
  const creation=p.context.attributes.creation,origin=el('div','overview-line');origin.append(el('span','overview-key','創作の由来'),el('span',creation.status==='technical_failure'?'badge failure':'',value(creation)));
  box.append(hair,origin);
  box.append(el('p','small-note','この100投稿は旧基準の結果です。描写回数には同じキャラの繰り返しが含まれ、人数とは異なります。'));
  if(REVISION_NOTES[p.post_id])box.append(el('p','revision-note',REVISION_NOTES[p.post_id]));
  return box;
}
function renderLabels(){const p=current(),im=p.images[imageIndex],a=im.attributes,scope=`image${im.media_index}`,container=$('labels');container.replaceChildren();container.append(overview(p,im));container.append(section('画像の判定',`画像 ${imageIndex+1} に対応`));for(const field of ['content_kind','format','subject_types','depiction_count','color_mode','background'])if(a[field])container.append(attribute(field,a[field],scope));
  container.append(section('この画像に見える髪色'));const hairs=el('div','hair-list');let positive=0,unknown=0;for(const color of COLORS){const h=a[`has_${color}_hair`];if(statusValue(h)===true){const chip=el('span','hair-chip');chip.append(el('i',`swatch ${color}`),document.createTextNode(word(color)));hairs.append(chip);positive++;}if(h?.status!=='observed')unknown++;}if(!positive)hairs.append(el('span','badge unknown',unknown?'髪色は判別できず':'該当する髪色なし'));container.append(hairs);if(unknown)container.append(el('p','small-note',`${unknown}色の有無が不明です。「不明」は「なし」と区別しています。`));const hairDetail=detail('髪色ごとの判定を見る');for(const color of COLORS)if(a[`has_${color}_hair`])hairDetail.append(attribute(`has_${color}_hair`,a[`has_${color}_hair`],scope));container.append(hairDetail);
  const extra=detail('その他の画像属性');for(const field of ['background_detail','design_kind','environment','technique','time_of_day','visible_promotion','work_in_progress'])if(a[field])extra.append(attribute(field,a[field],scope));container.append(extra);
  container.append(section('旧版の描写ごとの記録',`${im.depictions.length}描写分`));
  container.append(el('p','small-note','同じキャラの別コマ・別ポーズも別々の記録です。キャラ単位への統合は次版で行います。'));
  if(im.detail_coverage==='partial')container.append(el('p','small-note','小さな対象など、詳しく記録できていない描写が含まれます。'));
  if(!im.depictions.length)container.append(el('p','small-note','詳細な描写対象の記録はありません。'));
  for(const [i,d] of im.depictions.entries()){
    const block=detail(`${i+1}. ${d.location}`,value(d.attributes.body_form));block.open=im.depictions.length===1;
    for(const field of ['body_form','hair_colors','fur_colors','expression'])if(d.attributes[field])block.append(attribute(field,d.attributes[field],`${scope}.${d.id}`));
    const auxiliary=detail('旧版の補助項目','描写範囲・画風など');
    for(const field of ['crop','animal_features','anthropomorphism','style'])if(d.attributes[field])auxiliary.append(attribute(field,d.attributes[field],`${scope}.${d.id}`));
    auxiliary.append(el('p','small-note','「様式化」は普通のアニメ・漫画表現も含みます。頭身の低いちびキャラだけを指す区分ではありません。'));
    block.append(auxiliary);
    if(d.identity){const identity=el('div','identity');identity.append(el('strong','',d.identity.name||word(d.identity.status)));if(d.identity.work)identity.append(el('p','small-note',d.identity.work));if(d.identity.evidence)identity.append(el('p','small-note',d.identity.evidence));for(const source of d.identity.sources||[]){const link=safeLink(source.url);if(link)identity.append(link);}block.append(identity);}container.append(block);
  }
  const context=el('div','context-card');context.append(section('投稿全体の判定','本文・外部資料も使用'));for(const field of ['creation','poster_relation','promotion'])if(p.context.attributes[field])context.append(attribute(field,p.context.attributes[field],'context'));if(p.context.state==='technical_failure')context.append(el('p','context-state','本文や照合先を取得できず、由来などは判定できていません。画像の判定とは別です。'));context.append(el('p','small-note',`追加検索 ${p.context.searches}回 · 参照ページ ${p.context.pages}件`));container.append(context);
}
function renderReview(){const r=review();$('note').value=r.note;for(const s of ['ok','issue','hold']){const button=$(`mark-${s}`);button.classList.toggle('selected',r.status===s);button.setAttribute('aria-pressed',String(r.status===s));}$('flag-count').textContent=r.flags.length?`⚑ ${r.flags.length}項目`:'';renderReviewStatus();}
function renderReviewStatus(){const p=current();if(!p)return;const r=review();$('review-status').textContent=`${word(r.status)} · 画面に表示した画像 ${r.displayed_media.length} / ${p.images.length}枚　｜　AIの元の判定を残したまま、あなたの確認結果を保存します。`;}
function mark(status){const p=current();if(!p)return;flushNotes();const list=filtered(),i=list.findIndex(x=>x.post_id===p.post_id),next=list[i+1]||null;review().status=status;scheduleSave(currentId);if(status!=='pending'&&$('auto-next').checked&&next){go(next.post_id);}else{renderList();renderReview();}}
function openZoom(){if(!current())return;$('zoom-image').src=imageUrl(current().images[imageIndex]);$('zoom-image').classList.remove('actual');$('zoom-size').textContent='原寸で見る';$('zoom-dialog').showModal();}

$('filter').onchange=applyFilter;$('search').oninput=applyFilter;
$('previous').onclick=()=>navigate(-1);$('next').onclick=()=>navigate(1);
$('sample').onclick=()=>{const pool=[...posts];for(let i=pool.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[pool[i],pool[j]]=[pool[j],pool[i]];}sampleIds=new Set(pool.slice(0,10).map(p=>p.post_id));$('filter').value='all';$('search').value='';currentId='';applyFilter();};
$('reset-sample').onclick=()=>{sampleIds=null;applyFilter();};
for(const status of ['ok','issue','hold','pending'])$(`mark-${status}`).onclick=()=>mark(status);
$('note').oninput=()=>{const pid=currentId;if(!pid)return;review(pid).note=$('note').value;if(noteTimers.has(pid))clearTimeout(noteTimers.get(pid));noteTimers.set(pid,setTimeout(()=>scheduleSave(pid),450));updateSaveState();};
$('note').onblur=flushNotes;
$('auto-next').checked=localStorage.getItem('pilot-review-auto-next')!=='false';$('auto-next').onchange=()=>localStorage.setItem('pilot-review-auto-next',String($('auto-next').checked));
$('retry').onclick=()=>{saveFailed=false;clearError();flushNotes();void drain();};
$('export').onclick=async()=>{if(!await waitForSaves())return;const a=el('a');a.href='/api/export';a.download=`${runId}-human-review.json`;document.body.append(a);a.click();a.remove();};
$('image-stage').onclick=openZoom;$('zoom').onclick=openZoom;$('close-zoom').onclick=()=>$('zoom-dialog').close();$('zoom-size').onclick=()=>{$('zoom-image').classList.toggle('actual');$('zoom-size').textContent=$('zoom-image').classList.contains('actual')?'全体を表示':'原寸で見る';};
document.addEventListener('keydown',e=>{if(['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName)||e.ctrlKey||e.metaKey||e.altKey||$('zoom-dialog').open)return;if(e.key==='ArrowLeft'){e.preventDefault();navigate(-1);}if(e.key==='ArrowRight'){e.preventDefault();navigate(1);}if(['1','2','3'].includes(e.key)){e.preventDefault();mark({'1':'ok','2':'issue','3':'hold'}[e.key]);}});
window.addEventListener('beforeunload',e=>{flushNotes();if(pending.size||saving||noteTimers.size){e.preventDefault();e.returnValue='';}});

(async()=>{try{const r=await fetch('/api/data');if(!r.ok)throw new Error('データを読み込めませんでした');const data=await r.json();posts=data.posts;byId=new Map(posts.map(p=>[p.post_id,p]));reviews=data.review.reviews;for(const [pid,item] of Object.entries(reviews))revisions[pid]=item.revision;token=data.token;runId=data.run_id;fingerprint=data.fingerprint;$('total-count').textContent=`${posts.length} POSTS`;const last=localStorage.getItem(`pilot-review-position:${fingerprint}`);currentId=byId.has(last)?last:posts[0]?.post_id||'';$('loading').hidden=true;$('app').hidden=false;render();updateSaveState();}catch(e){$('loading').textContent='読み込みに失敗しました。起動ツールから開き直してください。';showError(e.message);}})();
