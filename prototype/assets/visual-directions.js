/* Independent visual study. Original assets are read, never modified. */
(() => {
  const proposals = [
    { id: 'a', letter: 'A', title: '晴蓝 · 清爽闯关', label: '推荐',
      description: '蓝色顶栏建立识别，淡蓝底托起白色内容。',
      colors: ['#336AE8', '#EDF3FF', '#FFFFFF', '#FFD84D'],
      notes: ['顶部：状态栏与导航连成一块蓝色。', '背景：浅蓝纸底，叠卡线条只留在页角。', '气质：清楚、轻快，与现有蓝色按钮最连贯。'] },
    { id: 'b', letter: 'B', title: '晴黄 · 灵感笔记', label: '更活泼',
      description: '浅黄顶栏接住标题黄线，格纹带来笔记感。',
      colors: ['#FFDF70', '#FFFCF2', '#FFFFFF', '#336AE8'],
      notes: ['顶部：柔和的课本黄，配深色文字。', '背景：低对比方格，白色卡片隔开内容。', '气质：亲切、有学习氛围，颜色存在感更强。'] },
    { id: 'c', letter: 'C', title: '薄荷 · 轻盈书页', label: '更柔和',
      description: '薄荷色从导航延伸下来，白纸形成安静层次。',
      colors: ['#CDECE2', '#F1F8F5', '#FFFFFF', '#336AE8'],
      notes: ['顶部：浅薄荷色向下延伸，留出呼吸感。', '背景：叠纸轮廓与白色内容区形成层次。', '气质：柔和、耐看，品牌表达比 A 更轻。'] }
  ];
  const allowedScreens = ['L02', 'L09', 'L15'];
  const requested = new URLSearchParams(location.search).get('screen');
  let selectedScreen = allowedScreens.includes(requested) ? requested : 'L02';
  let showOriginal = false;
  const grid = document.getElementById('proposal-grid');

  function phone(screen) {
    return `<article class="screen-card footer-refined ${screen.id === 'L09' ? 'question-layout' : ''}" data-id="${screen.id}">
      <div class="phone">
        <div class="status-bar"><span>9:41</span><span class="status-icons">${UI.icon('signal')}${UI.icon('wifi')}<span class="battery"><b></b></span></span></div>
        <div class="mini-bar"><span class="mini-title"><span class="mini-back" aria-hidden="true">${UI.icon('back')}</span><span class="mini-label">${screen.bar || screen.name}</span></span><div class="wechat-capsule" aria-label="微信小程序胶囊示意"><span class="capsule-divider"></span></div></div>
        <div class="phone-scroll" tabindex="0" role="region" aria-label="${screen.name}视觉预览，可滚动"><div class="content">${screen.render()}</div></div>
        ${screen.footer ? `<div class="phone-bottom">${screen.footer()}</div>` : ''}
        <div class="home-indicator"></div>
      </div>
    </article>`;
  }

  function render() {
    const screen = SCREENS.find(item => item.id === selectedScreen);
    grid.innerHTML = proposals.map(proposal => `<section class="proposal ${showOriginal ? 'original' : `theme-${proposal.id}`}" data-proposal="${proposal.id}">
      <div class="proposal-heading"><div class="proposal-title"><span class="proposal-letter">${proposal.letter}</span><h2>${proposal.title}</h2><span class="proposal-label">${showOriginal ? '原版对照中' : proposal.label}</span></div><p>${proposal.description}</p></div>
      ${phone(screen)}
      <div class="proposal-notes"><div class="palette" aria-label="方案色板">${proposal.colors.map(color => `<span style="background:${color}" title="${color}"></span>`).join('')}<span class="palette-label">${showOriginal ? '点击上方按钮返回方案' : '正文保持深色 · 主按钮沿用蓝色'}</span></div><ul>${proposal.notes.map(note => `<li>${note}</li>`).join('')}</ul></div>
    </section>`).join('');
    // Keep the current gallery's question navigation visible in this static study.
    if (selectedScreen === 'L09') {
      grid.querySelectorAll('.screen-card').forEach(card => {
        if (!showOriginal) card.querySelector('.quiz-progress > span').textContent = '1 / 3';
        card.querySelector('.quiz-progress .progress-track').outerHTML = `<div class="quiz-steps" role="navigation" aria-label="题号示意">${[1, 2, 3].map(n => `<button class="quiz-step ${n === 1 ? 'current' : ''}"><span class="quiz-step-number">${n}</span></button>`).join('')}</div>`;
        card.querySelector('.phone-bottom').innerHTML = `<div class="quiz-navigation">${UI.btn('上一题', '', 'secondary', 'disabled')}${UI.btn('下一题')}</div><p class="small muted center quiz-completion">已答 0 / 3 题，全部作答后可完成本关</p>`;
      });
    }
    FooterTheme.decorateAll();

    // Scope duplicate form IDs to each preview; keep the original files intact.
    grid.querySelectorAll('.proposal').forEach(proposal => {
      const suffix = proposal.dataset.proposal;
      proposal.querySelectorAll('[id]').forEach(node => {
        const oldId = node.id;
        node.id = `${oldId}-${suffix}`;
        proposal.querySelectorAll('label[for]').forEach(label => {
          if (label.htmlFor === oldId) label.htmlFor = node.id;
        });
      });
      proposal.querySelectorAll('input[name]').forEach(input => { input.name += `-${suffix}`; });
      proposal.querySelectorAll('input[type="radio"]').forEach(input => { input.checked = input.defaultChecked; });
      proposal.querySelectorAll('.phone a, .phone button, .phone input, .phone summary').forEach(control => {
        control.tabIndex = -1;
        control.setAttribute('aria-disabled', 'true');
      });
      proposal.querySelectorAll('.phone input').forEach(input => {
        if (input.type !== 'radio' && input.type !== 'checkbox') input.disabled = true;
      });
    });

    document.querySelectorAll('[data-screen]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.screen === selectedScreen)));
  }

  document.querySelectorAll('[data-screen]').forEach(button => {
    button.addEventListener('click', () => {
      selectedScreen = button.dataset.screen;
      const url = new URL(location.href);
      url.searchParams.set('screen', selectedScreen);
      history.replaceState(null, '', url);
      render();
    });
  });
  document.querySelector('.original-toggle').addEventListener('click', event => {
    showOriginal = !showOriginal;
    event.currentTarget.setAttribute('aria-pressed', String(showOriginal));
    event.currentTarget.textContent = showOriginal ? '返回三组方案' : '查看原版对照';
    render();
  });
  // These are visual samples, not a parallel implementation of the learning flow.
  grid.addEventListener('click', event => {
    if (event.target.closest('.phone a, .phone button, .phone label, .phone input, .phone summary')) event.preventDefault();
  }, true);
  render();
})();
