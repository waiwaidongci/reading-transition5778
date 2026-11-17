import {research} from '../stores/research.js';
import {session} from '../stores/session.js';
import {sourcesApi,dictionaryApi} from '../api/research.js';
import {sourceOptions} from '../components/common/business.js';
import {dictStates,backfillStates} from '../constants/enums.js';
import {esc,localTime} from '../utils/format.js';
import {action,toast,bind} from '../hooks/actions.js';

let versions=[];let records=[];

async function load(){
  versions=research.sourceId?await dictionaryApi.versions(research.sourceId):[];
  records=research.sourceId?await sourcesApi.records(research.sourceId):[];
}
function pct(job){
  if(!job||!job.total_sessions)return 0;
  return Math.min(100,Math.round(job.processed_sessions/job.total_sessions*100));
}
function versionCard(v){
  const job=v.backfill;
  const isActive=research.sources.find(s=>s.id==research.sourceId)?.active_version_id===v.id;
  return '<article class="dict-version '+esc(v.state)+'">'
    +'<header><small>v'+v.version+'</small><span class="status '+esc(v.state)+'">'+esc(dictStates[v.state]||v.state)+'</span>'
    +(isActive?'<span class="status completed">页面当前版本</span>':'')+'</header>'
    +'<p class="fine">'+esc(v.created_by)+' · '+esc(localTime(v.created_at))+(v.published_at?' · 发布于 '+esc(localTime(v.published_at)):'')+'</p>'
    +'<p class="alias-count">别名条目 '+v.aliases.length+' 条'
    +(v.aliases.length?'：'+v.aliases.slice(0,6).map(([o,n])=>esc(o)+'→'+esc(n)).join('，')+(v.aliases.length>6?' 等':''):'（空词典＝完整旧版原文）')+'</p>'
    +(job?'<div class="backfill"><div class="progress"><i style="width:'+pct(job)+'%"></i></div>'
      +'<small>'+esc(backfillStates[job.state]||job.state)+' · '+job.processed_sessions+'/'+job.total_sessions+' 会话 · 尝试 '+job.attempts+' 次</small>'
      +(job.state==='failed'?'<p class="failure-reason">失败原因：'+esc(job.error)+'</p>':'')+'</div>':'<p class="fine">空词典基线无需回填，始终完整可用</p>')
    +(session.writable?'<footer>'
      +(v.state==='building'&&job&&job.state==='completed'?'<button data-publish="'+v.id+'">发布这一版（原子切换）</button>':'')
      +(v.state==='building'&&job&&(job.state==='failed'||job.state==='completed')?'<button class="secondary" data-retry="'+job.id+'">重试/补齐回填</button>':'')
      +(isActive&&v.aliases.length?'<button class="secondary" data-revert>撤销合并，恢复原文</button>':'')
      +'</footer>':'')+'</article>';
}

