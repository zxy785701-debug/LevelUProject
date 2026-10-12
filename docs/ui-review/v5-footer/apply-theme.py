"""Apply the approved E style to the existing interactive prototype."""
from pathlib import Path

root = Path(__file__).resolve().parents[3]
path = root / 'prototype/assets/app.js'
source = path.read_text(encoding='utf-8')

def replace_once(before, after):
    global source
    assert source.count(before) == 1, f'Unexpected occurrence count: {before[:100]}'
    source = source.replace(before, after, 1)

replace_once('<article class="screen-card" data-id="${s.id}"',
             '<article class="screen-card ${FooterTheme.ids.has(s.id)?\'footer-refined\':\'\'}" data-id="${s.id}"')
replace_once('<a href="00-design-system.html">设计规范</a>',
             '<a href="00-design-system.html">设计规范</a><a href="07-footer-review.html">本次验收</a>')
replace_once(' / 2026.10.11', ' / 2026.10.12')
replace_once('<div class="index-section-title" id="directory">',
             '<a class="system-link footer-review-link" href="07-footer-review.html"><div><h2>查看本次风格更新</h2><p>55 个页面与状态：蓝色底部主按钮、黄色标题划线和清晰的辅助说明。</p></div>${U.icon(\'arrow\')}</a><div class="index-section-title" id="directory">')

review = '''  let reviewGroup='all';
  function footerReview(){
    const priority=['R08','L02','S05'];
    const list=[...priority.map(id=>SCREENS.find(s=>s.id===id)),...SCREENS.filter(s=>FooterTheme.ids.has(s.id)&&!priority.includes(s.id))];
    document.title='底部按钮风格验收 · LevelUProject';
    return `<main class="site-main"><div class="page-heading"><div><div class="file-index">LevelUProject / 本次风格验收</div><h1>蓝色行动，黄色呼应。</h1><p>以你调整后的错题本为基准，统一底部主按钮、标题划线、列表字级与说明留白。</p></div><a class="text-btn" href="index.html">${U.icon('back')}全部原型</a></div><div class="footer-review-intro"><strong>${list.length} 个页面与状态已更新</strong>。作答页面先选择答案，即可查看新出现的蓝色底部按钮。暂停弹层也已同步；不可用按钮仍显示灰色。</div><div class="review-tools"><nav class="group-tabs footer-review-tabs" aria-label="验收分组"><button type="button" class="active" aria-pressed="true" data-footer-group="all">全部<small>${list.length}</small></button>${Object.entries(groups).map(([id,g])=>`<button type="button" aria-pressed="false" data-footer-group="${id}">${g.short}<small>${list.filter(s=>s.group===id).length}</small></button>`).join('')}</nav><label><span class="sr-only">搜索本次更新页面</span><input class="review-search" data-gallery-search placeholder="搜索名称或编号"></label></div><div class="gallery">${list.map(phone).join('')}<p class="no-search" hidden data-no-search>没有匹配页面，请换个关键词或分组。</p></div></main>`;
  }
  function filterGallery(){
    const q=$('[data-gallery-search]')?.value.toLowerCase().trim()||'';
    let count=0;
    $$('.screen-card').forEach(card=>{
      const inGroup=page!=='footer-review'||reviewGroup==='all'||card.dataset.id[0]===reviewGroup;
      card.hidden=!(inGroup&&card.dataset.search.toLowerCase().includes(q));
      if(!card.hidden)count++;
    });
    const empty=$('[data-no-search]');if(empty)empty.hidden=count>0;
  }
'''
replace_once('  function system(){', review+'  function system(){')
replace_once('原创设计系统 v3', '原创设计系统 v5')
replace_once("block('主行动有明确分量','主按钮用黄色和轻硬投影；按下时下沉。次行动安静，禁用说明仍可读。',`<div class=\"component-demo stack\">",
             "block('底部行动，统一用蓝','底部主按钮使用蓝色、50px 高度与 12px 圆角；标题用黄色划线呼应。次要行动使用细边框，禁用状态保持灰色。',`<div class=\"component-demo stack footer-style-sample\">")
replace_once("${U.btn('生成我的关卡','','','data-action=\"sample-button\"')}",
             "${U.btn('开始复习','','','data-action=\"sample-button\"')}")
