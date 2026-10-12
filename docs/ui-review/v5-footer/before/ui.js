/* Shared original UI primitives. Buildless and usable from file://. */
window.UI = (() => {
  const paths={
    arrow:'M5 12h14m-6-6 6 6-6 6',back:'m14 6-6 6 6 6',chevron:'m9 6 6 6-6 6',check:'m5 12 4 4L19 6',close:'m6 6 12 12M18 6 6 18',
    home:'m3 10 9-7 9 7M5 9v11h5v-7h4v7h5V9',book:'M3 4h7l2 2 2-2h7v15h-7l-2 2-2-2H3V4m9 2v15',user:'M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0M4 21v-3a8 8 0 0 1 16 0v3',
    chart:'M4 3v18h17M8 16v-5m5 5V6m5 10v-8',file:'M14 3H5v18h14V8l-5-5v5h5M8 12h8m-8 4h6',link:'m10 13 4-4M8 16l-1 1a4 4 0 0 1-5-5l4-4a4 4 0 0 1 5 0m2 0 1-1a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-5 0',
    video:'M4 4h16v16H4zM10 8l6 4-6 4V8',spark:'m12 2 2.5 7.5L22 12l-7.5 2.5L12 22l-2.5-7.5L2 12l7.5-2.5L12 2',bolt:'m13 2-9 12h7l-1 8 10-13h-7l0-7',
    coin:'M20 12a8 8 0 1 1-16 0 8 8 0 0 1 16 0m-8-4v8m-2-6h4m-4 4h4',clock:'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0M12 7v5l4 2',search:'M16 10a6 6 0 1 1-12 0 6 6 0 0 1 12 0m-2 4 6 6',
    folder:'M3 6h7l2 2h9v12H3V6',plus:'M12 5v14M5 12h14',upload:'M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6',download:'M12 3v13m-5-5 5 5 5-5M4 16v5h16v-5',
    flag:'M5 21V3m0 0h12l-2 4 2 4H5',trophy:'M7 3h10v7a5 5 0 0 1-10 0V3M7 5H3v4a4 4 0 0 0 4 4m10-8h4v4a4 4 0 0 1-4 4M12 15v5m-4 1h8',
    shield:'m12 2 8 3v7c0 5-8 10-8 10S4 17 4 12V5l8-3m-4 9 3 3 5-6',bell:'M6 9a6 6 0 0 1 12 0v7l2 2H4l2-2V9m4 12h4',settings:'m9 3-1 3-3 1-2 3 2 2-1 3 2 3h3l2 3 3-1 1-3 3-1 2-3-2-2 1-3-2-3h-3l-2-3H9m6 9a3 3 0 1 1-6 0 3 3 0 0 1 6 0',
    refresh:'M20 9a8 8 0 1 0 0 7M20 3v6h-6',wifi:'M3 8a14 14 0 0 1 18 0M6 12a9 9 0 0 1 12 0m-9 4a4 4 0 0 1 6 0m-3 4h0',mic:'M9 5a3 3 0 0 1 6 0v7a3 3 0 0 1-6 0V5M6 10v2a6 6 0 0 0 12 0v-2M12 18v4m-4 0h8',
    sound:'M3 9h4l5-5v16l-5-5H3V9m13-1a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14',share:'M12 15V3m-4 4 4-4 4 4M5 12v9h14v-9',lock:'M7 10V7a5 5 0 0 1 10 0v3M5 10h14v12H5V10m7 5v3',
    star:'m12 2 3 6 7 1-5 5 1 7-6-3-6 3 1-7-5-5 7-1 3-6',mail:'M3 5h18v14H3V5m0 1 9 7 9-7',eye:'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12m13 0a3 3 0 1 1-6 0 3 3 0 0 1 6 0',trash:'M4 6h16M9 6V3h6v3M6 6l1 15h10l1-15m-8 4v7m4-7v7',expand:'M8 3H3v5m13-5h5v5M3 16v5h5m8 0h5v-5',help:'M9 8a3 3 0 1 1 5 2c-2 1-2 2-2 4m0 4h0M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',heart:'M12 21 3 12a5 5 0 0 1 9-6 5 5 0 0 1 9 6l-9 9',signal:'M4 19v-4m5 4v-7m5 7V8m5 11V4'
  };
  const icon=(n,cls='')=>`<svg class="${cls}" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[n]||paths.spark}"/></svg>`;
  const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const files={L:'01-core-learning.html',R:'02-review-center.html',K:'03-knowledge-library.html',S:'04-social-challenge.html',A:'05-account-and-extensions.html',E:'06-states.html'};
  const url=id=>`${files[id[0]]}?screen=${id}`;
  const btn=(label,id='',kind='',extra='')=>id?`<a class="btn ${kind}" href="${url(id)}" ${extra}>${label}</a>`:`<button type="button" class="btn ${kind}" ${extra}>${label}</button>`;
  const tag=(s,c='')=>`<span class="tag ${c}">${s}</span>`;
  const title=(s,sub='')=>`<h1 class="page-title">${s}</h1>${sub?`<p class="body-copy">${sub}</p>`:''}`;
  const section=(s,id='',link='查看全部')=>`<h2 class="section-title">${s}${id?`<a class="text-btn" href="${url(id)}">${link}${icon('chevron')}</a>`:''}</h2>`;
  const mascot=(who='u',cls='')=>`<img class="mascot ${cls}" src="assets/${{u:'u-book',pencil:'pencil',paper:'paper'}[who]}.png" alt="${{u:'小U，U形书灵',pencil:'笔仔，涂鸦铅笔同学',paper:'团团，纸团探险家'}[who]}" loading="lazy">`;
  const hero=(s,sub='',who='u')=>`<div class="hero-small">${title(s,sub)}${mascot(who)}</div>`;
  const stage=(who='u',sticker='',yellow=false)=>`<div class="hero-stage ${yellow?'yellow':''}"><span class="spark" aria-hidden="true">✧</span>${mascot(who)}${sticker?`<span class="sticker">${sticker}</span>`:''}</div>`;
  const buddy=(s,who='u')=>`<div class="buddy-note">${mascot(who)}<div class="bubble">${s}</div></div>`;
  const row=(name,sub='',ico='book',id='',end='',color='')=>`<${id?'a':'div'} class="list-row" ${id?`href="${url(id)}"`:''}><span class="icon-tile ${color}">${icon(ico)}</span><div class="list-text"><strong>${name}</strong>${sub?`<p>${sub}</p>`:''}</div>${end?`<span class="list-end">${end}</span>`:''}${id?icon('chevron','chevron'):''}</${id?'a':'div'}>`;
  const progress=(n=1,total=5,xp=0)=>`<div class="quiz-progress"><span>${n} / ${total}</span><div class="progress-track"><span style="width:${n/total*100}%"></span></div><span class="xp">${icon('bolt')}${xp} XP</span></div>`;
  const stat=(arr,two=false)=>`<div class="stat-grid ${two?'two':''}">${arr.map(([v,l])=>`<div><b>${v}</b><span>${l}</span></div>`).join('')}</div>`;
  const mastery=(s,v,c='')=>`<div class="mastery-row"><div class="row"><span>${s}</span><b>${v}%</b></div><div class="progress-track ${c}"><span style="width:${v}%"></span></div></div>`;
  const input=(label,placeholder,value='',attrs='')=>`<div class="field"><label>${label}<input class="input" placeholder="${placeholder}" value="${esc(value)}" ${attrs}></label></div>`;
  const chips=(values,active=0)=>`<div class="chips" data-chips>${values.map((v,i)=>`<button class="chip ${i===active?'active':''}" type="button" aria-pressed="${i===active}">${v}</button>`).join('')}</div>`;
  const segments=arr=>`<div class="segmented" data-segments>${arr.map((s,i)=>`<button type="button" class="${i===0?'active':''}" aria-pressed="${i===0}">${s}</button>`).join('')}</div>`;
  const toggle=(label,on=true)=>`<button class="toggle" type="button" role="switch" aria-label="${label}" aria-checked="${on}"></button>`;
  const file=(name='HTTP 学习笔记.pdf',meta='12 页 / 2.4 MB',status='已就绪')=>`<div class="file-card"><span class="icon-tile">${icon('file')}</span><div class="file-details"><b>${name}</b><p>${meta}</p></div>${tag(status,status==='已就绪'?'green':'blue')}</div>`;
  const steps=(arr,current=1)=>`<ol class="steps">${arr.map(([s,d],i)=>`<li class="${i<current?'done':i===current?'current':''}"><span class="step-icon">${i<current?icon('check'):i+1}</span><div><strong>${s}</strong><p>${d}</p></div></li>`).join('')}</ol>`;
  const trend=()=>`<svg class="chart" viewBox="0 0 300 142" role="img" aria-label="示例正确率趋势，10月5日至11日，从50%上升至80%"><path class="axis" d="M29 12H290M29 62H290M29 112H290"/><text x="0" y="16">100%</text><text x="8" y="66">50%</text><text x="15" y="116">0%</text><path d="M30 62 73 52 116 62 159 32 202 42 245 22 288 32V112H30Z" fill="#edf3ff"/><path d="m30 62 43-10 43 10 43-30 43 10 43-20 43 10" fill="none" stroke="#336ae8" stroke-width="2.5"/><circle cx="288" cy="32" r="4" fill="#336ae8"/><text x="29" y="134">10/05</text><text x="143" y="134">10/08</text><text x="264" y="134">10/11</text></svg>`;
  const config=()=>`<details><summary>出题设置 <span class="muted small">5 题 / 入门</span></summary><div class="config-row"><span>题量</span><select aria-label="题量"><option>5 题</option><option>3 题</option></select></div><div class="config-row"><span>难度</span><select aria-label="难度"><option>入门</option><option>进阶</option></select></div></details>`;
  const source=()=>`<a class="source-link" href="${url('K05')}">${icon('link')}查看知识来源${icon('chevron')}</a>`;
  const materials=()=>`<div class="material-grid"><a href="${url('L02')}">${icon('file')}文档</a><a href="${url('L03')}">${icon('link')}网页</a><a href="${url('L04')}">${icon('video')}视频</a></div>`;
  const crew=()=>`<div class="poster-crew">${mascot('pencil')}${mascot('u')}${mascot('paper')}</div>`;
  const notice=(s='当前为原型演示，不连接真实服务')=>`<p class="business-notice">${s}</p>`;
  return {icon,esc,files,url,btn,tag,title,section,mascot,hero,stage,buddy,row,progress,stat,mastery,input,chips,segments,toggle,file,steps,trend,config,source,materials,crew,notice};
})();
