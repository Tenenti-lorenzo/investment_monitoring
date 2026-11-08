/* ═══════════════════════════════════════
   PortfolioLab – Navbar overflow menu
   Shows as many .nav-links as fit in the bar; the rest move into a dropdown
   ("Altro ▾"). When none fit (phones) the button becomes a ☰ menu holding
   every link. Re-fits on resize and on language change (label widths vary).
═══════════════════════════════════════ */
(function () {
  const t = (key, fallback) => {
    const s = window.I18n ? I18n.t(key) : key;
    return s === key ? fallback : s;
  };

  function init() {
    const bar = document.querySelector('.nav-links');
    if (!bar) return;
    const links = [...bar.querySelectorAll(':scope > a')];
    if (!links.length) return;

    const more = document.createElement('div');
    more.className = 'nav-more';
    more.innerHTML = '<button type="button" class="nav-more-btn" aria-haspopup="true" aria-expanded="false"></button>'
      + '<div class="nav-more-menu" role="menu"></div>';
    bar.appendChild(more);
    const btn = more.querySelector('.nav-more-btn');
    const menu = more.querySelector('.nav-more-menu');

    function label(allHidden) {
      btn.classList.toggle('is-burger', allHidden);
      btn.textContent = allHidden ? '☰' : t('nav.more', 'Altro') + ' ▾';
      btn.setAttribute('aria-label', allHidden ? t('nav.menu', 'Menu') : t('nav.more', 'Altro'));
    }

    function fit() {
      links.forEach(a => bar.insertBefore(a, more));
      more.hidden = false;
      label(false);
      const avail = bar.clientWidth;
      const gap = parseFloat(getComputedStyle(bar).columnGap) || 0;
      const widths = links.map(a => a.offsetWidth);
      const total = widths.reduce((s, w) => s + w, 0) + gap * (links.length - 1);
      if (total <= avail) { more.hidden = true; return; }

      const room = avail - more.offsetWidth - gap;
      let used = 0, n = 0;
      for (; n < links.length; n++) {
        const w = widths[n] + (n ? gap : 0);
        if (used + w > room) break;
        used += w;
      }
      links.slice(n).forEach(a => menu.appendChild(a));
      label(n === 0);
    }

    function open() {
      more.classList.add('open');
      btn.setAttribute('aria-expanded', 'true');
      // keep the dropdown inside the viewport
      menu.style.left = '0'; menu.style.right = 'auto';
      if (menu.getBoundingClientRect().right > window.innerWidth - 8) {
        menu.style.left = 'auto'; menu.style.right = '0';
      }
    }
    function close() {
      more.classList.remove('open');
      btn.setAttribute('aria-expanded', 'false');
    }

    btn.addEventListener('click', e => {
      e.stopPropagation();
      more.classList.contains('open') ? close() : open();
    });
    menu.addEventListener('click', e => { if (e.target.closest('a')) close(); });
    document.addEventListener('click', e => { if (!more.contains(e.target)) close(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') { close(); btn.focus(); } });

    let raf = 0;
    const schedule = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(fit); };
    new ResizeObserver(schedule).observe(bar);
    window.addEventListener('langchange', schedule);
    if (document.fonts) document.fonts.ready.then(schedule);
    fit();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
