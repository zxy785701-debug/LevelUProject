/* Independent visual study. Original assets are read, never modified. */
(() => {
  const proposals = [
    { id: 'a', letter: 'A', title: '晴空蓝 · 深浅渐变', label: '推荐',
      description: '深蓝 → 亮蓝 → 浅天蓝，拉开明暗变化。',
      gradient: 'linear-gradient(105deg, #163C9F 0%, #285DDD 38%, #429AF0 72%, #9ADEFF 100%)',
      colors: ['#163C9F', '#9ADEFF', '#D7EAFF', '#FFFFFF'],
      notes: ['顶部：从左侧深蓝过渡到右侧浅天蓝，色差更明显。', '背景：上方蓝色稍浓，向下逐渐淡入白色。', '气质：清爽、明亮，保留蓝色主调与白色内容。'] },
    { id: 'b', letter: 'B', title: '海风蓝 · 蓝青渐变', label: '更清新',
      description: '由蓝色过渡到青蓝，带一点海风般的清新。',
      gradient: 'linear-gradient(112deg, #2857CA 0%, #2175B5 55%, #087C8E 100%)',
      colors: ['#2857CA', '#087C8E', '#E5F6FA', '#FFFFFF'],
      notes: ['顶部：湖蓝 → 青蓝，蓝色仍是主调。', '背景：淡蓝与浅青交融，向下收进白色。', '气质：清新、有活力，渐变色相变化更明显。'] },
    { id: 'c', letter: 'C', title: '晨雾蓝 · 蓝紫渐变', label: '更柔和',
      description: '浅蓝慢慢融入淡紫，像晨光落在书页上。',
      gradient: 'linear-gradient(112deg, #D2E5FF 0%, #DDE8FF 52%, #E9DEFA 100%)',
      colors: ['#D2E5FF', '#E9DEFA', '#F4F6FF', '#FFFFFF'],
      notes: ['顶部：浅蓝 → 淡紫，深蓝文字保持清楚。', '背景：延续顶部色调，渐渐淡入大面积白色。', '气质：安静、柔和，适合更克制的色彩表达。'] }
  ];
  const allowedScreens = ['L02', 'L09', 'L15'];
  const requested = new URLSearchParams(location.search).get('screen');
  let selectedScreen = allowedScreens.includes(requested) ? requested : 'L02';
  let showOriginal = false;
  const grid = document.getElementById('proposal-grid');

  function phone(screen) {
    return `<article class="screen-card footer-refined ${screen.id === 'L09' ? 'question-layout' : ''}" data-id="${screen.id}">
      <div class="phone">
        <div class="phone-chrome">
        <div class="status-bar"><span>9:41</span><span class="status-icons">${UI.icon('signal')}${UI.icon('wifi')}<span class="battery"><b></b></span></span></div>
        <div class="mini-bar"><span class="mini-title"><span class="mini-back" aria-hidden="true">${UI.icon('back')}</span><span class="mini-label">${screen.bar || screen.name}</span></span><div class="wechat-capsule" aria-label="微信小程序胶囊示意"><span class="capsule-divider"></span></div></div>
        </div>
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
      <div class="proposal-notes"><div class="palette" aria-label="渐变与方案色板"><span class="gradient-swatch" style="background:${proposal.gradient}" title="顶部渐变"></span>${proposal.colors.slice(2).map(color => `<span style="background:${color}" title="${color}"></span>`).join('')}<span class="palette-label">${showOriginal ? '点击上方按钮返回方案' : '顶部渐变 · 浅色背景 · 白色内容'}</span></div><ul>${proposal.notes.map(note => `<li>${note}</li>`).join('')}</ul></div>
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