replace_once("page==='system'?system():gallery()", "page==='system'?system():page==='footer-review'?footerReview():gallery()")
replace_once("+siteFooter();\n", "+siteFooter();\n  FooterTheme.decorateAll();\n")
old_filter="if(t.matches('[data-gallery-search]')){const q=t.value.toLowerCase().trim();let count=0;$$('.screen-card').forEach(c=>{c.hidden=!c.dataset.search.toLowerCase().includes(q);if(!c.hidden)count++});$('[data-no-search]').hidden=count>0}"
replace_once(old_filter, "if(t.matches('[data-gallery-search]'))filterGallery();")
old_review="    if(id==='R08'){const list=$$('.list-row',card),names=index===1?['HTTP 无状态的含义','Cookie 通常保存在哪里','如何识别同一用户']:['哪些方式可以识别用户会话？','闭包中的变量什么时候释放？','条件概率中分母代表什么？'];list.forEach((el,i)=>{el.querySelector('strong').textContent=names[i];el.querySelector('.list-end').innerHTML=U.tag(index===1?'已巩固':['今日复习','待巩固','待巩固'][i],index===1?'green':'yellow')});toast(index===1?'显示已巩固示例记录':'显示待巩固示例记录')}"
new_review='''    if(id==='R08'){
      const mastered=$$('[data-segments] button',card).findIndex(b=>b.classList.contains('active'))===1;
      const topic=$$('[data-chips] button',card).findIndex(b=>b.classList.contains('active'));
      const pending=[['HTTP 会话识别','多选题 · 今天答错'],['闭包中的变量释放','JavaScript · 单选题 · 昨天答错'],['条件概率的分母','概率 · 单选题 · 10月9日答错']];
      const learned=[['HTTP 无状态的含义','单选题 · 今天掌握'],['Cookie 的保存位置','计算机 · 单选题 · 昨天掌握'],['条件概率的计算','概率 · 单选题 · 10月9日掌握']];
      $$('[data-review-rows] .list-row',card).forEach((row,i)=>{
        const data=(mastered?learned:pending)[i];
        $('.list-text strong',row).textContent=data[0];$('.list-text p',row).textContent=data[1];
        let end=$('.list-end',row);
        if(!end){end=document.createElement('span');end.className='list-end';row.insertBefore(end,$('.chevron',row))}
        end.innerHTML=mastered?U.tag('已掌握','green'):i===0?U.tag('今天复习','red'):'';
        row.hidden=topic!==0&&(topic===1?i===2:i!==2);
      });
      if(parent.matches('[data-segments]'))toast(mastered?'显示已掌握示例记录':'显示待复习示例记录');
    }'''
replace_once(old_review, new_review)
replace_once("    if(id==='S06'){$$('.rank-xp',card).forEach((e,i)=>e.textContent=([680,620,590,320][i]*(index+1))+' XP');toast('已切换'+button.textContent+'示例榜单')}\n  }",
             "    if(id==='S06'){$$('.rank-xp',card).forEach((e,i)=>e.textContent=([680,620,590,320][i]*(index+1))+' XP');toast('已切换'+button.textContent+'示例榜单')}\n    FooterTheme.decorate(card);\n  }")
replace_once("$('[data-payment-description]').textContent=map[1]}",
             "$('[data-payment-description]').textContent=map[1];FooterTheme.decorate($('[data-payment-title]').closest('.screen-card'))}")
replace_once("if(b.matches('[data-adjust-example]'))", "if(b.matches('[data-footer-group]')){reviewGroup=b.dataset.footerGroup;$$('[data-footer-group]').forEach(tab=>{tab.classList.toggle('active',tab===b);tab.setAttribute('aria-pressed',tab===b)});filterGallery()}\n    if(b.matches('[data-adjust-example]'))")
replace_once("  if(focusId==='L01'&&store.get('saved-progress',false)&&savedRound&&!savedRound.complete)toast('上次未完成的学习进度已保留，可继续这一关');",
             "  FooterTheme.decorateAll();\n  if(focusId==='L01'&&store.get('saved-progress',false)&&savedRound&&!savedRound.complete)toast('上次未完成的学习进度已保留，可继续这一关');")
path.write_text(source, encoding='utf-8')
print('Applied approved footer style and acceptance gallery.')
