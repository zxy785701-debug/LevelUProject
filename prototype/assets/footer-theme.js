/* 已确认的 E 版视觉：仅应用到原底部黄色主按钮所在页面。 */
window.FooterTheme = (() => {
  const primary = '.btn:not(.secondary):not(.blue):not(.danger)';
  const dynamic = new Set(['L09', 'L11', 'A08']);
  const records = SCREENS.flatMap(screen => {
    const fragment = document.createElement('div');
    fragment.innerHTML = screen.footer ? screen.footer() : '';
    if (fragment.querySelector(primary)) return [{id:screen.id, kind:'footer'}];
    if (dynamic.has(screen.id)) return [{id:screen.id, kind:'dynamic'}];
    if (screen.id === 'L14') return [{id:screen.id, kind:'sheet'}];
    return [];
  });
  const ids = new Set(records.map(record => record.id));
  const phrases = {
    L02:'变成关卡', L03:'新关卡', L04:'学进去', L05:'整理一下',
    L06:'学这些', L07:'正在成形', L08:'认识一下', L14:'歇一下',
    L15:'搞懂了一点', L16:'正在整理', L17:'与会话', L18:'分享出去',
    L19:'下一关', L21:'串起来了', R03:'与会话', R06:'学习的旅程',
    R07:'更懂一点', R08:'再懂一次。', R10:'再遇见它们', R12:'新理解',
    R13:'该见个面了', K01:'一个小书架', K02:'计算机基础', K03:'新主题',
    K04:'新知识', K05:'学习笔记', K06:'从书架里学', S02:'叫上朋友',
    S03:'已到位', S05:'更有用', S07:'会传染', A02:'学习旅程',
    A04:'多一点空间', A05:'多一点额度', A06:'学习权益', A07:'模拟支付',
    A09:'讲给搭子听', E01:'从一个问题开始', E02:'再加一点线索',
    E03:'这份内容', E04:'不能解析', E05:'中断了', E06:'生成关卡',
    E07:'再等一小会儿', E08:'进度还在', E09:'保存图片'
  };
  const bookPath = new DOMParser().parseFromString(UI.icon('book'), 'text/html')
    .querySelector('path').getAttribute('d');
  function decorate(card) {
    if (!card || !ids.has(card.dataset.id)) return;
    const heading = card.querySelector('.page-title, .sheet h2');
    card.classList.toggle('question-layout', !heading);
    if (heading && !heading.querySelector('.handline')) {
      const walker = document.createTreeWalker(heading, NodeFilter.SHOW_TEXT);
      const nodes = [];
      while (walker.nextNode()) nodes.push(walker.currentNode);
      const phrase = phrases[card.dataset.id];
      let node = phrase && nodes.find(n => n.textContent.includes(phrase));
      let mark = phrase;
      if (!node) {
        node = nodes.filter(n => n.textContent.trim()).at(-1);
        // 状态切换后的标题也保持短划线；长题干不会进入这里。
        mark = node?.textContent.trim().replace(/[。！？，、]$/u, '').slice(-7);
      }
      if (node && mark) {
        const start = node.textContent.indexOf(mark);
        const range = document.createRange();
        range.setStart(node, start);
        range.setEnd(node, start + mark.length);
        const span = document.createElement('span');
        span.className = 'handline';
        range.surroundContents(span);
      }
    }
    card.querySelectorAll('.list-row').forEach(row => {
      if (row.querySelector('.icon-tile path')?.getAttribute('d') === bookPath) {
        row.classList.add('text-led');
      }
    });
    card.querySelectorAll('.content > p.small.muted.mt').forEach(note => {
      note.classList.add('review-note');
    });
  }
  const decorateAll = () => document.querySelectorAll('.footer-refined').forEach(decorate);
  return {ids, records, decorate, decorateAll};
})();