export async function dictionaryPage(){
  await load();
  const selected=research.sources.find(s=>s.id==research.sourceId);
  const busy=versions.some(v=>v.backfill&&['queued','running'].includes(v.backfill.state));
  return '<section class="page-heading"><p class="eyebrow">03 / CHAPTER DICTIONARY</p><h1>同章旧名新名，归一到同一终点。</h1>'
    +'<p>别名链一律归到终点章节；循环引用与一名多义直接拒绝。原始路径永久保留在样本中，归一仅折叠连续同章后重算接续与全部分母。回填中的版本不发布，页面只见完整旧版或新版。</p></section>'
    +'<label class="compact">来源文集<select id="dict-source-select">'+sourceOptions(research.sources,research.sourceId)+'</select></label>'
    +(busy?'<p class="fine"><span class="spinner"></span> 十万级会话回填分批进行，进度自动刷新；期间仍可追加新会话，发布前会要求全部纳入。</p>':'')
    +'<div class="split dict-split"><section><h2>词典版本账册</h2>'
    +(versions.length?versions.map(versionCard).join(''):'<div class="empty">该文集还没有词典版本，系统将在首次研究时自动建立 v1 空词典基线。</div>')
    +'<h2>样本路径对照（前8条）<small>原始路径保留，归一列随发布版原子切换</small></h2>'
    +'<div class="table-wrap"><table><thead><tr><th>样本编号</th><th>原始路径</th><th>当前发布版归一路径</th></tr></thead><tbody>'
    +records.slice(0,8).map(r=>'<tr><td>'+esc(r.reference)+'</td><td>'+esc(r.values.path)+'</td><td>'+esc(r.canonical_path)+'</td></tr>').join('')
    +'</tbody></table></div></section>'
    +'<aside class="entry-sheet">'+(session.writable?'<h2>切一版新词典</h2>'
    +'<p class="fine">每行一条「旧名 → 新名」，可多级成链；受理中的研究会锁定词典与输入。</p>'
    +'<form id="alias-form"><div id="alias-rows">'
    +[0,1].map(i=>'<div class="alias-row"><input name="old" placeholder="旧名（如 楔子）" maxlength="120"><span>→</span><input name="new" placeholder="新名（如 开篇）" maxlength="120"><button type="button" class="secondary" data-remove>删</button></div>').join('')
    +'</div><button type="button" class="secondary" id="add-alias-row">再加一条别名</button>'
    +'<div id="alias-preview" class="alias-preview" hidden></div>'
    +'<button type="button" id="alias-validate">先校验别名链</button>'
    +'<button type="submit">提交切版并开始回填 →</button></form>'
    +'<details><summary>切版规则说明</summary><p class="fine">① 别名链归到终点，如 楔子→序章→开篇，最终都按「开篇」计数；② 循环（甲→乙→甲）与一名多义（同章指向两个新名）拒绝切版；③ 连续同章折叠后不再产生接续边，条件概率、基率、提升度的分母全部按归一后路径重算；④ 回填可中断恢复，重试幂等不新增接续；⑤ 并发切版串行，同时只有一个回填中版本，发布是原子切换。</p></details>'
    :'<h2>版本阅读权限</h2><p>可查看全部词典版本、回填进度与失败原因；切版、发布与撤销由分析师或负责人执行。</p>')+'</aside></div>';
}

function aliasRows(){
  return [...document.querySelectorAll('#alias-rows .alias-row')].map(row=>{
    const inputs=row.querySelectorAll('input');
    return {old:inputs[0].value.trim(),new:inputs[1].value.trim()};
  }).filter(x=>x.old&&x.new);
}
function addAliasRow(){
  const div=document.createElement('div');div.className='alias-row';
  div.innerHTML='<input name="old" placeholder="旧名" maxlength="120"><span>→</span><input name="new" placeholder="新名" maxlength="120"><button type="button" class="secondary" data-remove>删</button>';
  document.getElementById('alias-rows').appendChild(div);
  div.querySelector('[data-remove]').onclick=()=>div.remove();
}

export function bindDictionary(refresh){
  bind('#dict-source-select','change',async e=>{research.sourceId=Number(e.target.value);research.page=0;await refresh()});
  bind('#add-alias-row','click',addAliasRow);
  document.querySelectorAll('#alias-rows [data-remove]').forEach(b=>b.onclick=()=>b.closest('.alias-row').remove());
  bind('#alias-validate','click',async()=>{
    const box=document.getElementById('alias-preview');
    try{
      const r=await dictionaryApi.preview(research.sourceId,aliasRows());
      box.hidden=false;box.className='alias-preview ok';
      box.innerHTML='<b>校验通过，别名链终点：</b>'+Object.entries(r.mapping).map(([o,t])=>esc(o)+' → '+esc(t)).join('；');
      toast('别名链校验通过');
    }catch(e){box.hidden=false;box.className='alias-preview error';box.textContent=e.message;toast(e.message,true)}
  });
  action('#alias-form',async ()=>{
    const aliases=aliasRows();
    const v=await dictionaryApi.create(research.sourceId,aliases);
    toast('新词典 v'+v.version+' 已进入回填队列，完成后可发布');
    await refresh();
  });
  for(const b of document.querySelectorAll('[data-publish]'))b.onclick=async()=>{
    try{await dictionaryApi.publish(b.dataset.publish);toast('已原子切换，页面现在只见新版');await refresh()}catch(e){toast(e.message,true)}
  };
  for(const b of document.querySelectorAll('[data-retry]'))b.onclick=async()=>{
    try{await dictionaryApi.retry(b.dataset.retry);toast('已从断点继续回填，不新增重复接续');await refresh()}catch(e){toast(e.message,true)}
  };
  bind('[data-revert]','click',async()=>{
    try{await dictionaryApi.revert(research.sourceId);toast('已撤销合并，归一路径恢复为原文');await refresh()}catch(e){toast(e.message,true)}
  });
  if(versions.some(v=>v.backfill&&['queued','running'].includes(v.backfill.state)))setTimeout(refresh,2000);
}
